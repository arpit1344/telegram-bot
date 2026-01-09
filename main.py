import os, json, asyncio, sys
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button

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
    "mode": None,
    "confirm": None
}

# ================= INIT =================
def init_runtime():
    QUEUES.clear()
    STATS.clear()
    for b, bot in CONFIG["bots"].items():
        QUEUES[b] = {}
        STATS[b] = {"total": 0, "sources": {}, "destinations": {}}
        for s in bot.get("sources", []):
            QUEUES[b][str(s)] = []

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

def breadcrumb():
    bot = STATE.get("selected_bot") or "None"
    mode = STATE.get("mode") or "idle"
    return f"🧭 Panel → Bot: {bot} → Mode: {mode}"

# ================= PANEL =================
def panel():
    bot_selected = STATE.get("selected_bot") is not None

    def safe(btn, enabled=True):
        return btn if enabled else Button.inline("🚫 Disabled", b"noop")

    return [
        [Button.inline(f"🤖 Select Bot ({STATE.get('selected_bot') or 'None'})", b"select_bot")],
        [
            Button.inline("➕ Add Bot", b"add_bot"),
            Button.inline("❌ Remove Bot", b"rm_bot")
        ],
        [
            safe(Button.inline("🗃 Set Store Channel", b"set_store"), bot_selected)
        ],
        [
            safe(Button.inline("➕ Add Source", b"add_src"), bot_selected),
            safe(Button.inline("❌ Remove Source", b"rm_src"), bot_selected)
        ],
        [
            safe(Button.inline("➕ Add Dest", b"add_dest"), bot_selected),
            safe(Button.inline("❌ Remove Dest", b"rm_dest"), bot_selected)
        ],
        [
            Button.inline("📊 Status", b"status"),
            Button.inline("📈 Traffic", b"traffic")
        ],
        [
            Button.inline("⏸ Pause", b"pause"),
            Button.inline("▶ Start", b"start")
        ],
        [
            Button.inline("♻ Restart", b"restart"),
            Button.inline("⬅ Back", b"back")
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

        bot = CONFIG["bots"][bot_key]
        sent = 0
        for src, q in QUEUES[bot_key].items():
            while q and sent < bot.get("batch", 10):
                msg = q.pop(0)
                await client.send_message(bot["username"], msg.text or "")
                STATS[bot_key]["total"] += 1
                sent += 1

        if sent:
            await asyncio.sleep(bot.get("interval", 1800))
        await asyncio.sleep(1)

# ================= ADMIN TEXT =================
@admin_bot.on(events.NewMessage)
async def admin_text(event):
    if event.sender_id not in ADMINS:
        return

    if event.text == "/panel":
        STATE.update({"mode": None, "confirm": None})
        await event.reply(breadcrumb(), buttons=panel())
        return

# ================= BUTTON HANDLER =================
@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    d = event.data.decode()

    if d == "noop":
        await event.answer("❗ Select bot first", alert=True)
        return

    if d == "back":
        STATE.update({"mode": None, "confirm": None})
        await event.edit(breadcrumb(), buttons=panel())

    elif d == "restart":
        STATE["confirm"] = "restart"
        await event.edit(
            "♻ Restart system?",
            buttons=[
                [Button.inline("✅ Yes", b"confirm_restart"),
                 Button.inline("❌ Cancel", b"back")]
            ]
        )

    elif d == "confirm_restart":
        os.execv(sys.executable, ["python"] + sys.argv)

    elif d == "rm_bot":
        STATE["confirm"] = "rm_bot"
        await event.edit(
            "❌ Remove selected bot?",
            buttons=[
                [Button.inline("✅ Yes", b"confirm_rm_bot"),
                 Button.inline("❌ Cancel", b"back")]
            ]
        )

    elif d == "confirm_rm_bot":
        b = STATE.get("selected_bot")
        if b:
            CONFIG["bots"].pop(b)
            QUEUES.pop(b)
            STATS.pop(b)
            save_config(CONFIG)
            STATE["selected_bot"] = None
        await event.edit("✅ Bot removed", buttons=panel())

    elif d == "select_bot":
        rows = [[Button.inline(k, f"sel_{k}".encode())] for k in CONFIG["bots"]]
        rows.append([Button.inline("⬅ Back", b"back")])
        await event.edit("🤖 Select Bot", buttons=rows)

    elif d.startswith("sel_"):
        STATE["selected_bot"] = d.replace("sel_", "")
        await event.edit(breadcrumb(), buttons=panel())

# ================= START =================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)
    for b in CONFIG["bots"]:
        asyncio.create_task(worker(b))
    print("✅ SYSTEM RUNNING (FINAL UX VERSION)")
    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
