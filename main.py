from workers import worker
import os, json, asyncio, sys
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
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

STATE = {
    "selected_bot": None,
    "mode": None
}

# ================= PERSISTENT QUEUE =================
QUEUE_DIR = "queues"
os.makedirs(QUEUE_DIR, exist_ok=True)

def qfile(bot):
    return f"{QUEUE_DIR}/queue_{bot}.json"

def load_queue(bot):
    if os.path.exists(qfile(bot)):
        with open(qfile(bot)) as f:
            return json.load(f)
    return {}

def save_queue(bot):
    with open(qfile(bot), "w") as f:
        json.dump(QUEUES.get(bot, {}), f, indent=2)

# ================= INIT =================
def init_runtime():
    QUEUES.clear()
    STATS.clear()
    for b, bot in CONFIG["bots"].items():
        QUEUES[b] = load_queue(b)
        STATS[b] = {"total": 0, "sources": {}, "destinations": {}}
        for s in bot.get("sources", []):
            QUEUES[b].setdefault(str(s), [])

init_runtime()

# ================= UTIL =================
async def detect_channel_id(event):
    if event.forward and event.forward.chat:
        return event.forward.chat.id

    text = (event.text or "").strip()
    if not text:
        return None

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

    total_q = sum(len(q) for q in QUEUES.get(bot_key, {}).values())
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
    sel = STATE["selected_bot"] or "None"
    return [
        [Button.inline(f"🤖 Select Bot ({sel})", b"select_bot"),
         Button.inline("➕ Add Bot", b"add_bot"),
         Button.inline("❌ Remove Bot", b"rm_bot")],

        [Button.inline("🗃 Set Store Channel", b"set_store")],

        [Button.inline("➕ Add Source", b"add_src"),
         Button.inline("❌ Remove Source", b"rm_src")],

        [Button.inline("➕ Add Dest", b"add_dest"),
         Button.inline("❌ Remove Dest", b"rm_dest")],

        [Button.inline("📦 5", b"b_5"),
         Button.inline("📦 10", b"b_10"),
         Button.inline("📦 20", b"b_20"),
         Button.inline("📦 50", b"b_50")],

        [Button.inline("⏳ 5m", b"i_300"),
         Button.inline("⏳ 10m", b"i_600"),
         Button.inline("⏳ 30m", b"i_1800"),
         Button.inline("⏳ 60m", b"i_3600")],

        [Button.inline("🤖 AutoScale ON", b"as_on"),
         Button.inline("🤖 AutoScale OFF", b"as_off")],

        [Button.inline("⏸ Pause", b"pause"),
         Button.inline("▶ Start", b"start"),
         Button.inline("♻ Restart", b"restart")],

        [Button.inline("📊 Status", b"status"),
         Button.inline("📈 Traffic", b"traffic")],

        [Button.inline("⬅ Back", b"back")]
    ]

# ================= MESSAGE ROUTER =================
@client.on(events.NewMessage)
async def message_router(event):

    # SOURCE → QUEUE
    for b, bot in CONFIG["bots"].items():
        if event.chat_id in bot.get("sources", []):
            QUEUES[b].setdefault(str(event.chat_id), [])
            QUEUES[b][str(event.chat_id)].append(event.message)
            save_queue(b)
            return

    # BOT → STORE → DESTINATION
    for b, bot in CONFIG["bots"].items():
        if event.sender_id == bot["id"]:
            store = bot.get("store_channel")
            if not store:
                return

            if event.message.media and not isinstance(event.message.media, MessageMediaWebPage):
                await client.send_file(store, event.message.media, caption=event.text)
            else:
                await client.send_message(store, event.text or "")

            for d in bot.get("destinations", []):
                if event.message.media and not isinstance(event.message.media, MessageMediaWebPage):
                    await client.send_file(d, event.message.media, caption=event.text)
                else:
                    await client.send_message(d, event.text or "")

                STATS[b]["destinations"].setdefault(str(d), 0)
                STATS[b]["destinations"][str(d)] += 1
            return

# ================= WORKER =================
async def worker(bot_key):
    while True:
        if SYSTEM_PAUSED:
            await asyncio.sleep(1)
            continue

        bot = CONFIG["bots"][bot_key]
        if AUTO_SCALE:
            auto_scale(bot_key)

        sent = 0
        for src, q in QUEUES.get(bot_key, {}).items():
            while q and sent < bot.get("batch", 10):
                msg = q.pop(0)

                if msg.media and not isinstance(msg.media, MessageMediaWebPage):
                    await client.send_file(bot["username"], msg.media, caption=msg.text)
                else:
                    await client.send_message(bot["username"], msg.text or "")

                STATS[bot_key]["total"] += 1
                STATS[bot_key]["sources"].setdefault(src, 0)
                STATS[bot_key]["sources"][src] += 1
                sent += 1
                save_queue(bot_key)

        if sent:
            await asyncio.sleep(bot.get("interval", 1800))
        await asyncio.sleep(1)

# ================= ADMIN TEXT =================
@admin_bot.on(events.NewMessage)
async def admin_text(event):
    if event.sender_id not in ADMINS:
        return

    if event.text == "/panel":
        STATE["mode"] = None
        await event.reply("🛠 ADMIN PANEL", buttons=panel())
        return

# ================= BUTTONS =================
@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    global SYSTEM_PAUSED, AUTO_SCALE

    if event.sender_id not in ADMINS:
        return

    d = event.data.decode()

    if d == "back":
        STATE["mode"] = None
        await event.edit("🛠 ADMIN PANEL", buttons=panel())
        return

    if d == "pause":
        SYSTEM_PAUSED = True
        await event.edit("⏸ Paused", buttons=panel())
        return

    if d == "start":
        SYSTEM_PAUSED = False
        await event.edit("▶ Started", buttons=panel())
        return

    if d == "restart":
        os.execv(sys.executable, ["python"] + sys.argv)

    # -------- STATUS --------
    if d == "status":
        b = STATE.get("selected_bot")
        bot = CONFIG["bots"][b]
        stats = STATS[b]

        total_q = sum(len(q) for q in QUEUES.get(b, {}).values())
        batch = bot.get("batch", 10)
        interval = bot.get("interval", 1800)
        eta = int((total_q / batch) * interval) if batch else 0

        lines = [
            "📊 BOT STATUS\n",
            f"📥 Total Pending Queue : {total_q}",
            f"🕒 ETA (approx)        : {eta} sec\n",
            f"📦 Batch Size         : {batch}",
            f"⏳ Interval           : {interval}",
            f"⚙ AutoScale          : {'ON' if AUTO_SCALE else 'OFF'}",
            f"⏸ Paused             : {'YES' if SYSTEM_PAUSED else 'NO'}",
            "",
            "📥 Sources:"
        ]

        for s in bot.get("sources", []):
            queued = len(QUEUES[b].get(str(s), []))
            sent = stats["sources"].get(str(s), 0)
            lines.append(f" • {s} | Queued: {queued} | Sent: {sent}")

        await event.edit("\n".join(lines), buttons=panel())
        return

    # -------- TRAFFIC --------
    if d == "traffic":
        b = STATE.get("selected_bot")
        bot = CONFIG["bots"][b]
        stats = STATS[b]

        def bar(c, scale=5):
            return "█" * (c // scale)

        lines = ["📈 LIVE TRAFFIC\n"]

        for s in bot.get("sources", []):
            c = stats["sources"].get(str(s), 0)
            q = len(QUEUES[b].get(str(s), []))
            lines.append(f"{s} | Q:{q} {bar(c)} {c}")

        await event.edit("\n".join(lines), buttons=panel())
        return

# ================= START =================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    for b in CONFIG["bots"]:
        asyncio.create_task(worker(b))

    print("✅ SYSTEM RUNNING (FULL FEATURES + QUEUE + ETA)")
    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
