import os, json, asyncio, time, sys
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button

# ================= ENV =================
load_dotenv("/home/ubuntu/telegram-bot/.env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# ================= FILE =================
CONFIG_FILE = "config.json"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

ADMINS = set(CONFIG.get("admins", []))

# ================= CLIENTS =================
client = TelegramClient("main_session", API_ID, API_HASH)
admin_bot = TelegramClient("admin_session", API_ID, API_HASH)

# ================= STATE =================
SYSTEM_PAUSED = False
QUEUES = {}


# ================= INIT QUEUES (SAFE – ONE TIME) =================
def build_queues():
    for b, bot in CONFIG["bots"].items():
        QUEUES[b] = {}
        for s in bot["sources"]:
            QUEUES[b][str(s)] = []

build_queues()

# ================= PANEL =================
def panel():
    return [
        [Button.inline("📊 Full Status", b"status")],
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
async def worker(bot_key):
    bot = CONFIG["bots"][bot_key]

    while True:
        if SYSTEM_PAUSED:
            await asyncio.sleep(2)
            continue

        for src, q in QUEUES[bot_key].items():
            if not q:
                continue

            msg = q.pop(0)

            if msg.media:
                await client.send_file(bot["username"], msg.media, caption=msg.text)
            else:
                await client.send_message(bot["username"], msg.text)

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

    text = event.text.lower().strip()

    if text == "/panel":
        await event.reply("🛠 ADMIN PANEL", buttons=panel())
        return

    if text == "/status":
        lines = ["📊 **FULL STATUS**\n"]

        for b, bot in CONFIG["bots"].items():
            lines.append(f"🤖 {b} ({bot['username']})")
            lines.append(f"  Sources:")
            for s in bot["sources"]:
                qlen = len(QUEUES[b][str(s)])
                lines.append(f"   • {s} | Queue: {qlen}")
            lines.append(f"  Destinations:")
            for d in bot["destinations"]:
                lines.append(f"   • {d}")
            lines.append("")

        await event.reply("\n".join(lines))
        return

# ================= BUTTON HANDLER =================
@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    global SYSTEM_PAUSED

    if event.sender_id not in ADMINS:
        return

    d = event.data.decode()

    if d == "status":
        await admin_cmd(event)

    elif d == "pause":
        SYSTEM_PAUSED = True
        await event.edit("⏸ Paused", buttons=panel())

    elif d == "start":
        SYSTEM_PAUSED = False
        await event.edit("▶ Started", buttons=panel())

    elif d == "restart":
        os.execv(sys.executable, ["python"] + sys.argv)

# ================= START =================
async def main():
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
