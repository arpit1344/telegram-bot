import asyncio
from redis_queue import pop
from telethon.tl.types import MessageMediaWebPage

# uses globals from main.py:
# client, CONFIG, STATS, SYSTEM_PAUSED, AUTO_SCALE
# auto_scale()

async def worker(bot_key):
    while True:

        if SYSTEM_PAUSED:
            await asyncio.sleep(1)
            continue

        bot = CONFIG["bots"].get(bot_key)
        if not bot:
            await asyncio.sleep(5)
            continue

        if AUTO_SCALE:
            auto_scale(bot_key)

        batch = bot.get("batch", 10)
        interval = bot.get("interval", 1800)

        sent = 0

        for src in bot.get("sources", []):
            while sent < batch:
                msg = pop(bot_key, src)
                if not msg:
                    break

                try:
                    await client.send_message(
                        bot["username"],
                        msg.get("text") or ""
                    )

                    STATS[bot_key]["total"] += 1
                    STATS[bot_key]["sources"].setdefault(str(src), 0)
                    STATS[bot_key]["sources"][str(src)] += 1
                    sent += 1

                except Exception:
                    await asyncio.sleep(5)
                    break

        if sent:
            await asyncio.sleep(interval)

        await asyncio.sleep(1)
