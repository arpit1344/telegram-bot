import asyncio
from telethon.tl.types import MessageMediaWebPage

# expects globals from main.py:
# client, CONFIG, QUEUES, STATS, SYSTEM_PAUSED, AUTO_SCALE
# auto_scale(), save_queue()

async def worker(bot_key):
    while True:
        if SYSTEM_PAUSED:
            await asyncio.sleep(1); continue

        bot = CONFIG["bots"].get(bot_key)
        if not bot:
            await asyncio.sleep(5); continue

        if AUTO_SCALE:
            auto_scale(bot_key)

        batch = bot.get("batch", 10)
        interval = bot.get("interval", 1800)
        sent = 0

        for src, q in QUEUES.get(bot_key, {}).items():
            while q and sent < batch:
                msg = q.pop(0)
                try:
                    if msg.media and not isinstance(msg.media, MessageMediaWebPage):
                        await client.send_file(bot["username"], msg.media, caption=msg.text)
                    else:
                        await client.send_message(bot["username"], msg.text or "")

                    STATS[bot_key]["total"] += 1
                    STATS[bot_key]["sources"].setdefault(src, 0)
                    STATS[bot_key]["sources"][src] += 1
                    sent += 1
                    save_queue(bot_key)

                except Exception:
                    q.insert(0, msg)
                    save_queue(bot_key)
                    await asyncio.sleep(5)
                    break

        if sent:
            await asyncio.sleep(interval)
        await asyncio.sleep(1)
