#!/usr/bin/env python3
"""
Run this once from Terminal on the Mac that has IABot open in Safari.
It saves the session cookie to ~/.iabot_cookie so the main script
can use it without needing Full Disk Access every run.
"""
import browser_cookie3
from pathlib import Path

cookies = list(browser_cookie3.safari(domain_name="iabot.wmcloud.org"))
if not cookies:
    print("No IABot cookies found — make sure you're logged in at iabot.wmcloud.org in Safari.")
else:
    c = cookies[0]
    cookie_file = Path.home() / ".iabot_cookie"
    cookie_file.write_text(f"{c.name}={c.value}")
    cookie_file.chmod(0o600)
    print(f"Saved: {c.name} = {c.value[:8]}…  →  {cookie_file}")
