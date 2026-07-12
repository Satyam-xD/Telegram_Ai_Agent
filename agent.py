"""
agent.py — Autonomous AI agent with native tool-calling.

The agent receives natural language, decides which tools to use, executes them
(possibly chaining multiple calls), and returns a final natural-language reply.

Tool-calling is native for all three providers:
  Gemini  → FunctionDeclaration / FunctionResponse (protos)
  Claude  → tool_use / tool_result blocks
  OpenAI  → function calling / tool messages

Available tools (11):
  check_inbox, read_email, search_emails,
  draft_email, send_email, reply_to_email,
  start_monitoring, stop_monitoring,
  add_vip, remove_vip, list_vip
"""
from __future__ import annotations

import json
import logging

import google.generativeai as genai
from google.generativeai import protos

import ai_engine
from config import POLL_INTERVAL_MINS, claude_client, openai_client
from email_utils import (
    build_message,
    cleanup_file,
    fetch_msg,
    get_attachments,
    get_body,
    imap_connect,
    smtp_connect,
)

logger = logging.getLogger(__name__)

_MAX_ROUNDS = 8          # max tool-call iterations per request
_HISTORY_LIMIT = 24      # messages kept in rolling memory


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an autonomous AI Email Assistant running inside a Telegram bot.
You help the user manage their inbox through natural conversation.
You have 11 tools. Use them proactively — don't wait to be asked twice.

## Rules

1. **Act immediately.** Interpret intent and call the right tool(s) without
   unnecessary clarifying questions.

2. **Draft before send.** For ANY outgoing email or reply, ALWAYS call
   `draft_email` first — never `send_email` directly. The user will confirm.
   Only call `send_email` if the user explicitly said "send" / "yes" /
   "go ahead" in a *follow-up* message after seeing the draft.

3. **Chain tools** for complex requests.
   e.g. "check emails and reply to the one from Alice":
        → check_inbox → find Alice's ID → reply_to_email

4. **Be concise and friendly** in final replies. Summarise what you did.

## Conversation history
{history}
"""


# ── Tool schema (provider-agnostic definition) ────────────────────────────────

_TOOLS: list[dict] = [
    {
        "name": "check_inbox",
        "description": (
            "Fetch and summarise the latest unread emails. "
            "Call this whenever the user asks about new / unread emails."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of latest unread emails to fetch (default 5, max 10).",
                }
            },
            "required": [],
        },
    },
    {
        "name": "read_email",
        "description": "Read the full content of a specific email by its numeric ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "msg_id": {
                    "type": "integer",
                    "description": "Numeric email message ID.",
                }
            },
            "required": ["msg_id"],
        },
    },
    {
        "name": "search_emails",
        "description": (
            "Search emails by keyword or sender. "
            "Use plain text to search subject/body, "
            "or 'from:email@example.com' to filter by sender."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, e.g. 'invoice' or 'from:boss@company.com'.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "draft_email",
        "description": (
            "Create and preview an email draft for user confirmation. "
            "ALWAYS call this before sending any new email. "
            "The user then confirms by saying 'send'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to":      {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string", "description": "Subject line."},
                "body":    {"type": "string", "description": "Full professional email body."},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "send_email",
        "description": (
            "Send an email immediately. "
            "Only call this after the user has explicitly confirmed a pending draft."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to":      {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string", "description": "Subject line."},
                "body":    {"type": "string", "description": "Email body text."},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "reply_to_email",
        "description": (
            "Compose and preview a reply to a specific email. "
            "Fetches the original, AI-writes the reply, and shows a draft for confirmation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "msg_id": {
                    "type": "integer",
                    "description": "ID of the email to reply to.",
                },
                "instruction": {
                    "type": "string",
                    "description": "What the reply should say or accomplish.",
                },
            },
            "required": ["msg_id", "instruction"],
        },
    },
    {
        "name": "start_monitoring",
        "description": (
            "Start background inbox monitoring. "
            "The bot will push Telegram notifications for every new email."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "stop_monitoring",
        "description": "Stop background inbox monitoring and push notifications.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "add_vip",
        "description": "Add an email address to the VIP list (starred alerts).",
        "parameters": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Email address to mark as VIP."}
            },
            "required": ["email"],
        },
    },
    {
        "name": "remove_vip",
        "description": "Remove an email address from the VIP list.",
        "parameters": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Email address to remove from VIP."}
            },
            "required": ["email"],
        },
    },
    {
        "name": "list_vip",
        "description": "List all VIP email addresses currently configured.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]

# Progress messages shown to the user before each tool executes
_STATUS: dict[str, str] = {
    "check_inbox":      "📥 Checking your inbox…",
    "read_email":       "📖 Reading email…",
    "search_emails":    "🔍 Searching emails…",
    "draft_email":      "✏️ Composing draft…",
    "send_email":       "📤 Sending…",
    "reply_to_email":   "✍️ Drafting reply…",
    "start_monitoring": "👀 Enabling monitoring…",
    "stop_monitoring":  "🔕 Disabling monitoring…",
    "add_vip":          "⭐ Updating VIP list…",
    "remove_vip":       "⭐ Updating VIP list…",
    "list_vip":         "⭐ Fetching VIP list…",
}


# ── Provider-specific schema builders ─────────────────────────────────────────

def _gemini_tools() -> list:
    _type = {
        "string":  protos.Type.STRING,
        "integer": protos.Type.INTEGER,
        "boolean": protos.Type.BOOLEAN,
        "number":  protos.Type.NUMBER,
    }
    decls = []
    for t in _TOOLS:
        props = {
            name: protos.Schema(
                type=_type.get(pdef.get("type", "string"), protos.Type.STRING),
                description=pdef.get("description", ""),
            )
            for name, pdef in t["parameters"].get("properties", {}).items()
        }
        decls.append(protos.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters=protos.Schema(
                type=protos.Type.OBJECT,
                properties=props,
                required=t["parameters"].get("required", []),
            ),
        ))
    return [protos.Tool(function_declarations=decls)]


def _claude_tools() -> list:
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": {
                "type": "object",
                "properties": t["parameters"].get("properties", {}),
                "required": t["parameters"].get("required", []),
            },
        }
        for t in _TOOLS
    ]


def _openai_tools() -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": {
                    "type": "object",
                    "properties": t["parameters"].get("properties", {}),
                    "required": t["parameters"].get("required", []),
                },
            },
        }
        for t in _TOOLS
    ]


# ── Tool implementations ──────────────────────────────────────────────────────

async def _exec(name: str, args: dict, update, context) -> str:
    """Dispatch a tool call; return a string result for the AI."""
    try:
        match name:
            case "check_inbox":
                return await _check_inbox(int(args.get("count", 5)))
            case "read_email":
                return await _read_email(int(args["msg_id"]))
            case "search_emails":
                return await _search_emails(str(args["query"]))
            case "draft_email":
                return await _draft_email(
                    args["to"], args["subject"], args["body"], update, context,
                )
            case "send_email":
                return await _send_email(
                    args["to"], args["subject"], args["body"], update, context,
                )
            case "reply_to_email":
                return await _reply_to_email(
                    int(args["msg_id"]), str(args["instruction"]), update, context,
                )
            case "start_monitoring":
                return await _start_monitoring(update, context)
            case "stop_monitoring":
                return await _stop_monitoring(update, context)
            case "add_vip":
                return await _add_vip(str(args["email"]), update, context)
            case "remove_vip":
                return await _remove_vip(str(args["email"]), update, context)
            case "list_vip":
                return _list_vip(context)
            case _:
                return f"Unknown tool: {name}"
    except Exception as exc:
        logger.error("Tool %s failed: %s", name, exc)
        return f"Error in {name}: {exc}"


async def _check_inbox(count: int) -> str:
    count = min(max(count, 1), 10)
    with imap_connect() as client:
        unseen = client.search(["UNSEEN"])
        if not unseen:
            return "Inbox is clear — no unread emails."
        latest = unseen[-count:]
        lines = [f"Total unread: {len(unseen)}. Showing latest {len(latest)}:\n"]
        for mid in reversed(latest):
            msg  = fetch_msg(client, mid)
            body = get_body(msg)[:400]
            att  = " [attachment]" if get_attachments(msg) else ""
            lines.append(
                f"ID {mid}{att}\n"
                f"From: {msg.get('From', '?')}\n"
                f"Subject: {msg.get('Subject', '?')}\n"
                f"Preview: {body}\n"
            )
        return "\n".join(lines)


async def _read_email(msg_id: int) -> str:
    with imap_connect() as client:
        msg = fetch_msg(client, msg_id)
    if not msg:
        return f"Email {msg_id} not found."
    atts = [a[0] for a in get_attachments(msg)]
    return (
        f"From: {msg.get('From', '?')}\n"
        f"Subject: {msg.get('Subject', '?')}\n"
        f"Date: {msg.get('Date', '')}\n"
        f"Attachments: {', '.join(atts) or 'None'}\n\n"
        f"{get_body(msg)[:2500]}"
    )


async def _search_emails(query: str) -> str:
    with imap_connect() as client:
        criteria = (
            ["FROM", query[5:].strip()]
            if query.lower().startswith("from:")
            else ["TEXT", query]
        )
        ids = client.search(criteria)
        if not ids:
            return f"No emails found for: {query}"
        latest = ids[-5:]
        lines = [f"Found {len(ids)} result(s) for '{query}'. Latest {len(latest)}:\n"]
        for mid in reversed(latest):
            msg = fetch_msg(client, mid)
            lines.append(
                f"ID {mid}: {msg.get('Subject', '?')} — from {msg.get('From', '?')}"
            )
        return "\n".join(lines)


async def _draft_email(
    to: str, subject: str, body: str, update, context,
    in_reply_to: str = "", references: str = "",
) -> str:
    """Store draft and display preview to user. Returns status for the AI."""
    context.user_data["draft"] = {
        "to": to, "subject": subject, "body": body,
        "in_reply_to": in_reply_to, "references": references,
    }
    pending     = context.user_data.get("pending_attachment")
    attach_note = f"\n\n📎 *Attachment:* `{pending['filename']}`" if pending else ""
    await update.message.reply_text(
        f"📝 *Draft Ready!*\n\n"
        f"*To:* `{to}`\n"
        f"*Subject:* {subject}\n\n"
        f"{body}{attach_note}\n\n"
        "──────────────────────────\n"
        "Reply *send* to send · *cancel* to discard",
        parse_mode="Markdown",
    )
    return f"Draft shown to user (To: {to}, Subject: {subject}). Awaiting confirmation."


async def _send_email(to: str, subject: str, body: str, update, context) -> str:
    pending = context.user_data.get("pending_attachment")
    msg     = build_message(to, subject, body, attachment=pending)
    with smtp_connect() as srv:
        srv.send_message(msg)
    if pending:
        cleanup_file(pending["path"])
        context.user_data.pop("pending_attachment", None)
    context.user_data.pop("draft", None)
    await update.message.reply_text(
        f"✅ *Email sent to {to}!*\n*Subject:* {subject}",
        parse_mode="Markdown",
    )
    return f"Email sent to {to}."


async def _reply_to_email(msg_id: int, instruction: str, update, context) -> str:
    with imap_connect() as client:
        orig = fetch_msg(client, msg_id)
    if not orig:
        return f"Email {msg_id} not found."
    orig_subject = orig.get("Subject", "(No Subject)")
    orig_from    = orig.get("From", "(Unknown)")
    reply_to     = orig.get("Reply-To") or orig_from
    orig_msg_id  = orig.get("Message-ID", "")
    reply_body   = ai_engine.generate(
        f"Write a professional email reply.\n\n"
        f"Instructions: {instruction}\n\n"
        f"Original — From: {orig_from}\nSubject: {orig_subject}\n"
        f"Body:\n{get_body(orig)[:1500]}\n\n"
        f"Write ONLY the email body. No subject line, no placeholders."
    )
    subject = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"
    return await _draft_email(
        reply_to, subject, reply_body, update, context,
        in_reply_to=orig_msg_id,
        references=orig.get("References", ""),
    )


async def _start_monitoring(update, context) -> str:
    if context.bot_data.get("watching"):
        return "Monitoring is already active."
    from handlers.monitoring import poll_emails   # local — avoids circular import
    context.bot_data["watching"]      = True
    context.bot_data["watch_chat_id"] = update.effective_chat.id
    context.bot_data.setdefault("seen_email_ids", set())
    context.job_queue.run_repeating(
        poll_emails,
        interval=POLL_INTERVAL_MINS * 60,
        first=10,
        name="email_poller",
    )
    await update.message.reply_text(
        f"👀 *Monitoring started!* Checking every {POLL_INTERVAL_MINS} min.",
        parse_mode="Markdown",
    )
    return f"Monitoring started ({POLL_INTERVAL_MINS} min interval)."


async def _stop_monitoring(update, context) -> str:
    context.bot_data["watching"] = False
    for job in context.job_queue.get_jobs_by_name("email_poller"):
        job.schedule_removal()
    await update.message.reply_text("🔕 Monitoring stopped.")
    return "Monitoring stopped."


async def _add_vip(email: str, update, context) -> str:
    context.bot_data.setdefault("vip_senders", set()).add(email.lower())
    await update.message.reply_text(f"⭐ `{email}` added to VIP.", parse_mode="Markdown")
    return f"Added {email} to VIP."


async def _remove_vip(email: str, update, context) -> str:
    context.bot_data.setdefault("vip_senders", set()).discard(email.lower())
    await update.message.reply_text(f"✅ `{email}` removed from VIP.", parse_mode="Markdown")
    return f"Removed {email} from VIP."


def _list_vip(context) -> str:
    vip = context.bot_data.get("vip_senders", set())
    return ("VIP senders:\n" + "\n".join(f"• {s}" for s in sorted(vip))) if vip else "VIP list is empty."


# ── Provider runners ──────────────────────────────────────────────────────────

async def _gemini(system: str, message: str, update, context) -> str:
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        tools=_gemini_tools(),
        system_instruction=system,
    )
    chat = model.start_chat()
    resp = chat.send_message(message)

    for _ in range(_MAX_ROUNDS):
        calls = [
            p.function_call
            for p in resp.candidates[0].content.parts
            if hasattr(p, "function_call") and p.function_call.name
        ]
        if not calls:
            break
        parts = []
        for fc in calls:
            if msg := _STATUS.get(fc.name):
                await update.message.reply_text(msg)
            result = await _exec(fc.name, dict(fc.args), update, context)
            parts.append(protos.Part(
                function_response=protos.FunctionResponse(
                    name=fc.name, response={"result": result}
                )
            ))
        resp = chat.send_message(parts)

    try:
        return resp.text or ""
    except Exception:
        return ""


async def _claude(system: str, message: str, update, context) -> str:
    msgs  = [{"role": "user", "content": message}]
    tools = _claude_tools()
    for _ in range(_MAX_ROUNDS):
        resp     = claude_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=4096,
            system=system,
            tools=tools,
            messages=msgs,
        )
        uses     = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            return next((b.text for b in resp.content if hasattr(b, "text")), "")
        msgs.append({"role": "assistant", "content": resp.content})
        results  = []
        for tu in uses:
            if msg := _STATUS.get(tu.name):
                await update.message.reply_text(msg)
            r = await _exec(tu.name, tu.input, update, context)
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": r})
        msgs.append({"role": "user", "content": results})
    return ""


async def _openai(system: str, message: str, update, context) -> str:
    msgs  = [{"role": "system", "content": system}, {"role": "user", "content": message}]
    tools = _openai_tools()
    for _ in range(_MAX_ROUNDS):
        resp   = openai_client.chat.completions.create(
            model="gpt-4o-mini", tools=tools, messages=msgs,
        )
        choice = resp.choices[0]
        if choice.finish_reason == "stop" or not choice.message.tool_calls:
            return choice.message.content or ""
        msgs.append(choice.message)
        for tc in choice.message.tool_calls:
            if msg := _STATUS.get(tc.function.name):
                await update.message.reply_text(msg)
            r = await _exec(tc.function.name, json.loads(tc.function.arguments), update, context)
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": r})
    return ""


# ── Public entry point ────────────────────────────────────────────────────────

async def run(text: str, update, context) -> None:
    """
    Run the autonomous agent for a single user message.
    Tries Gemini → Claude → OpenAI, sends the final reply to Telegram.
    """
    history: list = context.user_data.setdefault("chat_history", [])
    if len(history) > _HISTORY_LIMIT:
        history = history[-_HISTORY_LIMIT:]
        context.user_data["chat_history"] = history

    system    = _SYSTEM_PROMPT.format(history="\n".join(history) or "No history yet.")
    last_err  = None
    result    = ""

    # Gemini ──────────────────────────────────────────────────────────────────
    try:
        result = await _gemini(system, text, update, context)
    except Exception as exc:
        logger.warning("Gemini agent failed: %s", exc)
        last_err = exc

    # Claude ──────────────────────────────────────────────────────────────────
    if not result and claude_client:
        try:
            result = await _claude(system, text, update, context)
        except Exception as exc:
            logger.warning("Claude agent failed: %s", exc)
            last_err = exc

    # OpenAI ──────────────────────────────────────────────────────────────────
    if not result and openai_client:
        try:
            result = await _openai(system, text, update, context)
        except Exception as exc:
            logger.error("OpenAI agent failed: %s", exc)
            last_err = exc

    if result and result.strip():
        history.extend([f"User: {text}", f"Assistant: {result}"])
        context.user_data["chat_history"] = history
        await update.message.reply_text(result)
    elif not result:
        await update.message.reply_text(f"❌ All AI providers failed: {last_err}")
