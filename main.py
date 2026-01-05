# =====================================================
# 🔧 CONFIG SECTION (EDIT ONLY api_id & api_hash)
# =====================================================

api_id = 36963896
api_hash = 'efc64243eb8abbec89f1b9df83a5a374'

# SOURCE → BOT FIXED MAPPING
SOURCE_BOT_MAP = {
    -1003424409974: {   # Source Channel 1
        "username": "@DW2DW_LinkConverterBot",
        "id": 7247805209
    },
    -1003619801050: {   # Source Channel 2
        "username": "@LinkConvertTera3bot",
        "id": 8236128760
    }
}

# DESTINATION CHANNELS (COMMON)
DESTINATION_CHANNELS = [
    -1003665638166,
    -1003510197761,
    -1003339660010
]

BATCH_SIZE = 10
INTERVAL = 1800   # 30 minutes

# =====================================================
# ❌ CONFIG END – BELOW DON'T TOUCH
# =====================================================

from telethon import TelegramClient, events
import asyncio, os, sys, time

client = TelegramClient("session", api_id, api_hash)

# =====================================================
# 📦 DATA STRUCTURES
# =====================================================

# Separate queue per source
queues = {sid: [] for sid in SOURCE_BOT_MAP.keys()}

# bot_id → expected replies count
pending_batches = {}

# bot_id → collected replies
reply_buffers = {}

SOURCE_IDS = list(SOURCE_BOT_MAP.keys())
BOT_IDS = [v["id"] for v in SOURCE_BOT_MAP.values()]

# =====================================================
# ♻ AUTO RESTART
# =====================================================

def restart():
    print("♻ Auto-restarting system...")
    time.sleep(5)
    os.execv(sys.executable, ['python'] + sys.argv)

# =====================================================
# 📥 SOURCE → QUEUE (PER SOURCE)
# =====================================================

@client.on(events.NewMessage(chats=SOURCE_IDS))
async def collect_messages(event):
    queues[event.chat_id].append(event.message)
    print(f"📦 Queue[{event.chat_id}] size: {len(queues[event.chat_id])}")

# =====================================================
# 🚀 QUEUE → BOT (AUTO SYNC WORKER)
# =====================================================

async def queue_worker(source_id):
    bot = SOURCE_BOT_MAP[source_id]
    bot_id = bot["id"]

    while True:
        try:
            q = queues[source_id]

            # Only start new batch if bot is free
            if bot_id not in pending_batches and len(q) >= BATCH_SIZE:
                batch = q[:BATCH_SIZE]
                del q[:BATCH_SIZE]

                print(f"📤 Sending {BATCH_SIZE} msgs → {bot['username']}")

                pending_batches[bot_id] = BATCH_SIZE
                reply_buffers[bot_id] = []

                for msg in batch:
                    await client.forward_messages(bot["username"], msg)

                print(f"⏳ Waiting replies from {bot['username']}")

            await asyncio.sleep(2)

        except Exception as e:
            print(f"🔥 Worker error (source {source_id}):", e)
            restart()

# =====================================================
# 🔗 BOT REPLY → DESTINATION (REPLY SYNC CORE)
# =====================================================

@client.on(events.NewMessage(from_users=BOT_IDS))
async def bot_reply_handler(event):
    bot_id = event.sender_id

    if bot_id not in pending_batches:
        return

    reply_buffers[bot_id].append(event.message)
    received = len(reply_buffers[bot_id])
    expected = pending_batches[bot_id]

    print(f"🤖 Bot {bot_id} reply {received}/{expected}")

    # When full batch replies received
    if received == expected:
        print(f"✅ Batch complete from bot {bot_id}, forwarding...")

        for msg in reply_buffers[bot_id]:
            for ch in DESTINATION_CHANNELS:
                try:
                    if msg.media:
                        await client.send_file(
                            ch,
                            msg.media,
                            caption=msg.text
                        )
                    else:
                        await client.send_message(ch, msg.text)
                except Exception as e:
                    print("❌ Forward error:", e)

        # Clear sync state
        del pending_batches[bot_id]
        del reply_buffers[bot_id]

# =====================================================
# ▶ START SYSTEM
# =====================================================

async def main():
    await client.start()

    # Start one worker per source (parallel)
    for source_id in SOURCE_IDS:
        asyncio.create_task(queue_worker(source_id))

    print("🚀 AUTO-SYNC SYSTEM RUNNING (PRODUCTION MODE)")
    await client.run_until_disconnected()

client.loop.run_until_complete(main())

