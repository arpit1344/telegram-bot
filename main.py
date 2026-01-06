import os, json, asyncio, sys, datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button

# ================= ENV =================
load_dotenv("/home/ubuntu/telegram-bot/.env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")

# ================= FILES =================
CONFIG_FILE = "config.json"
LOG_DIR = "logs"
LOG_FILE = f"{LOG_DIR}/admin_activity.log"
os.makedirs(LOG_DIR, exist_ok=True)

# ================= CONFIG =================
def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

CONFIG = load_config()
ADMINS = set(CONFIG.get("admins", []))
SUPER_ADMIN = list(ADMINS)[0]

# ================= LOG =================
def log_action(admin, action, detail=""):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] admin:{admin} | {action} | {detail}\n")

# ================= CLIENTS =================
client = TelegramClient("main_session", API_ID, API_HASH)
admin_bot = TelegramClient("admin_session", API_ID, API_HASH)

# ================= RUNTIME =================
SYSTEM_PAUSED = False
AUTO_SCALE = True

QUEUES = {}
STATS = {}

# 🔥 MULTI USER STATE (CORE FIX)
USER_STATE = {}

def get_state(uid):
    if uid not in USER_STATE:
        USER_STATE[uid] = {
            "selected_bot": None,
            "mode": None,
            "confirm": None
        }
    return USER_STATE[uid]

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

def visible_bots(admin):
    if admin == SUPER_ADMIN:
        return CONFIG["bots"]
    return {k:v for k,v in CONFIG["bots"].items() if v.get("owner") == admin}

# ================= PANEL =================
def panel(state, admin):
    sel = state["selected_bot"] or "None"
    bot_selected = state["selected_bot"] is not None

    def safe(btn):
        return btn if bot_selected else Button.inline("🚫 Select bot", b"noop")

    return [
        [Button.inline(f"🤖 Select Bot ({sel})", b"select_bot"),
         Button.inline("➕ Add Bot", b"add_bot"),
         Button.inline("❌ Remove Bot", b"rm_bot")],

        [Button.inline("⬆ Priority", b"bot_up"),
         Button.inline("⬇ Priority", b"bot_down")],

        [safe(Button.inline("🗃 Set Store Channel", b"set_store"))],

        [safe(Button.inline("➕ Add Source", b"add_src")),
         safe(Button.inline("❌ Remove Source", b"rm_src"))],

        [safe(Button.inline("➕ Add Dest", b"add_dest")),
         safe(Button.inline("❌ Remove Dest", b"rm_dest"))],

        [Button.inline("📊 Status", b"status"),
         Button.inline("📈 Traffic", b"traffic")],

        [Button.inline("🤖 AutoScale ON", b"as_on"),
         Button.inline("🤖 AutoScale OFF", b"as_off")],

        [Button.inline("⏸ Pause", b"pause"),
         Button.inline("▶ Start", b"start"),
         Button.inline("♻ Restart", b"restart")],

        [Button.inline("📜 My Activity Log", b"my_log"),
         Button.inline("⬅ Back", b"back")]
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
                STATS[bot_key]["sources"].setdefault(src, 0)
                STATS[bot_key]["sources"][src] += 1
                sent += 1

        if sent:
            await asyncio.sleep(bot.get("interval", 1800))
        await asyncio.sleep(1)

# ================= ADMIN TEXT =================
@admin_bot.on(events.NewMessage)
async def admin_text(event):
    uid = event.sender_id
    if uid not in ADMINS:
        return

    state = get_state(uid)

    if event.text == "/panel":
        state["mode"] = None
        await event.reply("🛠 ADMIN PANEL", buttons=panel(state, uid))

    if state["mode"] == "add_bot":
        u, i = event.text.split()
        key = f"bot{len(CONFIG['bots'])+1}"
        CONFIG["bots"][key] = {
            "owner": uid,
            "username": u,
            "id": int(i),
            "sources": [],
            "destinations": [],
            "batch": 10,
            "interval": 1800
        }
        save_config(CONFIG)
        init_runtime()
        log_action(uid, "ADD_BOT", key)
        state["mode"] = None
        await event.reply("✅ Bot added", buttons=panel(state, uid))

# ================= BUTTONS =================
@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    uid = event.sender_id
    if uid not in ADMINS:
        return

    state = get_state(uid)
    d = event.data.decode()
    bots = visible_bots(uid)

    if d == "noop":
        await event.answer("Select bot first", alert=True)

    elif d == "back":
        state["mode"] = None
        await event.edit("🛠 ADMIN PANEL", buttons=panel(state, uid))

    elif d == "select_bot":
        rows = [[Button.inline(k, f"sel_{k}".encode())] for k in bots]
        rows.append([Button.inline("⬅ Back", b"back")])
        await event.edit("🤖 Select Bot", buttons=rows)

    elif d.startswith("sel_"):
        state["selected_bot"] = d.replace("sel_", "")
        await event.edit("✅ Bot selected", buttons=panel(state, uid))

    elif d == "add_bot":
        state["mode"] = "add_bot"
        await event.edit("Send: @BotUsername bot_id", buttons=[[Button.inline("⬅ Back", b"back")]])

    elif d == "rm_bot":
        b = state["selected_bot"]
        if b:
            CONFIG["bots"].pop(b)
            save_config(CONFIG)
            init_runtime()
            log_action(uid, "REMOVE_BOT", b)
            state["selected_bot"] = None
        await event.edit("❌ Bot removed", buttons=panel(state, uid))

    elif d == "my_log":
        if not os.path.exists(LOG_FILE):
            await event.answer("No logs yet", alert=True)
            return
        with open(LOG_FILE) as f:
            lines = [l for l in f.readlines() if f"admin:{uid}" in l][-20:]
        await event.edit("📜 Your Activity Log\n\n" + "".join(lines),
                         buttons=[[Button.inline("⬅ Back", b"back")]])

    elif d == "pause":
        SYSTEM_PAUSED = True
        log_action(uid, "PAUSE_SYSTEM")
        await event.edit("⏸ Paused", buttons=panel(state, uid))

    elif d == "start":
        SYSTEM_PAUSED = False
        log_action(uid, "START_SYSTEM")
        await event.edit("▶ Started", buttons=panel(state, uid))

    elif d == "restart":
        log_action(uid, "RESTART_SYSTEM")
        os.execv(sys.executable, ["python"] + sys.argv)

# ================= START =================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    for b in CONFIG["bots"]:
        asyncio.create_task(worker(b))

    print("✅ SYSTEM RUNNING (FULL FEATURES + ISOLATION + LOGS)")
    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
