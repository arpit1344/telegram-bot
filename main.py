import os
from telethon import TelegramClient, events
from dotenv import load_dotenv
from core.panel import admin_panel

# ===== ENV =====
load_dotenv("/home/ubuntu/telegram-bot/.env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))  # single admin for phase 1

# ===== CLIENT =====
bot = TelegramClient("admin_panel_bot", API_ID, API_HASH)

# ===== COMMAND =====
@bot.on(events.NewMessage(pattern="/panel"))
async def show_panel(event):
    if event.sender_id != ADMIN_ID:
        return
    await event.reply("🛠 ADMIN PANEL", buttons=admin_panel())

# ===== BUTTON HANDLER (ACK ONLY) =====
@bot.on(events.CallbackQuery)
async def handle_buttons(event):
    if event.sender_id != ADMIN_ID:
        return
    data = event.data.decode()
    await event.answer(f"Clicked: {data}", alert=True)

# ===== START =====
async def main():
    await bot.start(bot_token=ADMIN_BOT_TOKEN)
    print("✅ PHASE 1 ADMIN PANEL RUNNING")
    await bot.run_until_disconnected()

bot.loop.run_until_complete(main())
