"""
handlers/chat.py — Thin message router.

Routes incoming text:
  1. Draft confirmation flow  — send / cancel a pending draft
  2. Inline-button reply flow — instructions after tapping Reply
  3. Autonomous agent         — everything else (free natural language)
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import agent
from utils import is_authorized, send_draft

logger = logging.getLogger(__name__)

_SEND_WORDS = {
    "send", "send it", "send it now", "send now", "send email", "send the email",
    "yes", "yes send", "yes send it", "yeah send it", "yep", "sure",
    "ok", "ok send", "ok go ahead", "go ahead", "go ahead and send",
    "confirm", "do it", "shoot it",
}
_CANCEL_WORDS = {
    "cancel", "discard", "abort", "no", "nope",
    "don't send", "dont send", "stop", "cancel it", "trash it",
}


def is_authorized_check(update: Update) -> bool:
    return is_authorized(update)


async def chat_with_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    text = update.message.text.strip()
    if await _draft_flow(update, context, text):
        return
    if await _reply_flow(update, context, text):
        return
    await agent.run(text, update, context)


async def _draft_flow(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> bool:
    """Handle send/cancel when a draft is pending. Returns True if consumed."""
    draft = context.user_data.get("draft")
    if not draft:
        return False

    lower = text.lower().strip().rstrip("!")
    if lower in _SEND_WORDS:
        await send_draft(update, context, draft)
        return True
    if lower in _CANCEL_WORDS:
        context.user_data.pop("draft", None)
        await update.message.reply_text("❌ Draft discarded.")
        return True

    # Any other message while a draft is pending — keep draft, remind user
    await update.message.reply_text(
        f"📬 Pending draft to *{draft['to']}*.\n"
        "Reply *send* to send it · *cancel* to discard.",
        parse_mode="Markdown",
    )
    return True


async def _reply_flow(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> bool:
    """If a Reply button was tapped, inject email ID context and run agent."""
    msg_id = context.user_data.pop("pending_reply_id", None)
    if msg_id is None:
        return False
    await agent.run(f"Reply to email ID {msg_id}: {text}", update, context)
    return True
