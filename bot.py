import os
import logging
import httpx
import anthropic
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN     = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
COMPOSIO_API_KEY   = os.environ["COMPOSIO_API_KEY"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Claude client (explicit httpx client to avoid proxies bug) ────────────────
http_client = httpx.Client()
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, http_client=http_client)

SYSTEM_PROMPT = """You are Ali's personal morning assistant. Your name is Claude Assistant.

Your capabilities:
- Triage and summarize Zoho emails by priority
- Help manage R&D team tasks via ClickUp
- Answer questions and provide analysis
- Draft emails and messages

Always respond in English unless the user writes in another language.
Be concise, professional, and actionable.
When asked about emails, use the Zoho Mail tools available to you."""

conversation_histories = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hello Ali! I'm your Claude Assistant.\n\n"
        "I can help you with:\n"
        "• 📧 Check and triage your Zoho emails\n"
        "• ✅ Manage ClickUp tasks\n"
        "• 💬 Answer questions and draft messages\n\n"
        "Just type your request and I'll get to work!"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    chat_id = update.effective_chat.id
    user_id = str(update.effective_user.id)

    logger.info(f"Message from {user_id}: {user_message}")
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    if user_id not in conversation_histories:
        conversation_histories[user_id] = []

    conversation_histories[user_id].append({"role": "user", "content": user_message})

    if len(conversation_histories[user_id]) > 20:
        conversation_histories[user_id] = conversation_histories[user_id][-20:]

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=conversation_histories[user_id],
            mcp_servers=[
                {
                    "type": "url",
                    "url": "https://connect.composio.dev/mcp",
                    "name": "composio",
                    "authorization_token": COMPOSIO_API_KEY
                }
            ]
        )

        reply = response.content[0].text
        conversation_histories[user_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"Sorry, error: {str(e)[:200]}")

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    conversation_histories[user_id] = []
    await update.message.reply_text("✅ Conversation history cleared.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
