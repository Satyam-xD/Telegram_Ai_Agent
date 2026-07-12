"""
email_utils.py — Pure helpers for parsing emails and building outgoing messages.

No Telegram or AI dependencies — safe to unit-test in isolation.

Send priority:
  1. Resend API (HTTPS, works everywhere including Render free tier)
  2. SMTP SSL / STARTTLS fallback (for local dev without Resend key)
"""
import email
import logging
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
    RESEND_API_KEY,
)

logger = logging.getLogger(__name__)


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
    """
    Return an authenticated IMAPClient (caller must use as context manager).

    Tries in order:
      1. SSL on port 993
      2. STARTTLS on port 143  (fallback when 993 is blocked)

    Raises a descriptive RuntimeError if both fail.
    """
    attempts = [
        (True,  993, "IMAP SSL:993"),
        (False, 143, "IMAP STARTTLS:143"),
    ]
    last_error: Exception | None = None
    for use_ssl, port, label in attempts:
        try:
            client = IMAPClient(EMAIL_IMAP, port=port, ssl=use_ssl, timeout=15)
            if not use_ssl:
                client.starttls()
            client.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            client.select_folder("INBOX")
            return client
        except OSError as exc:
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            continue

    raise RuntimeError(
        f"Cannot reach IMAP server '{EMAIL_IMAP}'. "
        f"Tried {' and '.join(a[2] for a in attempts)}. "
        "Possible causes:\n"
        "  • Your network blocks outbound IMAP (ports 993/143)\n"
        "  • EMAIL_IMAP_SERVER is wrong in your .env\n"
        f"Last error: {last_error}"
    )


def fetch_msg(client: IMAPClient, msg_id: int):
    """Fetch a single raw email and parse it into an email.Message."""
    raw = client.fetch([msg_id], ["RFC822"])
    if not raw or msg_id not in raw:
        return None
    return email.message_from_bytes(raw[msg_id][b"RFC822"], policy=default)


# ── SMTP helpers (local-dev fallback) ──────────────────────────────────────────────

def smtp_connect() -> smtplib.SMTP:
    """
    Return an authenticated SMTP connection.

    Tries in order:
      1. SMTP_SSL on EMAIL_SMTP_PORT (default 465)
      2. SMTP + STARTTLS on port 587  (fallback when 465 is blocked)

    Raises a descriptive RuntimeError if both fail.
    """
    attempts = [
        ("ssl",      EMAIL_SMTP_PORT, f"SMTP_SSL:{EMAIL_SMTP_PORT}"),
        ("starttls", 587,             "SMTP+STARTTLS:587"),
    ]
    if EMAIL_SMTP_PORT == 587:
        attempts = [("starttls", 587, "SMTP+STARTTLS:587")]

    last_error: Exception | None = None
    for method, port, label in attempts:
        try:
            if method == "ssl":
                srv = smtplib.SMTP_SSL(EMAIL_SMTP, port, timeout=15)
            else:
                srv = smtplib.SMTP(EMAIL_SMTP, port, timeout=15)
                srv.ehlo()
                srv.starttls()
                srv.ehlo()
            srv.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            return srv
        except OSError as exc:
            last_error = exc
            continue
        except smtplib.SMTPAuthenticationError as exc:
            raise RuntimeError(
                f"SMTP login failed on {label}. "
                "Check EMAIL_USERNAME / EMAIL_PASSWORD in your .env. "
                "Gmail: use an App Password, not your main password."
            ) from exc
        except smtplib.SMTPException as exc:
            last_error = exc
            continue

    raise RuntimeError(
        f"Cannot reach {EMAIL_SMTP} on ports 465/587. "
        f"Last error: {last_error}"
    )


# ── Unified send (Resend → SMTP fallback) ───────────────────────────────────────

def send_message(
    to: str,
    subject: str,
    body: str,
    attachment: dict | None = None,
    in_reply_to: str = "",
    references: str = "",
) -> str:
    """
    Send an email using the best available transport.

    Priority:
      1. Resend API  — works on Render free tier (pure HTTPS)
      2. SMTP        — local dev fallback

    Returns a human-readable status string.
    """
    if RESEND_API_KEY:
        return _send_via_resend(to, subject, body, attachment)
    return _send_via_smtp(to, subject, body, attachment, in_reply_to, references)


def _send_via_resend(
    to: str,
    subject: str,
    body: str,
    attachment: dict | None = None,
) -> str:
    """Send through Resend's HTTP API (port 443 — never blocked)."""
    import resend  # optional dep; present when RESEND_API_KEY is set
    resend.api_key = RESEND_API_KEY

    params: dict = {
        "from":    f"AI Agent <{EMAIL_USERNAME}>",
        "to":      [to],
        "subject": subject,
        "text":    body,
    }
    if attachment:
        import base64
        with open(attachment["path"], "rb") as f:
            params["attachments"] = [{
                "filename": attachment["filename"],
                "content":  base64.b64encode(f.read()).decode("utf-8"),
            }]

    resend.Emails.send(params)
    return f"Sent via Resend to {to}."


def _send_via_smtp(
    to: str,
    subject: str,
    body: str,
    attachment: dict | None = None,
    in_reply_to: str = "",
    references: str = "",
) -> str:
    """Send through SMTP (local dev — ports 465/587)."""
    msg = build_message(to, subject, body, attachment, in_reply_to, references)
    with smtp_connect() as srv:
        srv.send_message(msg)
    return f"Sent via SMTP to {to}."



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
