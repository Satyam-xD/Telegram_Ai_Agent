"""
mail_agent.py — Entry point.

Registers all handlers and starts the bot. No business logic lives here.
"""
import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN
from handlers.chat import chat_with_ai
from handlers.commands import (
    check_emails,
    draft_email,
    reply_email,
    search_emails,
    send_email,
    start,
)
from handlers.files import clear_attachment, handle_file
from handlers.monitoring import unwatch, vip_command, watch
from keyboards import button_callback

logger = logging.getLogger(__name__)

_FILE_FILTER = (
    filters.Document.ALL
    | filters.PHOTO
    | filters.VIDEO
    | filters.AUDIO
    | filters.VOICE
)


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    # ── Email commands ────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("check",   check_emails))
    app.add_handler(CommandHandler("send",    send_email))
    app.add_handler(CommandHandler("reply",   reply_email))
    app.add_handler(CommandHandler("draft",   draft_email))
    app.add_handler(CommandHandler("search",  search_emails))

    # ── Monitoring ────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("watch",   watch))
    app.add_handler(CommandHandler("unwatch", unwatch))
    app.add_handler(CommandHandler("vip",     vip_command))

    # ── Files & attachments ───────────────────────────────────────────────────
    app.add_handler(CommandHandler("clear",   clear_attachment))
    app.add_handler(MessageHandler(_FILE_FILTER, handle_file))

    # ── Inline keyboard callbacks ─────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(button_callback))

    # ── AI chat (must be last) ────────────────────────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_with_ai))

    logger.info("Bot starting — Gemini → Claude → OpenAI fallback chain active.")
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped gracefully.")
