# store_flow.py
async def bot_to_store(client, config, event):
    for b, bot in config["bots"].items():
        if event.sender_id == bot["id"]:
            store = bot.get("store_channel")
            if not store:
                return
            if event.message.media:
                await client.send_file(store, event.message.media, caption=event.text)
            else:
                await client.send_message(store, event.text)

async def store_to_dest(client, config, stats, event):
    for b, bot in config["bots"].items():
        if event.chat_id == bot.get("store_channel"):
            for d in bot.get("destinations", []):
                if event.message.media:
                    await client.send_file(d, event.message.media, caption=event.text)
                else:
                    await client.send_message(d, event.text)
                stats[b]["destinations"].setdefault(str(d), 0)
                stats[b]["destinations"][str(d)] += 1
