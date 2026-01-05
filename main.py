import os, asyncio, sys, time
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button

# ================= ENV =================
load_dotenv("/home/ubuntu/telegram-bot/.env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# ================= CLIENTS (DEFINE FIRST!) =================
client = TelegramClient("main_session", API_ID, API_HASH)
admin_bot = TelegramClient("admin_session", API_ID, API_HASH)

# ================= STATE =================
SYSTEM_PAUSED = False

# ================= PANEL =================
def panel():
    return [
        [Button.inline("📊 Status", b"status")],
        [Button.inline("⏸ Pause", b"pause"), Button.inline("▶ Start", b"start")],
    ]

# ================= ADMIN MESSAGE HANDLER =================
@admin_bot.on(events.NewMessage)
async def admin_handler(event):
    global SYSTEM_PAUSED

    if event.sender_id != ADMIN_ID:
        return
    if not event.text:
        return

    text = event.text.strip().lower()
    print("ADMIN CMD:", text)   # log me dikhega

    if text == "/start":
        await event.reply("✅ Admin bot running")
        return

    if text == "/status":
        await event.reply(f"📊 STATUS\nPaused: {SYSTEM_PAUSED}")
        return

    if text in ("/panel", "/pannel"):
        await event.reply("🛠 ADMIN PANEL", buttons=panel())
        return

# ================= BUTTON HANDLER =================
@admin_bot.on(events.CallbackQuery)
async def admin_buttons(event):
    global SYSTEM_PAUSED

    if event.sender_id != ADMIN_ID:
        return

    data = event.data.decode()

    if data == "status":
        await event.edit(f"📊 STATUS\nPaused: {SYSTEM_PAUSED}", buttons=panel())

    elif data == "pause":
        SYSTEM_PAUSED = True
        await event.edit("⏸ Paused", buttons=panel())

    elif data == "start":
        SYSTEM_PAUSED = False
        await event.edit("▶ Started", buttons=panel())

# ================= START =================
async def main():
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    print("✅ ADMIN BOT STARTED")

    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
