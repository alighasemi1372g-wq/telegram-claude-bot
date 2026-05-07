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
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(msg.encode())
        else:
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Bot is running!")
    def log_message(self, format, *args):
        pass


def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), TokenHandler)
    server.serve_forever()


def get_zoho_access_token():
    global zoho_access_token
    if not zoho_refresh_token:
        return None
    resp = requests.post("https://accounts.zoho.com/oauth/v2/token", data={
        "refresh_token": zoho_refresh_token,
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token"
    }).json()
    zoho_access_token = resp.get("access_token")
    return zoho_access_token


def get_zoho_emails():
    try:
        token = get_zoho_access_token()
        if not token:
            return "Zoho not connected. No refresh token set."
        accounts_resp = requests.get(
            "https://mail.zoho.com/api/accounts",
            headers={"Authorization": f"Zoho-oauthtoken {token}"}
        ).json()
        logger.info(f"Zoho accounts response: {accounts_resp}")
        accounts_data = accounts_resp.get("data", [])
        if not accounts_data:
            return f"No Zoho accounts found: {accounts_resp}"
        account_id = accounts_data[0].get("accountId")
        if not account_id:
            return f"No account ID found: {accounts_data[0]}"
        emails_resp = requests.get(
            f"https://mail.zoho.com/api/accounts/{account_id}/messages/view?limit=5&sortorder=false",
            headers={"Authorization": f"Zoho-oauthtoken {token}"}
        ).json()
        logger.info(f"Zoho emails response: {emails_resp}")
        messages = emails_resp.get("data", [])
        if not messages:
            return f"No emails found: {emails_resp}"
        lines = []
        for m in messages:
            sender = m.get("fromAddress", "?")
            subject = m.get("subject", "(no subject)")
            lines.append(f"• From: {sender}\n  Subject: {subject}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Zoho error: {e}")
        return f"Error: {e}"
def send_zoho_email(to, subject, body):
    try:
        token = get_zoho_access_token()
        if not token:
            return "Zoho not connected."
        accounts_resp = requests.get(
            "https://mail.zoho.com/api/accounts",
            headers={"Authorization": f"Zoho-oauthtoken {token}"}
        ).json()
        accounts_data = accounts_resp.get("data", [])
        if not accounts_data:
            return f"No accounts found: {accounts_resp}"
        account_id = accounts_data[0].get("accountId")
        from_address = accounts_data[0].get("emailAddress")
        resp = requests.post(
            f"https://mail.zoho.com/api/accounts/{account_id}/messages",
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            json={
                "fromAddress": from_address,
                "toAddress": to,
                "subject": subject,
                "content": body,
                "mailFormat": "plaintext"
            }
        ).json()
        if resp.get("status", {}).get("code") == 200:
            return f"Email sent to {to}!"
        return f"Error sending: {resp}"
    except Exception as e:
        return f"Error: {e}"

def get_clickup_tasks(search=""):
    try:
        teams = requests.get("https://api.clickup.com/api/v2/team", headers=CLICKUP_HEADERS).json()
        team_id = teams["teams"][0]["id"]
        url = f"https://api.clickup.com/api/v2/team/{team_id}/task?include_closed=false&page=0"
        if search:
            url += f"&search={search}"
        tasks = requests.get(url, headers=CLICKUP_HEADERS).json().get("tasks", [])[:5]
        if not tasks:
            return "No tasks found."
        lines = []
        for t in tasks:
            name = t.get("name", "?")
            status = t.get("status", {}).get("status", "?")
            priority = t.get("priority", {}).get("priority", "-") if t.get("priority") else "-"
            lines.append(f"• {name} [{status}] [{priority}]")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def create_clickup_task(name, list_id, description=""):
    try:
        data = {"name": name, "description": description}
        result = requests.post(
            f"https://api.clickup.com/api/v2/list/{list_id}/task",
            headers=CLICKUP_HEADERS, json=data
        ).json()
        return f"Task created: {result.get('name', 'done')}"
    except Exception as e:
        return f"Error: {e}"


tools = [
    {
        "name": "get_zoho_emails",
        "description": "Get Ali's latest Zoho emails",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_clickup_tasks",
        "description": "Get Ali's ClickUp tasks, optionally filtered by keyword",
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Keyword to filter tasks"}
            }
        }
    },
    {
        "name": "create_clickup_task",
        "description": "Create a new ClickUp task",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "list_id": {"type": "string"}
            },
            "required": ["name", "list_id"]
        }
    }
]

conversation_histories = {}


def get_claude_response(messages):
    response = claude_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=messages,
        tools=tools
    )
    if response.stop_reason == "tool_use":
        tool_use = next(b for b in response.content if b.type == "tool_use")
        if tool_use.name == "get_zoho_emails":
            tool_result = get_zoho_emails()
        elif tool_use.name == "get_clickup_tasks":
            tool_result = get_clickup_tasks(**tool_use.input)
        elif tool_use.name == "create_clickup_task":
            tool_result = create_clickup_task(**tool_use.input)
        else:
            tool_result = "Unknown tool"
        messages = messages + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use.id, "content": tool_result}]}
        ]
        response = claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=tools
        )
    return response.content[0].text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello Ali! I can help with ClickUp tasks and Zoho emails!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = str(update.effective_user.id)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    if user_id not in conversation_histories:
        conversation_histories[user_id] = []
    conversation_histories[user_id].append({"role": "user", "content": user_message})
    if len(conversation_histories[user_id]) > 10:
        conversation_histories[user_id] = conversation_histories[user_id][-10:]
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
    threading.Thread(target=start_web_server, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
