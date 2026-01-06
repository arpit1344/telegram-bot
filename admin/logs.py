# admin/logs.py
import os, datetime

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "admin_activity.log")
os.makedirs(LOG_DIR, exist_ok=True)

def log_action(admin_id, action, detail=""):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] admin:{admin_id} | {action} | {detail}\n")
