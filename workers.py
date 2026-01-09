import asyncio
from redis_queue import pop
from telethon.errors import FloodWaitError

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
        try:
            if is_paused():
                await asyncio.sleep(1)
                continue

            bot = CONFIG["bots"].get(bot_key)
            if not bot:
                await asyncio.sleep(5)
                continue

            if is_autoscale():
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

                        # VERY IMPORTANT delay
                        await asyncio.sleep(1)

                    except FloodWaitError as e:
                        wait_time = int(e.seconds) + 10
                        print(f"⏳ FloodWait {wait_time}s – worker sleeping")
                        await asyncio.sleep(wait_time)
                        break  # exit src loop safely

                    except Exception as e:
                        print("⚠ Worker inner error:", e)
                        await asyncio.sleep(5)
                        break

            if sent:
                await asyncio.sleep(interval)

        except Exception as e:
            # 🔒 LAST SAFETY NET (worker NEVER dies)
            print("🔥 Worker loop error:", e)
            await asyncio.sleep(10)
