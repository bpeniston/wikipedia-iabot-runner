# CLAUDE.md — Wikipedia IABot Runner

## What this project does

Automates submitting Wikipedia watchlist articles to IABot's "run bot on single page" web interface, one per minute. IABot archives dead/unarchived external links and updates citations. Edits appear under the authenticated Wikipedia user's account.

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
3. **Status upload** — `scp` to DreamHost after each submission
4. **Progress** — saved to `~/.iabot_progress.json` (queue + done list)

## Critical implementation details

### The `archiveall` checkbox
The IABot form has a checkbox `name="archiveall"` that must be set to `"on"` in the POST payload. Without it IABot only analyzes the page and reports results but **does not save any changes to Wikipedia**. This was the main bug discovered during development.

### Form field name
The URL input field on IABot's form is `name="pagesearch"` — not `url`, `article`, or other common names.

### Cookie authentication
IABot uses Wikimedia OAuth. The session cookie is named `IABotManagementConsole`. The script reads it from Safari via `browser_cookie3` (requires Full Disk Access for Terminal on macOS), saves it to `~/.iabot_cookie`, and loads from that file on subsequent runs. This allows the script to run via SSH without needing FDA each time.

### IABot response format
The response body starts with an HTML comment `<!--` containing the processing log. The result line looks like:
```
Rescued: 2; Tagged dead: 0; Archived: 2; Memory Used: 16 MB; Max System Memory Used: 16 MB
```
Extracted with: `re.search(r'Rescued:.*?(?=\n|$)', r2.text)`

### Wikipedia API quirk
`list=watchlistraw` returns results at the **top level** of the response (not nested under `query` as most other list APIs do). The script handles both locations.

### Two edits per article
When IABot finds work to do, it makes two Wikipedia edits: a first pass that adds archive URLs, and a second refinement pass. This is normal IABot behavior, not a script bug.

## Environment variables (`.env`)

```
WP_USERNAME=PRRfan@ArchiveBot      # Wikipedia username + bot password name
WP_PASSWORD=<bot-password>         # Bot password (from Special:BotPasswords)
IABOT_SESSION=<cookie-value>       # Fallback only; prefer save_iabot_cookie.py
```

The bot password needs **Edit watchlist** permission from Special:BotPasswords.

## Deployment

Runs on a MacBook Air as a background `nohup` process. Status JSON is uploaded via `scp` to DreamHost shared hosting after each submission and displayed at `navybook.com/WP`.

To start:
```bash
# First time on a new machine:
.venv/bin/python3 save_iabot_cookie.py   # must run from Terminal.app, not SSH

# Normal start / resume:
nohup .venv/bin/python3 iabot_runner.py > ~/iabot_runner_out.txt 2>&1 &

# Full restart:
nohup .venv/bin/python3 iabot_runner.py --reset > ~/iabot_runner_out.txt 2>&1 &
```
