import os, json, asyncio, sys
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button

# ================= ENV =================
load_dotenv("/home/ubuntu/telegram-bot/.env")

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

# ================= STATE =================
SYSTEM_PAUSED = False
QUEUES = {}
STATE = {
    "selected_bot": None,
    "mode": None
}

# ================= INIT QUEUES =================
def init_queues():
    QUEUES.clear()
    for b, bot in CONFIG["bots"].items():
        QUEUES[b] = {}
        for s in bot.get("sources", []):
            QUEUES[b][str(s)] = []

init_queues()

# ================= AUTO SOURCE ID DETECT =================
async def detect_channel_id(event):
    if event.forward and event.forward.chat:
        return event.forward.chat.id

    text = (event.text or "").strip()

    if text.startswith("-100"):
        return int(text)

    if text.startswith("@"):
        ent = await client.get_entity(text)
        return ent.id

    if "t.me/" in text:
        uname = text.split("t.me/")[-1]
        ent = await client.get_entity(uname)
        return ent.id

    return None

# ================= PANEL =================
def panel():
    sel = STATE.get("selected_bot")
    sel_txt = sel if sel else "None"

    return [
        [Button.inline(f"🤖 Select Bot ({sel_txt})", b"select_bot")],
        [Button.inline("📊 Status", b"status")],

        [Button.inline("➕ Add Source", b"add_src"), Button.inline("❌ Remove Source", b"rm_src")],
        [Button.inline("➕ Add Dest", b"add_dest"), Button.inline("❌ Remove Dest", b"rm_dest")],

        [
            Button.inline("📦 5", b"b_5"),
            Button.inline("📦 10", b"b_10"),
            Button.inline("📦 20", b"b_20"),
            Button.inline("📦 50", b"b_50")
        ],
        [
            Button.inline("⏳ 5m", b"i_300"),
            Button.inline("⏳ 10m", b"i_600"),
            Button.inline("⏳ 30m", b"i_1800"),
            Button.inline("⏳ 60m", b"i_3600")
        ],

        [Button.inline("⏸ Pause", b"pause"), Button.inline("▶ Start", b"start")],
        [Button.inline("♻ Restart", b"restart")]
    ]

# ================= SOURCE LISTENER =================
@client.on(events.NewMessage)
async def collect(event):
    for b, bot in CONFIG["bots"].items():
        if event.chat_id in bot.get("sources", []):
            QUEUES[b][str(event.chat_id)].append(event.message)

# ================= WORKER =================
async def worker(bot_key):
    bot = CONFIG["bots"][bot_key]

    while True:
        if SYSTEM_PAUSED:
            await asyncio.sleep(2)
            continue

        batch = bot.get("batch", 10)
        interval = bot.get("interval", 1800)

        sent = 0
        for src, q in QUEUES[bot_key].items():
            while q and sent < batch:
                msg = q.pop(0)
                if msg.media:
                    await client.send_file(bot["username"], msg.media, caption=msg.text)
                else:
                    await client.send_message(bot["username"], msg.text)
                sent += 1

        if sent >= batch:
            await asyncio.sleep(interval)

        await asyncio.sleep(1)

# ================= BOT → DEST =================
@client.on(events.NewMessage)
async def bot_reply(event):
    for bot in CONFIG["bots"].values():
        if event.sender_id == bot["id"]:
            for d in bot.get("destinations", []):
                if event.message.media:
                    await client.send_file(d, event.message.media, caption=event.text)
                else:
                    await client.send_message(d, event.text)

# ================= ADMIN TEXT =================
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
    bot = STATE.get("selected_bot")

    if not bot:
        await event.reply("❗ Select a bot first using 🤖 Select Bot")
        return

    if mode == "add_src":
        cid = await detect_channel_id(event)
        if not cid:
            await event.reply("❌ Cannot detect channel")
            return
        CONFIG["bots"][bot].setdefault("sources", []).append(cid)
        QUEUES[bot][str(cid)] = []
        save_config(CONFIG)
        STATE["mode"] = None
        await event.reply(f"✅ Source added\n{cid}", buttons=panel())

    elif mode == "rm_src":
        cid = int(text)
        CONFIG["bots"][bot]["sources"].remove(cid)
        QUEUES[bot].pop(str(cid), None)
        save_config(CONFIG)
        STATE["mode"] = None
        await event.reply("❌ Source removed", buttons=panel())

    elif mode == "add_dest":
        did = int(text)
        CONFIG["bots"][bot].setdefault("destinations", []).append(did)
        save_config(CONFIG)
        STATE["mode"] = None
        await event.reply("✅ Destination added", buttons=panel())

    elif mode == "rm_dest":
        did = int(text)
        CONFIG["bots"][bot]["destinations"].remove(did)
        save_config(CONFIG)
        STATE["mode"] = None
        await event.reply("❌ Destination removed", buttons=panel())

# ================= BUTTONS =================
@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    global SYSTEM_PAUSED

    if event.sender_id not in ADMINS:
        return

    d = event.data.decode()

    # ---- BOT SELECT ----
    if d == "select_bot":
        rows = [
            [Button.inline(f"{k} ({v['username']})", f"sel_{k}".encode())]
            for k, v in CONFIG["bots"].items()
        ]
        await event.edit("🤖 Select a bot:", buttons=rows)

    elif d.startswith("sel_"):
        STATE["selected_bot"] = d.replace("sel_", "")
        await event.edit("✅ Bot selected", buttons=panel())

    # ---- STATUS ----
    elif d == "status":
        lines = ["📊 FULL STATUS\n"]
        for b, bot in CONFIG["bots"].items():
            lines.append(f"🤖 {b} ({bot['username']})")
            lines.append(f" Batch: {bot.get('batch',10)} | Interval: {bot.get('interval',1800)}")
            lines.append(" Sources:")
            for s in bot.get("sources", []):
                q = len(QUEUES[b][str(s)])
                lines.append(f"  • {s} | Queue: {q}")
            lines.append(" Destinations:")
            for x in bot.get("destinations", []):
                lines.append(f"  • {x}")
            lines.append("")
        await event.edit("\n".join(lines), buttons=panel())

    # ---- MODES ----
    elif d in ("add_src","rm_src","add_dest","rm_dest"):
        if not STATE.get("selected_bot"):
            await event.answer("Select a bot first", alert=True)
            return
        STATE["mode"] = d
        await event.edit("Send input now", buttons=panel())

    # ---- PER BOT BATCH ----
    elif d.startswith("b_"):
        if not STATE.get("selected_bot"):
            await event.answer("Select a bot first", alert=True)
            return
        val = int(d.split("_")[1])
        CONFIG["bots"][STATE["selected_bot"]]["batch"] = val
        save_config(CONFIG)
        await event.edit(f"📦 Batch set to {val}", buttons=panel())

    # ---- PER BOT INTERVAL ----
    elif d.startswith("i_"):
        if not STATE.get("selected_bot"):
            await event.answer("Select a bot first", alert=True)
            return
        val = int(d.split("_")[1])
        CONFIG["bots"][STATE["selected_bot"]]["interval"] = val
        save_config(CONFIG)
        await event.edit(f"⏳ Interval set to {val}s", buttons=panel())

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
