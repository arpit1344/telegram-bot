import asyncio
from redis_queue import pop

async def worker(
    bot_key,
    *,
    client,
    CONFIG,
    STATS,
    auto_scale,
    is_paused,
    is_autoscale
):
    while True:
        if is_paused():
            await asyncio.sleep(1)
            continue

        bot = CONFIG["bots"].get(bot_key)
        if not bot:
            await asyncio.sleep(5)
            continue

        if is_autoscale():
            auto_scale(bot_key)

        sent = 0
        batch = bot.get("batch", 10)
        interval = bot.get("interval", 1800)

        for src in bot.get("sources", []):
            while sent < batch:
                msg = pop(bot_key, src)
                if not msg:
                    break

                await client.send_message(bot["username"], msg.get("text") or "")
                STATS[bot_key]["total"] += 1
                STATS[bot_key]["sources"].setdefault(str(src), 0)
                STATS[bot_key]["sources"][str(src)] += 1
                sent += 1

        if sent:
            await asyncio.sleep(interval)

        await asyncio.sleep(1)
