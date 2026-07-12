"""
mail_agent.py — Entry point.

Run modes (auto-detected from environment):

  Webhook mode  — set WEBHOOK_URL=https://<your-render-service>.onrender.com
                  python-telegram-bot's aiohttp server binds to PORT.
                  Render health checks pass automatically.

  Polling mode  — leave WEBHOOK_URL unset (local dev default).
                  A tiny stdlib health-check server binds to PORT in a
                  background thread so Render's deploy check still passes.
"""
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

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


# ── Health-check server (polling mode only) ───────────────────────────────────

class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that returns 200 OK for any GET request."""

    def do_GET(self) -> None:                      # noqa: N802
        body = b"OK"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_) -> None:             # suppress access logs
        pass


def _start_health_server(port: int) -> None:
    """
    Start a lightweight health-check HTTP server in a daemon thread.

    Binds to 0.0.0.0:<port> so Render's health probe gets a 200 response
    and marks the deploy as complete, even when the bot runs in polling mode.
    """
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health-check server listening on port %s.", port)


# ── App builder ───────────────────────────────────────────────────────────────

def _build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands (explicit shortcuts — agent handles same via free text)
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("check",   check_emails))
    app.add_handler(CommandHandler("send",    send_email))
    app.add_handler(CommandHandler("reply",   reply_email))
    app.add_handler(CommandHandler("draft",   draft_email))
    app.add_handler(CommandHandler("search",  search_emails))

    # Monitoring
    app.add_handler(CommandHandler("watch",   watch))
    app.add_handler(CommandHandler("unwatch", unwatch))
    app.add_handler(CommandHandler("vip",     vip_command))

    # Files & attachments
    app.add_handler(CommandHandler("clear",   clear_attachment))
    app.add_handler(MessageHandler(_FILE_FILTER, handle_file))

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(button_callback))

    # Autonomous AI agent — must be last (catches all plain text)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_with_ai))

    return app


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app = _build_app()

    if WEBHOOK_URL:
        # Webhook mode — PTB's aiohttp server binds to PORT, Render is happy
        webhook_path = BOT_TOKEN      # token as secret URL path
        logger.info(
            "Starting WEBHOOK mode — %s  (port %s)", WEBHOOK_URL, WEBHOOK_PORT
        )
        app.run_webhook(
            listen="0.0.0.0",
            port=WEBHOOK_PORT,
            url_path=webhook_path,
            webhook_url=f"{WEBHOOK_URL}/{webhook_path}",
        )
    else:
        # Polling mode — start health server so Render deploy check passes
        logger.info("Starting POLLING mode.")
        _start_health_server(WEBHOOK_PORT)
        app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
