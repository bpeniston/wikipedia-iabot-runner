#!/usr/bin/env python3
"""
Wikipedia Watchlist → IABot Runner
====================================
Reads your Wikipedia watchlist and submits each article to IABot's
"run bot on single page" tool, one page per minute.

If IABot reports a heavy load, the script sleeps for one hour then retries
the same page.  Progress is saved to ~/.iabot_progress.json so the script
can be safely interrupted and resumed.

Requirements
------------
    pip install requests beautifulsoup4

Authentication
--------------
1. Wikipedia (for watchlist):
       export WP_USERNAME="YourWikipediaUsername"
       export WP_PASSWORD="YourWikipediaPassword"

   Tip: use a bot password from
   https://en.wikipedia.org/wiki/Special:BotPasswords
   so your main password is never stored anywhere.

2. IABot (the submission site uses Wikimedia OAuth):
   a. Log in at https://iabot.wmcloud.org in your normal browser.
   b. Open DevTools (Cmd-Option-I) → Application tab → Cookies →
      https://iabot.wmcloud.org
   c. Find the cookie named PHPSESSID (or iabot_session / similar).
   d. Copy its value and export it:
       export IABOT_SESSION="paste-value-here"
   The cookie lasts for your browser session; re-copy if the script
   starts getting redirected to the login page.

Usage
-----
    python3 iabot_runner.py            # processes full watchlist
    python3 iabot_runner.py --reset    # clears saved progress and starts over
"""

import os
import sys
import time
import json
import logging
import argparse
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Load .env from the same directory as this script
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ── Constants ────────────────────────────────────────────────────────────────

IABOT_BASE    = "https://iabot.wmcloud.org/index.php"
WP_API        = "https://en.wikipedia.org/w/api.php"
PROGRESS_FILE = Path.home() / ".iabot_progress.json"
LOG_FILE      = Path.home() / ".iabot_runner.log"
STATUS_FILE   = Path.home() / ".iabot_status.json"
INTERVAL      = 60    # seconds between submissions
HEAVY_WAIT    = 3600  # seconds to wait when IABot reports heavy load

DREAMHOST_USER = "bradwu"
DREAMHOST_HOST = "pdx1-shared-a1-08.dreamhost.com"
DREAMHOST_PATH = "~/navybook.com/WP/status.json"
RECENT_MAX     = 50   # how many recent submissions to keep in status

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE),
    ],
)
log = logging.getLogger(__name__)

# ── Progress helpers ──────────────────────────────────────────────────────────

def load_progress():
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"done": [], "queue": []}

def save_progress(state):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ── Status helpers ───────────────────────────────────────────────────────────

def write_status(state, recent):
    total    = len(state["done"]) + len(state["queue"])
    skipped  = sum(1 for r in recent if r["result"] != "ok")
    data = {
        "total":           total,
        "done":            len(state["done"]),
        "skipped":         skipped,
        "queue_remaining": len(state["queue"]),
        "last_update":     datetime.now().isoformat(timespec="seconds"),
        "recent":          recent[-RECENT_MAX:],
    }
    with open(STATUS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def upload_status():
    import subprocess
    try:
        subprocess.run(
            ["scp", "-q", str(STATUS_FILE),
             f"{DREAMHOST_USER}@{DREAMHOST_HOST}:{DREAMHOST_PATH}"],
            timeout=15, check=True
        )
    except Exception as exc:
        log.warning("Could not upload status.json: %s", exc)

# ── Wikipedia API ─────────────────────────────────────────────────────────────

def wp_login(session, username, password):
    """Log in to Wikipedia and return the session (cookies set in place)."""
    # 1. Fetch login token
    r = session.get(WP_API, params={
        "action": "query",
        "meta": "tokens",
        "type": "login",
        "format": "json",
    })
    r.raise_for_status()
    token = r.json()["query"]["tokens"]["logintoken"]

    # 2. Log in
    r = session.post(WP_API, data={
        "action": "login",
        "lgname": username,
        "lgpassword": password,
        "lgtoken": token,
        "format": "json",
    })
    r.raise_for_status()
    result = r.json().get("login", {}).get("result", "")
    if result != "Success":
        raise RuntimeError(
            f"Wikipedia login failed: {result}\n"
            "Check WP_USERNAME / WP_PASSWORD (or use a bot password from\n"
            "https://en.wikipedia.org/wiki/Special:BotPasswords)."
        )
    log.info("Logged in to Wikipedia as %s", username)

def get_watchlist(session):
    """Fetch all article titles (namespace 0) from the authenticated watchlist."""
    titles, params = [], {
        "action": "query",
        "list": "watchlistraw",
        "wrlimit": "max",
        "wrnamespace": "0",   # main article namespace only
        "format": "json",
    }
    while True:
        r = session.get(WP_API, params=params)
        r.raise_for_status()
        data = r.json()
        # API returns watchlistraw at top level (not nested under "query")
        batch = data.get("watchlistraw") or data.get("query", {}).get("watchlistraw", [])
        titles.extend(p["title"] for p in batch)
        if "continue" not in data:
            break
        params.update(data["continue"])
    log.info("Fetched %d articles from watchlist", len(titles))
    return titles

# ── IABot ─────────────────────────────────────────────────────────────────────

def is_heavy_load(html):
    return "heavy load" in html.lower()

def is_logged_out(html):
    """Detect if IABot has redirected us to a login / OAuth page."""
    lower = html.lower()
    return (
        "log in" in lower
        or "oauth" in lower and "authorize" in lower
        or "you must be logged" in lower
    )

def _short_exc(exc):
    """Return a concise, human-readable version of a requests exception."""
    msg = str(exc)
    if "timed out" in msg or "Read timeout" in msg:
        return "timed out"
    if "Connection" in msg:
        return "connection error"
    if "401" in msg:
        return "401 Unauthorized"
    if "403" in msg:
        return "403 Forbidden"
    # Fall back to the first sentence / 60 chars
    return msg.split("\n")[0][:60]

def submit_page(session, title):
    """
    Submit one Wikipedia article to IABot.

    Returns one of:
        "ok"          – submitted successfully
        "heavy_load"  – IABot reported heavy load; caller should wait
        "logged_out"  – session expired; caller should warn and abort
        "error"       – some other problem; caller should skip
    """
    wp_url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")

    # ── Step 1: Load the form ──────────────────────────────────────────────
    try:
        r = session.get(
            IABOT_BASE,
            params={"page": "runbotsingle"},
            timeout=30,
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        log.error("Network error fetching IABot form: %s", exc)
        return "error", _short_exc(exc)

    if is_heavy_load(r.text):
        return "heavy_load", None
    if is_logged_out(r.text):
        return "logged_out", None

    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form")
    if not form:
        log.warning("No <form> found on IABot page – HTML snippet:\n%s",
                    r.text[:400])
        return "error", "no form on IABot page"

    # ── Step 2: Build POST payload ─────────────────────────────────────────
    payload = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        itype = inp.get("type", "text").lower()
        if itype == "checkbox":
            # Only include checked checkboxes; use "on" if no value set
            if inp.has_attr("checked"):
                payload[name] = inp.get("value", "on") or "on"
        elif itype != "submit":
            payload[name] = inp.get("value", "")

    # Always check the "add archives" box — this is what actually makes IABot
    # apply the archives to the article, not just analyze it.
    payload["archiveall"] = "on"

    # Find the URL / article field (try known names, then any text input)
    url_field = (
        form.find("input", {"name": "pagesearch"})
        or form.find("input", {"name": "url"})
        or form.find("input", {"name": "page_url"})
        or form.find("input", {"name": "article"})
        or form.find("input", {"name": "wikipediaurl"})
        or form.find("input", {"type": "text"})
    )
    if url_field and url_field.get("name"):
        payload[url_field["name"]] = wp_url
        log.info("  Form field: %r = %s", url_field["name"], wp_url)
    else:
        payload["url"] = wp_url
        log.warning("  Could not identify URL field — dumping all inputs:")
        for k, v in payload.items():
            log.warning("    %r = %r", k, v)

    # Resolve form action URL
    action = form.get("action") or IABOT_BASE
    if not action.startswith("http"):
        action = "https://iabot.wmcloud.org/" + action.lstrip("/")

    # ── Step 3: Submit ─────────────────────────────────────────────────────
    try:
        r2 = session.post(action, data=payload, timeout=120)
        r2.raise_for_status()
    except requests.RequestException as exc:
        log.error("Network error submitting to IABot: %s", exc)
        return "error", _short_exc(exc)

    if is_heavy_load(r2.text):
        return "heavy_load", None
    if is_logged_out(r2.text):
        return "logged_out", None

    # Extract result message from IABot's response page
    soup2 = BeautifulSoup(r2.text, "html.parser")
    iabot_msg = None
    for selector in [
        {"id": "mw-content-text"},
        {"class": "mw-parser-output"},
        {"class": "successbox"},
        {"class": "errorbox"},
        {"class": "warningbox"},
    ]:
        el = soup2.find(attrs=selector)
        if el:
            p = el.find("p")
            iabot_msg = (p or el).get_text(" ", strip=True)[:200]
            if iabot_msg:
                break

    if not iabot_msg:
        # IABot embeds its processing log in an HTML comment at the top.
        # Extract the summary line: "Rescued: X; Tagged dead: Y; Archived: Z"
        import re
        m = re.search(r'Rescued:.*?(?=\n|$)', r2.text)
        if m:
            # Strip unhelpful memory stats from the result line
            iabot_msg = re.sub(r';?\s*Memory Used:.*', '', m.group(0)).strip()

    return "ok", iabot_msg

# ── Entry-point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true",
                        help="Clear saved progress and rebuild queue from watchlist")
    args = parser.parse_args()

    # ── Credentials ────────────────────────────────────────────────────────
    wp_user = os.getenv("WP_USERNAME", "").strip()
    wp_pass = os.getenv("WP_PASSWORD", "").strip()
    iabot_session = os.getenv("IABOT_SESSION", "").strip()

    missing = []
    if not wp_user:   missing.append("WP_USERNAME")
    if not wp_pass:   missing.append("WP_PASSWORD")
    if missing:
        sys.exit(
            "Missing environment variable(s): " + ", ".join(missing) + "\n\n"
            "Set them before running:\n"
            "  export WP_USERNAME='YourWikipediaUsername'\n"
            "  export WP_PASSWORD='YourPassword'\n"
            "  export IABOT_SESSION='your-PHPSESSID-cookie-value'\n\n"
            "See the docstring at the top of this file for details."
        )

    # ── Build session ───────────────────────────────────────────────────────
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "IABot-watchlist-runner/1.0 "
            "(https://en.wikipedia.org/wiki/User:PRRfan)"
        )
    })

    # Try to load IABot cookies directly from Safari (most reliable)
    iabot_cookies_loaded = False
    try:
        import browser_cookie3
        safari_cookies = browser_cookie3.safari(domain_name="iabot.wmcloud.org")
        cookie_list = list(safari_cookies)
        if cookie_list:
            for c in cookie_list:
                session.cookies.set(c.name, c.value,
                                    domain="iabot.wmcloud.org", path="/")
            log.info("Loaded %d IABot cookie(s) from Safari", len(cookie_list))
            iabot_cookies_loaded = True
        else:
            log.warning("No IABot cookies found in Safari — are you logged in at iabot.wmcloud.org?")
    except Exception as exc:
        log.warning("Could not read Safari cookies (%s); falling back to IABOT_SESSION env var", exc)

    if not iabot_cookies_loaded:
        # Try the saved cookie file (~/.iabot_cookie written by save_iabot_cookie.py)
        cookie_file = Path.home() / ".iabot_cookie"
        if cookie_file.exists():
            raw = cookie_file.read_text().strip()
            if "=" in raw:
                name, _, value = raw.partition("=")
                session.cookies.set(name.strip(), value.strip(),
                                    domain="iabot.wmcloud.org", path="/")
                log.info("Loaded IABot cookie from ~/.iabot_cookie")
                iabot_cookies_loaded = True

    if not iabot_cookies_loaded:
        if iabot_session:
            session.cookies.set("IABotManagementConsole", iabot_session,
                                domain="iabot.wmcloud.org", path="/")
            log.info("Using IABOT_SESSION cookie from .env")
        else:
            sys.exit(
                "No IABot session found.\n"
                "Run save_iabot_cookie.py from Terminal on the Air, then restart."
            )

    # Log in to Wikipedia to access watchlist
    wp_login(session, wp_user, wp_pass)

    # ── Load / build queue ──────────────────────────────────────────────────
    if args.reset:
        PROGRESS_FILE.unlink(missing_ok=True)
        log.info("Progress reset.")

    state = load_progress()

    if not state["queue"]:
        log.info("Fetching watchlist to build queue…")
        all_titles = get_watchlist(session)
        done_set = set(state["done"])
        state["queue"] = [t for t in all_titles if t not in done_set]
        save_progress(state)

    total_remaining = len(state["queue"])
    log.info("Queue: %d articles to process  (log: %s)", total_remaining, LOG_FILE)

    if total_remaining == 0:
        log.info("Nothing left to do.  Run with --reset to start over.")
        return

    # ── Main loop ───────────────────────────────────────────────────────────
    recent = []

    while state["queue"]:
        title = state["queue"][0]
        done  = len(state["done"])
        total = done + len(state["queue"])
        log.info("[%d/%d] Submitting: %s", done + 1, total, title)

        result, iabot_msg = submit_page(session, title)

        if result == "heavy_load":
            resume_at = datetime.now() + timedelta(seconds=HEAVY_WAIT)
            log.warning(
                "IABot reports heavy load.  Sleeping 1 hour; will resume at %s.",
                resume_at.strftime("%H:%M:%S"),
            )
            time.sleep(HEAVY_WAIT)
            continue

        if result == "logged_out":
            log.error(
                "IABot session has expired or is invalid.\n"
                "Log back in at https://iabot.wmcloud.org then restart the script."
            )
            webbrowser.open("https://iabot.wmcloud.org")
            sys.exit(1)

        if result == "error":
            # Retry once after a short wait before giving up
            log.warning("  Retrying in 30s…")
            time.sleep(30)
            result, iabot_msg = submit_page(session, title)

        entry = {
            "title":     title,
            "result":    result,
            "iabot_msg": iabot_msg,
            "time":      datetime.now().isoformat(timespec="seconds"),
        }
        recent.append(entry)

        if result == "ok":
            state["done"].append(title)
            state["queue"].pop(0)
            save_progress(state)
            log.info("  ✓ submitted  —  %s", iabot_msg or "")
        elif result == "error":
            # Move to end of queue so it gets another chance later
            state["queue"].pop(0)
            state["queue"].append(title)
            save_progress(state)
            log.warning("  ✗ timed out — moved %s to end of queue", title)
        else:
            log.warning("  ✗ skipping %s", title)
            state["queue"].pop(0)
            save_progress(state)

        write_status(state, recent)
        if len(recent) % 10 == 0:
            upload_status()

        if state["queue"]:
            log.info("  Waiting %d seconds…", INTERVAL)
            time.sleep(INTERVAL)

    log.info("All done!  Processed %d articles total.", len(state["done"]))


if __name__ == "__main__":
    main()
