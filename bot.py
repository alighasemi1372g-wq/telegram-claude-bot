import os
import logging
import threading
import anthropic
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
COMPOSIO_API_KEY = os.environ["COMPOSIO_API_KEY"]
CLICKUP_API_KEY = os.environ["CLICKUP_API_KEY"]
ZOHO_CLIENT_ID = os.environ["ZOHO_CLIENT_ID"]
ZOHO_CLIENT_SECRET = os.environ["ZOHO_CLIENT_SECRET"]
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


class TokenHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global zoho_refresh_token, zoho_access_token
        if self.path.startswith("/zoho-auth"):
            from urllib.parse import urlparse, parse_qs
            params = parse_qs(urlparse(self.path).query)
            code = params.get("code", [None])[0]
            if code:
                resp = requests.post("https://accounts.zoho.com/oauth/v2/token", data={
                    "code": code,
                    "client_id": ZOHO_CLIENT_ID,
                    "client_secret": ZOHO_CLIENT_SECRET,
                    "redirect_uri": f"https://{self.headers.get('Host')}/zoho-auth",
                    "grant_type": "authorization_code"
                }).json()
                logger.info(f"Zoho exchange result: {resp}")
                rt = resp.get("refresh_token", "")
                at = resp.get("access_token", "")
                if rt:
                    zoho_refresh_token = rt
                    zoho_access_token = at
                    msg = f"SUCCESS! Save this refresh token in Railway variables as ZOHO_REFRESH_TOKEN:\n\n{rt}"
                else:
                    msg = f"Error: {resp}"
            else:
                msg = "No code found in URL."
            self.send_response(200)
