import os
import re
import logging
import email
import warnings
from email.policy import default
from email.message import EmailMessage
import smtplib
from imapclient import IMAPClient
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from openai import OpenAI

# Suppress the GenerativeAI deprecation warning to keep terminal logs clean
warnings.filterwarnings("ignore", category=FutureWarning)

# Load environment variables
load_dotenv()

# Configure logging format
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Validate credentials
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTHORIZED_USER_ID = os.getenv("AUTHORIZED_USER_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

if not all([BOT_TOKEN, AUTHORIZED_USER_ID, GEMINI_KEY]):
    logger.error("Missing critical environment variables! Please check your .env file.")
    exit(1)

# Configure Gemini API & Fallback Logic
genai.configure(api_key=GEMINI_KEY)

# Initialize OpenAI client if key is provided
openai_client = None
if OPENAI_KEY:
    logger.info("OpenAI API key detected. OpenAI will be available as a fallback.")
    openai_client = OpenAI(api_key=OPENAI_KEY)

# Helper function to generate content with fallback models to bypass 429 quota limits
def generate_content_with_fallback(prompt: str) -> str:
    # List of models to try in order of preference
    fallback_models = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.5-flash-lite",
        "gemini-flash-latest"
    ]
    
    for idx, model_name in enumerate(fallback_models):
        try:
            logger.info(f"Attempting content generation using model: {model_name}")
            gen_model = genai.GenerativeModel(model_name)
            response = gen_model.generate_content(prompt)
            return response.text
        except Exception as e:
            err_msg = str(e)
            # If rate limited (429) and we have more models, try the next model
            if ("429" in err_msg or "quota" in err_msg.lower()) and idx < len(fallback_models) - 1:
                logger.warning(f"Model {model_name} rate-limited or quota exceeded. Falling back to the next model...")
                continue
            # If all Gemini models failed/rate-limited, fall back to OpenAI if configured
            elif openai_client:
                logger.warning("All Gemini models rate-limited or failed. Falling back to OpenAI (gpt-4o-mini)...")
                try:
                    res = openai_client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}]
                    )
                    return res.choices[0].message.content
                except Exception as oe:
                    logger.error(f"OpenAI fallback also failed: {oe}")
                    raise oe
            else:
                logger.error(f"Error executing generate_content with model {model_name}: {e}")
                raise e
    
    raise RuntimeError("All fallback models failed to generate content.")


# Helper: Clean HTML tags and formatting from email bodies
def clean_html(raw_html: str) -> str:
    # Strip script and style blocks
    clean_text = re.sub(r'<script.*?>.*?</script>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r'<style.*?>.*?</style>', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
    # Strip HTML tags
    clean_text = re.sub(r'<.*?>', '', clean_text)
    # Normalize multiple newlines and spaces
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text


# Helper: Safely walk message parts to extract readable text
def get_email_body(msg) -> str:
    if msg.is_multipart():
        html_body = None
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            
            # Look for plain text first
            if content_type == 'text/plain' and "attachment" not in content_disposition:
                try:
                    return part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except Exception:
                    pass
            # Store HTML body as a fallback
            elif content_type == 'text/html' and "attachment" not in content_disposition:
                try:
                    html_body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except Exception:
                    pass
        
        # If no plain text was found, clean up the HTML content
        if html_body:
            return clean_html(html_body)
    else:
        content_type = msg.get_content_type()
        try:
            payload = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            if content_type == 'text/html':
                return clean_html(payload)
            return payload
        except Exception:
            pass
    return ""


# Helper: Restrict access to only the authorized user ID
def is_authorized(update: Update) -> bool:
    user_id = str(update.effective_user.id)
    return user_id == AUTHORIZED_USER_ID


# Command: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return
    await update.message.reply_text(
        "👋 **Welcome to your AI Email Agent!**\n\n"
        "Here are the commands you can use to manage your inbox:\n"
        "📥 `/check` - Fetch and summarize the latest 5 unread emails\n"
        "✍️ `/reply [msg_id] [instructions]` - Reply to an email by ID using AI drafts\n"
        "📧 `/send [recipient] [subject] | [body]` - Send a new email (separate subject and body with a pipe '|')\n\n"
        "🤖 **Chat Assistant:**\n"
        "Send any normal message to draft replies, translate emails, or ask general questions.",
        parse_mode='Markdown'
    )


# Command: /check (Fetches, processes, and summarizes unread emails)
async def check_emails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return
    
    await update.message.reply_text("Checking your inbox... 🔍")
    
    try:
        username = os.getenv("EMAIL_USERNAME")
        password = os.getenv("EMAIL_PASSWORD")
        imap_server = os.getenv("EMAIL_IMAP_SERVER")
        
        # Connect using a 15-second timeout to prevent hanging
        with IMAPClient(imap_server, ssl=True, timeout=15) as client:
            client.login(username, password)
            client.select_folder('INBOX')
            
            # Fetch unread messages
            messages = client.search(['UNSEEN'])
            if not messages:
                await update.message.reply_text("No new unread emails! 🎉")
                return
            
            # Select the latest 5 unread messages
            latest_messages = messages[-5:]
            
            emails_data = []
            for msg_id in reversed(latest_messages):
                raw_data = client.fetch([msg_id], ['RFC822'])
                msg_bytes = raw_data[msg_id][b'RFC822']
                msg = email.message_from_bytes(msg_bytes, policy=default)
                
                subject = msg.get('Subject', '(No Subject)')
                from_addr = msg.get('From', '(Unknown Sender)')
                body = get_email_body(msg)
                
                # Store email metadata and a snippet of the body
                emails_data.append({
                    "id": msg_id,
                    "from": from_addr,
                    "subject": subject,
                    "body": body[:1500]  # Truncate to save tokens and prevent huge prompt sizes
                })
            
            # Construct a single combined prompt for Gemini to avoid 429 quota limits
            prompt = (
                "You are an expert AI Email Assistant. Below are the latest unread emails in the user's inbox.\n"
                "Please summarize each email separately and format the output beautifully.\n"
                "For each email, format it as follows:\n"
                "📬 Msg ID: [ID]\n"
                "From: [Sender]\n"
                "Subject: [Subject]\n"
                "Summary:\n"
                "- [2-3 concise bullet points summarizing the core request/topic]\n"
                "──────────────────────────────\n\n"
            )
            for e in emails_data:
                prompt += f"Msg ID: {e['id']}\nFrom: {e['from']}\nSubject: {e['subject']}\nBody:\n{e['body']}\n\n──────────────────────────────\n\n"
            
            # Request combined summary using the fallback mechanism to avoid quota errors
            summary_text = generate_content_with_fallback(prompt)
            response_header = f"Found {len(messages)} unread emails. Here is the summary of the latest {len(latest_messages)}:\n\n"
            
            await update.message.reply_text(response_header + summary_text)
            
    except Exception as e:
        logger.error(f"Error checking emails: {e}")
        await update.message.reply_text(f"Failed to check emails: {str(e)}")


# Command: /send (Sends SMTP emails)
async def send_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return
    
    # Arguments check: /send recipient@domain.com Subject | Body
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "❌ **Invalid usage.**\n"
            "Format: `/send [recipient] [subject] | [body]`\n"
            "Example: `/send friend@example.com Lunch Plans | Hey! Are we meeting today?`",
            parse_mode='Markdown'
        )
        return
    
    try:
        full_text = " ".join(args)
        recipient = args[0]
        rest = full_text[len(recipient):].strip()
        
        # Split subject and body by the pipe '|' symbol
        if '|' in rest:
            subject, body = rest.split('|', 1)
            subject = subject.strip()
            body = body.strip()
        else:
            subject = "Quick Mail from Bot"
            body = rest.strip()
            
        username = os.getenv("EMAIL_USERNAME")
        password = os.getenv("EMAIL_PASSWORD")
        smtp_server = os.getenv("EMAIL_SMTP_SERVER")
        smtp_port = int(os.getenv("EMAIL_SMTP_PORT", 465))
        
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = username
        msg['To'] = recipient
        
        await update.message.reply_text("Sending email... 📤")
        
        # Connect and send with a 15-second timeout
        with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15) as server:
            server.login(username, password)
            server.send_message(msg)
            
        await update.message.reply_text(f"Email successfully sent to {recipient}! ✅")
        
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        await update.message.reply_text(f"Failed to send email: {str(e)}")


# Command: /reply (Fetches original email, drafts reply using Gemini, and sends it)
async def reply_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized access.")
        return
    
    # Expected: /reply [msg_id] [reply instruction]
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "❌ **Invalid usage.**\n"
            "Format: `/reply [msg_id] [your instructions]`\n"
            "Example: `/reply 688 say I will attend the meeting tomorrow at 3 PM`",
            parse_mode='Markdown'
        )
        return
    
    msg_id_str = args[0]
    instruction = " ".join(args[1:])
    
    try:
        msg_id = int(msg_id_str)
    except ValueError:
        await update.message.reply_text("❌ **Invalid Message ID.** The ID must be a number.")
        return
    
    await update.message.reply_text(f"Fetching email {msg_id}... 🔍")
    
    try:
        username = os.getenv("EMAIL_USERNAME")
        password = os.getenv("EMAIL_PASSWORD")
        imap_server = os.getenv("EMAIL_IMAP_SERVER")
        smtp_server = os.getenv("EMAIL_SMTP_SERVER")
        smtp_port = int(os.getenv("EMAIL_SMTP_PORT", 465))
        
        # 1. Fetch original email from IMAP
        with IMAPClient(imap_server, ssl=True, timeout=15) as client:
            client.login(username, password)
            client.select_folder('INBOX')
            
            raw_data = client.fetch([msg_id], ['RFC822'])
            if not raw_data or msg_id not in raw_data:
                await update.message.reply_text(f"❌ Could not find email with ID {msg_id} in your inbox.")
                return
                
            msg_bytes = raw_data[msg_id][b'RFC822']
            orig_msg = email.message_from_bytes(msg_bytes, policy=default)
            
        orig_subject = orig_msg.get('Subject', '(No Subject)')
        orig_from = orig_msg.get('From', '(Unknown Sender)')
        orig_msg_id = orig_msg.get('Message-ID', '')
        orig_body = get_email_body(orig_msg)
        
        # Extract clean reply email address (handles formats like "Name <email@domain.com>")
        reply_to_addr = orig_msg.get('Reply-To') or orig_from
        
        await update.message.reply_text("Drafting reply with Gemini... 🤖")
        
        # 2. Use Gemini to draft the reply
        prompt = (
            f"You are a helpful AI Email Assistant. Write a professional email reply based on the original email "
            f"and the user's instructions.\n\n"
            f"User Instructions: {instruction}\n\n"
            f"Original Email:\n"
            f"From: {orig_from}\n"
            f"Subject: {orig_subject}\n"
            f"Body:\n{orig_body[:1500]}\n\n"
            f"Write ONLY the email body response. Do not include subject lines, placeholders, or headers."
        )
        reply_body = generate_content_with_fallback(prompt)
        
        # 3. Construct and send the email
        reply_msg = EmailMessage()
        reply_msg.set_content(reply_body)
        
        # Set reply subject (prepend Re: if not present)
        subject = orig_subject
        if not subject.lower().startswith("re:"):
            subject = "Re: " + subject
        reply_msg['Subject'] = subject
        
        reply_msg['From'] = username
        reply_msg['To'] = reply_to_addr
        
        # Threading headers
        if orig_msg_id:
            reply_msg['In-Reply-To'] = orig_msg_id
            orig_references = orig_msg.get('References', '')
            reply_msg['References'] = f"{orig_references} {orig_msg_id}".strip()
            
        await update.message.reply_text("Sending reply email... 📤")
        
        with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15) as server:
            server.login(username, password)
            server.send_message(reply_msg)
            
        await update.message.reply_text(
            f"✅ **Reply sent successfully to {reply_to_addr}!**\n\n"
            f"📝 **Draft sent:**\n{reply_body}"
        )
        
    except Exception as e:
        logger.error(f"Error replying to email {msg_id}: {e}")
        await update.message.reply_text(f"❌ Failed to send reply: {str(e)}")


# Message Handler: Handles non-command messages using Gemini
async def chat_with_gemini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    user_text = update.message.text
    await update.message.reply_text("Thinking... 🤖")
    
    try:
        prompt = (
            f"You are a helpful AI Email Assistant helping the user manage their inbox.\n"
            f"The user says: {user_text}\n"
            f"Provide a helpful reply. If they ask to draft an email, draft a professional response."
        )
        ai_text = generate_content_with_fallback(prompt)
        await update.message.reply_text(ai_text)
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        await update.message.reply_text(f"AI Assistant Error: {str(e)}")


# Main execution flow
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Hook handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_emails))
    app.add_handler(CommandHandler("reply", reply_email))
    app.add_handler(CommandHandler("send", send_email))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_with_gemini))
    
    logger.info("Bot is starting up...")
    app.run_polling()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped gracefully by keyboard interrupt.")
