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
        tasks = requests.get(f"https://api.clickup.com/api/v2/team/{team_id}/task?include_closed=false", headers=CLICKUP_HEADERS).json()
        return tasks.get("tasks", [])
    except Exception as e:
        return f"Error fetching tasks: {e}"

def
