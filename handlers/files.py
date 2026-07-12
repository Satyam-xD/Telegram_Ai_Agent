"""
handlers/files.py — Inbound file/media handler and email attachment forwarding.

Responsibilities:
  • Accept files/photos/video/audio and save as pending attachment.
  • Forward email attachments to a Telegram chat.
  • /clear command to discard a pending attachment.
"""
import logging
import mimetypes
import os
import tempfile

from telegram import Update
from telegram.ext import ContextTypes

from email_utils import cleanup_file, get_attachments, save_to_tempfile
from utils import is_authorized

logger = logging.getLogger(__name__)

_IMAGE_MIME = {"image/jpeg", "image/png", "image/gif", "image/webp"}


# ── Inbound: Telegram → pending attachment ────────────────────────────────────

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save any file/photo/video/audio sent by the user as a pending attachment."""
    if not is_authorized(update):
        return

    file_obj, filename, mime_type = await _resolve_file(update.message)
    if not file_obj:
        return

    old = context.user_data.get("pending_attachment")
    if old:
        cleanup_file(old["path"])

    tmp_dir   = tempfile.mkdtemp()
    file_path = os.path.join(tmp_dir, filename)
    await file_obj.download_to_drive(file_path)

    context.user_data["pending_attachment"] = {
        "path":      file_path,
        "filename":  filename,
        "mime_type": mime_type,
    }
    await update.message.reply_text(
        f"📎 *File saved:* `{filename}`\n\n"
        "Use `/send`, `/reply`, or `/draft` to attach it to your next email.\n"
        "Use `/clear` to discard.",
        parse_mode="Markdown",
    )


async def clear_attachment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/clear — discard the current pending attachment."""
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return

    pending = context.user_data.pop("pending_attachment", None)
    if pending:
        cleanup_file(pending["path"])
        await update.message.reply_text(
            f"🗑️ Cleared: `{pending['filename']}`", parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("No pending attachment to clear.")


# ── Outbound: email attachments → Telegram ────────────────────────────────────

async def forward_email_attachments(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    msg,
) -> None:
    """Download all attachments from an email.Message and push them to Telegram."""
    for filename, mime_type, data in get_attachments(msg):
        ext      = os.path.splitext(filename)[1] or mimetypes.guess_extension(mime_type) or ".bin"
        tmp_path = save_to_tempfile(data, ext)
        try:
            with open(tmp_path, "rb") as f:
                if mime_type in _IMAGE_MIME:
                    await context.bot.send_photo(
                        chat_id=chat_id, photo=f, caption=f"📎 {filename}"
                    )
                else:
                    await context.bot.send_document(
                        chat_id=chat_id, document=f, filename=filename, caption=f"📎 {filename}"
                    )
        except Exception as exc:
            logger.error("Failed to forward attachment %s: %s", filename, exc)
        finally:
            cleanup_file(tmp_path)


# ── Private helpers ───────────────────────────────────────────────────────────

async def _resolve_file(message) -> tuple:
    """Return (file_obj, filename, mime_type) from any supported Telegram message type."""
    if message.document:
        f = message.document
        return await f.get_file(), f.file_name or f"document_{f.file_unique_id}", f.mime_type or "application/octet-stream"
    if message.photo:
        p = message.photo[-1]
        return await p.get_file(), f"photo_{p.file_unique_id}.jpg", "image/jpeg"
    if message.video:
        v = message.video
        return await v.get_file(), v.file_name or f"video_{v.file_unique_id}.mp4", v.mime_type or "video/mp4"
    if message.audio:
        a = message.audio
        return await a.get_file(), a.file_name or f"audio_{a.file_unique_id}.mp3", a.mime_type or "audio/mpeg"
    if message.voice:
        vo = message.voice
        return await vo.get_file(), f"voice_{vo.file_unique_id}.ogg", "audio/ogg"
    return None, None, None
