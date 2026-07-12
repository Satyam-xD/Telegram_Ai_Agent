"""
config.py — Single source of truth for all environment variables and AI clients.
"""
import logging
import os
import warnings

import anthropic
import google.generativeai as genai
from dotenv import load_dotenv
from openai import OpenAI

warnings.filterwarnings("ignore", category=FutureWarning)
load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Telegram ──────────────────────────────────────────────────────────────────
BOT_TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN", "")
AUTHORIZED_USER_ID = os.getenv("AUTHORIZED_USER_ID", "")

# ── AI keys ───────────────────────────────────────────────────────────────────
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
CLAUDE_KEY = os.getenv("CLAUDE_API_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

# ── Email ─────────────────────────────────────────────────────────────────────
EMAIL_USERNAME  = os.getenv("EMAIL_USERNAME", "")
EMAIL_PASSWORD  = os.getenv("EMAIL_PASSWORD", "")
EMAIL_IMAP      = os.getenv("EMAIL_IMAP_SERVER", "imap.gmail.com")
EMAIL_SMTP      = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", 465))

# ── Polling / monitoring ──────────────────────────────────────────────────────
POLL_INTERVAL_MINS = int(os.getenv("POLL_INTERVAL_MINUTES", 5))

# ── Render / webhook ──────────────────────────────────────────────────────────
# Set WEBHOOK_URL to your Render service URL (e.g. https://mybot.onrender.com)
# to enable webhook mode. Leave unset to use polling (local dev).
WEBHOOK_URL  = os.getenv("WEBHOOK_URL")          # e.g. https://mybot.onrender.com
WEBHOOK_PORT = int(os.getenv("PORT", 8443))       # Render injects PORT automatically

# ── Validation ────────────────────────────────────────────────────────────────
_missing = [k for k, v in {
    "TELEGRAM_BOT_TOKEN": BOT_TOKEN,
    "AUTHORIZED_USER_ID": AUTHORIZED_USER_ID,
    "GEMINI_API_KEY":     GEMINI_KEY,
    "EMAIL_USERNAME":     EMAIL_USERNAME,
    "EMAIL_PASSWORD":     EMAIL_PASSWORD,
}.items() if not v]

if _missing:
    logger.error("Missing required env vars: %s — check your .env file.", ", ".join(_missing))
    raise SystemExit(1)

# ── AI client initialisation ──────────────────────────────────────────────────
genai.configure(api_key=GEMINI_KEY)

openai_client: OpenAI | None = None
if OPENAI_KEY:
    openai_client = OpenAI(api_key=OPENAI_KEY)
    logger.info("OpenAI client initialised (fallback #2).")

claude_client: anthropic.Anthropic | None = None
if CLAUDE_KEY:
    claude_client = anthropic.Anthropic(api_key=CLAUDE_KEY)
    logger.info("Claude client initialised (fallback #1).")
