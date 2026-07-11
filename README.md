# 🤖 Telegram AI Email Agent

An advanced, self-hosted Telegram bot that acts as your personal AI-powered email assistant. It monitors your inbox, automatically drafts replies, summarizes unread emails, and sends outgoing emails using Google Gemini (with OpenAI GPT-4o-mini as a resilient fallback).

---

## ✨ Features

- **📬 Smart Summarization:** Fetch the latest unread emails and get concise bulleted summaries via Google Gemini.
- **✍️ AI-Powered Replies:** Draft context-aware professional replies based on email history and your simple custom instructions.
- **✉️ Direct SMTP Mailer:** Compose and send outbound emails right from your Telegram chat using custom formatting rules.
- **🧠 Resilient Fallback Mechanics:** Built-in model rotation (Gemini 2.5/2.0/Lite/Flash) and OpenAI GPT-4o-mini integration to handle rate limits and API quota constraints.
- **🔒 Security & Auth:** Restricts interaction exclusively to your configured Telegram user ID, keeping your inbox secure.
- **🧵 Auto-Threading:** Automatically adds email references and header metadata so replies thread cleanly in modern email clients.

---

## 🛠️ Tech Stack & Requirements

- **Python 3.8+**
- `python-telegram-bot` for Telegram Bot API integration
- `google-generativeai` & `openai` for LLM drafting and summaries
- `imapclient` for secure SSL-based IMAP email fetching
- `smtplib` for SMTP sending

---

## 🚀 Getting Started

### 1. Clone the Repository
```bash
git clone https://github.com/Satyam-xD/Telegram_Ai_Agent.git
cd Telegram_Ai_Agent
```

### 2. Set Up Virtual Environment
It is highly recommended to run this bot in a virtual environment:
```bash
# Create virtual environment
python -m venv .venv

# Activate it (Windows)
.venv\Scripts\activate

# Activate it (Mac/Linux)
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configuration
Create a `.env` file in the root directory based on the `.env.example` template:
```bash
cp .env.example .env
```

Open `.env` and fill in the required environment variables:
```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
AUTHORIZED_USER_ID=your_telegram_user_id

# AI API Credentials
GEMINI_API_KEY=your_gemini_api_key
OPENAI_API_KEY=your_openai_api_key_optional_fallback

# Email Credentials
EMAIL_USERNAME=your_email@example.com
EMAIL_PASSWORD=your_app_specific_password
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=465
```
> ⚠️ **Note for Gmail users:** You must use an **App Password** instead of your primary account password. Set up App Passwords in your [Google Account Settings](https://myaccount.google.com/).

---

## 🤖 Usage & Bot Commands

Start the bot by running:
```bash
python mail_agent.py
```

Once online, send `/start` to your bot on Telegram. It supports the following commands:

| Command | Usage | Description |
|---|---|---|
| **`/start`** | `/start` | Welcome message and commands guide. |
| **`/check`** | `/check` | Fetches the latest 5 unread emails, summarizes them into bullet points using AI, and presents them in a unified summary list. |
| **`/reply`** | `/reply [msg_id] [instructions]` | Automatically fetches the original message by ID, generates a professional response using Gemini based on your prompt, and sends the reply back. |
| **`/send`** | `/send [recipient] [subject] \| [body]` | Composes a new email from scratch. Use `\|` to separate the subject and the message body. |

### 💬 Chat Assistant
Sending a normal message (without any command prefix) to the bot triggers a general assistant chat. You can use this to brainstorm email replies, translate copy, or ask general questions.

---

## 🔒 Security
Your email agent is configured to verify the user ID of incoming Telegram requests. Any commands sent by unauthorized users will receive an `Unauthorized access` message and be ignored. Make sure `AUTHORIZED_USER_ID` is set to your correct numeric Telegram ID (you can get this from bots like `@userinfobot` on Telegram).
