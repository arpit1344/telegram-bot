import asyncio
from telethon.tl.types import MessageMediaWebPage
from redis_queue import pop

# 🔥 IMPORT GLOBALS FROM main
import main


async def worker(bot_key):
    while True:

        # ⏸ PAUSE CHECK
        if main.SYSTEM_PAUSED:
            await asyncio.sleep(1)
            continue

        bot = main.CONFIG["bots"].get(bot_key)
        if not bot:
            await asyncio.sleep(5)
            continue

        # ⚙ AUTOSCALE
        if main.AUTO_SCALE:
            main.auto_scale(bot_key)

        batch = bot.get("batch", 10)
        interval = bot.get("interval", 1800)
        sent = 0

        for src in bot.get("sources", []):
            while sent < batch:
                msg = pop(bot_key, src)
                if not msg:
                    break

                try:
                    # 📤 SEND TO BOT
                    await main.client.send_message(
                        bot["username"],
                        msg.get("text") or ""
                    )

                    # 📊 STATS
                    main.STATS[bot_key]["total"] += 1
                    main.STATS[bot_key]["sources"].setdefault(str(src), 0)
                    main.STATS[bot_key]["sources"][str(src)] += 1

                    sent += 1

                except Exception as e:
                    await asyncio.sleep(5)
                    break

        if sent:
            await asyncio.sleep(interval)

        await asyncio.sleep(1)
