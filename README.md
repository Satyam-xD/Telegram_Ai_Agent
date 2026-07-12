# 🤖 Telegram AI Email Agent

An autonomous AI agent that manages your inbox through natural Telegram conversation.
No rigid commands needed — just talk to it. The AI decides what to do, chains multiple actions, and always asks before sending.

Deployable on **Render** in minutes. Runs locally with zero config changes.

---

## ✨ Features

| | Feature | Description |
|---|---|---|
| 🧠 | **Autonomous Agent** | Understands natural language — "check my emails and reply to anything from my boss" works out of the box |
| 🔧 | **Tool Chaining** | AI chains multiple actions in one message — check → read → draft → confirm |
| 📬 | **AI Summaries** | Bullet-point summaries of unread emails |
| 🔔 | **Push Monitoring** | Background polling — new emails arrive as Telegram alerts automatically |
| 🎛️ | **Inline Buttons** | One-tap **Reply / Skip** on every alert |
| ✏️ | **Smart Drafting** | Full professional email from one sentence, always shown for confirmation |
| 🔍 | **Inbox Search** | Search by keyword, subject, or `from:sender` |
| ⭐ | **VIP Alerts** | Priority ⭐ flag for emails from key senders |
| 📎 | **Attachments** | Send files to the bot → attaches to next email; email attachments forwarded to Telegram |
| 🔁 | **AI Fallback** | Auto-failover: Gemini → Claude → OpenAI. All three support native function calling |

---

## 🧠 How the Agent Works

```
You: "Any urgent emails? If there's one from my boss, draft a reply saying I'll be there."

Agent:
  → calls check_inbox()          finds 3 unread
  → calls search_emails("from:boss@...")  finds the one
  → calls reply_to_email(id, "say I'll be there")
  → shows draft in Telegram

You: "send it"
  → email sent ✅
```

The AI autonomously decides which of its **11 tools** to call, in what order, and how many times — all from a single natural language message.

---

## 🔧 Agent Tools

| Tool | What it does |
|---|---|
| `check_inbox` | Fetch & summarise latest unread emails |
| `read_email` | Read a specific email by ID |
| `search_emails` | Search by keyword or `from:sender` |
| `draft_email` | Compose draft → preview → wait for "send" |
| `send_email` | Send (only after user confirms a draft) |
| `reply_to_email` | AI-write a reply → preview → wait for "send" |
| `start_monitoring` | Enable push notifications for new emails |
| `stop_monitoring` | Disable push notifications |
| `add_vip` | Add a sender to VIP list (starred alerts) |
| `remove_vip` | Remove from VIP list |
| `list_vip` | Show all VIP senders |

---

## 🔁 AI Provider Chain

```
Gemini 2.5 Flash  (primary — required)
  └→ Claude 3 Haiku       (fallback #1 — optional)
       └→ OpenAI GPT-4o-mini  (fallback #2 — optional)
```

All three use **native function/tool calling** — no prompt hacks. If one fails or hits a quota limit, the next takes over automatically.

---

## 🗂️ Project Structure

```
├── mail_agent.py        Entry point — registers handlers & starts the bot
├── agent.py             Autonomous AI agent — tools, runners, provider loop
├── config.py            Environment variables & AI client initialisation
├── ai_engine.py         Simple text generation with Gemini → Claude → OpenAI fallback
├── email_utils.py       Pure IMAP/SMTP helpers (no Telegram/AI imports)
├── keyboards.py         Inline keyboard factory & button callback
├── utils.py             Shared helpers — auth check, show_draft, send_draft
├── requirements.txt
├── Procfile             Render start command
├── render.yaml          Render service config
├── .env.example
└── handlers/
    ├── commands.py      /start /check /send /reply /draft /search
    ├── monitoring.py    /watch /unwatch /vip + background poll job
    ├── files.py         File/media upload, /clear, attachment forwarding
    └── chat.py          Thin router — draft flow, reply flow, agent dispatch
```

**Design principles:**
- `email_utils.py` — zero Telegram/AI imports (pure, unit-testable)
- `agent.py` — zero Telegram handler boilerplate (pure AI logic)
- `chat.py` — zero business logic (routes only)
- `utils.py` — single source of truth for `is_authorized`, draft lifecycle

---

## 🚀 Quick Start (Local)

### 1. Clone
```bash
git clone https://github.com/Satyam-xD/Telegram_Ai_Agent.git
cd Telegram_Ai_Agent
```

### 2. Virtual environment
```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure `.env`
```bash
cp .env.example .env
```

Fill in your credentials:

```env
TELEGRAM_BOT_TOKEN=your_bot_token        # from @BotFather
AUTHORIZED_USER_ID=your_user_id          # from @userinfobot

GEMINI_API_KEY=your_gemini_key           # required
CLAUDE_API_KEY=your_claude_key           # optional
OPENAI_API_KEY=your_openai_key           # optional

EMAIL_USERNAME=your@gmail.com
EMAIL_PASSWORD=your_app_password         # Gmail: use an App Password
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=465

POLL_INTERVAL_MINUTES=5
# WEBHOOK_URL=                           # leave blank for local polling
```

> ⚠️ **Gmail users**: Enable 2-Step Verification and generate an [App Password](https://myaccount.google.com/apppasswords). The bot cannot use your main account password.

### 5. Run
```bash
python mail_agent.py
```

---

## ☁️ Deploy on Render

The bot auto-switches between **polling** (local) and **webhook** (Render) based on the `WEBHOOK_URL` env var — no code changes needed.

### Steps

1. **Push to GitHub**

2. **Create a new Web Service on Render**
   - Connect your GitHub repo
   - Render detects `render.yaml` automatically
   - Build command: `pip install -r requirements.txt`
   - Start command: `python mail_agent.py`

3. **Add environment variables** in the Render dashboard (all the same as `.env` above)

4. **After first deploy**, copy your Render URL (e.g. `https://telegram-ai-agent.onrender.com`)

5. **Set `WEBHOOK_URL`** to that URL in Render's environment variables

6. **Redeploy** — the bot switches to webhook mode automatically

> 💡 Render injects `PORT` automatically. Do not set it manually.

---

## 💬 Usage

### Natural language (recommended)

Just talk to the bot — no commands needed:

```
"Any new emails?"
"Check my inbox and summarise what's important"
"Send an email to alice@co.com about the budget meeting tomorrow"
"Reply to email 512 and say I'll attend"
"Start watching my inbox"
"Add boss@co.com to VIP"
"Search for emails from Amazon"
```

When the agent drafts an email, it always previews it first:
- Reply **`send`** (or "yes", "go ahead", "ok") → sends
- Reply **`cancel`** (or "no", "discard") → discards

### Commands (shortcuts)

Commands still work for quick, explicit actions:

| Command | Example | Description |
|---|---|---|
| `/start` | `/start` | Welcome message + active AI providers |
| `/check` | `/check` | Latest 5 unread emails with inline Reply buttons |
| `/send` | `/send bob@co.com Invoice \| Please find it attached.` | Send immediately (subject and body separated by `\|`) |
| `/send` | `/send` (no args) | Send pending draft (same as saying "send") |
| `/reply` | `/reply 451 decline politely` | AI-draft a reply to email ID 451 |
| `/draft` | `/draft boss@co.com request 3 days leave` | Generate email from a topic |
| `/search` | `/search invoice` or `/search from:hr@co.com` | Search inbox |
| `/watch` | `/watch` | Start push notifications |
| `/unwatch` | `/unwatch` | Stop monitoring |
| `/vip add` | `/vip add ceo@co.com` | Add VIP sender |
| `/vip remove` | `/vip remove ceo@co.com` | Remove VIP sender |
| `/vip list` | `/vip list` | List VIP senders |
| `/clear` | `/clear` | Discard pending file attachment |

### Attachments

Send any file or photo to the bot — it's saved as a pending attachment.
The next email you send (via command or chat) will include it automatically.

---

## 🔒 Security

- All messages from non-authorized users are **silently ignored** — no error, no acknowledgement
- The single `AUTHORIZED_USER_ID` is the only Telegram user that can interact with the bot
- `.env` is excluded from git via `.gitignore`
- The bot token is used as the webhook URL path (secret endpoint)

Get your Telegram user ID from [@userinfobot](https://t.me/userinfobot).
