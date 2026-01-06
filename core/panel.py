from telethon import Button

def admin_panel():
    return [
        [
            Button.inline("🤖 Select Bot", b"select_bot"),
            Button.inline("➕ Add Bot", b"add_bot"),
            Button.inline("❌ Remove Bot", b"rm_bot")
        ],
        [
            Button.inline("⬆ Priority", b"prio_up"),
            Button.inline("⬇ Priority", b"prio_down")
        ],
        [
            Button.inline("🗃 Set Store Channel", b"set_store")
        ],
        [
            Button.inline("📊 Status", b"status"),
            Button.inline("📈 Traffic", b"traffic")
        ],
        [
            Button.inline("➕ Add Source", b"add_src"),
            Button.inline("❌ Remove Source", b"rm_src")
        ],
        [
            Button.inline("➕ Add Dest", b"add_dest"),
            Button.inline("❌ Remove Dest", b"rm_dest")
        ],
        [
            Button.inline("📦 5", b"batch_5"),
            Button.inline("📦 10", b"batch_10"),
            Button.inline("📦 20", b"batch_20"),
            Button.inline("📦 50", b"batch_50")
        ],
        [
            Button.inline("⏱ 5m", b"int_300"),
            Button.inline("⏱ 10m", b"int_600"),
            Button.inline("⏱ 30m", b"int_1800"),
            Button.inline("⏱ 60m", b"int_3600")
        ],
        [
            Button.inline("🤖 AutoScale ON", b"as_on"),
            Button.inline("🤖 AutoScale OFF", b"as_off")
        ],
        [
            Button.inline("⏸ Pause", b"pause"),
            Button.inline("▶ Start", b"start"),
            Button.inline("♻ Restart", b"restart")
        ]
    ]
