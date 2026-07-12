"""
handlers/commands.py — Explicit email command handlers.

These are shortcuts — the autonomous agent handles the same actions from
free text. Commands give power-users precise, fast control.

Commands: /start, /check, /send, /reply, /draft, /search
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import agent
import ai_engine
from config import claude_client, openai_client
from email_utils import (
    build_message,
    fetch_msg,
    get_attachments,
    get_body,
    imap_connect,
    smtp_connect,
)
from handlers.files import forward_email_attachments
from keyboards import email_keyboard
from utils import clear_pending, is_authorized, send_draft, show_draft

logger = logging.getLogger(__name__)


# ── /start ────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    providers = ["Gemini (primary)"]
    if claude_client:
        providers.append("Claude (fallback #1)")
    if openai_client:
        providers.append("OpenAI (fallback #2)")

    await update.message.reply_text(
        "👋 *Welcome to your AI Email Agent!*\n\n"
        f"🧠 *AI:* {' → '.join(providers)}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💬 *Just chat naturally!*\n"
        "\"Any new emails?\" · \"Mail John about the meeting\" · \"Search for invoices\"\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⌨️ *Quick commands*\n"
        "📥 `/check` — Summarize latest unread emails\n"
        "✍️ `/reply [id] [instructions]` — AI-draft a reply\n"
        "📧 `/send [to] [subject] | [body]` — Send a new email\n"
        "✏️ `/draft [to] [topic]` — Draft from a one-liner\n"
        "🔍 `/search [keyword]` — Search inbox\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔔 *Monitoring*\n"
        "👀 `/watch` — Start push notifications\n"
        "🔕 `/unwatch` — Stop monitoring\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⭐ *VIP Alerts*\n"
        "`/vip add email` · `/vip remove email` · `/vip list`\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📎 *Attachments*\n"
        "Send any file/photo · `/clear` to discard",
        parse_mode="Markdown",
    )


# ── /check ────────────────────────────────────────────────────────────────────

async def check_emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    await update.message.reply_text("📥 Checking your inbox…")
    try:
        with imap_connect() as client:
            all_unseen = client.search(["UNSEEN"])
            if not all_unseen:
                await update.message.reply_text("No new unread emails! 🎉")
                return

            latest    = all_unseen[-5:]
            emails    = []
            msg_cache = {}

            for mid in reversed(latest):
                msg = fetch_msg(client, mid)
                emails.append({
                    "id":         mid,
                    "from":       msg.get("From", "(Unknown)"),
                    "subject":    msg.get("Subject", "(No Subject)"),
                    "body":       get_body(msg)[:1500],
                    "has_attach": bool(get_attachments(msg)),
                })
                msg_cache[mid] = msg

        prompt = (
            "Summarize each email below as:\n"
            "📬 Msg ID: [ID]\nFrom: [Sender]\nSubject: [Subject]\n"
            "Summary:\n- [2-3 bullet points]\n──────────────────────────────\n\n"
        )
        for e in emails:
            prompt += f"Msg ID: {e['id']}\nFrom: {e['from']}\nSubject: {e['subject']}\nBody:\n{e['body']}\n\n──────────\n\n"

        summary = ai_engine.generate(prompt)
        await update.message.reply_text(
            f"Found *{len(all_unseen)}* unread. Latest {len(latest)}:\n\n{summary}",
            parse_mode="Markdown",
        )
        for e in emails:
            att = " 📎" if e["has_attach"] else ""
            await update.message.reply_text(
                f"📬 *ID: {e['id']}*{att}\n*From:* {e['from']}\n*Subject:* {e['subject']}",
                parse_mode="Markdown",
                reply_markup=email_keyboard(e["id"]),
            )
            if e["has_attach"]:
                await forward_email_attachments(context, update.effective_chat.id, msg_cache[e["id"]])

    except Exception as exc:
        logger.error("check_emails: %s", exc)
        await update.message.reply_text(f"❌ Failed to check inbox: {exc}")


# ── /send ─────────────────────────────────────────────────────────────────────

async def send_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    args = context.args or []

    # /send with no args → send pending draft
    if not args:
        draft = context.user_data.get("draft")
        if draft:
            await send_draft(update, context, draft)
        else:
            await update.message.reply_text(
                "📭 No pending draft.\n\n"
                "Use `/send to subject | body` or just tell me:\n"
                "_\"Send an email to alice@example.com about the project\"_",
                parse_mode="Markdown",
            )
        return

    if len(args) < 2:
        await update.message.reply_text(
            "❌ *Usage:* `/send [to] [subject] | [body]`",
            parse_mode="Markdown",
        )
        return

    try:
        full            = " ".join(args)
        to              = args[0]
        rest            = full[len(to):].strip()
        subject, body   = (rest.split("|", 1) if "|" in rest else ("Quick Mail", rest))
        subject, body   = subject.strip(), body.strip()
        pending         = context.user_data.get("pending_attachment")
        msg             = build_message(to, subject, body, attachment=pending)

        await update.message.reply_text("📤 Sending…")
        with smtp_connect() as srv:
            srv.send_message(msg)

        clear_pending(context, pending)
        await update.message.reply_text(
            f"✅ Email{'  📎' if pending else ''} sent to {to}!"
        )
    except Exception as exc:
        logger.error("send_email: %s", exc)
        await update.message.reply_text(f"❌ Failed: {exc}")


# ── /reply ────────────────────────────────────────────────────────────────────

async def reply_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "❌ *Usage:* `/reply [msg_id] [instructions]`",
            parse_mode="Markdown",
        )
        return

    try:
        msg_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Message ID must be a number.")
        return

    instruction = " ".join(args[1:])
    await update.message.reply_text(f"🔍 Fetching email {msg_id}…")

    try:
        with imap_connect() as client:
            orig = fetch_msg(client, msg_id)
        if not orig:
            await update.message.reply_text(f"❌ Email {msg_id} not found.")
            return

        orig_subject = orig.get("Subject", "(No Subject)")
        orig_from    = orig.get("From", "(Unknown)")
        reply_to     = orig.get("Reply-To") or orig_from
        orig_msg_id  = orig.get("Message-ID", "")

        await update.message.reply_text("✍️ Drafting reply with AI…")
        reply_body = ai_engine.generate(
            f"Write a professional email reply.\n\n"
            f"Instructions: {instruction}\n\n"
            f"Original — From: {orig_from}\nSubject: {orig_subject}\n"
            f"Body:\n{get_body(orig)[:1500]}\n\n"
            f"Write ONLY the email body. No subject line or placeholders."
        )

        subject = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"
        await show_draft(
            update, context, reply_to, subject, reply_body,
            in_reply_to=orig_msg_id,
            references=orig.get("References", ""),
        )

    except Exception as exc:
        logger.error("reply_email: %s", exc)
        await update.message.reply_text(f"❌ Failed: {exc}")


# ── /draft ────────────────────────────────────────────────────────────────────

async def draft_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "❌ *Usage:* `/draft [to] [topic]`",
            parse_mode="Markdown",
        )
        return

    to    = args[0]
    topic = " ".join(args[1:])
    await update.message.reply_text("✏️ Drafting with AI…")

    try:
        raw = ai_engine.generate(
            f"Draft a complete, professional email.\n"
            f"Recipient: {to}\nTopic: {topic}\n\n"
            f"Format EXACTLY as:\nSUBJECT: [subject line]\n\n[email body]\n\n"
            f"No extra commentary."
        )
        subject, body = _parse_subject_body(raw)
        await show_draft(update, context, to, subject, body)

    except Exception as exc:
        await update.message.reply_text(f"❌ Failed to generate draft: {exc}")


# ── /search ───────────────────────────────────────────────────────────────────

async def search_emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ *Usage:* `/search [keyword]` or `/search from:[sender]`",
            parse_mode="Markdown",
        )
        return

    query = " ".join(args)
    await update.message.reply_text(f"🔍 Searching: `{query}`…", parse_mode="Markdown")

    try:
        with imap_connect() as client:
            criteria = (
                ["FROM", query[5:].strip()]
                if query.lower().startswith("from:")
                else ["TEXT", query]
            )
            ids = client.search(criteria)

        if not ids:
            await update.message.reply_text(f"No emails found for: `{query}`", parse_mode="Markdown")
            return

        latest = ids[-5:]
        await update.message.reply_text(
            f"🔍 *{len(ids)}* result(s). Latest {len(latest)}:",
            parse_mode="Markdown",
        )
        with imap_connect() as client:
            for mid in reversed(latest):
                msg = fetch_msg(client, mid)
                att = " 📎" if get_attachments(msg) else ""
                await update.message.reply_text(
                    f"📬 *ID: {mid}*{att}\n"
                    f"*From:* {msg.get('From', '?')}\n"
                    f"*Subject:* {msg.get('Subject', '?')}",
                    parse_mode="Markdown",
                    reply_markup=email_keyboard(mid),
                )

    except Exception as exc:
        logger.error("search_emails: %s", exc)
        await update.message.reply_text(f"❌ Search failed: {exc}")


# ── Private helpers ───────────────────────────────────────────────────────────

def _parse_subject_body(raw: str) -> tuple[str, str]:
    """Extract (subject, body) from 'SUBJECT: ...\n\n...' formatted AI output."""
    if "SUBJECT:" not in raw:
        return "Draft Email", raw
    lines   = raw.split("\n", 2)
    subject = lines[0].replace("SUBJECT:", "").strip()
    body    = "\n".join(lines[2:]).strip() if len(lines) > 2 else raw
    return subject, body
