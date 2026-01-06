# admin/isolation.py
def visible_bots(config, admin_id):
    admins = config.get("admins", [])
    super_admin = admins[0] if admins else None

    # Super admin sees all
    if admin_id == super_admin:
        return config.get("bots", {})

    # Others see only owned bots
    return {
        k: v for k, v in config.get("bots", {}).items()
        if v.get("owner") == admin_id
    }
