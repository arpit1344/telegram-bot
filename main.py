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

        [Button.inline("📦 10", b"b_10"),
         Button.inline("📦 20", b"b_20"),
         Button.inline("📦 50", b"b_50")],

        [Button.inline("⏳ 10m", b"i_600"),
         Button.inline("⏳ 30m", b"i_1800"),
         Button.inline("⏳ 60m", b"i_3600")],

        [Button.inline("🤖 AutoScale ON", b"as_on"),
         Button.inline("🤖 AutoScale OFF", b"as_off")],

        [Button.inline("⏸ Pause", b"pause"),
         Button.inline("▶ Start", b"start")],

        [Button.inline("📊 Status", b"status"),
         Button.inline("📈 Traffic", b"traffic")]
    ]

# ================= MESSAGE ROUTER =================
@client.on(events.NewMessage)
async def message_router(event):

    # SOURCE → QUEUE
    for b, bot in CONFIG["bots"].items():
        if event.chat_id in bot.get("sources", []):
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
        sent = 0

        for src, q in QUEUES[bot_key].items():
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

# ================= ADMIN =================
@admin_bot.on(events.NewMessage)
async def admin_text(event):
    if event.sender_id not in ADMINS:
        return
    if event.text == "/panel":
        await event.reply("🛠 ADMIN PANEL", buttons=panel())

@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    global SYSTEM_PAUSED, AUTO_SCALE

    if event.sender_id not in ADMINS:
        return

    d = event.data.decode()

    if d == "select_bot":
        rows = [[Button.inline(k, f"sel_{k}".encode())] for k in CONFIG["bots"]]
        await event.edit("🤖 Select Bot:", buttons=rows)

    elif d.startswith("sel_"):
        STATE["selected_bot"] = d.replace("sel_", "")
        await event.edit("✅ Bot selected", buttons=panel())

    elif d == "pause":
        SYSTEM_PAUSED = True
        await event.edit("⏸ Paused", buttons=panel())

    elif d == "start":
        SYSTEM_PAUSED = False
        await event.edit("▶ Started", buttons=panel())

    elif d == "status":
        b = STATE["selected_bot"]
        if not b:
            await event.edit("❗ Select a bot first", buttons=panel())
            return
        bot = CONFIG["bots"][b]
        stats = STATS[b]
        txt = (
            f"📊 STATUS\n\n"
            f"🤖 {bot['username']}\n"
            f"🗃 Store: {bot.get('store_channel')}\n"
            f"📦 Batch: {bot.get('batch')}\n"
            f"⏳ Interval: {bot.get('interval')}\n"
            f"📨 Total: {stats['total']}"
        )
        await event.edit(txt, buttons=panel())

    elif d == "traffic":
        b = STATE["selected_bot"]
        if not b:
            await event.edit("❗ Select a bot first", buttons=panel())
            return
        stats = STATS[b]
        lines = ["📈 TRAFFIC\n"]
        for s, c in stats["sources"].items():
            lines.append(f"SRC {s}: {c}")
        for d2, c2 in stats["destinations"].items():
            lines.append(f"DEST {d2}: {c2}")
        await event.edit("\n".join(lines), buttons=panel())

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
