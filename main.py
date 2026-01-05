# =====================================================
# 🔧 LOAD ENV
# =====================================================
import os, sys, time, asyncio
from dotenv import load_dotenv

from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaWebPage

load_dotenv()

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")

ADMIN_ID = int(os.getenv("ADMIN_ID"))
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")

# =====================================================
# 🔧 CONFIG
# =====================================================
SOURCE_BOT_MAP = {
    -1003424409974: {
        "username": "@DW2DW_LinkConverterBot",
        "id": 7247805209
    },
    -1003619801050: {
        "username": "@LinkConvertTera3bot",
        "id": 8236128760
    }
}

DESTINATION_CHANNELS = [
    -1003665638166,
    -1003510197761,
    -1003339660010
]

BATCH_SIZE = 10
INTERVAL = 1800
RETRY_DELAY = 90

BUSY_KEYWORDS = ["system busy", "try again", "busy"]
SYSTEM_PAUSED = False

# =====================================================
# 🔧 CLIENTS (IMPORTANT FIX HERE)
# =====================================================
client = TelegramClient("main_session", api_id, api_hash)
admin_bot = TelegramClient("admin_session", api_id, api_hash)

# =====================================================
# 🔧 QUEUES
# =====================================================
queues = {sid: [] for sid in SOURCE_BOT_MAP}
retry_queues = {sid: [] for sid in SOURCE_BOT_MAP}
BOT_IDS = [v["id"] for v in SOURCE_BOT_MAP.values()]

# =====================================================
# 🔁 AUTO RESTART
# =====================================================
def restart():
    time.sleep(3)
    os.execv(sys.executable, ["python"] + sys.argv)

# =====================================================
# 📥 SOURCE → QUEUE
# =====================================================
@client.on(events.NewMessage(chats=list(SOURCE_BOT_MAP.keys())))
async def collect(event):
    queues[event.chat_id].append(event.message)
    print(f"📦 Queue[{event.chat_id}] = {len(queues[event.chat_id])}")

# =====================================================
# 🚀 BOT WORKER
# =====================================================
async def bot_worker(source_id):
    global SYSTEM_PAUSED
    bot = SOURCE_BOT_MAP[source_id]
    q = queues[source_id]

    while True:
        try:
            if SYSTEM_PAUSED:
                await asyncio.sleep(5)
                continue

            qlen = len(q)

            if 0 < qlen <= BATCH_SIZE:
                batch = q[:]
                q.clear()

                for msg in batch:
                    if msg.media:
                        await client.send_file(bot["username"], msg.media, caption=msg.text)
                    else:
                        await client.send_message(bot["username"], msg.text)
                continue

            if qlen > BATCH_SIZE:
                batch = q[:BATCH_SIZE]
                del q[:BATCH_SIZE]

                for msg in batch:
                    if msg.media:
                        await client.send_file(bot["username"], msg.media, caption=msg.text)
                    else:
                        await client.send_message(bot["username"], msg.text)

                await asyncio.sleep(INTERVAL)

            await asyncio.sleep(1)

        except Exception as e:
            print("🔥 Worker error:", e)
            restart()

# =====================================================
# 🔁 RETRY WORKER
# =====================================================
async def retry_worker(source_id):
    bot = SOURCE_BOT_MAP[source_id]
    rq = retry_queues[source_id]

    while True:
        try:
            if rq:
                msg = rq.pop(0)
                if msg.media:
                    await client.send_file(bot["username"], msg.media, caption=msg.text)
                else:
                    await client.send_message(bot["username"], msg.text)
                await asyncio.sleep(RETRY_DELAY)
            else:
                await asyncio.sleep(5)
        except Exception as e:
            print("🔥 Retry error:", e)
            restart()

# =====================================================
# 🔗 BOT REPLY → DESTINATION
# =====================================================
@client.on(events.NewMessage(from_users=BOT_IDS))
async def bot_reply(event):
    text_lower = (event.message.text or "").lower()
    if any(k in text_lower for k in BUSY_KEYWORDS):
        return

    for ch in DESTINATION_CHANNELS:
        try:
            if isinstance(event.message.media, MessageMediaWebPage):
                await client.send_message(ch, event.message.text)
            elif event.message.media:
                await client.send_file(ch, event.message.media, caption=event.message.text)
            else:
                await client.send_message(ch, event.message.text)
        except Exception as e:
            print("❌ Forward error:", e)

# =====================================================
# 👑 ADMIN COMMANDS (FIXED & SIMPLE)
# =====================================================
@admin_bot.on(events.NewMessage)
async def admin_commands(event):
    global SYSTEM_PAUSED, INTERVAL, BATCH_SIZE

    if event.sender_id != ADMIN_ID:
        return
    if not event.text:
        return

    cmd = event.text.lower().strip()

    if cmd == "/status":
        await event.reply("✅ ADMIN BOT WORKING")

    elif cmd == "/pause":
        SYSTEM_PAUSED = True
        await event.reply("⏸ Bot paused")

    elif cmd == "/start":
        SYSTEM_PAUSED = False
        await event.reply("▶ Bot resumed")

    elif cmd.startswith("/setinterval"):
        INTERVAL = int(cmd.split()[1])
        await event.reply(f"⏳ Interval set to {INTERVAL}")

    elif cmd.startswith("/setbatch"):
        BATCH_SIZE = int(cmd.split()[1])
        await event.reply(f"📦 Batch size set to {BATCH_SIZE}")

    elif cmd == "/restart":
        await event.reply("♻ Restarting")
        restart()

# =====================================================
# ▶ START SYSTEM
# =====================================================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    for sid in SOURCE_BOT_MAP:
        asyncio.create_task(bot_worker(sid))
        asyncio.create_task(retry_worker(sid))

    print("🚀 MAIN BOT + ADMIN BOT BOTH RUNNING")

    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
