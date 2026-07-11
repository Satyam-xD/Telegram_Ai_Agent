"""
email_utils.py — Pure helpers for parsing emails and building outgoing messages.

No Telegram or AI dependencies — safe to unit-test in isolation.
"""
import email
import os
import re
import smtplib
import tempfile
from email.message import EmailMessage
from email.policy import default

from imapclient import IMAPClient

from config import (
    EMAIL_IMAP,
    EMAIL_PASSWORD,
    EMAIL_SMTP,
    EMAIL_SMTP_PORT,
    EMAIL_USERNAME,
)


# ── HTML / body parsing ───────────────────────────────────────────────────────

def clean_html(raw: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    text = re.sub(r"<script.*?>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?>.*?</style>",   "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<.*?>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def get_body(msg) -> str:
    """Extract the plaintext body from an email.Message object."""
    if msg.is_multipart():
        html_fallback = None
        for part in msg.walk():
            ct  = part.get_content_type()
            cd  = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                continue
            if ct == "text/plain":
                try:
                    return part.get_payload(decode=True).decode("utf-8", errors="ignore")
                except Exception:
                    pass
            elif ct == "text/html":
                try:
                    html_fallback = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                except Exception:
                    pass
        if html_fallback:
            return clean_html(html_fallback)
    else:
        try:
            payload = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
            return clean_html(payload) if msg.get_content_type() == "text/html" else payload
        except Exception:
            pass
    return ""


def get_attachments(msg) -> list[tuple[str, str, bytes]]:
    """Return [(filename, mime_type, data), ...] for all email attachments."""
    results = []
    if not msg.is_multipart():
        return results
    for part in msg.walk():
        if "attachment" not in str(part.get("Content-Disposition", "")):
            continue
        filename = part.get_filename()
        data     = part.get_payload(decode=True)
        if filename and data:
            results.append((filename, part.get_content_type() or "application/octet-stream", data))
    return results


# ── IMAP helpers ──────────────────────────────────────────────────────────────

def imap_connect() -> IMAPClient:
    """Return an authenticated IMAPClient (caller must use as context manager)."""
    client = IMAPClient(EMAIL_IMAP, ssl=True, timeout=15)
    client.login(EMAIL_USERNAME, EMAIL_PASSWORD)
    client.select_folder("INBOX")
    return client


def fetch_msg(client: IMAPClient, msg_id: int):
    """Fetch a single raw email and parse it into an email.Message."""
    raw = client.fetch([msg_id], ["RFC822"])
    if not raw or msg_id not in raw:
        return None
    return email.message_from_bytes(raw[msg_id][b"RFC822"], policy=default)


# ── SMTP helpers ──────────────────────────────────────────────────────────────

def smtp_connect() -> smtplib.SMTP_SSL:
    """Return an authenticated SMTP_SSL connection."""
    server = smtplib.SMTP_SSL(EMAIL_SMTP, EMAIL_SMTP_PORT, timeout=15)
    server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
    return server


def build_message(
    to: str,
    subject: str,
    body: str,
    attachment: dict | None = None,
    in_reply_to: str = "",
    references: str = "",
) -> EmailMessage:
    """Construct a ready-to-send EmailMessage."""
    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"]    = EMAIL_USERNAME
    msg["To"]      = to
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"]  = f"{references} {in_reply_to}".strip()
    if attachment:
        _attach_file(msg, attachment)
    return msg


def _attach_file(msg: EmailMessage, attachment: dict) -> None:
    """Inline-attach a pending file dict to an EmailMessage."""
    maintype, subtype = (
        attachment["mime_type"].split("/", 1)
        if "/" in attachment["mime_type"]
        else ("application", "octet-stream")
    )
    with open(attachment["path"], "rb") as f:
        msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=attachment["filename"])


# ── Temp-file helpers ─────────────────────────────────────────────────────────

def save_to_tempfile(data: bytes, suffix: str) -> str:
    """Write bytes to a named temp file and return its path."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        return tmp.name


def cleanup_file(path: str) -> None:
    """Silently delete a file path."""
    try:
        os.unlink(path)
    except Exception:
        pass
