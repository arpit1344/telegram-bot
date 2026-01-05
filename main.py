# =====================================================
# 🔧 CONFIG
# =====================================================
api_id = 36963896
api_hash = "efc64243eb8abbec89f1b9df83a5a374"

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
INTERVAL = 1800       # 30 min delay only when >10
RETRY_DELAY = 90

BUSY_KEYWORDS = ["system busy", "try again", "busy"]

# =====================================================
# ❌ CONFIG END
# =====================================================

from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaWebPage
import asyncio, os, sys, time

client = TelegramClient("session", api_id, api_hash)

# 🔹 Separate queues per source
queues = {sid: [] for sid in SOURCE_BOT_MAP}
retry_queues = {sid: [] for sid in SOURCE_BOT_MAP}

BOT_IDS = [v["id"] for v in SOURCE_BOT_MAP.values()]

# =====================================================
# 🔁 AUTO RESTART
# =====================================================
def restart():
    print("♻ Restarting...")
    time.sleep(5)
    os.execv(sys.executable, ['python'] + sys.argv)

# =====================================================
# 📥 SOURCE → QUEUE
# =====================================================
@client.on(events.NewMessage(chats=list(SOURCE_BOT_MAP.keys())))
async def collect(event):
    queues[event.chat_id].append(event.message)
    print(f"📦 Queue[{event.chat_id}] =", len(queues[event.chat_id]))

# =====================================================
# 🚀 BOT WORKER (FINAL LOGIC)
# =====================================================
async def bot_worker(source_id):
    bot = SOURCE_BOT_MAP[source_id]
    q = queues[source_id]

    while True:
        try:
            qlen = len(q)

            # ✅ CASE 1: 1–10 → send all immediately
            if 0 < qlen <= BATCH_SIZE:
                batch = q[:]
                q.clear()

                print(f"🤖 {bot['username']} → instant send {len(batch)}")

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

            # ✅ CASE 2: >10 → strict 10-10 batch
            if qlen > BATCH_SIZE:
                batch = q[:BATCH_SIZE]
                del q[:BATCH_SIZE]

                print(f"🤖 {bot['username']} → batch send 10")

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

                print(f"⏳ {bot['username']} waiting 30 min")
                await asyncio.sleep(INTERVAL)

            await asyncio.sleep(1)

        except Exception as e:
            print("🔥 Worker error:", e)
            restart()

# =====================================================
# 🔁 RETRY WORKER (BUSY CASE)
# =====================================================
async def retry_worker(source_id):
    bot = SOURCE_BOT_MAP[source_id]
    rq = retry_queues[source_id]

    while True:
        try:
            if rq:
                msg = rq.pop(0)
                print(f"🔁 Retrying for {bot['username']}")

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

    # BUSY DETECT
    if any(k in text_lower for k in BUSY_KEYWORDS):
        print("⏳ Bot busy reply detected (ignored)")
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
# ▶ START SYSTEM
# =====================================================
async def main():
    await client.start()

    # 🔥 Parallel workers for both bots
    for sid in SOURCE_BOT_MAP:
        asyncio.create_task(bot_worker(sid))
        asyncio.create_task(retry_worker(sid))

    print("🚀 FULL FINAL SYSTEM RUNNING")
    await client.run_until_disconnected()

client.loop.run_until_complete(main())
