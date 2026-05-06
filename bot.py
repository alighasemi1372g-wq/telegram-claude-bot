import os
import logging
import anthropic
import requests
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
COMPOSIO_API_KEY = os.environ["COMPOSIO_API_KEY"]
CLICKUP_API_KEY = os.environ["CLICKUP_API_KEY"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """You are Ali's personal assistant. You have access to his ClickUp tasks.
When asked about tasks, use the get_clickup_tasks tool.
When asked to create a task, use the create_clickup_task tool.
Be concise and helpful. Respond in English."""

CLICKUP_HEADERS = {"Authorization": CLICKUP_API_KEY}


def get_clickup_tasks():
    try:
        teams = requests.get("https://api.clickup.com/api/v2/team", headers=CLICKUP_HEADERS).json()
        team_id = teams["teams"][0]["id"]
        tasks = requests.get(
            f"https://api.clickup.com/api/v2/team/{team_id}/task?include_closed=false",
            headers=CLICKUP_HEADERS
        ).json()
        return tasks.get("tasks", [])
    except Exception as e:
        return f"Error fetching tasks: {e}"


def create_clickup_task(name, list_id, description=""):
    try:
        data = {"name": name, "description": description}
        result = requests.post(
            f"https://api.clickup.com/api/v2/list/{list_id}/task",
            headers=CLICKUP_HEADERS,
            json=data
        ).json()
        return result
    except Exception as e:
        return f"Error creating task: {e}"


tools = [
    {
        "name": "get_clickup_tasks",
        "description": "Get Ali's current ClickUp tasks",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "create_clickup_task",
        "description": "Create a new task in ClickUp",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Task name"},
                "description": {"type": "string", "description": "Task description"},
                "list_id": {"type": "string", "description": "ClickUp list ID"}
            },
            "required": ["name", "list_id"]
        }
    }
]

conversation_histories = {}


def get_claude_response(messages):
    response = claude_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=messages,
        tools=tools
    )
    if response.stop_reason == "tool_use":
        tool_use = next(b for b in response.content if b.type == "tool_use")
        if tool_use.name == "get_clickup_tasks":
            tool_result = str(get_clickup_tasks())
        elif tool_use.name == "create_clickup_task":
            tool_result = str(create_clickup_task(**tool_use.input))
        else:
            tool_result = "Unknown tool"
        messages = messages + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use.id, "content": tool_result}]}
        ]
        response = claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=tools
        )
    return response.content[0].text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello Ali! I'm your Claude Assistant. I can help with ClickUp tasks and more!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = str(update.effective_user.id)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    if user_id not in conversation_histories:
        conversation_histories[user_id] = []
    conversation_histories[user_id].append({"role": "user", "content": user_message})
    if len(conversation_histories[user_id]) > 20:
        conversation_histories[user_id] = conversation_histories[user_id][-20:]
    try:
        reply = get_claude_response(conversation_histories[user_id])
        conversation_histories[user_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"Error: {str(e)[:200]}")


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversation_histories[str(update.effective_user.id)] = []
    await update.message.reply_text("✅ Cleared.")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
