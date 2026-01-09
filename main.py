import os, json, asyncio, sys
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.tl.types import MessageMediaWebPage
from workers import worker   # ✅ workers import

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

# ================= QUEUE PERSIST =================
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

# ================= AUTO SCALE =================
def auto_scale(bot_key):
    if not AUTO_SCALE:
        return

    total_q = sum(len(q) for q in QUEUES.get(bot_key, {}).values())
    bot = CONFIG["bots"][bot_key]

    if total_q > 100:
        bot["batch"], bot["interval"] = 50, 300
    elif total_q > 20:
        bot["batch"], bot["interval"] = 20, 600
    else:
        bot.setdefault("batch", 10)
        bot.setdefault("interval", 1800)

# ================= PANEL =================
def panel():
    sel = STATE["selected_bot"] or "None"
    return [
        [Button.inline(f"🤖 Select Bot ({sel})", b"select_bot")],
        [Button.inline("⏸ Pause", b"pause"),
         Button.inline("▶ Start", b"start")],
        [Button.inline("📊 Status", b"status"),
         Button.inline("📈 Traffic", b"traffic")]
    ]

# ================= MESSAGE ROUTER =================
@client.on(events.NewMessage)
async def message_router(event):
    for b, bot in CONFIG["bots"].items():
        if event.chat_id in bot.get("sources", []):
            QUEUES[b].setdefault(str(event.chat_id), [])
            QUEUES[b][str(event.chat_id)].append(event.message)
            save_queue(b)
            return

# ================= ADMIN TEXT =================
@admin_bot.on(events.NewMessage)
async def admin_text(event):
    if event.sender_id not in ADMINS:
        return

    if event.text == "/panel":
        STATE["mode"] = None
        await event.reply("🛠 ADMIN PANEL", buttons=panel())
        return

# ================= BUTTON HANDLER (FIXED) =================
@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    global SYSTEM_PAUSED

    await event.answer()  # 🔥 MOST IMPORTANT FIX

    if event.sender_id not in ADMINS:
        return

    d = event.data.decode()

    # ---------- BACK ----------
    if d == "back":
        await event.edit("🛠 ADMIN PANEL", buttons=panel())
        return

    # ---------- SELECT BOT ----------
    if d == "select_bot":
        rows = [[Button.inline(k, f"sel_{k}".encode())] for k in CONFIG["bots"]]
        rows.append([Button.inline("⬅ Back", b"back")])
        await event.edit("🤖 Select Bot:", buttons=rows)
        return

    if d.startswith("sel_"):
        STATE["selected_bot"] = d.replace("sel_", "")
        await event.edit("✅ Bot selected", buttons=panel())
        return

    # ---------- PAUSE / START ----------
    if d == "pause":
        SYSTEM_PAUSED = True
        await event.edit("⏸ System Paused", buttons=panel())
        return

    if d == "start":
        SYSTEM_PAUSED = False
        await event.edit("▶ System Started", buttons=panel())
        return

    # ---------- NEED BOT SELECT ----------
    b = STATE.get("selected_bot")
    if not b or b not in CONFIG["bots"]:
        await event.edit("❗ Please select a bot first", buttons=panel())
        return

    bot = CONFIG["bots"][b]
    stats = STATS[b]

    # ---------- STATUS ----------
    if d == "status":
        total_q = sum(len(q) for q in QUEUES[b].values())
        batch = bot.get("batch", 10)
        interval = bot.get("interval", 1800)
        eta = int((total_q / batch) * interval) if batch else 0

        lines = [
            "📊 BOT STATUS\n",
            f"🤖 Bot Key : {b}",
            f"📥 Pending Queue : {total_q}",
            f"🕒 ETA : {eta} sec",
            f"📦 Batch : {batch}",
            f"⏳ Interval : {interval}",
            f"⏸ Paused : {'YES' if SYSTEM_PAUSED else 'NO'}",
            "",
            "📥 Sources:"
        ]

        for s in bot.get("sources", []):
            q = len(QUEUES[b].get(str(s), []))
            sent = stats["sources"].get(str(s), 0)
            lines.append(f" • {s} | Q:{q} | Sent:{sent}")

        await event.edit("\n".join(lines), buttons=panel())
        return

    # ---------- TRAFFIC ----------
    if d == "traffic":
        lines = ["📈 LIVE TRAFFIC\n"]
        for s in bot.get("sources", []):
            q = len(QUEUES[b].get(str(s), []))
            c = stats["sources"].get(str(s), 0)
            lines.append(f"{s} | Q:{q} | Sent:{c}")

        await event.edit("\n".join(lines), buttons=panel())
        return

# ================= START =================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    for b in CONFIG["bots"]:
        asyncio.create_task(worker(b))

    print("✅ SYSTEM RUNNING (BUTTONS FIXED)")
    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
