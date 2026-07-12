"""
handlers/monitoring.py — Background inbox polling and VIP alert management.

Commands: /watch, /unwatch, /vip
Background job: poll_emails
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import ai_engine
from config import AUTHORIZED_USER_ID, POLL_INTERVAL_MINS
from email_utils import fetch_msg, get_attachments, get_body, imap_connect
from handlers.files import forward_email_attachments
from keyboards import email_keyboard
from utils import is_authorized

logger = logging.getLogger(__name__)


# ── Background poll job ───────────────────────────────────────────────────────

async def poll_emails(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue callback — push Telegram alerts for new unread emails."""
    if not context.bot_data.get("watching"):
        return
    chat_id: int = context.bot_data.get("watch_chat_id")
    if not chat_id:
        return

    seen: set     = context.bot_data.setdefault("seen_email_ids", set())
    vip:  set     = context.bot_data.get("vip_senders", set())

    try:
        with imap_connect() as client:
            new = [m for m in client.search(["UNSEEN"]) if m not in seen]
            if not new:
                return
            for mid in new:
                seen.add(mid)
                msg = fetch_msg(client, mid)
                if not msg:
                    continue

                subject   = msg.get("Subject", "(No Subject)")
                from_addr = msg.get("From", "(Unknown)")
                body      = get_body(msg)
                is_vip    = any(v.lower() in from_addr.lower() for v in vip)
                has_att   = bool(get_attachments(msg))
                summary   = _summarize(from_addr, subject, body)

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"{'⭐ *VIP SENDER*\n' if is_vip else ''}"
                        f"📬 *New Email*{'  📎' if has_att else ''} (ID: {mid})\n"
                        f"*From:* {from_addr}\n"
                        f"*Subject:* {subject}\n\n"
                        f"{summary}"
                    ),
                    parse_mode="Markdown",
                    reply_markup=email_keyboard(mid),
                )
                if has_att:
                    await forward_email_attachments(context, chat_id, msg)

    except Exception as exc:
        logger.error("poll_emails: %s", exc)


def _summarize(from_addr: str, subject: str, body: str) -> str:
    try:
        return ai_engine.generate(
            f"Summarize in 2-3 bullets:\nFrom: {from_addr}\nSubject: {subject}\nBody:\n{body[:1000]}"
        )
    except Exception:
        return (body[:300] + "…") if len(body) > 300 else body


# ── /watch ────────────────────────────────────────────────────────────────────

async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return
    if context.bot_data.get("watching"):
        await update.message.reply_text("👀 Already monitoring your inbox!")
        return

    context.bot_data["watching"]      = True
    context.bot_data["watch_chat_id"] = update.effective_chat.id
    context.bot_data.setdefault("seen_email_ids", set())
    context.job_queue.run_repeating(
        poll_emails, interval=POLL_INTERVAL_MINS * 60, first=10, name="email_poller"
    )
    await update.message.reply_text(
        f"👀 *Monitoring started!* Checking every {POLL_INTERVAL_MINS} min.\n"
        "VIP senders flagged ⭐ · Attachments forwarded 📎\n\n"
        "Use /unwatch to stop.",
        parse_mode="Markdown",
    )


# ── /unwatch ──────────────────────────────────────────────────────────────────

async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return
    context.bot_data["watching"] = False
    for job in context.job_queue.get_jobs_by_name("email_poller"):
        job.schedule_removal()
    await update.message.reply_text("🔕 Monitoring stopped.")


# ── /vip ──────────────────────────────────────────────────────────────────────

async def vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    vip:    set  = context.bot_data.setdefault("vip_senders", set())
    args         = context.args or []
    action       = args[0].lower() if args else ""

    if action == "list":
        text = ("⭐ *VIP Senders:*\n" + "\n".join(f"• {s}" for s in sorted(vip))) if vip else "⭐ No VIP senders yet."
        await update.message.reply_text(text, parse_mode="Markdown")

    elif action == "add" and len(args) > 1:
        addr = args[1].lower()
        vip.add(addr)
        await update.message.reply_text(f"⭐ Added `{addr}` to VIP.", parse_mode="Markdown")

    elif action == "remove" and len(args) > 1:
        addr = args[1].lower()
        vip.discard(addr)
        await update.message.reply_text(f"✅ Removed `{addr}` from VIP.", parse_mode="Markdown")

    else:
        await update.message.reply_text(
            "Usage:\n"
            "`/vip add email@example.com`\n"
            "`/vip remove email@example.com`\n"
            "`/vip list`",
            parse_mode="Markdown",
        )
