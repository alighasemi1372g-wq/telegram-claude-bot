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

HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are Ali's personal assistant. You have tools for ClickUp tasks and Zoho emails.
Use get_zoho_emails for latest emails, search_zoho_emails to find emails by keyword/sender/subject.
Use get_clickup_tasks for tasks, send_zoho_email to send, create_clickup_task to create tasks.
When asked about a specific person, company, or topic, always use search_zoho_emails.
Be very concise. Plain text only. No markdown tables."""

CLICKUP_HEADERS = {"Authorization": CLICKUP_API_KEY}
zoho_refresh_token = ZOHO_REFRESH_TOKEN


def pick_model(text):
    heavy = ["draft", "write", "analyze", "analyse", "summarize", "summarise", "compose", "explain", "detail"]
    return SONNET if any(w in text.lower() for w in heavy) else HAIKU


class TokenHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global zoho_refresh_token
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
                if rt:
                    zoho_refresh_token = rt
                    msg = f"SUCCESS! ZOHO_REFRESH_TOKEN:\n\n{rt}"
                else:
                    msg = f"Error: {resp}"
            else:
                msg = "No code found."
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
    HTTPServer(("0.0.0.0", port), TokenHandler).serve_forever()


def get_zoho_token():
    if not zoho_refresh_token:
        return None
    resp = requests.post("https://accounts.zoho.com/oauth/v2/token", data={
        "refresh_token": zoho_refresh_token,
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token"
    }).json()
    return resp.get("access_token")


def get_zoho_account():
    token = get_zoho_token()
    if not token:
        return None, None, None
    accounts = requests.get(
        "https://mail.zoho.com/api/accounts",
        headers={"Authorization": f"Zoho-oauthtoken {token}"}
    ).json().get("data", [])
    if not accounts:
        return None, None, None
    aid = accounts[0].get("accountId")
    from_addr = accounts[0].get("primaryEmailAddress") or accounts[0].get("emailAddress")
    return token, aid, from_addr


def format_messages(msgs):
    if not msgs:
        return "No emails found."
    return "\n".join([
        f"{i+1}. From: {m.get('fromAddress','?')} | {m.get('subject','(no subject)')}"
        for i, m in enumerate(msgs)
    ])


def get_zoho_emails():
    try:
        token, aid, _ = get_zoho_account()
        if not token:
            return "Zoho not connected."
        msgs = requests.get(
            f"https://mail.zoho.com/api/accounts/{aid}/messages/view?limit=5&sortorder=false",
            headers={"Authorization": f"Zoho-oauthtoken {token}"}
        ).json().get("data", [])
        return format_messages(msgs)
    except Exception as e:
        return f"Error: {e}"


def search_zoho_emails(query):
    try:
        token, aid, _ = get_zoho_account()
        if not token:
            return "Zoho not connected."
        q = query.strip()
        if "@" in q and " " not in q:
            search_key = f"sender:{q}"
        else:
            value = f'"{q}"' if " " in q else q
            search_key = f"entire:{value}"
        msgs = requests.get(
            f"https://mail.zoho.com/api/accounts/{aid}/messages/search",
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            params={"searchKey": search_key, "limit": 10, "sortorder": "false"}
        ).json().get("data", [])
        return format_messages(msgs)
    except Exception as e:
        return f"Error: {e}"


def send_zoho_email(to, subject, body):
    try:
        token, aid, from_addr = get_zoho_account()
        if not token:
            return "Zoho not connected."
        resp = requests.post(
            f"https://mail.zoho.com/api/accounts/{aid}/messages",
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            json={"fromAddress": from_addr, "toAddress": to, "subject": subject, "content": body, "mailFormat": "plaintext"}
        ).json()
        if resp.get("status", {}).get("code") == 200:
            return f"Email sent to {to}."
        return f"Send error: {resp}"
    except Exception as e:
        return f"Error: {e}"


def get_clickup_tasks(search=""):
    try:
        teams = requests.get("https://api.clickup.com/api/v2/team", headers=CLICKUP_HEADERS).json()
        tid = teams["teams"][0]["id"]
        url = f"https://api.clickup.com/api/v2/team/{tid}/task?include_closed=false&page=0"
        if search:
            url += f"&search={search}"
        tasks = requests.get(url, headers=CLICKUP_HEADERS).json().get("tasks", [])[:5]
        if not tasks:
            return "No tasks found."
        return "\n".join([
            f"- {t.get('name','?')} [{t.get('status',{}).get('status','?')}] [{t.get('priority',{}).get('priority','-') if t.get('priority') else '-'}]"
            for t in tasks
        ])
    except Exception as e:
        return f"Error: {e}"


def create_clickup_task(name, list_id, description=""):
    try:
        r = requests.post(
            f"https://api.clickup.com/api/v2/list/{list_id}/task",
            headers=CLICKUP_HEADERS,
            json={"name": name, "description": description}
        ).json()
        return f"Created: {r.get('name', 'done')}"
    except Exception as e:
        return f"Error: {e}"


tools = [
    {
        "name": "get_zoho_emails",
        "description": "Get Ali's 5 most recent Zoho emails",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "search_zoho_emails",
        "description": "Search Zoho emails by sender name, company, or subject keyword",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term e.g. Excellgene, Benjamin, contract"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "send_zoho_email",
        "description": "Send an email via Zoho",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"}
            },
            "required": ["to", "subject", "body"]
        }
    },
    {
        "name": "get_clickup_tasks",
        "description": "Get Ali's ClickUp tasks, filtered by optional keyword",
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string"}
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


def get_claude_response(messages, model):
    response = claude_client.messages.create(
        model=model,
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=messages,
        tools=tools
    )
    if response.stop_reason == "tool_use":
        tool_use = next(b for b in response.content if b.type == "tool_use")
        if tool_use.name == "get_zoho_emails":
            result = get_zoho_emails()
        elif tool_use.name == "search_zoho_emails":
            result = search_zoho_emails(**tool_use.input)
        elif tool_use.name == "send_zoho_email":
            result = send_zoho_email(**tool_use.input)
        elif tool_use.name == "get_clickup_tasks":
            result = get_clickup_tasks(**tool_use.input)
        elif tool_use.name == "create_clickup_task":
            result = create_clickup_task(**tool_use.input)
        else:
            result = "Unknown tool"
        messages = messages + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use.id, "content": result}]}
        ]
        response = claude_client.messages.create(
            model=model,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=tools
        )
    return response.content[0].text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hi Ali! Ask me about your emails or ClickUp tasks.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = str(update.effective_user.id)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    if user_id not in conversation_histories:
        conversation_histories[user_id] = []

    conversation_histories[user_id].append({"role": "user", "content": user_message})

    if len(conversation_histories[user_id]) > 6:
        conversation_histories[user_id] = conversation_histories[user_id][-6:]

    model = pick_model(user_message)
    logger.info(f"Model: {model} | Message: {user_message[:50]}")

    try:
        reply = get_claude_response(conversation_histories[user_id], model)
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
