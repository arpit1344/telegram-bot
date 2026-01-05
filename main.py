import os, json, asyncio, time, sys
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button

# ================= ENV =================
load_dotenv("/home/ubuntu/telegram-bot/.env")

def must(k):
    v = os.getenv(k)
    if not v:
        raise RuntimeError(f"Missing ENV {k}")
    return v

API_ID = int(must("API_ID"))
API_HASH = must("API_HASH")
ADMIN_BOT_TOKEN = must("ADMIN_BOT_TOKEN")
MAIN_ADMIN = int(must("ADMIN_ID"))

# ================= FILES =================
CONFIG_FILE = "config.json"

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

def save_config(c):
    with open(CONFIG_FILE, "w") as f:
        json.dump(c, f, indent=2)

CONFIG = load_config()

# add main admin if not present
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

def init_runtime():
    QUEUES.clear()
    for b, bot in CONFIG["bots"].items():
        QUEUES[b] = {}
        for s in bot["sources"]:
            QUEUES[b][str(s)] = []

# ================= ALERT =================
async def alert(msg):
    for a in ADMINS:
        try:
            await admin_bot.send_message(a, msg)
        except:
            pass

# ================= RESTART =================
def restart():
    time.sleep(2)
    os.execv(sys.executable, ["python"] + sys.argv)

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
            await asyncio.sleep(3)
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

# ================= PANEL =================
def panel():
    return [
        [Button.inline("➕ Add Bot", b"add_bot"), Button.inline("❌ Remove Bot", b"rm_bot")],
        [Button.inline("➕ Add Source", b"add_src"), Button.inline("❌ Remove Source", b"rm_src")],
        [Button.inline("➕ Add Dest", b"add_dest")],
        [Button.inline("📦 Batch +", b"b+"), Button.inline("📦 Batch -", b"b-")],
        [Button.inline("⏳ Interval +", b"i+"), Button.inline("⏳ Interval -", b"i-")],
        [Button.inline("👥 Add Admin", b"add_admin")],
        [Button.inline("📊 Stats", b"stats")],
        [Button.inline("⏸ Pause", b"pause"), Button.inline("▶ Start", b"start")],
        [Button.inline("♻ Restart", b"restart")]
    ]

STATE = {}

# ================= ADMIN COMMAND =================
@admin_bot.on(events.NewMessage)
async def admin_cmd(event):
    if event.sender_id not in ADMINS:
        return

    if event.text == "/panel":
        await event.reply("🛠 ADMIN PANEL", buttons=panel())

    elif STATE.get("mode") == "add_admin":
        aid = int(event.text)
        ADMINS.add(aid)
        CONFIG["admins"].append(aid)
        save_config(CONFIG)
        STATE.clear()
        await event.reply("✅ Admin added")

    elif STATE.get("mode") == "add_bot":
        u, i = event.text.split()
        key = f"bot{len(CONFIG['bots'])+1}"
        CONFIG["bots"][key] = {"username": u, "id": int(i), "sources": [], "destinations": []}
        save_config(CONFIG)
        init_runtime()
        asyncio.create_task(worker(key))
        STATE.clear()
        await event.reply("✅ Bot added")

    elif STATE.get("mode") == "add_src":
        b, s = event.text.split()
        CONFIG["bots"][b]["sources"].append(int(s))
        save_config(CONFIG)
        init_runtime()
        STATE.clear()
        await event.reply("✅ Source added")

    elif STATE.get("mode") == "rm_src":
        b, s = event.text.split()
        CONFIG["bots"][b]["sources"].remove(int(s))
        save_config(CONFIG)
        init_runtime()
        STATE.clear()
        await event.reply("❌ Source removed")

    elif STATE.get("mode") == "add_dest":
        b, d = event.text.split()
        CONFIG["bots"][b]["destinations"].append(int(d))
        save_config(CONFIG)
        STATE.clear()
        await event.reply("✅ Destination added")

# ================= BUTTONS =================
@admin_bot.on(events.CallbackQuery)
async def btn(event):
    if event.sender_id not in ADMINS:
        return

    d = event.data.decode()

    if d == "add_admin":
        STATE["mode"] = "add_admin"
        await event.edit("Send new ADMIN_ID")

    elif d == "add_bot":
        STATE["mode"] = "add_bot"
        await event.edit("Send: @botusername bot_id")

    elif d == "add_src":
        STATE["mode"] = "add_src"
        await event.edit("Send: bot_key source_id")

    elif d == "rm_src":
        STATE["mode"] = "rm_src"
        await event.edit("Send: bot_key source_id")

    elif d == "add_dest":
        STATE["mode"] = "add_dest"
        await event.edit("Send: bot_key destination_id")

    elif d == "b+":
        CONFIG["batch_size"] += 1; save_config(CONFIG)
        await event.edit("Batch updated", buttons=panel())

    elif d == "b-":
        CONFIG["batch_size"] = max(1, CONFIG["batch_size"]-1); save_config(CONFIG)
        await event.edit("Batch updated", buttons=panel())

    elif d == "i+":
        CONFIG["interval"] += 300; save_config(CONFIG)
        await event.edit("Interval updated", buttons=panel())

    elif d == "i-":
        CONFIG["interval"] = max(60, CONFIG["interval"]-300); save_config(CONFIG)
        await event.edit("Interval updated", buttons=panel())

    elif d == "stats":
        msg = ""
        for b, srcs in QUEUES.items():
            msg += f"\n🤖 {b}\n"
            for s, q in srcs.items():
                msg += f"{s} → {len(q)}\n"
        await event.edit(msg or "No data", buttons=panel())

    elif d == "pause":
        global SYSTEM_PAUSED
        SYSTEM_PAUSED = True
        await event.edit("⏸ Paused", buttons=panel())

    elif d == "start":
        SYSTEM_PAUSED = False
        await event.edit("▶ Started", buttons=panel())

    elif d == "restart":
        await alert("♻ Bot restarting")
        restart()

# ================= START =================
async def main():
    init_runtime()
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    for b in CONFIG["bots"]:
        asyncio.create_task(worker(b))

    await alert("✅ Bot started successfully")
    await asyncio.gather(client.run_until_disconnected(),
                         admin_bot.run_until_disconnected())

client.loop.run_until_complete(main())
