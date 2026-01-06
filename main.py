import os, sys, json
from telethon import TelegramClient, events, Button
from dotenv import load_dotenv

from core.panel import admin_panel
from state import STATE                         # Phase 2
from admin.state import get_state               # NEW
from admin.isolation import visible_bots        # NEW
from admin.logs import log_action               # NEW

# ===== ENV =====
load_dotenv("/home/ubuntu/telegram-bot/.env")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")

# ===== CONFIG =====
CONFIG_FILE = "config.json"
def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

CONFIG = load_config()
ADMINS = set(CONFIG.get("admins", []))

# ===== CLIENT =====
bot = TelegramClient("admin_panel_bot", API_ID, API_HASH)

# ===== /panel =====
@bot.on(events.NewMessage(pattern="/panel"))
async def show_panel(event):
    if event.sender_id not in ADMINS:
        return
    get_state(event.sender_id)["mode"] = None
    await event.reply(panel_status_text(), buttons=admin_panel())

# ===== BUTTON HANDLER =====
@bot.on(events.CallbackQuery)
async def handle_buttons(event):
    uid = event.sender_id
    if uid not in ADMINS:
        return

    state = get_state(uid)
    data = event.data.decode()

    # ---- BACK ----
    if data == "back":
        state["mode"] = None
        await event.edit(panel_status_text(), buttons=admin_panel())
        return

    # ---- SELECT BOT (ISOLATED LIST) ----
    if data == "select_bot":
        bots = visible_bots(CONFIG, uid)
        rows = [[Button.inline(k, f"sel_{k}".encode())] for k in bots]
        rows.append([Button.inline("⬅ Back", b"back")])
        await event.edit("🤖 Select Bot", buttons=rows)
        return

    if data.startswith("sel_"):
        state["selected_bot"] = data.replace("sel_", "")
        await event.edit(panel_status_text(), buttons=admin_panel())
        return

    # ---- PAUSE / START ----
    if data == "pause":
        STATE["paused"] = True
        log_action(uid, "PAUSE_SYSTEM")
        await event.edit(panel_status_text(), buttons=admin_panel())
        return

    if data == "start":
        STATE["paused"] = False
        log_action(uid, "START_SYSTEM")
        await event.edit(panel_status_text(), buttons=admin_panel())
        return

    # ---- AUTOSCALE ----
    if data == "as_on":
        STATE["autoscale"] = True
        log_action(uid, "AUTOSCALE_ON")
        await event.answer("AutoScale ON", alert=True)
        return

    if data == "as_off":
        STATE["autoscale"] = False
        log_action(uid, "AUTOSCALE_OFF")
        await event.answer("AutoScale OFF", alert=True)
        return

    # ---- BATCH ----
    if data.startswith("batch_"):
        STATE["batch"] = int(data.split("_")[1])
        log_action(uid, "SET_BATCH", STATE["batch"])
        await event.answer(f"Batch set to {STATE['batch']}", alert=True)
        return

    # ---- INTERVAL ----
    if data.startswith("int_"):
        STATE["interval"] = int(data.split("_")[1])
        log_action(uid, "SET_INTERVAL", STATE["interval"])
        await event.answer(f"Interval set to {STATE['interval']} sec", alert=True)
        return

    # ---- RESTART CONFIRM ----
    if data == "restart":
        state["confirm"] = "restart"
        await event.edit(
            "♻ Restart system?\n\nAre you sure?",
            buttons=[
                [Button.inline("✅ Yes", b"confirm_restart"),
                 Button.inline("❌ No", b"back")]
            ]
        )
        return

    if data == "confirm_restart":
        log_action(uid, "RESTART_SYSTEM")
        os.execv(sys.executable, ["python"] + sys.argv)

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
    print("✅ PHASE 3 RUNNING (Multi-Admin + Isolation + Logs)")
    await bot.run_until_disconnected()

bot.loop.run_until_complete(main())
