import os, json, asyncio, sys, time, hashlib
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.errors import MessageNotModifiedError
from telethon.tl.types import MessageMediaWebPage

# ================= ENV =================
load_dotenv("/home/ubuntu/telegram-bot/.env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")

# ================= CONFIG =================
CONFIG_FILE = "config.json"

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

CONFIG = load_config()
ADMINS = set(CONFIG.get("admins", []))

# ================= CLIENTS =================
client = TelegramClient("main_session", API_ID, API_HASH)
admin_bot = TelegramClient("admin_session", API_ID, API_HASH)

# ================= RUNTIME =================
QUEUES = {}
STATS = {}
STATE = {"selected_bot": None}

REFRESH_TASK = None
LAST_HASH = None
SHUTDOWN = False

# ================= INIT =================
def init_runtime():
    for b, bot in CONFIG["bots"].items():
        QUEUES[b] = {}
        STATS[b] = {"total": 0, "sources": {}}
        for s in bot.get("sources", []):
            QUEUES[b][str(s)] = []

init_runtime()

# ================= UTILS =================
def hash_text(txt):
    return hashlib.md5(txt.encode()).hexdigest()

async def safe_edit(event, text, buttons=None):
    global LAST_HASH
    h = hash_text(text)
    if h == LAST_HASH:
        return
    LAST_HASH = h
    try:
        await event.edit(text, buttons=buttons)
    except MessageNotModifiedError:
        pass
    except Exception as e:
        print("EDIT ERROR:", e)

def stop_refresh():
    global REFRESH_TASK
    if REFRESH_TASK:
        REFRESH_TASK.cancel()
        REFRESH_TASK = None

def bar(n):
    return "█" * min(10, n)

# ================= PANEL =================
def panel():
    sel = STATE["selected_bot"] or "None"
    return [
        [Button.inline(f"🤖 Bot: {sel}", b"select_bot")],
        [Button.inline("📊 Status", b"status"),
         Button.inline("📈 Traffic", b"traffic")],
        [Button.inline("🚀 Restart", b"restart")]
    ]

# ================= REFRESH =================
async def refresh_loop(event, mode):
    while True:
        await asyncio.sleep(5)
        txt = []

        if mode == "status":
            txt.append("📊 STATUS\n")
            for b, bot in CONFIG["bots"].items():
                txt.append(f"🤖 {b}")
                for s in bot.get("sources", []):
                    q = len(QUEUES[b].get(str(s), []))
                    txt.append(f"{s} | {bar(q)} {q}")
                txt.append("")

        elif mode == "traffic":
            txt.append("📈 TRAFFIC\n")
            for b, data in STATS.items():
                txt.append(f"🤖 {b} Total: {data['total']}")
                for s, c in data["sources"].items():
                    txt.append(f"{s}: {bar(c//5)} {c}")
                txt.append("")

        await safe_edit(event, "\n".join(txt), panel())

# ================= SOURCE =================
@client.on(events.NewMessage)
async def source_listener(event):
    for b, bot in CONFIG["bots"].items():
        if event.chat_id in bot.get("sources", []):
            QUEUES[b][str(event.chat_id)].append(event.message)

# ================= WORKER =================
async def worker(bot_key):
    while not SHUTDOWN:
        bot = CONFIG["bots"][bot_key]
        batch = bot.get("batch", 10)
        sent = 0

        for src, q in QUEUES[bot_key].items():
            while q and sent < batch:
                msg = q.pop(0)
                try:
                    await client.send_message(bot["username"], msg.text or "")
                except:
                    pass
                STATS[bot_key]["total"] += 1
                STATS[bot_key]["sources"].setdefault(src, 0)
                STATS[bot_key]["sources"][src] += 1
                sent += 1

        await asyncio.sleep(1)

# ================= BOT → STORE =================
@client.on(events.NewMessage)
async def bot_reply(event):
    for bot in CONFIG["bots"].values():
        if event.sender_id == bot["id"]:
            for store in bot.get("store_channels", []):
                try:
                    if isinstance(event.message.media, MessageMediaWebPage):
                        await client.send_message(store, event.text or "")
                    elif event.message.media:
                        await client.send_file(store, event.message.media, caption=event.text)
                    else:
                        await client.send_message(store, event.text or "")
                except Exception as e:
                    print("STORE ERROR:", e)

# ================= ADMIN =================
@admin_bot.on(events.NewMessage)
async def admin(event):
    if event.sender_id not in ADMINS:
        return
    if event.text == "/panel":
        await event.reply("🛠 ADMIN PANEL", buttons=panel())

# ================= BUTTONS =================
@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    global REFRESH_TASK, SHUTDOWN

    if event.sender_id not in ADMINS:
        return

    d = event.data.decode()
    stop_refresh()

    if d == "status":
        REFRESH_TASK = asyncio.create_task(refresh_loop(event, "status"))

    elif d == "traffic":
        REFRESH_TASK = asyncio.create_task(refresh_loop(event, "traffic"))

    elif d == "restart":
        SHUTDOWN = True
        await safe_edit(event, "🚀 Restarting safely...", panel())
        await asyncio.sleep(2)
        os.execv(sys.executable, ["python"] + sys.argv)

# ================= START =================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    for b in CONFIG["bots"]:
        asyncio.create_task(worker(b))

    print("✅ SYSTEM RUNNING – FINAL STABLE")
    a
