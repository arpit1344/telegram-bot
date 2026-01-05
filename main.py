import os, json, asyncio, sys
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button

# =====================================================
# ENV
# =====================================================
load_dotenv("/home/ubuntu/telegram-bot/.env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# =====================================================
# FILES
# =====================================================
CONFIG_FILE = "config.json"

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

CONFIG = load_config()
ADMINS = set(CONFIG.get("admins", []))

# =====================================================
# CLIENTS
# =====================================================
client = TelegramClient("main_session", API_ID, API_HASH)
admin_bot = TelegramClient("admin_session", API_ID, API_HASH)

# =====================================================
# RUNTIME STATE
# =====================================================
SYSTEM_PAUSED = False
QUEUES = {}        # { bot_key : { source_id : [messages] } }
STATE = {}         # admin conversation state

# =====================================================
# INIT QUEUES (ONE TIME – SAFE)
# =====================================================
def init_queues():
    QUEUES.clear()
    for b, bot in CONFIG["bots"].items():
        QUEUES[b] = {}
        for s in bot["sources"]:
            QUEUES[b][str(s)] = []

init_queues()

# =====================================================
# ADMIN PANEL UI
# =====================================================
def panel():
    return [
        [Button.inline("🤖 Bots", b"bots"), Button.inline("📊 Status", b"status")],
        [Button.inline("➕ Add Bot", b"add_bot"), Button.inline("❌ Remove Bot", b"rm_bot")],
        [Button.inline("➕ Add Source", b"add_src"), Button.inline("❌ Remove Source", b"rm_src")],
        [Button.inline("➕ Add Dest", b"add_dest"), Button.inline("❌ Remove Dest", b"rm_dest")],
        [Button.inline("📦 Batch +", b"b+"), Button.inline("📦 Batch -", b"b-")],
        [Button.inline("⏳ Interval +", b"i+"), Button.inline("⏳ Interval -", b"i-")],
        [Button.inline("⏸ Pause", b"pause"), Button.inline("▶ Start", b"start")],
        [Button.inline("♻ Restart", b"restart")]
    ]

# =====================================================
# SOURCE LISTENER
# =====================================================
@client.on(events.NewMessage)
async def collect(event):
    for b, bot in CONFIG["bots"].items():
        if event.chat_id in bot["sources"]:
            QUEUES[b][str(event.chat_id)].append(event.message)

# =====================================================
# WORKER (PER BOT)
# =====================================================
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

# =====================================================
# BOT → DESTINATION
# =====================================================
@client.on(events.NewMessage)
async def bot_reply(event):
    for bot in CONFIG["bots"].values():
        if event.sender_id == bot["id"]:
            for d in bot["destinations"]:
                if event.message.media:
                    await client.send_file(d, event.message.media, caption=event.text)
                else:
                    await client.send_message(d, event.text)

# =====================================================
# ADMIN TEXT COMMANDS
# =====================================================
@admin_bot.on(events.NewMessage)
async def admin_text(event):
    if event.sender_id not in ADMINS:
        return
    if not event.text:
        return

    text = event.text.strip()

    if text == "/panel":
        await event.reply("🛠 ADMIN PANEL", buttons=panel())
        return

    mode = STATE.get("mode")

    if mode == "add_bot":
        u, i = text.split()
        key = f"bot{len(CONFIG['bots'])+1}"
        CONFIG["bots"][key] = {
            "username": u,
            "id": int(i),
            "sources": [],
            "destinations": []
        }
        save_config(CONFIG)
        QUEUES[key] = {}
        asyncio.create_task(worker(key))
        STATE.clear()
        await event.reply("✅ Bot added")
        return

    if mode == "add_src":
        b, s = text.split()
        CONFIG["bots"][b]["sources"].append(int(s))
        QUEUES[b][str(s)] = []
        save_config(CONFIG)
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

# =====================================================
# ADMIN BUTTONS
# =====================================================
@admin_bot.on(events.CallbackQuery)
async def admin_buttons(event):
    global SYSTEM_PAUSED

    if event.sender_id not in ADMINS:
        return

    d = event.data.decode()

    # -------- STATUS --------
    if d == "status":
        lines = ["📊 FULL STATUS\n"]
        for b, bot in CONFIG["bots"].items():
            lines.append(f"🤖 {b} ({bot['username']})")
            lines.append(" Sources:")
            for s in bot["sources"]:
                q = len(QUEUES[b][str(s)])
                lines.append(f"  • {s} | Queue: {q}")
            lines.append(" Destinations:")
            for x in bot["destinations"]:
                lines.append(f"  • {x}")
            lines.append("")
        await event.edit("\n".join(lines), buttons=panel())

    # -------- BOT LIST --------
    elif d == "bots":
        txt = "🤖 BOTS\n\n"
        for b, bot in CONFIG["bots"].items():
            txt += f"{b} → {bot['username']}\n"
        await event.edit(txt, buttons=panel())

    # -------- ADD / REMOVE --------
    elif d == "add_bot":
        STATE["mode"] = "add_bot"
        await event.edit("Send: @botusername bot_id")

    elif d == "add_src":
        STATE["mode"] = "add_src"
        await event.edit("Send: bot_key source_channel_id")

    elif d == "add_dest":
        STATE["mode"] = "add_dest"
        await event.edit("Send: bot_key destination_channel_id")

    # -------- BATCH / INTERVAL --------
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

    # -------- SYSTEM --------
    elif d == "pause":
        SYSTEM_PAUSED = True
        await event.edit("⏸ Paused", buttons=panel())

    elif d == "start":
        SYSTEM_PAUSED = False
        await event.edit("▶ Started", buttons=panel())

    elif d == "restart":
        os.execv(sys.executable, ["python"] + sys.argv)

# =====================================================
# START
# =====================================================
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
