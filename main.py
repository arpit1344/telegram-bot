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
WORKERS_PER_BOT = 2   # 🔥 MULTIPLE WORKERS

STATS = {}
STATE = {"selected_bot": None, "mode": None}

for b in CONFIG["bots"]:
    STATS[b] = {"total": 0, "sources": {}, "destinations": {}}

# ================= HELPERS =================
def is_paused(): return SYSTEM_PAUSED
def is_autoscale(): return AUTO_SCALE

def auto_scale(bot_key):
    q = total(bot_key)
    bot = CONFIG["bots"][bot_key]
    if q > 100:
        bot["batch"], bot["interval"] = 50, 300
    elif q > 20:
        bot["batch"], bot["interval"] = 20, 600
    else:
        bot.setdefault("batch", 10)
        bot.setdefault("interval", 1800)

# ================= PANEL =================
def panel():
    sel = STATE["selected_bot"] or "None"
    return [
        [Button.inline(f"🤖 Select Bot ({sel})", b"select_bot")],
        [Button.inline("🗃 Set Store", b"set_store")],
        [Button.inline("➕ Add Source", b"add_src"),
         Button.inline("➕ Add Dest", b"add_dest")],
        [Button.inline("⏸ Pause", b"pause"),
         Button.inline("▶ Start", b"start")],
        [Button.inline("📊 Status", b"status"),
         Button.inline("📈 Traffic", b"traffic")]
    ]

# ================= ROUTER =================
@client.on(events.NewMessage)
async def router(event):
    # SOURCE → REDIS QUEUE
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
                if event.media and not isinstance(event.media, MessageMediaWebPage):
                    await client.send_file(d, event.media, caption=event.text)
                else:
                    await client.send_message(d, event.text or "")

                STATS[b]["destinations"].setdefault(str(d), 0)
                STATS[b]["destinations"][str(d)] += 1

# ================= ADMIN =================
@admin_bot.on(events.NewMessage)
async def admin(event):
    if event.sender_id not in ADMINS:
        return
    if event.text == "/panel":
        await event.reply("🛠 ADMIN PANEL", buttons=panel())

# ================= BUTTONS =================
@admin_bot.on(events.CallbackQuery)
async def buttons(event):
    global SYSTEM_PAUSED
    await event.answer()
    d = event.data.decode()

    if d == "select_bot":
        rows = [[Button.inline(k, f"sel_{k}".encode())] for k in CONFIG["bots"]]
        await event.edit("Select bot", buttons=rows); return

    if d.startswith("sel_"):
        STATE["selected_bot"] = d.replace("sel_", "")
        await event.edit("Bot selected", buttons=panel()); return

    if d == "pause":
        SYSTEM_PAUSED = True
        await event.edit("Paused", buttons=panel()); return

    if d == "start":
        SYSTEM_PAUSED = False
        await event.edit("Started", buttons=panel()); return

    b = STATE["selected_bot"]
    if not b:
        await event.edit("Select bot first", buttons=panel()); return

    if d == "status":
        lines = [f"Pending: {total(b)}"]
        for s in CONFIG["bots"][b]["sources"]:
            lines.append(f"{s} → Q:{size(b,s)} Sent:{STATS[b]['sources'].get(str(s),0)}")
        await event.edit("\n".join(lines), buttons=panel()); return

    if d == "traffic":
        lines = ["Traffic:"]
        for d2 in CONFIG["bots"][b]["destinations"]:
            lines.append(f"{d2} → {STATS[b]['destinations'].get(str(d2),0)}")
        await event.edit("\n".join(lines), buttons=panel())

# ================= START =================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    for b in CONFIG["bots"]:
        for i in range(WORKERS_PER_BOT):
            asyncio.create_task(
                worker(
                    b,
                    wid=i,
                    client=client,
                    CONFIG=CONFIG,
                    STATS=STATS,
                    auto_scale=auto_scale,
                    is_paused=is_paused,
                    is_autoscale=is_autoscale
                )
            )

    print("✅ SYSTEM RUNNING (FULL FINAL VERSION)")
    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
