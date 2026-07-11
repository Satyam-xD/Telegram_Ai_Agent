# 🤖 Telegram AI Email Agent

A self-hosted, modular Telegram bot that turns your inbox into a fully AI-powered command centre. Get push alerts for new emails, reply with a single tap, send files as attachments, and chat with a context-aware AI assistant — all from Telegram.

---

## ✨ Feature Overview

| Feature | Description |
|---|---|
| 📬 **AI Summaries** | Bullet-point summaries of unread emails via Gemini/Claude/OpenAI |
| 🔔 **Auto-Polling** | Background inbox monitoring — push alerts without ever typing `/check` |
| 🎛️ **Inline Buttons** | One-tap **Reply** / **Skip** on every email alert |
| ✏️ **AI Draft** | Generate a full professional email from a one-line topic |
| 🔍 **Inbox Search** | Search by keyword, subject, or sender |
| ⭐ **VIP Alerts** | Priority ⭐ flag + instant notification for emails from key senders |
| 📎 **Inbound Attachments** | Email PDFs, images, and docs forwarded directly to your Telegram |
| 📎 **Outbound Attachments** | Send any file/photo to the bot — it attaches to the next email you send |
| 🧠 **Conversation Memory** | Rolling 8-exchange context window for natural multi-turn AI chat |
| 🔁 **AI Fallback Chain** | Automatic failover across Gemini → Claude → OpenAI on quota/rate-limit errors |

---

## 🧠 AI Provider Fallback Chain

```
Gemini 2.5 Flash
  └→ Gemini 2.0 Flash
       └→ Gemini 2.5 Flash Lite
            └→ Gemini Flash Latest
                 └→ Claude 3 Haiku       (optional — requires CLAUDE_API_KEY)
                      └→ OpenAI GPT-4o-mini  (optional — requires OPENAI_API_KEY)
```

Only **Gemini is required**. Claude and OpenAI activate automatically when their keys are present.

---

## 🗂️ Project Structure

```
Telegram_Ai_Agent/
├── mail_agent.py          ← Entry point — registers handlers & starts the bot
├── config.py              ← Environment variables & AI client initialisation
├── ai_engine.py           ← Multi-provider generation with automatic fallback
├── email_utils.py         ← IMAP/SMTP helpers, email parser, message builder
├── keyboards.py           ← Inline keyboard factory & button callback handler
├── requirements.txt
├── .env.example
└── handlers/
    ├── commands.py        ← /start /check /send /reply /draft /search
    ├── monitoring.py      ← /watch /unwatch /vip + background poll job
    ├── files.py           ← File/media upload, /clear, attachment forwarding
    └── chat.py            ← AI chat with memory, draft flow & reply flow
```

Each module has a single responsibility — `email_utils.py` has zero Telegram/AI imports, `ai_engine.py` exposes one function (`generate`), and `mail_agent.py` contains only handler registration.

---

## 🛠️ Requirements

- **Python 3.10+**
- `python-telegram-bot[job-queue]` — Telegram Bot API + background jobs
- `google-generativeai` — Gemini (primary AI)
- `anthropic` — Claude (fallback AI, optional)
- `openai` — OpenAI GPT (fallback AI, optional)
- `imapclient` — IMAP inbox access
- `python-dotenv` — `.env` file loading

---

## 🚀 Getting Started

### 1. Clone the Repository
```bash
git clone https://github.com/Satyam-xD/Telegram_Ai_Agent.git
cd Telegram_Ai_Agent
```

### 2. Create a Virtual Environment
```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
```bash
cp .env.example .env
```

Open `.env` and fill in your credentials:

```env
# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=your_bot_token        # from @BotFather
AUTHORIZED_USER_ID=your_user_id         # from @userinfobot

# ── AI Providers (only Gemini is required) ────────────────────────────────────
GEMINI_API_KEY=your_gemini_key
CLAUDE_API_KEY=your_claude_key           # optional
OPENAI_API_KEY=your_openai_key           # optional

# ── Email (Gmail example) ─────────────────────────────────────────────────────
EMAIL_USERNAME=your@gmail.com
EMAIL_PASSWORD=your_app_password         # use an App Password, not your main password
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=465

# ── Auto-polling ──────────────────────────────────────────────────────────────
POLL_INTERVAL_MINUTES=5
```

> ⚠️ **Gmail users**: Enable 2-Step Verification and create an [App Password](https://myaccount.google.com/apppasswords) — the bot cannot use your main account password.

### 5. Run the Bot
```bash
python mail_agent.py
```

---

## 🤖 Command Reference

### 📩 Email Commands

| Command | Example | Description |
|---|---|---|
| `/start` | `/start` | Welcome message and full command guide, shows active AI providers |
| `/check` | `/check` | Fetch & AI-summarize your latest 5 unread emails with inline Reply buttons |
| `/send` | `/send bob@co.com Invoice \| Please find it attached.` | Send a new email (separate subject and body with `\|`) |
| `/reply` | `/reply 451 decline politely and suggest next week` | AI-draft a reply to an email by its ID and send it |
| `/draft` | `/draft boss@co.com request 3 days annual leave` | Generate a complete email from a short topic — confirm with *send* |
| `/search` | `/search invoice` or `/search from:hr@co.com` | Search inbox by keyword or by sender using `from:` prefix |

### 🔔 Auto-Monitoring

| Command | Description |
|---|---|
| `/watch` | Start background inbox polling — new emails arrive as Telegram alerts automatically |
| `/unwatch` | Stop background monitoring |

Each auto-alert includes an AI summary and inline **Reply / Skip** buttons. Email attachments are forwarded automatically.

### ⭐ VIP Alerts

| Command | Description |
|---|---|
| `/vip add email@example.com` | Add a VIP sender — emails from them are flagged ⭐ |
| `/vip remove email@example.com` | Remove a VIP sender |
| `/vip list` | Show all currently configured VIP senders |

### 📎 Files & Media

| Action | Description |
|---|---|
| *Send any file or photo to the bot* | Saved as a pending attachment for the next `/send`, `/reply`, or `/draft` |
| `/clear` | Discard the currently pending attachment |

Supported inbound types: documents, photos, videos, audio, voice messages.  
Supported outbound (from emails): PDFs, images, Word/Excel/Zip — anything with a `Content-Disposition: attachment` header is forwarded to Telegram automatically.

### 💬 AI Chat Assistant

Send any plain text (no `/` prefix) to talk to the AI. The bot maintains a rolling 8-exchange memory window, so you can have natural multi-turn conversations:

```
You:  summarize the last email from John
Bot:  [summary]
You:  now draft a reply declining the meeting
Bot:  [draft]
You:  make it shorter and more casual
Bot:  [revised draft]
```

After `/draft`, reply with:
- **`send`** — confirm and send the email
- **`cancel`** — discard the draft

---

## 🔒 Security

All commands are restricted to the single `AUTHORIZED_USER_ID` configured in your `.env`. Any request from a different Telegram user is silently rejected. Get your Telegram user ID from [@userinfobot](https://t.me/userinfobot).

Your `.env` file (containing all credentials) is excluded from version control via `.gitignore`.
