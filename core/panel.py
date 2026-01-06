def admin_panel():
    return [
        ...
        [
            Button.inline("⏸ Pause", b"pause"),
            Button.inline("▶ Start", b"start"),
            Button.inline("♻ Restart", b"restart")
        ]
    ]
