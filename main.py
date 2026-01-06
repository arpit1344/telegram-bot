import os, sys
from telethon import TelegramClient, events, Button
from dotenv import load_dotenv

from core.panel import admin_panel
from state import STATE

# ===== ENV =====
load_dotenv("/home/ubuntu/telegram-bot/.env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# ===== CLIENT =====
bot = TelegramClient("admin_panel_bot", API_ID, API_HASH)

# ===== PANEL COMMAND =====
@bot.on(events.NewMessage(pattern="/panel"))
async def show_panel(event):
    if event.sender_id != ADMIN_ID:
        return

    STATE["mode"] = None
    await event.reply(
        panel_status_text(),
        buttons=admin_panel()
    )

# ===== BUTTON HANDLER =====
@bot.on(events.CallbackQuery)
async def handle_buttons(event):
    if event.sender_id != ADMIN_ID:
        return

    data = event.data.decode()

    # ---- BACK ----
    if data == "back":
        STATE["mode"] = None
        await event.edit(panel_status_text(), buttons=admin_panel())
        return

    # ---- PAUSE / START ----
    if data == "pause":
        STATE["paused"] = True
        await event.edit(panel_status_text(), buttons=admin_panel())
        return

    if data == "start":
        STATE["paused"] = False
        await event.edit(panel_status_text(), buttons=admin_panel())
        return

    # ---- AUTOSCALE ----
    if data == "as_on":
        STATE["autoscale"] = True
        await event.answer("🤖 AutoScale ON", alert=True)
        return

    if data == "as_off":
        STATE["autoscale"] = False
        await event.answer("🤖 AutoScale OFF", alert=True)
        return

    # ---- BATCH ----
    if data.startswith("batch_"):
        STATE["batch"] = int(data.split("_")[1])
        await event.answer(f"📦 Batch set to {STATE['batch']}", alert=True)
        return

    # ---- INTERVAL ----
    if data.startswith("int_"):
        STATE["interval"] = int(data.split("_")[1])
        await event.answer(f"⏱ Interval set to {STATE['interval']} sec", alert=True)
        return

    # ---- RESTART (CONFIRM) ----
    if data == "restart":
        STATE["mode"] = "confirm_restart"
        await event.edit(
            "♻ Restart system?\n\nAre you sure?",
            buttons=[
                [
                    Button.inline("✅ Yes", b"confirm_restart"),
                    Button.inline("❌ No", b"back")
                ]
            ]
        )
        return

    if data == "confirm_restart":
        await event.answer("♻ Restarting…", alert=True)
        os.execv(sys.executable, ["python"] + sys.argv)

    # ---- DEFAULT ----
    await event.answer(f"Clicked: {data}", alert=True)

# ===== STATUS TEXT =====
def panel_status_text():
    return (
        "🛠 ADMIN PANEL\n\n"
        f"⏸ Paused: {'YES' if STATE['paused'] else 'NO'}\n"
        f"📦 Batch: {STATE['batch']}\n"
        f"⏱ Interval: {STATE['interval']} sec\n"
        f"🤖 AutoScale: {'ON' if STATE['autoscale'] else 'OFF'}"
    )

# ===== START =====
async def main():
    await bot.start(bot_token=ADMIN_BOT_TOKEN)
    print("✅ PHASE 2 RUNNING (LOGIC + UX ACTIVE)")
    await bot.run_until_disconnected()

bot.loop.run_until_complete(main())
