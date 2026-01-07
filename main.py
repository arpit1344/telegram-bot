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

# ================= RUNTIME =================
SYSTEM_PAUSED = False
AUTO_SCALE = True

QUEUES = {}        # { bot_key : { source_id : [msgs] } }
STATS = {}         # traffic stats
STATE = {
    "selected_bot": None,
    "mode": None
}

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

# ================= AUTO SOURCE DETECT =================
async def detect_channel_id(event):
    if event.forward and event.forward.chat:
        return event.forward.chat.id

    text = (event.text or "").strip()

    if text.startswith("-100"):
        return int(text)

    if text.startswith("@"):
        e = await client.get_entity(text)
        return e.id

    if "t.me/" in text:
        u = text.split("t.me/")[-1]
        e = await client.get_entity(u)
        return e.id

    return None

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

# ================= PANEL =================
def panel():
    sel = STATE.get("selected_bot") or "None"
    return [
        [
            Button.inline(f"🤖 Select Bot ({sel})", b"select_bot"),
            Button.inline("➕ Add Bot", b"add_bot"),
            Button.inline("❌ Remove Bot", b"rm_bot")
        ],
        [
            Button.inline("⬆ Priority", b"bot_up"),
            Button.inline("⬇ Priority", b"bot_down")
        ],
        [Button.inline("📊 Status", b"status"), Button.inline("📈 Traffic", b"traffic")],
        [
            Button.inline("➕ Add Source", b"add_src"),
            Button.inline("❌ Remove Source", b"rm_src")
        ],
        [
            Button.inline("➕ Add Dest", b"add_dest"),
            Button.inline("❌ Remove Dest", b"rm_dest")
        ],
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
        [
            Button.inline("🤖 AutoScale ON", b"as_on"),
            Button.inline("🤖 AutoScale OFF", b"as_off")
        ],
        [
            Button.inline("⏸ Pause", b"pause"),
            Button.inline("▶ Start", b"start"),
            Button.inline("♻ Restart", b"restart")
        ]
    ]

# ================= SOURCE LISTENER =================
@client.on(events.NewMessage)
async def collect(event):
    for b, bot in CONFIG["bots"].items():
        if event.chat_id in bot.get("sources", []):
            QUEUES[b][str(event.chat_id)].append(event.message)

# ================= WORKER =================
async def worker(bot_key):
    while True:
        if SYSTEM_PAUSED:
            await asyncio.sleep(2)
            continue

        auto_scale(bot_key)
        bot = CONFIG["bots"][bot_key]

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

                STATS[bot_key]["total"] += 1
                STATS[bot_key]["sources"].setdefault(src, 0)
                STATS[bot_key]["sources"][src] += 1

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

    b = STATE.get("selected_bot")
    m = STATE.get("mode")

    if m == "add_bot":
        u, i = text.split()
        key = f"bot{len(CONFIG['bots'])+1}"
        CONFIG["bots"][key] = {
            "username": u,
            "id": int(i),
            "sources": [],
            "destinations": [],
            "batch": 10,
            "interval": 1800
        }
        QUEUES[key] = {}
        STATS[key] = {"total": 0, "sources": {}}
        save_config(CONFIG)
        asyncio.create_task(worker(key))
        STATE["selected_bot"] = key
        STATE["mode"] = None
        await event.reply("✅ Bot added", buttons=panel())
        return

    if not b:
        await event.reply("❗ Select a bot first")
        return

    if m == "add_src":
        cid = await detect_channel_id(event)
        CONFIG["bots"][b]["sources"].append(cid)
        QUEUES[b][str(cid)] = []
        save_config(CONFIG)
        STATE["mode"] = None
        await event.reply(f"✅ Source added\n{cid}", buttons=panel())

    elif m == "rm_src":
        cid = int(text)
        CONFIG["bots"][b]["sources"].remove(cid)
        QUEUES[b].pop(str(cid), None)
        save_config(CONFIG)
        STATE["mode"] = None
        await event.reply("❌ Source removed", buttons=panel())

    elif m == "add_dest":
        did = int(text)
        CONFIG["bots"][b]["destinations"].append(did)
        save_config(CONFIG)
        STATE["mode"] = None
        await event.reply("✅ Destination added", buttons=panel())

    elif m == "rm_dest":
        did = int(text)
        CONFIG["bots"][b]["destinations"].remove(did)
        save_config(CONFIG)
        STATE["mode"] = None
        await event.reply("❌ Destination removed", buttons=panel())

# ================= BUTTONS =================
@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    global SYSTEM_PAUSED, AUTO_SCALE

    if event.sender_id not in ADMINS:
        return

    d = event.data.decode()

    if d == "select_bot":
        rows = [[Button.inline(f"{k} ({v['username']})", f"sel_{k}".encode())]
                for k, v in CONFIG["bots"].items()]
        await event.edit("🤖 Select a bot:", buttons=rows)

    elif d.startswith("sel_"):
        STATE["selected_bot"] = d.replace("sel_", "")
        await event.edit("✅ Bot selected", buttons=panel())

    elif d == "add_bot":
        STATE["mode"] = "add_bot"
        await event.edit("Send: @BotUsername bot_id")

    elif d == "rm_bot":
        b = STATE.get("selected_bot")
        if b:
            CONFIG["bots"].pop(b)
            QUEUES.pop(b)
            STATS.pop(b)
            STATE["selected_bot"] = None
            save_config(CONFIG)
        await event.edit("❌ Bot removed", buttons=panel())

    elif d == "status":
        lines = ["📊 STATUS\n"]
        for b, bot in CONFIG["bots"].items():
            lines.append(f"🤖 {b} ({bot['username']})")
            lines.append(f" Batch:{bot.get('batch')} Interval:{bot.get('interval')}")
            for s in bot.get("sources", []):
                lines.append(f"  • {s} | Queue:{len(QUEUES[b][str(s)])}")
            lines.append("")
        await event.edit("\n".join(lines), buttons=panel())

    elif d == "traffic":
        lines = ["📈 TRAFFIC\n"]
        for b, data in STATS.items():
            lines.append(f"🤖 {b} Total:{data['total']}")
            for s, c in data["sources"].items():
                bars = "█" * min(10, c // 5)
                lines.append(f"  {s}: {bars} ({c})")
            lines.append("")
        await event.edit("\n".join(lines), buttons=panel())

    elif d in ("add_src", "rm_src", "add_dest", "rm_dest"):
        STATE["mode"] = d
        await event.edit("Send input now")

    elif d.startswith("b_"):
        CONFIG["bots"][STATE["selected_bot"]]["batch"] = int(d.split("_")[1])
        save_config(CONFIG)
        await event.edit("📦 Batch updated", buttons=panel())

    elif d.startswith("i_"):
        CONFIG["bots"][STATE["selected_bot"]]["interval"] = int(d.split("_")[1])
        save_config(CONFIG)
        await event.edit("⏳ Interval updated", buttons=panel())

    elif d == "as_on":
        AUTO_SCALE = True
        await event.edit("🤖 AutoScale ON", buttons=panel())

    elif d == "as_off":
        AUTO_SCALE = False
        await event.edit("🤖 AutoScale OFF", buttons=panel())

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
