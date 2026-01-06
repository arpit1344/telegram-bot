import os, json, asyncio, sys, datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button

# ================= ENV =================
load_dotenv("/home/ubuntu/telegram-bot/.env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")

# ================= CONFIG =================
CONFIG_FILE = "config.json"
LOG_DIR = "logs"
LOG_FILE = f"{LOG_DIR}/admin_activity.log"

os.makedirs(LOG_DIR, exist_ok=True)

def log_action(admin_id, action, detail=""):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] admin:{admin_id} | {action} | {detail}\n")

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

CONFIG = load_config()
ADMINS = set(CONFIG.get("admins", []))
SUPER_ADMIN = list(ADMINS)[0]   # first admin = super admin

# ================= CLIENTS =================
client = TelegramClient("main_session", API_ID, API_HASH)
admin_bot = TelegramClient("admin_session", API_ID, API_HASH)

# ================= RUNTIME =================
SYSTEM_PAUSED = False
QUEUES = {}
STATS = {}

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
        STATS[b] = {"total": 0}
        for s in bot.get("sources", []):
            QUEUES[b][str(s)] = []

init_runtime()

# ================= BOT VISIBILITY =================
def get_admin_bots(admin_id):
    if admin_id == SUPER_ADMIN:
        return CONFIG["bots"]
    return {
        k: v for k, v in CONFIG["bots"].items()
        if v.get("owner") == admin_id
    }

# ================= PANEL =================
def panel(state, admin_id):
    bots = get_admin_bots(admin_id)
    sel = state["selected_bot"] or "None"

    def safe(btn):
        return btn if state["selected_bot"] else Button.inline("🚫 Select bot", b"noop")

    return [
        [Button.inline(f"🤖 Select Bot ({sel})", b"select_bot")],
        [Button.inline("➕ Add Bot", b"add_bot"),
         Button.inline("❌ Remove Bot", b"rm_bot")],
        [safe(Button.inline("🗃 Set Store Channel", b"set_store"))],
        [safe(Button.inline("➕ Add Source", b"add_src")),
         safe(Button.inline("❌ Remove Source", b"rm_src"))],
        [safe(Button.inline("➕ Add Dest", b"add_dest")),
         safe(Button.inline("❌ Remove Dest", b"rm_dest"))],
        [Button.inline("📊 Status", b"status"),
         Button.inline("📜 My Activity Log", b"my_log")],
        [Button.inline("⏸ Pause", b"pause"),
         Button.inline("▶ Start", b"start")],
        [Button.inline("♻ Restart", b"restart"),
         Button.inline("⬅ Back", b"back")]
    ]

# ================= ADMIN TEXT =================
@admin_bot.on(events.NewMessage)
async def admin_text(event):
    uid = event.sender_id
    if uid not in ADMINS:
        return

    state = get_state(uid)

    if event.text == "/panel":
        await event.reply(
            "🛠 ADMIN PANEL",
            buttons=panel(state, uid)
        )

    if state["mode"] == "add_bot":
        u, i = event.text.split()
        key = f"bot{len(CONFIG['bots'])+1}"
        CONFIG["bots"][key] = {
            "username": u,
            "id": int(i),
            "owner": uid,
            "sources": [],
            "destinations": [],
            "batch": 10,
            "interval": 1800
        }
        save_config(CONFIG)
        log_action(uid, "ADD_BOT", key)
        state["mode"] = None
        await event.reply("✅ Bot added", buttons=panel(state, uid))

# ================= BUTTON HANDLER =================
@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    uid = event.sender_id
    if uid not in ADMINS:
        return

    state = get_state(uid)
    d = event.data.decode()

    bots = get_admin_bots(uid)

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
            log_action(uid, "REMOVE_BOT", b)
            state["selected_bot"] = None
        await event.edit("❌ Bot removed", buttons=panel(state, uid))

    elif d == "my_log":
        if not os.path.exists(LOG_FILE):
            await event.answer("No logs yet", alert=True)
            return
        with open(LOG_FILE) as f:
            lines = [l for l in f.readlines() if f"admin:{uid}" in l][-20:]
        await event.edit("📜 Your Activity Log\n\n" + "".join(lines), buttons=panel(state, uid))

    elif d == "restart":
        log_action(uid, "SYSTEM_RESTART")
        os.execv(sys.executable, ["python"] + sys.argv)

# ================= START =================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)
    print("✅ SYSTEM RUNNING (MULTI-ADMIN + ISOLATION + LOGGING)")
    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
