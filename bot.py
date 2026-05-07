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
ZOHO_CLIENT_ID = os.environ["ZOHO_CLIENT_ID"]
ZOHO_CLIENT_SECRET = os.environ["ZOHO_CLIENT_SECRET"]
ZOHO_AUTH_CODE = os.environ.get("ZOHO_AUTH_CODE", "")
ZOHO_REFRESH_TOKEN = os.environ.get("ZOHO_REFRESH_TOKEN", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """You are Ali's personal assistant. You have access to his ClickUp tasks and Zoho emails.
When asked about tasks, use get_clickup_tasks.
When asked about emails, use get_zoho_emails.
When asked to create a task, use create_clickup_task.
Be concise. Respond in English. Never use markdown tables."""

CLICKUP_HEADERS = {"Authorization": CLICKUP_API_KEY}

zoho_access_token = None
zoho_refresh_token = ZOHO_REFRESH_TOKEN


def get_zoho_access_token():
    global zoho_access_token, zoho_refresh_token
    if zoho_refresh_token:
        resp = requests.post("https://accounts.zoho.com/oauth/v2/token", data={
            "refresh_token": zoho_refresh_token,
            "client_id": ZOHO_CLIENT_ID,
            "client_secret": ZOHO_CLIENT_SECRET,
            "grant_type": "refresh_token"
        }).json()
        zoho_access_token = resp.get("access_token")
        return zoho_access_token
    elif ZOHO_AUTH_CODE:
        resp = requests.post("https://accounts.zoho.com/oauth/v2/token", data={
            "code": ZOHO_AUTH_CODE,
            "client_id": ZOHO_CLIENT_ID,
            "client_secret": ZOHO_CLIENT_SECRET,
            "redirect_uri": "https://localhost",
            "grant_type": "authorization_code"
        }).json()
        logger.info(f"Zoho token exchange: {resp}")
        zoho_refresh_token = resp.get("refresh_token", "")
        zoho_access_token = resp.get("access_token")
        if zoho_refresh_token:
            logger.info(f"SAVE THIS REFRESH TOKEN: {zoho_refresh_token}")
        return zoho_access_token
    return None


def get_zoho_emails():
    try:
        token = get_zoho_access_token()
        if not token:
            return "Zoho not connected."
        accounts = requests.get(
            "https://mail.zoho.com/api/accounts",
            headers={"Authorization": f"Zoho-oauthtoken {token}"}
        ).json()
        account_id = accounts["data"][0]["accountId"]
        emails = requests.get(
            f"https://mail.zoho.com/api/accounts/{account_id}/messages/view?limit=5&sortorder=false",
            headers={"Authorization": f"Zoho-oauthtoken {token}"}
        ).json()
        messages = emails.get("data", [])
        if not messages:
            return "No emails found."
        lines = []
        for m in messages:
            sender = m.get("fromAddress", "?")
            subject = m.get("subject", "(no subject)")
            lines.appen
