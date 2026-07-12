"""
utils.py — Shared helpers used across handlers.

Centralises: authorization check, draft display, pending-attachment cleanup.
"""
from telegram import Update
from telegram.ext import ContextTypes

from config import AUTHORIZED_USER_ID
from email_utils import build_message, cleanup_file, send_message, smtp_connect


def is_authorized(update: Update) -> bool:
    """Return True if the sender is the configured AUTHORIZED_USER_ID."""
    return str(update.effective_user.id) == AUTHORIZED_USER_ID


async def show_draft(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    to: str,
    subject: str,
    body: str,
    in_reply_to: str = "",
    references: str = "",
) -> None:
    """Store a draft in user_data and display it with send/cancel prompt."""
    context.user_data["draft"] = {
        "to": to,
        "subject": subject,
        "body": body,
        "in_reply_to": in_reply_to,
        "references": references,
    }
    pending     = context.user_data.get("pending_attachment")
    attach_note = f"\n\n📎 *Attachment:* `{pending['filename']}`" if pending else ""
    await update.message.reply_text(
        f"📝 *Draft Ready!*\n\n"
        f"*To:* `{to}`\n"
        f"*Subject:* {subject}\n\n"
        f"{body}{attach_note}\n\n"
        "──────────────────────────\n"
        "Reply *send* to send · *cancel* to discard",
        parse_mode="Markdown",
    )


async def send_draft(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    draft: dict,
) -> None:
    """Send a confirmed draft via the best available transport and clean up state."""
    import logging
    logger = logging.getLogger(__name__)
    try:
        pending = context.user_data.get("pending_attachment")
        send_message(
            draft["to"], draft["subject"], draft["body"],
            attachment=pending,
            in_reply_to=draft.get("in_reply_to", ""),
            references=draft.get("references", ""),
        )
        if pending:
            cleanup_file(pending["path"])
            context.user_data.pop("pending_attachment", None)
        context.user_data.pop("draft", None)
        await update.message.reply_text(
            f"✅ *Email sent to {draft['to']}!*\n*Subject:* {draft['subject']}",
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.error("send_draft error: %s", exc)
        await update.message.reply_text(f"❌ Failed to send: {exc}")


def clear_pending(context: ContextTypes.DEFAULT_TYPE, pending: dict | None) -> None:
    """Delete temp attachment file and remove it from user_data."""
    if pending:
        cleanup_file(pending["path"])
        context.user_data.pop("pending_attachment", None)
