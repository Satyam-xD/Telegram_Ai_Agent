"""
mail_agent.py — Entry point.

Run modes (auto-detected from environment):
  • Webhook mode  — set WEBHOOK_URL=https://<your-render-service>.onrender.com
                    Render injects PORT automatically.
  • Polling mode  — leave WEBHOOK_URL unset (default, great for local dev).
"""
import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN, WEBHOOK_PORT, WEBHOOK_URL
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


def _build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    # ── Commands (explicit shortcuts) ─────────────────────────────────────────
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

    # ── Autonomous AI agent (catches all free text — must be last) ────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_with_ai))

    return app


def main() -> None:
    app = _build_app()

    if WEBHOOK_URL:
        # ── Webhook mode (Render / any public HTTPS host) ─────────────────────
        webhook_path = BOT_TOKEN          # use token as secret URL path
        logger.info(
            "Starting in WEBHOOK mode — %s/%s  (port %s)",
            WEBHOOK_URL, webhook_path, WEBHOOK_PORT,
        )
        app.run_webhook(
            listen="0.0.0.0",
            port=WEBHOOK_PORT,
            url_path=webhook_path,
            webhook_url=f"{WEBHOOK_URL}/{webhook_path}",
        )
    else:
        # ── Polling mode (local development) ──────────────────────────────────
        logger.info("Starting in POLLING mode (local dev).")
        app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
