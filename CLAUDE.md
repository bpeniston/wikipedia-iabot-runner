# CLAUDE.md — Wikipedia IABot Runner

## What this project does

Automates submitting Wikipedia watchlist articles to IABot's "run bot on single page" web interface, one per minute. IABot archives dead/unarchived external links and updates citations. Edits appear under the authenticated Wikipedia user's account (PRRfan), tagged `IABotManagementConsole`.

## File overview

| File | Purpose |
|------|---------|
| `iabot_runner.py` | Main script — fetches watchlist, submits to IABot, uploads status |
| `save_iabot_cookie.py` | One-time helper to extract Safari's IABot session cookie and save to `~/.iabot_cookie` |
| `wp_status.html` | Static status page (deploy as `index.html` on web server) |
| `.env` | Credentials (gitignored) — see `.env.example` |
| `.env.example` | Template for `.env` |

## Architecture

1. **Watchlist** — fetched via Wikipedia API (`list=watchlistraw`) using bot password credentials
2. **IABot submission** — HTTP POST to `https://iabot.wmcloud.org/index.php?page=runbotsingle&action=analyzepage`
3. **Status upload** — `scp` to DreamHost every 10 submissions (~10 min) to avoid rate limiting
4. **Progress** — saved to `~/.iabot_progress.json` (queue + done list)

## Critical implementation details

### The `archiveall` checkbox
The IABot form has a checkbox `name="archiveall"` that must be explicitly set to `"on"` in the POST payload. Without it IABot only analyzes the page and reports results but **does not save any changes to Wikipedia**. This was the main bug discovered during development — IABot would return "Success" and a result line but make no edits.

### Form field name
The URL input field on IABot's form is `name="pagesearch"` — not `url`, `article`, or other common names.

### Cookie authentication
IABot uses Wikimedia OAuth. The session cookie is named `IABotManagementConsole`. The script reads it from Safari via `browser_cookie3` (requires Full Disk Access for Terminal on macOS), saves it to `~/.iabot_cookie`, and loads from that file on subsequent runs. This allows the script to run via SSH without needing FDA each time.

**Session expiry**: The cookie typically lasts a few days. When it expires the script logs `IABot session has expired` and exits. The status page detects this (last_update > 20 min old) and displays restart instructions automatically.

### IABot response format
The response body starts with an HTML comment `<!--` containing the processing log. The result line is extracted with a regex and memory stats are stripped:
```
Rescued: 2; Tagged dead: 0; Archived: 2
```
- **Rescued** = dead/404 links that already had an archive copy — IABot added that URL to the citation
- **Archived** = live links not yet in the Wayback Machine — IABot submitted them for future preservation
- **Tagged dead** = dead links with no archive available — marked as dead in the citation

### Wikipedia API quirk
`list=watchlistraw` returns results at the **top level** of the response (not nested under `query` as most other list APIs do). The script handles both locations.

### Two edits per article
When IABot finds work to do it makes two Wikipedia edits: a first pass that adds archive URLs, and a second refinement pass that cleans up the markup. This is normal IABot behavior, not a script bug.

### Status page stopped-script detection
`wp_status.html` compares `last_update` in `status.json` to the current time. If more than 20 minutes have elapsed, it shows a red alert with the three restart steps. The alert hides itself once the script resumes uploading.

### DreamHost rate limiting
Uploading `status.json` on every submission (once/min) triggers DreamHost's rate limiter ("Too Many Requests"). Upload is throttled to every 10 submissions.

## Environment variables (`.env`)

```
WP_USERNAME=PRRfan@ArchiveBot      # Wikipedia username + bot password name
WP_PASSWORD=<bot-password>         # Bot password (from Special:BotPasswords)
IABOT_SESSION=<cookie-value>       # Fallback only; prefer save_iabot_cookie.py
```

The bot password needs **Edit watchlist** permission from Special:BotPasswords.

## Deployment

Runs on a MacBook Air as a background `nohup` process. Status JSON is uploaded via `scp` to DreamHost shared hosting and displayed at `navybook.com/WP`.

### First time on a new machine
```bash
python3 -m venv .venv
.venv/bin/pip install requests beautifulsoup4 browser-cookie3

# Must run from Terminal.app directly (not SSH) — needs Full Disk Access:
.venv/bin/python3 save_iabot_cookie.py
```

Grant Terminal Full Disk Access: **System Settings → Privacy & Security → Full Disk Access → + → Terminal**

### Normal operation
```bash
# Start / resume from saved progress:
nohup .venv/bin/python3 iabot_runner.py >> ~/iabot_runner_out.txt 2>&1 &

# Full restart from scratch:
nohup .venv/bin/python3 iabot_runner.py --reset >> ~/iabot_runner_out.txt 2>&1 &

# Monitor from another machine:
ssh user@host "tail -f ~/iabot_runner_out.txt"
```

### When the session expires
The status page at `navybook.com/WP` will show a red alert. To fix:
1. Log back in at `https://iabot.wmcloud.org` in Safari
2. `~/Documents/devstuff/.venv/bin/python3 ~/Documents/devstuff/save_iabot_cookie.py`
3. `nohup ~/Documents/devstuff/.venv/bin/python3 ~/Documents/devstuff/iabot_runner.py >> ~/iabot_runner_out.txt 2>&1 &`
