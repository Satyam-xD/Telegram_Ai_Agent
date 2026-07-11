# 🤖 Telegram AI Email Agent

An advanced, self-hosted Telegram bot that acts as your personal AI-powered email assistant. It monitors your inbox in the background, pushes instant alerts, forwards attachments, auto-drafts replies, and supports full file/media sending — powered by **Google Gemini**, with **Claude** and **OpenAI** as automatic fallbacks.

---

## ✨ Features

| Feature | Description |
|---|---|
| 📬 **Smart Summaries** | AI-generated bullet-point summaries for unread emails |
| 🔔 **Auto-Polling** | Background inbox monitoring with push alerts — no manual `/check` needed |
| 🎛️ **Inline Buttons** | One-tap **Reply** / **Skip** buttons on every email alert |
| ✏️ **AI Drafting** | Generate a full email from a one-line topic using AI |
| 🔍 **Inbox Search** | Search by keyword, subject, or sender |
| ⭐ **VIP Alerts** | Instant priority flags for emails from specific senders |
| 📎 **File Attachments (Inbound)** | Email attachments (PDFs, images, docs) forwarded to Telegram automatically |
| 📎 **File Attachments (Outbound)** | Send any file/photo to the bot — it attaches to your next outgoing email |
| 🧠 **Conversation Memory** | Rolling context window for natural multi-turn AI chat |
| 🔁 **Multi-Provider AI Fallback** | Gemini → Claude → OpenAI, automatically on quota/rate-limit errors |

---

## 🧠 AI Fallback Chain

```
Gemini 2.5 Flash
  └→ Gemini 2.0 Flash
       └→ Gemini 2.5 Flash Lite
            └→ Gemini Flash Latest
                 └→ Claude 3 Haiku       (if CLAUDE_API_KEY set)
                      └→ OpenAI GPT-4o-mini  (if OPENAI_API_KEY set)
```

Only Gemini is required. Claude and OpenAI are fully optional — the bot activates them automatically if their keys are present.

---

## 🛠️ Requirements

- **Python 3.8+**
- `python-telegram-bot[job-queue]`
- `google-generativeai`
- `anthropic`
- `openai`
- `imapclient`
- `python-dotenv`

---

## 🚀 Getting Started

### 1. Clone the Repository
```bash
git clone https://github.com/Satyam-xD/Telegram_Ai_Agent.git
cd Telegram_Ai_Agent
```

### 2. Set Up Virtual Environment
```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac / Linux
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment
```bash
cp .env.example .env
```

Edit `.env`:

```env
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
AUTHORIZED_USER_ID=your_telegram_user_id

# AI Providers (only Gemini is required)
GEMINI_API_KEY=your_gemini_key
CLAUDE_API_KEY=your_claude_key        # optional
OPENAI_API_KEY=your_openai_key        # optional

# Email
EMAIL_USERNAME=your@email.com
EMAIL_PASSWORD=your_app_password
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=465

# Auto-polling interval in minutes
POLL_INTERVAL_MINUTES=5
```

> ⚠️ **Gmail users**: Use an [App Password](https://myaccount.google.com/apppasswords) — not your main account password.

### 5. Run the Bot
```bash
python mail_agent.py
```

---

## 🤖 Commands

### 📩 Email
| Command | Description |
|---|---|
| `/check` | Summarize latest 5 unread emails with inline Reply buttons |
| `/reply [id] [instructions]` | AI-draft and send a reply to an email by ID |
| `/send [to] [subject] \| [body]` | Send a new email (separate subject and body with `\|`) |
| `/draft [to] [topic]` | Generate a full email from a short topic — reply *send* to confirm |
| `/search [keyword]` | Search inbox by keyword or `/search from:email@example.com` |

### 🔔 Monitoring
| Command | Description |
|---|---|
| `/watch` | Start background polling — receive push alerts for new emails |
| `/unwatch` | Stop background monitoring |

### ⭐ VIP Alerts
| Command | Description |
|---|---|
| `/vip add email` | Flag emails from this sender with ⭐ and send instant alerts |
| `/vip remove email` | Remove a VIP sender |
| `/vip list` | Show all VIP senders |

### 📎 Files & Media
| Action | Description |
|---|---|
| *Send any file/photo to the bot* | Saves it as a pending attachment for the next outgoing email |
| `/clear` | Discard the pending attachment |

### 💬 Chat
Send any text message (no `/` prefix) to chat with the AI assistant. The bot remembers the last 8 exchanges for context.

---

## 🔒 Security

All commands are restricted to the single `AUTHORIZED_USER_ID` set in your `.env`. Unauthorized requests receive a silent rejection. Get your Telegram user ID from [@userinfobot](https://t.me/userinfobot).
