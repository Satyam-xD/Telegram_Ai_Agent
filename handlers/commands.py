"""
handlers/commands.py — Core email command handlers.

Commands: /start, /check, /send, /reply, /draft, /search
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import ai_engine
from config import (
    AUTHORIZED_USER_ID,
    EMAIL_USERNAME,
    claude_client,
    openai_client,
)
from email_utils import (
    build_message,
    cleanup_file,
    fetch_msg,
    get_attachments,
    get_body,
    imap_connect,
    smtp_connect,
)
from handlers.files import forward_email_attachments
from keyboards import email_keyboard

logger = logging.getLogger(__name__)


def is_authorized(update: Update) -> bool:
    return str(update.effective_user.id) == AUTHORIZED_USER_ID


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
        "📩 *Email*\n"
        "📥 `/check` — Summarize latest 5 unread emails\n"
        "✍️ `/reply [id] [instructions]` — AI-draft & send a reply\n"
        "📧 `/send [to] [subject] | [body]` — Send a new email\n"
        "✏️ `/draft [to] [topic]` — Full email from a one-liner\n"
        "🔍 `/search [keyword]` — Search inbox\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔔 *Monitoring*\n"
        "👀 `/watch` — Start push notifications\n"
        "🔕 `/unwatch` — Stop monitoring\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⭐ *VIP Alerts*\n"
        "`/vip add email` · `/vip remove email` · `/vip list`\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📎 *Files & Media*\n"
        "Send any file/photo to attach it to your next email\n"
        "🗑️ `/clear` — Discard pending attachment\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 *Chat Assistant*\n"
        "Send any text to chat with the AI",
        parse_mode="Markdown",
    )


# ── /check ────────────────────────────────────────────────────────────────────

async def check_emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    await update.message.reply_text("Checking your inbox... 🔍")

    try:
        with imap_connect() as client:
            all_unseen = client.search(["UNSEEN"])
            if not all_unseen:
                await update.message.reply_text("No new unread emails! 🎉")
                return

            latest = all_unseen[-5:]
            emails_data   = []
            msg_cache     = {}

            for msg_id in reversed(latest):
                msg  = fetch_msg(client, msg_id)
                body = get_body(msg)
                emails_data.append({
                    "id":         msg_id,
                    "from":       msg.get("From", "(Unknown)"),
                    "subject":    msg.get("Subject", "(No Subject)"),
                    "body":       body[:1500],
                    "has_attach": bool(get_attachments(msg)),
                })
                msg_cache[msg_id] = msg

        # Combined AI summary
        prompt = (
            "You are an expert AI Email Assistant. Summarize each email below.\n"
            "Format each as:\n"
            "📬 Msg ID: [ID]\nFrom: [Sender]\nSubject: [Subject]\n"
            "Summary:\n- [2-3 bullet points]\n──────────────────────────────\n\n"
        )
        for e in emails_data:
            prompt += (
                f"Msg ID: {e['id']}\nFrom: {e['from']}\n"
                f"Subject: {e['subject']}\nBody:\n{e['body']}\n\n──────────\n\n"
            )

        summary = ai_engine.generate(prompt)
        await update.message.reply_text(
            f"Found *{len(all_unseen)}* unread email(s). Latest {len(latest)}:\n\n{summary}",
            parse_mode="Markdown",
        )

        for e in emails_data:
            att_tag = " 📎" if e["has_attach"] else ""
            await update.message.reply_text(
                f"📬 *ID: {e['id']}*{att_tag}\n*From:* {e['from']}\n*Subject:* {e['subject']}",
                parse_mode="Markdown",
                reply_markup=email_keyboard(e["id"]),
            )
            if e["has_attach"]:
                await forward_email_attachments(context, update.effective_chat.id, msg_cache[e["id"]])

    except Exception as exc:
        logger.error("check_emails error: %s", exc)
        await update.message.reply_text(f"Failed to check emails: {exc}")


# ── /send ─────────────────────────────────────────────────────────────────────

async def send_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "❌ *Invalid usage.*\n"
            "Format: `/send [to] [subject] | [body]`\n"
            "Example: `/send friend@example.com Lunch Plans | Hey! Are we meeting today?`",
            parse_mode="Markdown",
        )
        return

    try:
        full = " ".join(args)
        to   = args[0]
        rest = full[len(to):].strip()
        subject, body = (rest.split("|", 1) if "|" in rest else ("Quick Mail from Bot", rest))
        subject, body = subject.strip(), body.strip()

        pending = context.user_data.get("pending_attachment")
        msg     = build_message(to, subject, body, attachment=pending)

        await update.message.reply_text("Sending email... 📤")
        with smtp_connect() as server:
            server.send_message(msg)

        _clear_pending(context, pending)
        suffix = " with attachment" if pending else ""
        await update.message.reply_text(f"✅ Email{suffix} sent to {to}!")

    except Exception as exc:
        logger.error("send_email error: %s", exc)
        await update.message.reply_text(f"Failed to send email: {exc}")


# ── /reply ────────────────────────────────────────────────────────────────────

async def reply_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "❌ *Invalid usage.*\n"
            "Format: `/reply [msg_id] [instructions]`\n"
            "Example: `/reply 688 say I will attend the meeting tomorrow`",
            parse_mode="Markdown",
        )
        return

    try:
        msg_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid Message ID — must be a number.")
        return

    instruction = " ".join(args[1:])
    await update.message.reply_text(f"Fetching email {msg_id}... 🔍")

    try:
        with imap_connect() as client:
            orig = fetch_msg(client, msg_id)
        if not orig:
            await update.message.reply_text(f"❌ Email {msg_id} not found.")
            return

        orig_subject  = orig.get("Subject", "(No Subject)")
        orig_from     = orig.get("From", "(Unknown)")
        orig_body     = get_body(orig)
        reply_to      = orig.get("Reply-To") or orig_from
        orig_msg_id   = orig.get("Message-ID", "")

        await update.message.reply_text("Drafting reply with AI... 🤖")

        reply_body = ai_engine.generate(
            f"Write a professional email reply.\n\n"
            f"Instructions: {instruction}\n\n"
            f"Original — From: {orig_from}\nSubject: {orig_subject}\nBody:\n{orig_body[:1500]}\n\n"
            f"Write ONLY the email body. No subject line or placeholders."
        )

        subject = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"
        pending = context.user_data.get("pending_attachment")
        msg     = build_message(
            reply_to, subject, reply_body,
            attachment=pending,
            in_reply_to=orig_msg_id,
            references=orig.get("References", ""),
        )

        await update.message.reply_text("Sending reply... 📤")
        with smtp_connect() as server:
            server.send_message(msg)

        _clear_pending(context, pending)
        await update.message.reply_text(
            f"✅ *Reply sent to {reply_to}!*\n\n📝 *Draft:*\n{reply_body}",
            parse_mode="Markdown",
        )

    except Exception as exc:
        logger.error("reply_email error: %s", exc)
        await update.message.reply_text(f"❌ Failed to send reply: {exc}")


# ── /draft ────────────────────────────────────────────────────────────────────

async def draft_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "❌ *Invalid usage.*\n"
            "Format: `/draft [to] [topic]`\n"
            "Example: `/draft boss@company.com request 3 days leave next week`",
            parse_mode="Markdown",
        )
        return

    to    = args[0]
    topic = " ".join(args[1:])
    await update.message.reply_text("✏️ Drafting email with AI...")

    try:
        raw_draft = ai_engine.generate(
            f"Draft a complete, professional email.\n"
            f"Recipient: {to}\nTopic: {topic}\n\n"
            f"Format EXACTLY as:\nSUBJECT: [subject line]\n\n[email body]\n\n"
            f"No extra commentary."
        )

        subject, body = _parse_draft(raw_draft)
        context.user_data["draft"] = {"to": to, "subject": subject, "body": body}

        pending     = context.user_data.get("pending_attachment")
        attach_note = f"\n\n📎 *Attachment:* `{pending['filename']}`" if pending else ""

        await update.message.reply_text(
            f"📝 *Draft Ready!*\n\n*To:* {to}\n*Subject:* {subject}\n\n{body}"
            f"{attach_note}\n\n──────────────────────────\n"
            "Reply *send* to send · *cancel* to discard",
            parse_mode="Markdown",
        )

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
            "❌ *Invalid usage.*\n"
            "Format: `/search [keyword]` or `/search from:[sender]`",
            parse_mode="Markdown",
        )
        return

    query = " ".join(args)
    await update.message.reply_text(f"🔍 Searching: `{query}`...", parse_mode="Markdown")

    try:
        with imap_connect() as client:
            criteria = (
                ["FROM", query[5:].strip()]
                if query.lower().startswith("from:")
                else ["TEXT", query]
            )
            messages = client.search(criteria)

            if not messages:
                await update.message.reply_text(f"No emails found for: `{query}`", parse_mode="Markdown")
                return

            latest = messages[-5:]
            await update.message.reply_text(
                f"🔍 *{len(messages)}* result(s). Showing latest {len(latest)}:",
                parse_mode="Markdown",
            )

            for msg_id in reversed(latest):
                msg     = fetch_msg(client, msg_id)
                att_tag = " 📎" if get_attachments(msg) else ""
                await update.message.reply_text(
                    f"📬 *ID: {msg_id}*{att_tag}\n"
                    f"*From:* {msg.get('From', '(Unknown)')}\n"
                    f"*Subject:* {msg.get('Subject', '(No Subject)')}",
                    parse_mode="Markdown",
                    reply_markup=email_keyboard(msg_id),
                )

    except Exception as exc:
        logger.error("search_emails error: %s", exc)
        await update.message.reply_text(f"❌ Search failed: {exc}")


# ── Private helpers ───────────────────────────────────────────────────────────

def _parse_draft(raw: str) -> tuple[str, str]:
    """Extract subject and body from a SUBJECT: ... \n\n ... formatted draft."""
    subject = "Draft Email"
    body    = raw
    if "SUBJECT:" in raw:
        lines   = raw.split("\n", 2)
        subject = lines[0].replace("SUBJECT:", "").strip()
        body    = "\n".join(lines[2:]).strip() if len(lines) > 2 else raw
    return subject, body


def _clear_pending(context: ContextTypes.DEFAULT_TYPE, pending: dict | None) -> None:
    """Delete temp file and remove pending_attachment from user_data."""
    if pending:
        cleanup_file(pending["path"])
        context.user_data.pop("pending_attachment", None)
