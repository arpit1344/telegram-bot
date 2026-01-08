import os, json, asyncio, sys
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button

# ================= ENV =================
load_dotenv(".env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

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
STATE = {"selected_bot": None, "mode": None}

# ================= INIT =================
def init_runtime():
    QUEUES.clear()
    STATS.clear()
    for b, bot in CONFIG["bots"].items():
        QUEUES[b] = {}
        STATS[b] = {"total": 0}
        for s in bot.get("sources", []):
            QUEUES[b][str(s)] = []

init_runtime()

# ================= AUTO SCALE =================
def auto_scale(bot_key):
    if not AUTO_SCALE:
        return
    total_q = sum(len(q) for q in QUEUES[bot_key].values())
    bot = CONFIG["bots"][bot_key]

    if total_q > 100:
        bot["batch"] = 50
        bot["interval"] = 300
    elif total_q > 20:
        bot["batch"] = 20
        bot["interval"] = 600
    else:
        bot.setdefault("batch", 10)
        bot.setdefault("interval", 1800)

# ================= SOURCE LISTENER =================
@client.on(events.NewMessage)
async def collect_source(event):
    for b, bot in CONFIG["bots"].items():
        if event.chat_id in bot.get("sources", []):
            QUEUES[b][str(event.chat_id)].append(event.message)

# ================= SOURCE → BOT WORKER =================
async def worker(bot_key):
    while True:
        if SYSTEM_PAUSED:
            await asyncio.sleep(2)
            continue

        auto_scale(bot_key)
        bot = CONFIG["bots"][bot_key]
        sent = 0

        for src, q in QUEUES[bot_key].items():
            while q and sent < bot["batch"]:
                msg = q.pop(0)

                if msg.media:
                    await client.send_file(
                        bot["username"],
                        msg.media,
                        caption=msg.text
                    )
                else:
                    await client.send_message(bot["username"], msg.text)

                STATS[bot_key]["total"] += 1
                sent += 1

        if sent:
            await asyncio.sleep(bot["interval"])
        await asyncio.sleep(1)

# ================= BOT → STORE CHANNEL =================
@client.on(events.NewMessage)
async def bot_to_store(event):
    for bot in CONFIG["bots"].values():
        if event.sender_id == bot["id"]:
            store = bot.get("store_channel")
            if not store:
                return

            if event.message.media:
                await client.send_file(
                    store,
                    event.message.media,
                    caption=event.text
                )
            else:
                await client.send_message(store, event.text)

# ================= STORE → DESTINATION =================
@client.on(events.NewMessage)
async def store_to_destination(event):
    for bot in CONFIG["bots"].values():
        if event.chat_id == bot.get("store_channel"):
            for d in bot.get("destinations", []):
                if event.message.media:
                    await client.send_file(
                        d,
                        event.message.media,
                        caption=event.text
                    )
                else:
                    await client.send_message(d, event.text)

# ================= ADMIN PANEL =================
def panel():
    sel = STATE.get("selected_bot") or "None"
    return [
        [Button.inline(f"🤖 Bot: {sel}", b"select")],
        [Button.inline("⏸ Pause", b"pause"), Button.inline("▶ Start", b"start")],
        [Button.inline("📊 Status", b"status")]
    ]

@admin_bot.on(events.NewMessage)
async def admin_text(event):
    if event.sender_id not in ADMINS:
        return
    if event.text == "/panel":
        await event.reply("🛠 ADMIN PANEL", buttons=panel())

@admin_bot.on(events.CallbackQuery)
async def admin_buttons(event):
    global SYSTEM_PAUSED
    if event.sender_id not in ADMINS:
        return

    d = event.data.decode()

    if d == "pause":
        SYSTEM_PAUSED = True
        await event.edit("⏸ SYSTEM PAUSED", buttons=panel())

    elif d == "start":
        SYSTEM_PAUSED = False
        await event.edit("▶ SYSTEM RUNNING", buttons=panel())

    elif d == "status":
        lines = ["📊 STATUS\n"]
        for b, s in STATS.items():
            lines.append(f"{b}: {s['total']} msgs")
        await event.edit("\n".join(lines), buttons=panel())

# ================= START =================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    for b in CONFIG["bots"]:
        asyncio.create_task(worker(b))

    print("✅ SYSTEM RUNNING WITH STORE CHANNEL")
    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
