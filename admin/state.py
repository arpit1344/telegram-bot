# admin/state.py
USER_STATE = {}

def get_state(admin_id):
    if admin_id not in USER_STATE:
        USER_STATE[admin_id] = {
            "selected_bot": None,
            "mode": None,
            "confirm": None
        }
    return USER_STATE[admin_id]
