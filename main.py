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
with open("config.json") as f:
    CONFIG = json.load(f)

ADMINS = set(CONFIG.get("admins", []))

# ================= CLIENTS =================
client = TelegramClient("main_session", API_ID, API_HASH)
admin_bot = TelegramClient("admin_session", API_ID, API_HASH)

# ================= STATE =================
SYSTEM_PAUSED = False
AUTO_SCALE = True
WORKERS_PER_BOT = 2

STATE = {"selected_bot": None, "mode": None}
STATS = {b: {"total": 0, "sources": {}, "destinations": {}} for b in CONFIG["bots"]}

# ================= HELPERS =================
def is_paused(): return SYSTEM_PAUSED
def is_autoscale(): return AUTO_SCALE

def auto_scale(bot):
    q = total(bot)
    b = CONFIG["bots"][bot]
    if q > 100:
        b["batch"], b["interval"] = 50, 300
    elif q > 20:
        b["batch"], b["interval"] = 20, 600
    else:
        b.setdefault("batch", 10)
        b.setdefault("interval", 1800)

# ================= PANEL (SAME AS IMAGE) =================
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
    for b, bot in CONFIG["bots"].items():
        if event.chat_id in bot.get("sources", []):
            push(b, event.chat_id, {"text": event.text})
            return

    for b, bot in CONFIG["bots"].items():
        if event.sender_id == bot.get("id"):
            store = bot.get("store_channel")
            if not store:
                return
            await client.send_message(store, event.text or "")
            for d in bot.get("destinations", []):
                await client.send_message(d, event.text or "")
                STATS[b]["destinations"].setdefault(str(d), 0)
                STATS[b]["destinations"][str(d)] += 1

# ================= ADMIN =================
@admin_bot.on(events.NewMessage)
async def admin(event):
    if event.sender_id in ADMINS and event.text == "/panel":
        await event.reply("🛠 ADMIN PANEL", buttons=panel())

@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    global SYSTEM_PAUSED, AUTO_SCALE
    await event.answer()
    d = event.data.decode()

    if d == "back":
        STATE["mode"] = None
        await event.edit("🛠 ADMIN PANEL", buttons=panel()); return

    if d == "pause":
        SYSTEM_PAUSED = True
        await event.edit("⏸ Paused", buttons=panel()); return

    if d == "start":
        SYSTEM_PAUSED = False
        await event.edit("▶ Started", buttons=panel()); return

    if d == "restart":
        os.execv(sys.executable, ["python"] + sys.argv)

    if d == "as_on":
        AUTO_SCALE = True
        await event.edit("🤖 AutoScale ON", buttons=panel()); return

    if d == "as_off":
        AUTO_SCALE = False
        await event.edit("🤖 AutoScale OFF", buttons=panel()); return

    if d.startswith("b_"):
        CONFIG["bots"][STATE["selected_bot"]]["batch"] = int(d.split("_")[1])
        await event.edit("📦 Batch Updated", buttons=panel()); return

    if d.startswith("i_"):
        CONFIG["bots"][STATE["selected_bot"]]["interval"] = int(d.split("_")[1])
        await event.edit("⏳ Interval Updated", buttons=panel()); return

    if d == "status":
        b = STATE["selected_bot"]
        msg = [f"Pending: {total(b)}"]
        for s in CONFIG["bots"][b]["sources"]:
            msg.append(f"{s} → {size(b,s)}")
        await event.edit("\n".join(msg), buttons=panel())

# ================= START =================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    for b in CONFIG["bots"]:
        for _ in range(WORKERS_PER_BOT):
            asyncio.create_task(worker(
                b,
                client=client,
                CONFIG=CONFIG,
                STATS=STATS,
                auto_scale=auto_scale,
                is_paused=is_paused,
                is_autoscale=is_autoscale
            ))

    print("✅ SYSTEM RUNNING (UI MATCHED)")
    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
