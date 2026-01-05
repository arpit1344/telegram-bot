# =====================================================
# 🔧 CONFIG
# =====================================================

api_id = 123456
api_hash = "YOUR_API_HASH"

SOURCE_BOT_MAP = {
    -1003424409974: {  # Source 1
        "username": "@DW2DW_LinkConverterBot",
        "id": 7247805209
    },
    -1003619801050: {  # Source 2
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
INTERVAL = 1800  # 30 min

# =====================================================
# ❌ CONFIG END
# =====================================================

from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaWebPage
import asyncio, os, sys, time

client = TelegramClient("session", api_id, api_hash)

# 🔹 Separate queues per source
queues = {
    source_id: [] for source_id in SOURCE_BOT_MAP
}

BOT_IDS = [v["id"] for v in SOURCE_BOT_MAP.values()]

# =====================================================
# 🔁 AUTO RESTART
# =====================================================
def restart():
    time.sleep(5)
    os.execv(sys.executable, ['python'] + sys.argv)

# =====================================================
# 📥 SOURCE → RESPECTIVE QUEUE
# =====================================================
@client.on(events.NewMessage(chats=list(SOURCE_BOT_MAP.keys())))
async def collect(event):
    queues[event.chat_id].append(event.message)
    print(f"📦 Queue[{event.chat_id}] size:", len(queues[event.chat_id]))

# =====================================================
# 🚀 WORKER PER BOT (STRICT 10-10)
# =====================================================
async def bot_worker(source_id):
    bot = SOURCE_BOT_MAP[source_id]

    while True:
        try:
            q = queues[source_id]

            if len(q) >= BATCH_SIZE:
                batch = q[:BATCH_SIZE]
                del q[:BATCH_SIZE]

                print(f"🤖 {bot['username']} → Sending 10 messages")

                # 🔥 BURST SEND (NO DELAY)
                for msg in batch:
                    await client.forward_messages(bot["username"], msg)

                print(f"⏳ {bot['username']} waiting 30 min")
                await asyncio.sleep(INTERVAL)

            else:
                await asyncio.sleep(1)

        except Exception as e:
            print("🔥 Worker crash:", e)
            restart()

# =====================================================
# 🔗 BOT REPLY → DESTINATION
# =====================================================
@client.on(events.NewMessage(from_users=BOT_IDS))
async def bot_reply(event):
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
# ▶ START
# =====================================================
async def main():
    await client.start()

    # 🔥 Start parallel workers
    for source_id in SOURCE_BOT_MAP:
        asyncio.create_task(bot_worker(source_id))

    print("🚀 PARALLEL BOT SYSTEM RUNNING")
    await client.run_until_disconnected()

client.loop.run_until_complete(main())
