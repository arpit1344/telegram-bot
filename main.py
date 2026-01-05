# =====================================================
# 🔧 LOAD ENV (NO TOKENS IN GITHUB)
# =====================================================
import os, sys, time, asyncio
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaWebPage
from telethon.sessions import StringSession

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
INTERVAL = 1800        # 30 min (used only when > batch)
RETRY_DELAY = 90

BUSY_KEYWORDS = ["system busy", "try again", "busy"]

SYSTEM_PAUSED = False

# =====================================================
# 🔧 CLIENTS
# =====================================================
client = TelegramClient("session", api_id, api_hash)

admin_bot = TelegramClient(
    StringSession(),
    api_id,
    api_hash
).start(bot_token=ADMIN_BOT_TOKEN)

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
    print("♻ Restarting service...")
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

            # CASE 1: 1–BATCH → instant send
            if 0 < qlen <= BATCH_SIZE:
                batch = q[:]
                q.clear()

                for msg in batch:
                    if msg.media:
                        await client.send_file(
                            bot["username"],
                            msg.media,
                            caption=msg.text
                        )
                    else:
                        await client.send_message(
                            bot["username"],
                            msg.text
                        )
                continue

            # CASE 2: > BATCH → strict batch + wait
            if qlen > BATCH_SIZE:
                batch = q[:BATCH_SIZE]
                del q[:BATCH_SIZE]

                for msg in batch:
                    if msg.media:
                        await client.send_file(
                            bot["username"],
                            msg.media,
                            caption=msg.text
                        )
                    else:
                        await client.send_message(
                            bot["username"],
                            msg.text
                        )

                print(f"⏳ Waiting {INTERVAL}s for {bot['username']}")
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
                    await client.send_file(
                        bot["username"],
                        msg.media,
                        caption=msg.text
                    )
                else:
                    await client.send_message(
                        bot["username"],
                        msg.text
                    )
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
        print("⏳ Busy reply ignored")
        return

    for ch in DESTINATION_CHANNELS:
        try:
            if isinstance(event.message.media, MessageMediaWebPage):
                await client.send_message(ch, event.message.text)
            elif event.message.media:
                await client.send_file(
                    ch,
                    event.message.media,
                    caption=event.message.text
                )
            else:
                await client.send_message(ch, event.message.text)
        except Exception as e:
            print("❌ Forward error:", e)

# =====================================================
# 👑 ADMIN COMMANDS
# =====================================================
@admin_bot.on(events.NewMessage(from_users=ADMIN_ID))
async def admin_commands(event):
    global SYSTEM_PAUSED, INTERVAL, BATCH_SIZE

    cmd = event.text.lower().strip()

    if cmd == "/pause":
        SYSTEM_PAUSED = True
        await event.reply("⏸ Bot paused")

    elif cmd == "/start":
        SYSTEM_PAUSED = False
        await event.reply("▶ Bot resumed")

    elif cmd.startswith("/setinterval"):
        INTERVAL = int(cmd.split()[1])
        await event.reply(f"⏳ Interval set to {INTERVAL}s")

    elif cmd.startswith("/setbatch"):
        BATCH_SIZE = int(cmd.split()[1])
        await event.reply(f"📦 Batch size set to {BATCH_SIZE}")

    elif cmd == "/status":
        msg = f"""
📊 STATUS

Paused: {SYSTEM_PAUSED}
Batch: {BATCH_SIZE}
Interval: {INTERVAL}

Queues:
"""
        for sid, q in queues.items():
            msg += f"\n{sid} → {len(q)}"
        await event.reply(msg)

    elif cmd == "/restart":
        await event.reply("♻ Restarting bot")
        restart()

    else:
        await event.reply(
            "/pause\n/start\n/setinterval 1800\n/setbatch 10\n/status\n/restart"
        )

# =====================================================
# ▶ START SYSTEM
# =====================================================
async def main():
    await client.start()
    await admin_bot.start()

    for sid in SOURCE_BOT_MAP:
        asyncio.create_task(bot_worker(sid))
        asyncio.create_task(retry_worker(sid))

    print("🚀 BOT + ADMIN RUNNING")
    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
