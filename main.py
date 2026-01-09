import os, json, asyncio, sys
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.tl.types import MessageMediaWebPage

from redis_queue import push, size, total
from workers import worker

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

def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump(CONFIG, f, indent=2)

CONFIG = load_config()
ADMINS = set(CONFIG.get("admins", []))

# ================= CLIENTS =================
client = TelegramClient("main_session", API_ID, API_HASH)
admin_bot = TelegramClient("admin_session", API_ID, API_HASH)

# ================= GLOBAL STATE =================
SYSTEM_PAUSED = False
AUTO_SCALE = True
WORKERS_PER_BOT = 1

STATE = {"selected_bot": None, "mode": None}

STATS = {
    b: {"total": 0, "sources": {}, "destinations": {}}
    for b in CONFIG["bots"]
}

# ================= HELPERS =================
def is_paused():
    return SYSTEM_PAUSED

def is_autoscale():
    return AUTO_SCALE

def auto_scale(bot_key):
    if not AUTO_SCALE:
        return

    q = total(bot_key)
    bot = CONFIG["bots"][bot_key]

    if q > 100:
        bot["batch"] = 50
        bot["interval"] = 300
    elif q > 20:
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

# ================= ROUTER =================
@client.on(events.NewMessage)
async def router(event):
    # SOURCE → QUEUE
    for b, bot in CONFIG["bots"].items():
        if event.chat_id in bot.get("sources", []):
            push(b, event.chat_id, {"text": event.text})
            return

    # BOT → STORE → DEST
    for b, bot in CONFIG["bots"].items():
        if event.sender_id == bot.get("id"):
            store = bot.get("store_channel")
            if not store:
                return

            if event.media and not isinstance(event.media, MessageMediaWebPage):
                await client.send_file(store, event.media, caption=event.text)
            else:
                await client.send_message(store, event.text or "")

            for d in bot.get("destinations", []):
                await client.send_message(d, event.text or "")
                STATS[b]["destinations"].setdefault(str(d), 0)
                STATS[b]["destinations"][str(d)] += 1

# ================= ADMIN TEXT =================
@admin_bot.on(events.NewMessage)
async def admin_text(event):
    if event.sender_id not in ADMINS:
        return

    if event.text == "/panel":
        STATE["mode"] = None
        await event.reply("🛠 ADMIN PANEL", buttons=panel())
        return

    b = STATE["selected_bot"]
    m = STATE["mode"]

    if not b or not m:
        return

    if m == "add_bot":
        u, i = event.text.split()
        key = f"bot{len(CONFIG['bots'])+1}"
        CONFIG["bots"][key] = {
            "username": u,
            "id": int(i),
            "sources": [],
            "destinations": [],
            "batch": 10,
            "interval": 1800
        }
        STATS[key] = {"total": 0, "sources": {}, "destinations": {}}
        save_config()

        for _ in range(WORKERS_PER_BOT):
            asyncio.create_task(
                worker(
                    key,
                    client=client,
                    CONFIG=CONFIG,
                    STATS=STATS,
                    auto_scale=auto_scale,
                    is_paused=is_paused,
                    is_autoscale=is_autoscale
                )
            )

        STATE["mode"] = None
        await event.reply("✅ Bot added", buttons=panel())

    elif m == "add_src":
        CONFIG["bots"][b]["sources"].append(int(event.text))
        save_config()
        STATE["mode"] = None
        await event.reply("✅ Source added", buttons=panel())

    elif m == "rm_src":
        CONFIG["bots"][b]["sources"].remove(int(event.text))
        save_config()
        STATE["mode"] = None
        await event.reply("❌ Source removed", buttons=panel())

    elif m == "add_dest":
        CONFIG["bots"][b]["destinations"].append(int(event.text))
        save_config()
        STATE["mode"] = None
        await event.reply("✅ Destination added", buttons=panel())

    elif m == "rm_dest":
        CONFIG["bots"][b]["destinations"].remove(int(event.text))
        save_config()
        STATE["mode"] = None
        await event.reply("❌ Destination removed", buttons=panel())

    elif m == "set_store":
        CONFIG["bots"][b]["store_channel"] = int(event.text)
        save_config()
        STATE["mode"] = None
        await event.reply("✅ Store channel set", buttons=panel())

# ================= BUTTONS =================
@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    global SYSTEM_PAUSED, AUTO_SCALE
    await event.answer()

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

    if d == "as_on":
        AUTO_SCALE = True
        await event.edit("🤖 AutoScale ON", buttons=panel())
        return

    if d == "as_off":
        AUTO_SCALE = False
        await event.edit("🤖 AutoScale OFF", buttons=panel())
        return

    if d == "select_bot":
        rows = [[Button.inline(k, f"sel_{k}".encode())] for k in CONFIG["bots"]]
        await event.edit("Select bot", buttons=rows)
        return

    if d.startswith("sel_"):
        STATE["selected_bot"] = d.replace("sel_", "")
        await event.edit("Bot selected", buttons=panel())
        return

    if d == "add_bot":
        STATE["mode"] = "add_bot"
        await event.edit("Send: @botusername bot_id")
        return

    if d == "rm_bot":
        b = STATE["selected_bot"]
        if b:
            CONFIG["bots"].pop(b)
            STATS.pop(b)
            save_config()
            STATE["selected_bot"] = None
        await event.edit("❌ Bot removed", buttons=panel())
        return

    if d in ("add_src", "rm_src", "add_dest", "rm_dest", "set_store"):
        STATE["mode"] = d
        await event.edit("Send channel ID")
        return

    if d.startswith("b_"):
        CONFIG["bots"][STATE["selected_bot"]]["batch"] = int(d.split("_")[1])
        save_config()
        await event.edit("📦 Batch updated", buttons=panel())
        return

    if d.startswith("i_"):
        CONFIG["bots"][STATE["selected_bot"]]["interval"] = int(d.split("_")[1])
        save_config()
        await event.edit("⏳ Interval updated", buttons=panel())
        return

    b = STATE["selected_bot"]
    if not b:
        await event.edit("Select bot first", buttons=panel())
        return

    if d == "status":
        lines = [
            f"📥 Pending Queue : {total(b)}",
            f"📦 Batch         : {CONFIG['bots'][b]['batch']}",
            f"⏳ Interval      : {CONFIG['bots'][b]['interval']} sec"
        ]
        for s in CONFIG["bots"][b]["sources"]:
            lines.append(f"{s} → Q:{size(b,s)}")
        await event.edit("\n".join(lines), buttons=panel())

    if d == "traffic":
        lines = ["📈 Traffic"]
        for d2 in CONFIG["bots"][b]["destinations"]:
            lines.append(f"{d2} → {STATS[b]['destinations'].get(str(d2),0)}")
        await event.edit("\n".join(lines), buttons=panel())

# ================= START =================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    for b in CONFIG["bots"]:
        for _ in range(WORKERS_PER_BOT):
            asyncio.create_task(
                worker(
                    b,
                    client=client,
                    CONFIG=CONFIG,
                    STATS=STATS,
                    auto_scale=auto_scale,
                    is_paused=is_paused,
                    is_autoscale=is_autoscale
                )
            )

    print("✅ SYSTEM RUNNING (INDENTATION SAFE)")
    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
