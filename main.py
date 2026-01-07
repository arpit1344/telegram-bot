import os, json, asyncio, sys, time
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.errors import MessageNotModifiedError

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

QUEUES = {}
STATS = {}
STATE = {"selected_bot": None, "mode": None}

# debounce: {(user_id, button): last_time}
DEBOUNCE = {}

# auto refresh tasks
AUTO_TASKS = {}   # {"status": task, "traffic": task}

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

# ================= UTIL =================
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

def debounce_ok(user_id, key, gap=1.0):
    now = time.time()
    last = DEBOUNCE.get((user_id, key), 0)
    if now - last < gap:
        return False
    DEBOUNCE[(user_id, key)] = now
    return True

async def safe_edit(event, text, buttons=None):
    try:
        await event.edit(text, buttons=buttons)
    except MessageNotModifiedError:
        pass
    except Exception as e:
        print("EDIT ERROR:", e)

# ================= AUTOSCALE =================
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
        [Button.inline(f"🤖 Bot ({sel})", b"select_bot"),
         Button.inline("➕ Add Bot", b"add_bot"),
         Button.inline("❌ Remove Bot", b"rm_bot")],

        [Button.inline("➕ Add Source", b"add_src"),
         Button.inline("❌ Remove Source", b"rm_src")],

        [Button.inline("📦 Add Store", b"add_store"),
         Button.inline("❌ Remove Store", b"rm_store")],

        [Button.inline("➕ Add Dest", b"add_dest"),
         Button.inline("❌ Remove Dest", b"rm_dest")],

        [Button.inline("📊 Status", b"status"),
         Button.inline("📈 Traffic", b"traffic")],

        [Button.inline("📦 5", b"b_5"),
         Button.inline("📦 10", b"b_10"),
         Button.inline("📦 20", b"b_20"),
         Button.inline("📦 50", b"b_50")],

        [Button.inline("⏳ 5m", b"i_300"),
         Button.inline("⏳ 10m", b"i_600"),
         Button.inline("⏳ 30m", b"i_1800")],

        [Button.inline("🤖 AutoScale ON", b"as_on"),
         Button.inline("🤖 AutoScale OFF", b"as_off")],

        [Button.inline("⏸ Pause", b"pause"),
         Button.inline("▶ Start", b"start"),
         Button.inline("♻ Restart", b"restart")]
    ]

# ================= AUTO REFRESH =================
async def auto_refresh(event, mode):
    while True:
        await asyncio.sleep(10)
        if mode == "status":
            lines = ["📊 STATUS\n"]
            for b, bot in CONFIG["bots"].items():
                lines.append(f"🤖 {b} ({bot['username']})")
                lines.append(f" Batch:{bot.get('batch')} Interval:{bot.get('interval')}")
                lines.append(f" Store:{bot.get('store_channels', [])}")
                for s in bot.get("sources", []):
                    lines.append(f"  • {s} | Q:{len(QUEUES[b].get(str(s), []))}")
                lines.append("")
            await safe_edit(event, "\n".join(lines), panel())

        elif mode == "traffic":
            lines = ["📈 TRAFFIC\n"]
            for b, data in STATS.items():
                lines.append(f"🤖 {b} Total:{data['total']}")
                for s, c in data["sources"].items():
                    bars = "█" * min(10, c // 5)
                    lines.append(f"  {s}: {bars} ({c})")
                lines.append("")
            await safe_edit(event, "\n".join(lines), panel())

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
                try:
                    if msg.media:
                        await client.send_file(bot["username"], msg.media, caption=msg.text)
                    else:
                        await client.send_message(bot["username"], msg.text)
                except:
                    pass

                STATS[bot_key]["total"] += 1
                STATS[bot_key]["sources"].setdefault(src, 0)
                STATS[bot_key]["sources"][src] += 1
                sent += 1

        if sent >= batch:
            await asyncio.sleep(interval)

        await asyncio.sleep(1)

# ================= BOT → STORE =================
@client.on(events.NewMessage)
async def bot_reply(event):
    for bot in CONFIG["bots"].values():
        if event.sender_id == bot["id"]:
            for sc in bot.get("store_channels", []):
                try:
                    if event.message.media:
                        await client.send_file(sc, event.message.media, caption=event.text)
                    else:
                        await client.send_message(sc, event.text)
                except:
                    pass

# ================= STORE → DEST =================
@client.on(events.NewMessage)
async def store_forward(event):
    for bot in CONFIG["bots"].values():
        if event.chat_id in bot.get("store_channels", []):
            for d in bot.get("destinations", []):
                try:
                    if event.message.media:
                        await client.send_file(d, event.message.media, caption=event.text)
                    else:
                        await client.send_message(d, event.text)
                except:
                    pass

# ================= ADMIN TEXT =================
@admin_bot.on(events.NewMessage)
async def admin_text(event):
    if event.sender_id not in ADMINS or not event.text:
        return

    if event.text == "/panel":
        await event.reply("🛠 ADMIN PANEL", buttons=panel())
        return

# ================= BUTTONS =================
@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    global SYSTEM_PAUSED, AUTO_SCALE

    if event.sender_id not in ADMINS:
        return

    d = event.data.decode()

    if not debounce_ok(event.sender_id, d):
        return

    # stop previous auto refresh
    for t in AUTO_TASKS.values():
        t.cancel()
    AUTO_TASKS.clear()

    if d == "status":
        AUTO_TASKS["status"] = asyncio.create_task(auto_refresh(event, "status"))

    elif d == "traffic":
        AUTO_TASKS["traffic"] = asyncio.create_task(auto_refresh(event, "traffic"))

    elif d == "pause":
        SYSTEM_PAUSED = True
        await safe_edit(event, "⏸ Paused", panel())

    elif d == "start":
        SYSTEM_PAUSED = False
        await safe_edit(event, "▶ Started", panel())

    elif d == "as_on":
        AUTO_SCALE = True
        await safe_edit(event, "AutoScale ON", panel())

    elif d == "as_off":
        AUTO_SCALE = False
        await safe_edit(event, "AutoScale OFF", panel())

    elif d == "restart":
        os.execv(sys.executable, ["python"] + sys.argv)

    else:
        await safe_edit(event, "Updated", panel())

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
