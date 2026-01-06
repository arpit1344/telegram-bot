import os, sys, json, asyncio
from telethon import TelegramClient, events, Button
from dotenv import load_dotenv

from core.panel import admin_panel
from state import STATE
from admin.state import get_state
from admin.isolation import visible_bots
from admin.logs import log_action
from workers import init_queues, QUEUES, worker_loop
from store_flow import bot_to_store, store_to_dest

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
client = TelegramClient("main_session", API_ID, API_HASH)
admin_bot = TelegramClient("admin_panel_bot", API_ID, API_HASH)

# ===== STATS =====
STATS = { b: {"total": 0, "sources": {}, "destinations": {}} for b in CONFIG["bots"] }

# ===== INIT =====
init_queues(CONFIG)

# ===== SOURCE COLLECTOR =====
@client.on(events.NewMessage)
async def collect_source(event):
    for b, bot in CONFIG["bots"].items():
        if event.chat_id in bot.get("sources", []):
            QUEUES[b][str(event.chat_id)].append(event.message)

# ===== BOT → STORE =====
@client.on(events.NewMessage)
async def on_bot_message(event):
    await bot_to_store(client, CONFIG, event)

# ===== STORE → DEST =====
@client.on(events.NewMessage)
async def on_store_message(event):
    await store_to_dest(client, CONFIG, STATS, event)

# ===== /panel =====
@admin_bot.on(events.NewMessage(pattern="/panel"))
async def show_panel(event):
    if event.sender_id not in ADMINS:
        return
    get_state(event.sender_id)["mode"] = None
    await event.reply(panel_status_text(), buttons=admin_panel())

# ===== BUTTON HANDLER =====
@admin_bot.on(events.CallbackQuery)
async def handle_buttons(event):
    uid = event.sender_id
    if uid not in ADMINS:
        return

    state = get_state(uid)
    data = event.data.decode()

    if data == "back":
        state["mode"] = None
        await event.edit(panel_status_text(), buttons=admin_panel())
        return

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

    # Pause / Start
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

    # Batch / Interval / Autoscale
    if data.startswith("batch_"):
        STATE["batch"] = int(data.split("_")[1])
        log_action(uid, "SET_BATCH", STATE["batch"])
        await event.answer(f"Batch {STATE['batch']}", alert=True)
        return

    if data.startswith("int_"):
        STATE["interval"] = int(data.split("_")[1])
        log_action(uid, "SET_INTERVAL", STATE["interval"])
        await event.answer(f"Interval {STATE['interval']}s", alert=True)
        return

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

    if data == "restart":
        state["confirm"] = "restart"
        await event.edit(
            "♻ Restart system?\n\nAre you sure?",
            buttons=[[Button.inline("✅ Yes", b"confirm_restart"),
                      Button.inline("❌ No", b"back")]]
        )
        return

    if data == "confirm_restart":
        log_action(uid, "RESTART_SYSTEM")
        os.execv(sys.executable, ["python"] + sys.argv)

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
    await client.start()
    await admin_bot.start(bot_token=ADMIN_BOT_TOKEN)

    asyncio.create_task(worker_loop(client, CONFIG, STATE, STATS))
    print("✅ PHASE 4 RUNNING (REAL PIPELINE ACTIVE)")

    await asyncio.gather(
        client.run_until_disconnected(),
        admin_bot.run_until_disconnected()
    )

client.loop.run_until_complete(main())
