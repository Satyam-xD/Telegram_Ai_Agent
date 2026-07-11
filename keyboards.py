"""
keyboards.py — Inline keyboard factory and the button callback handler.
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def email_keyboard(msg_id: int) -> InlineKeyboardMarkup:
    """Return a Reply / Skip inline keyboard for a given email message ID."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✍️ Reply", callback_data=f"reply:{msg_id}"),
        InlineKeyboardButton("⏭️ Skip",  callback_data=f"skip:{msg_id}"),
    ]])


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Reply / Skip inline button presses."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""

    if data.startswith("reply:"):
        msg_id = int(data.split(":")[1])
        context.user_data["pending_reply_id"] = msg_id
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                f"✍️ How should I reply to email *{msg_id}*?\n"
                "Type your instructions and I'll draft and send the reply."
            ),
            parse_mode="Markdown",
        )

    elif data.startswith("skip:"):
        await query.edit_message_reply_markup(reply_markup=None)
