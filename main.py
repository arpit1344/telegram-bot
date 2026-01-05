import os, json, asyncio, time, sys
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button

# ================= LOAD ENV =================
load_dotenv("/home/ubuntu/telegram-bot/.env")

def must(k):
    v = os.getenv(k)
    if not v:
        raise RuntimeError(f"Missing ENV: {k}")
    return v

API_ID = int(must("API_ID"))
API_HASH = must("API_HASH")
ADMIN_BOT_TOKEN = must("ADMIN_BOT_TOKEN")
MAIN_ADMIN = int(must("ADMIN_ID"))

# ================= FILE =================
CONFIG_FILE = "config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump({
                "bots": {},
                "batch_size": 10,
                "interval": 1800,
                "admins": [MAIN_ADMIN]
            }, f, indent=2)

    with open(CONFIG_FILE) as f:
        return json.load(f)

def save_config(c):
    with open(CONFIG_FILE, "w") as f:
        json.dump(c, f, indent=2)

CONFIG = load_config()

if MAIN_ADMIN not in CONFIG["admins"]:
    CONFIG["admins"].append(MAIN_ADMIN)
    save_config(CONFIG)

ADMINS = set(CONFIG["admins"])

# ================= CLIENTS =================
client = TelegramClient("main_session", API_ID, API_HASH)
admin_bot = TelegramClient("admin_session", API_ID, API_HASH)

# ================= RUNTIME =================
SYSTEM_PAUSED = False
QUEUES = {}
STATE = {}

def init_runtime():
    QUEUES.clear()
    for b, bot in CONFIG["bots"].items():
        QUEUES[b] = {}
        for s in bot["sources"]:
            QUEUES[b][str(s)] = []

def restart():
    time.sleep(2)
    os.execv(sys.executable, ["python"] + sys.argv)

# ================= PANEL =================
def panel():
    return [
        [Button.inline("➕ Add Bot", b"add_bot"), Button.inline("➕ Add Source", b"add_src")],
        [Button.inline("➕ Add Dest", b"add_dest")],
        [Button.inline("📦 Batch +", b"b+"), Button.inline("📦 Batch -", b"b-")],
        [Button.inline("⏳ Interval +", b"i+"), Button.inline("⏳ Interval -", b"i-")],
        [Button.inline("📊 Status", b"status")],
        [Button.inline("⏸ Pause", b"pause"), Button.inline("▶ Start", b"start")],
        [Button.inline("♻ Restart", b"restart")]
    ]

# ================= SOURCE LISTENER =================
@client.on(events.NewMessage)
async def collect(event):
    for b, bot in CONFIG["bots"].items():
        if event.chat_id in bot["sources"]:
            QUEUES[b][str(event.chat_id)].append(event.message)

# ================= WORKER =================
async def worker(b):
    bot = CONFIG["bots"][b]

    while True:
        if SYSTEM_PAUSED:
            await asyncio.sleep(2)
            continue

        for src, q in QUEUES[b].items():
            if not q:
                continue

            batch = q[:CONFIG["batch_size"]]
            del q[:CONFIG["batch_size"]]

            for m in batch:
                if m.media:
                    await client.send_file(bot["username"], m.media, caption=m.text)
                else:
                    await client.send_message(bot["username"], m.text)

            if len(batch) == CONFIG["batch_size"]:
                await asyncio.sleep(CONFIG["interval"])

        await asyncio.sleep(1)

# ================= BOT REPLY =================
@client.on(events.NewMessage)
async def bot_reply(event):
    for bot in CONFIG["bots"].values():
        if event.sender_id == bot["id"]:
            for d in bot["destinations"]:
                if event.message.media:
                    await client.send_file(d, event.message.media, caption=event.text)
                else:
                    await client.send_message(d, event.text)

# ================= ADMIN COMMANDS =================
@admin_bot.on(events.NewMessage)
async def admin_cmd(event):
    if event.sender_id not in ADMINS:
        return
    if not event.text:
        return

    text = event.text.strip().lower()

    # 🔥 PANEL (FORCED FIX)
    if text in ("/panel", "/pannel"):
        await event.reply("🛠 ADMIN CONTROL PANEL", buttons=panel())
        return

    if text == "/start":
        await event.reply("✅ Bot running")
        return

    if text == "/status":
        await event.reply(
            f"📊 STATUS\nPaused: {SYSTEM_PAUSED}\nBatch: {CONFIG['batch_size']}\nInterval: {CONFIG['interval']}"
        )
        return

    mode = STATE.get("mode")

    if mode == "add_bot":
        u, i = text.split()
        key = f"bot{len(CONFIG['bots'])+1}"
        CONFIG["bots"][key] = {"username": u, "id": int(i), "sources": [], "destinations": []}
        save_config(CONFIG)
        init_runtime()
        asyncio.create_task(worker(key))
        STATE.clear()
        await event.reply("✅ Bot added")
        return

    if mode == "add_src":
        b, s = text.split()
        CONFIG["bots"][b]["sources"].append(int(s))
        save_config(CONFIG)
        init_runtime()
        STATE.clear()
        await event.reply("✅ Source added")
        return

    if mode == "add_dest":
        b, d = text.split()
        CONFIG["bots"][b]["destinations"].append(int(d))
        save_config(CONFIG)
        STATE.clear()
        await event.reply("✅ Destination added")
        return

# ================= BUTTON HANDLER =================
@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    global SYSTEM_PAUSED

    if event.sender_id not in ADMINS:
        return

    d = event.data.decode()

    if d == "add_bot":
        STATE["mode"] = "add_bot"
        await event.edit("Send: @botusername bot_id")

    elif d == "add_src":
        STATE["mode"] = "add_src"
        await event.edit("Send: bot_key source_channel_id")

    elif d == "add_dest":
        STATE["mode"] = "add_dest"
        await event.edit("Send: bot_key destination_channel_id")

    elif d == "b+":
        CONFIG["batch_size"] += 1
        save_config(CONFIG)
        await event.edit("Batch updated", buttons=panel())

    elif d == "b-":
        CONFIG["batch_size"] = max(1, CONFIG["batch_size"] - 1)
        save_config(CONFIG)
        await event.edit("Batch updated", buttons=panel())

    elif d == "i+":
        CONFIG["interval"] += 300
        save_config(CONFIG)
        await event.edit("Interval updated", buttons=panel())

    elif d == "i-":
        CONFIG["interval"] = max(60, CONFIG["interval"] - 300)
        save_config(CONFIG)
        await event.edit("Interval updated", buttons=panel())

    elif d == "pause":
        SYSTEM_PAUSED = True
        await event.edit("⏸ Paused", buttons=panel())

    elif d == "start":
        SYSTEM_PAUSED = False
        await event.edit("▶ Started", buttons=panel())

    elif d == "restart":
        restart()

# ================= START =================
async def main():
    init_runtime()
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    for b in CONFIG["bots"]:
        asyncio.create_task(worker(b))

    print("✅ SYSTEM RUNNING")
    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
