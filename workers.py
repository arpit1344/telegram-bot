# workers.py
import asyncio

QUEUES = {}   # { bot_key: { source_id: [messages] } }

def init_queues(config):
    QUEUES.clear()
    for b, bot in config["bots"].items():
        QUEUES[b] = {}
        for s in bot.get("sources", []):
            QUEUES[b][str(s)] = []

def autoscale(bot, qsize):
    if not bot.get("autoscale", True):
        return bot["batch"], bot["interval"]
    if qsize > 100:
        return 50, 300
    if qsize > 20:
        return 20, 600
    return bot["batch"], bot["interval"]

async def worker_loop(client, config, state, stats):
    while True:
        if state["paused"]:
            await asyncio.sleep(1)
            continue

        for b, bot in config["bots"].items():
            total_q = sum(len(v) for v in QUEUES.get(b, {}).values())
            batch, interval = autoscale(bot, total_q)

            sent = 0
            for src, q in QUEUES.get(b, {}).items():
                while q and sent < batch:
                    msg = q.pop(0)
                    if msg.media:
                        await client.send_file(bot["username"], msg.media, caption=msg.text)
                    else:
                        await client.send_message(bot["username"], msg.text or "")

                    stats[b]["total"] += 1
                    stats[b]["sources"].setdefault(src, 0)
                    stats[b]["sources"][src] += 1
                    sent += 1

            if sent:
                await asyncio.sleep(interval)

        await asyncio.sleep(1)
