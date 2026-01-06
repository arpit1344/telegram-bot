import os, json, asyncio, sys
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button

# ================= ENV =================
load_dotenv(".env")

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
        STATS[b] = {"total": 0, "destinations": {}}
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

    total_q = sum(len(q) for q in QUEUES[bot_key].values())
    bot = CONFIG["bots"][bot_key]

    if total_q > 100:
        bot["batch"] = 50
        bot["interval"] = 300
    elif total_q > 20:
        bot["batch"] = 20
        bot["interval"] = 600

# ================= SOURCE LISTENER =================
@client.on(events.NewMessage)
async def collect_source(event):
    for b, bot in CONFIG["bots"].items():
        if event.chat_id in bot.get("sources", []):
            QUEUES[b][str(event.chat_id)].append(event.message)

# ================= SOURCE → BOT =================
async def worker(bot_key):
    while True:
        if SYSTEM_PAUSED:
            await asyncio.sleep(2)
            continue

        auto_scale(bot_key)
        bot = CONFIG["bots"][bot_key]
        sent = 0

        for q in QUEUES[bot_key].values():
            while q and sent < bot.get("batch", 10):
                msg = q.pop(0)

                if msg.media:
                    await client.send_file(bot["username"], msg.media, caption=msg.text)
                else:
                    await client.send_message(bot["username"], msg.text)

                STATS[bot_key]["total"] += 1
                sent += 1

        if sent:
            await asyncio.sleep(bot.get("interval", 1800))

        await asyncio.sleep(1)

# ================= BOT → STORE =================
@client.on(events.NewMessage)
async def bot_to_store(event):
    for bot in CONFIG["bots"].values():
        if event.sender_id == bot["id"]:
            store = bot.get("store_channel")
            if not store:
                return

            if event.message.media:
                await client.send_file(store, event.message.media, caption=event.text)
            else:
                await client.send_message(store, event.text)

# ================= STORE → DEST =================
@client.on(events.NewMessage)
async def store_to_dest(event):
    for k, bot in CONFIG["bots"].items():
        if event.chat_id == bot.get("store_channel"):
            for d in bot.get("destinations", []):
                if event.message.media:
                    await client.send_file(d, event.message.media, caption=event.text)
                else:
                    await client.send_message(d, event.text)

                STATS[k]["destinations"].setdefault(str(d), 0)
                STATS[k]["destinations"][str(d)] += 1

# ================= ADMIN PANEL =================
def panel():
    sel = STATE.get("selected_bot") or "None"
    return [
        [Button.inline(f"🤖 Bot: {sel}", b"select_bot")],
        [Button.inline("🗃 Set Store Channel", b"set_store")],
        [
            Button.inline("▶ Start", b"start"),
            Button.inline("⏸ Pause", b"pause")
        ],
        [
            Button.inline("📊 Status", b"status"),
            Button.inline("📊 Dest Stats", b"dest_stats")
        ]
    ]

@admin_bot.on(events.NewMessage)
async def admin_text(event):
    if event.sender_id not in ADMINS:
        return

    if event.text == "/panel":
        await event.reply("🛠 ADMIN PANEL", buttons=panel())
        return

    if STATE["mode"] == "set_store":
        b = STATE.get("selected_bot")
        if not b:
            await event.reply("❗ Select bot first", buttons=panel())
            return

        cid = await detect_channel_id(event)
        if not cid:
            await event.reply("❌ Invalid channel\nSend ID / @username / forward msg")
            return

        CONFIG["bots"][b]["store_channel"] = cid
        save_config(CONFIG)
        STATE["mode"] = None

        await event.reply(f"✅ Store channel set\nID: `{cid}`", buttons=panel())

@admin_bot.on(events.CallbackQuery)
async def admin_buttons(event):
    global SYSTEM_PAUSED

    if event.sender_id not in ADMINS:
        return

    d = event.data.decode()

    if d == "select_bot":
        rows = [
            [Button.inline(k, f"sel_{k}".encode())]
            for k in CONFIG["bots"]
        ]
        await event.edit("🤖 Select Bot:", buttons=rows)

    elif d.startswith("sel_"):
        STATE["selected_bot"] = d.replace("sel_", "")
        await event.edit("✅ Bot selected", buttons=panel())

    elif d == "set_store":
        STATE["mode"] = "set_store"
        await event.edit(
            "🗃 Send store channel:\n"
            "• Forward any msg\n"
            "• OR send @username\n"
            "• OR send -100xxxx ID"
        )

    elif d == "pause":
        SYSTEM_PAUSED = True
        await event.edit("⏸ SYSTEM PAUSED", buttons=panel())

    elif d == "start":
        SYSTEM_PAUSED = False
        await event.edit("▶ SYSTEM RUNNING", buttons=panel())

    elif d == "status":
        txt = ["📊 STATUS\n"]
        for b, s in STATS.items():
            txt.append(f"{b}: {s['total']} msgs")
        await event.edit("\n".join(txt), buttons=panel())

    elif d == "dest_stats":
        txt = ["📊 PER-DESTINATION STATS\n"]
        for b, data in STATS.items():
            txt.append(f"🤖 {b}")
            for d, c in data["destinations"].items():
                txt.append(f"  {d}: {c}")
            txt.append("")
        await event.edit("\n".join(txt), buttons=panel())

# ================= START =================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    for b in CONFIG["bots"]:
        asyncio.create_task(worker(b))

    print("✅ SYSTEM RUNNING (STORE SET VIA ADMIN PANEL)")
    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
