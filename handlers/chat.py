"""
handlers/chat.py — AI chat handler with conversation memory and flow routing.

Handles:
  • Draft confirmation flow  (reply "send" / "cancel" after /draft)
  • Inline-button reply flow (instructions after tapping Reply button)
  • General AI chat with a rolling 8-exchange conversation buffer
"""
import logging
import smtplib

from telegram import Update
from telegram.ext import ContextTypes

import ai_engine
from config import AUTHORIZED_USER_ID
from email_utils import build_message, cleanup_file, smtp_connect

logger = logging.getLogger(__name__)

_MEMORY_LIMIT = 16  # 8 exchanges × 2 entries each


def is_authorized(update: Update) -> bool:
    return str(update.effective_user.id) == AUTHORIZED_USER_ID


async def chat_with_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route incoming text through the active flow, or fall back to general AI chat."""
    if not is_authorized(update):
        return

    text = update.message.text.strip()

    # ── 1. Draft confirmation flow ────────────────────────────────────────────
    if await _handle_draft_flow(update, context, text):
        return

    # ── 2. Inline-button reply flow ───────────────────────────────────────────
    if await _handle_reply_flow(update, context, text):
        return

    # ── 3. General AI chat with memory ────────────────────────────────────────
    await _general_chat(update, context, text)


# ── Flow: draft confirmation ──────────────────────────────────────────────────

async def _handle_draft_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> bool:
    """Return True if a draft is pending and the input was handled."""
    draft = context.user_data.get("draft")
    if not draft:
        return False

    if text.lower() == "send":
        await _send_draft(update, context, draft)
    elif text.lower() == "cancel":
        context.user_data.pop("draft", None)
        await update.message.reply_text("❌ Draft discarded.")
    else:
        # Not a recognised response — leave draft pending and fall through
        return False

    return True


async def _send_draft(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    try:
        pending = context.user_data.get("pending_attachment")
        msg     = build_message(draft["to"], draft["subject"], draft["body"], attachment=pending)

        with smtp_connect() as server:
            server.send_message(msg)

        if pending:
            cleanup_file(pending["path"])
            context.user_data.pop("pending_attachment", None)

        context.user_data.pop("draft", None)
        await update.message.reply_text(f"✅ Email sent to {draft['to']}!")

    except Exception as exc:
        logger.error("_send_draft error: %s", exc)
        await update.message.reply_text(f"❌ Failed to send: {exc}")


# ── Flow: inline reply ────────────────────────────────────────────────────────

async def _handle_reply_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> bool:
    """If a Reply button was tapped, treat the text as reply instructions."""
    msg_id = context.user_data.pop("pending_reply_id", None)
    if msg_id is None:
        return False

    # Delegate to the reply_email handler by injecting args
    from handlers.commands import reply_email  # local import avoids circular dep

    context.args = [str(msg_id)] + text.split()
    await reply_email(update, context)
    return True


# ── General AI chat ───────────────────────────────────────────────────────────

async def _general_chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    history: list = context.user_data.setdefault("chat_history", [])
    history.append(f"User: {text}")

    # Trim buffer
    if len(history) > _MEMORY_LIMIT:
        history = history[-_MEMORY_LIMIT:]
        context.user_data["chat_history"] = history

    await update.message.reply_text("Thinking... 🤖")

    try:
        memory = "\n".join(history[:-1]) if len(history) > 1 else ""
        prompt = (
            "You are a helpful AI Email Assistant helping the user manage their inbox.\n"
            + (f"Previous conversation:\n{memory}\n\n" if memory else "")
            + f"User: {text}\n\n"
            "Provide a concise, helpful reply. "
            "If asked to draft an email, write a professional response."
        )
        reply = ai_engine.generate(prompt)
        history.append(f"Assistant: {reply}")
        context.user_data["chat_history"] = history
        await update.message.reply_text(reply)

    except Exception as exc:
        logger.error("chat_with_ai error: %s", exc)
        await update.message.reply_text(f"AI Error: {exc}")
