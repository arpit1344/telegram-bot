import asyncio
from telethon.tl.types import MessageMediaWebPage

# ये variables main file से import होंगे
# client, CONFIG, QUEUES, STATS
# SYSTEM_PAUSED, AUTO_SCALE
# auto_scale(), save_queue()

async def worker(bot_key):
    """
    One worker per bot
    - Reads from QUEUES
    - Sends messages to bot username
    - Respects batch, interval, pause, autoscale
    - Saves queue to disk after every pop
    """

    while True:

        # ⏸ SYSTEM PAUSE
        if SYSTEM_PAUSED:
            await asyncio.sleep(1)
            continue

        bot = CONFIG["bots"].get(bot_key)
        if not bot:
            await asyncio.sleep(5)
            continue

        # 🤖 AUTO SCALE
        if AUTO_SCALE:
            auto_scale(bot_key)

        batch = bot.get("batch", 10)
        interval = bot.get("interval", 1800)

        sent = 0

        # 🔁 Iterate over sources
        for src, queue in QUEUES.get(bot_key, {}).items():

            while queue and sent < batch:
                msg = queue.pop(0)

                try:
                    # 📤 SEND TO BOT
                    if msg.media and not isinstance(msg.media, MessageMediaWebPage):
                        await client.send_file(
                            bot["username"],
                            msg.media,
                            caption=msg.text
                        )
                    else:
                        await client.send_message(
                            bot["username"],
                            msg.text or ""
                        )

                    # 📊 STATS UPDATE
                    STATS[bot_key]["total"] += 1
                    STATS[bot_key]["sources"].setdefault(src, 0)
                    STATS[bot_key]["sources"][src] += 1

                    sent += 1

                    # 💾 SAVE QUEUE STATE
                    save_queue(bot_key)

                except Exception as e:
                    # ❗ Failure → message वापस queue में
                    queue.insert(0, msg)
                    save_queue(bot_key)
                    await asyncio.sleep(5)
                    break

        # ⏳ INTERVAL SLEEP (only if something sent)
        if sent > 0:
            await asyncio.sleep(interval)

        await asyncio.sleep(1)
