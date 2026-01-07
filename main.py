import os, json, asyncio, sys, time, hashlib
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.errors import MessageNotModifiedError

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

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

CONFIG = load_config()
ADMINS = set(CONFIG.get("admins", []))

# ================= CLIENTS =================
client = TelegramClient("main_session", API_ID, API_HASH)
admin_bot = TelegramClient("admin_session", API_ID, API_HASH)

# ================= RUNTIME =================
SYSTEM_PAUSED = False
AUTO_SCALE = True

QUEUES = {}
STATS = {}
STATE = {"selected_bot": None}

DEBOUNCE = {}
REFRESH_TASK = None
LAST_HASH = None
SHUTTING_DOWN = False

# ================= INIT =================
def init_runtime():
    QUEUES.clear()
    STATS.clear()
    for b, bot in CONFIG["bots"].items():
        QUEUES[b] = {}
        STATS[b] = {"total": 0, "sources": {}}
        for s in bot.get("sources", []):
            QUEUES[b][str(s)] = []

init_runtime()

# ================= UTILS =================
def debounce_ok(uid, key, gap=1.0):
    now = time.time()
    last = DEBOUNCE.get((uid, key), 0)
    if now - last < gap:
        return False
    DEBOUNCE[(uid, key)] = now
    return True

def hash_text(text):
    return hashlib.md5(text.encode()).hexdigest()

async def smart_edit(event, text, buttons=None):
    global LAST_HASH
    h = hash_text(text)
    if h == LAST_HASH:
        return
    LAST_HASH = h
    try:
        await event.edit(text, buttons=buttons)
    except MessageNotModifiedError:
        pass

def queue_bar(n):
    return "█" * min(10, n)

def stop_refresh():
    global REFRESH_TASK
    if REFRESH_TASK:
        REFRESH_TASK.cancel()
        REFRESH_TASK = None

# ================= PANEL =================
def panel():
    sel = STATE.get("selected_bot") or "None"
    return [
        [Button.inline(f"🤖 Bot ({sel})", b"select_bot")],
        [Button.inline("📊 Status", b"status"),
         Button.inline("📈 Traffic", b"traffic")],
        [Button.inline("⏸ Pause", b"pause"),
         Button.inline("▶ Start", b"start")],
        [Button.inline("🚀 Zero Restart", b"zrestart")]
    ]

# ================= AUTO REFRESH =================
async def refresh_loop(event, mode):
    while True:
        await asyncio.sleep(5)

        if mode == "status":
            lines = ["📊 STATUS\n"]
            for b, bot in CONFIG["bots"].items():
                lines.append(f"🤖 {b} ({bot['username']})")
                for s in bot.get("sources", []):
                    q = len(QUEUES[b].get(str(s), []))
                    lines.append(f" {s} | {queue_bar(q)} {q}")
                lines.append("")
            await smart_edit(event, "\n".join(lines), panel())

        elif mode == "traffic":
            lines = ["📈 TRAFFIC\n"]
            for b, data in STATS.items():
                lines.append(f"🤖 {b} Total:{data['total']}")
                for s, c in data["sources"].items():
                    lines.append(f" {s}: {queue_bar(c//5)} {c}")
                lines.append("")
            await smart_edit(event, "\n".join(lines), panel())

# ================= SOURCE LISTENER =================
@client.on(events.NewMessage)
async def collect(event):
    for b, bot in CONFIG["bots"].items():
        if event.chat_id in bot.get("sources", []):
            QUEUES[b][str(event.chat_id)].append(event.message)

# ================= WORKER =================
async def worker(bot_key):
    while not SHUTTING_DOWN:
        if SYSTEM_PAUSED:
            await asyncio.sleep(1)
            continue

        bot = CONFIG["bots"][bot_key]
        batch = bot.get("batch", 10)
        sent = 0

        for src, q in QUEUES[bot_key].items():
            while q and sent < batch:
                msg = q.pop(0)
                try:
                    if msg.media:
                        await client.send_file(bot["username"], msg.media, caption=msg.text)
                    else:
                        await client.send_message(bot["username"], msg.text)
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
            for sc in bot.get("store_channels", []):
                try:
                    await client.send_message(sc, event.text or "")
                except:
                    pass

# ================= ADMIN =================
@admin_bot.on(events.NewMessage)
async def admin_text(event):
    if event.sender_id not in ADMINS:
        return
    if event.text == "/panel":
        await event.reply("🛠 ADMIN PANEL", buttons=panel())

# ================= BUTTONS =================
@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    global SYSTEM_PAUSED, REFRESH_TASK, SHUTTING_DOWN

    if event.sender_id not in ADMINS:
        return

    d = event.data.decode()
    if not debounce_ok(event.sender_id, d):
        return

    stop_refresh()

    if d == "status":
        REFRESH_TASK = asyncio.create_task(refresh_loop(event, "status"))

    elif d == "traffic":
        REFRESH_TASK = asyncio.create_task(refresh_loop(event, "traffic"))

    elif d == "pause":
        SYSTEM_PAUSED = True
        await smart_edit(event, "⏸ Paused", panel())

    elif d == "start":
        SYSTEM_PAUSED = False
        await smart_edit(event, "▶ Started", panel())

    elif d == "zrestart":
        SHUTTING_DOWN = True
        await smart_edit(event, "🚀 Restarting safely…", panel())
        await asyncio.sleep(2)
        os.execv(sys.executable, ["python"] + sys.argv)

# ================= START =================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    for b in CONFIG["bots"]:
        asyncio.create_task(worker(b))

    print("✅ SYSTEM RUNNING (HARDENED)")
    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
