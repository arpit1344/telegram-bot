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
            QUEUES.setdefault(b, {})
            QUEUES[b].setdefault(str(event.chat_id), [])
            QUEUES[b][str(event.chat_id)].append(event.message)
            return

    # BOT → STORE
    for b, bot in CONFIG["bots"].items():
        if event.sender_id == bot["id"]:
            store = bot.get("store_channel")
            if not store:
                return

            if event.message.media and not isinstance(event.message.media, MessageMediaWebPage):
                await client.send_file(store, event.message.media, caption=event.text)
            else:
                await client.send_message(store, event.text or "")
            return

    # STORE → DEST
    for b, bot in CONFIG["bots"].items():
        if event.chat_id == bot.get("store_channel"):
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

    b = STATE["selected_bot"]
    m = STATE["mode"]

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
        QUEUES[key] = {}
        STATS[key] = {"total": 0, "sources": {}, "destinations": {}}
        save_config(CONFIG)
        asyncio.create_task(worker(key))
        STATE["selected_bot"] = key
        STATE["mode"] = None
        await event.reply("✅ Bot added", buttons=panel())
        return

    if not b:
        return

    if m == "add_src":
        cid = await detect_channel_id(event)
        if cid not in CONFIG["bots"][b]["sources"]:
            CONFIG["bots"][b]["sources"].append(cid)
            QUEUES[b][str(cid)] = []
        save_config(CONFIG)
        STATE["mode"] = None
        await event.reply("✅ Source added", buttons=panel())

    elif m == "rm_src":
        cid = int(event.text)
        if cid in CONFIG["bots"][b]["sources"]:
            CONFIG["bots"][b]["sources"].remove(cid)
            QUEUES[b].pop(str(cid), None)
        save_config(CONFIG)
        STATE["mode"] = None
        await event.reply("❌ Source removed", buttons=panel())

    elif m == "add_dest":
        did = int(event.text)
        CONFIG["bots"][b]["destinations"].append(did)
        save_config(CONFIG)
        STATE["mode"] = None
        await event.reply("✅ Destination added", buttons=panel())

    elif m == "rm_dest":
        did = int(event.text)
        CONFIG["bots"][b]["destinations"].remove(did)
        save_config(CONFIG)
        STATE["mode"] = None
        await event.reply("❌ Destination removed", buttons=panel())

    elif m == "set_store":
        cid = await detect_channel_id(event)
        CONFIG["bots"][b]["store_channel"] = cid
        save_config(CONFIG)
        STATE["mode"] = None
        await event.reply("✅ Store channel set", buttons=panel())

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

    if d == "select_bot":
        rows = [[Button.inline(k, f"sel_{k}".encode())] for k in CONFIG["bots"]]
        rows.append([Button.inline("⬅ Back", b"back")])
        await event.edit("🤖 Select Bot:", buttons=rows)
        return

    if d.startswith("sel_"):
        STATE["selected_bot"] = d.replace("sel_", "")
        await event.edit("✅ Bot selected", buttons=panel())
        return

    if d == "add_bot":
        STATE["mode"] = "add_bot"
        await event.edit("Send: @BotUsername bot_id", buttons=[[Button.inline("⬅ Back", b"back")]])
        return

    if d == "rm_bot":
        b = STATE["selected_bot"]
        if b:
            CONFIG["bots"].pop(b)
            QUEUES.pop(b, None)
            STATS.pop(b, None)
            save_config(CONFIG)
            STATE["selected_bot"] = None
        await event.edit("❌ Bot removed", buttons=panel())
        return

    if d in ("add_src", "rm_src", "add_dest", "rm_dest", "set_store"):
        STATE["mode"] = d
        await event.edit("Send input now", buttons=[[Button.inline("⬅ Back", b"back")]])
        return

    if d.startswith("b_"):
        CONFIG["bots"][STATE["selected_bot"]]["batch"] = int(d.split("_")[1])
        save_config(CONFIG)
        await event.edit("📦 Batch updated", buttons=panel())
        return

    if d.startswith("i_"):
        CONFIG["bots"][STATE["selected_bot"]]["interval"] = int(d.split("_")[1])
        save_config(CONFIG)
        await event.edit("⏳ Interval updated", buttons=panel())
        return

    if d == "as_on":
        AUTO_SCALE = True
        await event.edit("🤖 AutoScale ON", buttons=panel())
        return

    if d == "as_off":
        AUTO_SCALE = False
        await event.edit("🤖 AutoScale OFF", buttons=panel())
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

    if d == "status":
        b = STATE.get("selected_bot")

        if not b or b not in CONFIG["bots"]:
            await event.edit("❗ Please select a bot first", buttons=panel())
            return

        bot = CONFIG["bots"][b]
        stats = STATS.get(b, {})

        lines = [
            "📊 BOT STATUS\n",
            f"🤖 Bot Key      : {b}",
            f"👤 Username     : {bot.get('username')}",
            f"🆔 Bot ID       : {bot.get('id')}",
            "",
            f"🗃 Store Channel: {bot.get('store_channel', 'Not set')}",
            "",
            f"📥 Sources ({len(bot.get('sources', []))}):"
        ]

        for s in bot.get("sources", []):
            count = stats.get("sources", {}).get(str(s), 0)
            lines.append(f" • {s}  | Forwarded: {count}")

        lines.append("")
        lines.append(f"📤 Destinations ({len(bot.get('destinations', []))}):")

        for d2 in bot.get("destinations", []):
            count = stats.get("destinations", {}).get(str(d2), 0)
            lines.append(f" • {d2}  | Sent: {count}")

        lines.extend([
            "",
            f"📨 Total sent to bot     : {stats.get('total', 0)}",
            f"🤖 Total bot replies    : {stats.get('total', 0)}",
            "",
            f"📦 Batch Size           : {bot.get('batch')}",
            f"⏳ Interval (seconds)   : {bot.get('interval')}",
            f"⚙ AutoScale            : {'ON' if AUTO_SCALE else 'OFF'}",
            f"⏸ System Paused        : {'YES' if SYSTEM_PAUSED else 'NO'}"
        ])

        await event.edit("\n".join(lines), buttons=panel())
        return

if d == "traffic":
    txt = ["📈 TRAFFIC\n"]
    for b, data in STATS.items():
        txt.append(f"🤖 {b}")
        for s, c in data["sources"].items():
            txt.append(f"  SRC {s}: {c}")
        for d2, c2 in data["destinations"].items():
            txt.append(f"  DEST {d2}: {c2}")
        txt.append("")
    await event.edit("\n".join(txt), buttons=panel())
    return

# ================= START =================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    for b in CONFIG["bots"]:
        asyncio.create_task(worker(b))

    print("✅ SYSTEM RUNNING (FINAL – WEBPAGE SAFE)")
    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
