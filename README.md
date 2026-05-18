# Wikipedia IABot Runner

Reads your Wikipedia watchlist and submits each article to [IABot](https://iabot.wmcloud.org)'s "run bot on single page" tool, one page per minute. IABot finds unarchived or dead URLs in article references, archives them with the Internet Archive, and updates the citations.

Edits appear in Wikipedia under your own account (not InternetArchiveBot) and are tagged `IABotManagementConsole`.

Progress is saved to `~/.iabot_progress.json` so the script can be interrupted and resumed at any time. A live status page (`navybook.com/WP` or similar) is uploaded to your web server after each submission.

## Requirements

- Python 3.9+
- macOS with Safari (the script reads your IABot session cookie automatically)
- A Wikipedia account with a [bot password](https://en.wikipedia.org/wiki/Special:BotPasswords) — needs **Edit watchlist** permission
- An IABot account — log in at [iabot.wmcloud.org](https://iabot.wmcloud.org) via Wikimedia OAuth

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests beautifulsoup4 browser-cookie3
```

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
nano .env
```

`.env` format:
```
WP_USERNAME=YourUsername@BotPasswordName
WP_PASSWORD=your-bot-password-here
```

(`IABOT_SESSION` is no longer needed — the script reads Safari cookies automatically.)

### macOS Full Disk Access

Grant **Terminal** Full Disk Access so the script can read Safari's IABot session cookie:

**System Settings → Privacy & Security → Full Disk Access → + → Terminal**

### Save the IABot cookie

Run this **once from Terminal** (not SSH) to save the cookie to `~/.iabot_cookie`:

```bash
.venv/bin/python3 save_iabot_cookie.py
```

Re-run this whenever the IABot session expires (roughly when Safari closes or after a few weeks). After saving, the script can be started from anywhere including SSH.

## Usage

```bash
# Run / resume from saved progress
.venv/bin/python3 iabot_runner.py

# Start over from scratch
.venv/bin/python3 iabot_runner.py --reset
```

Run in the background (survives closing the terminal):

```bash
nohup .venv/bin/python3 iabot_runner.py > ~/iabot_runner_out.txt 2>&1 &
```

Monitor from another machine:

```bash
ssh user@host "tail -f ~/iabot_runner_out.txt"
```

## Status page

The script uploads `status.json` to your web server after each submission. Deploy `wp_status.html` as `index.html` alongside it for a live progress page that auto-refreshes every 60 seconds.

Configure the upload destination in `iabot_runner.py`:

```python
DREAMHOST_USER = "youruser"
DREAMHOST_HOST = "your-server.example.com"
DREAMHOST_PATH = "~/yoursite.com/WP/status.json"
```

## Rate limiting & error handling

- One submission per minute (well within IABot's 5/min limit)
- Times out → retried once after 30 seconds; if still failing, moved to end of queue
- IABot reports heavy load → sleeps 1 hour then retries the same page
- IABot session expires → script opens iabot.wmcloud.org and exits with instructions

## What IABot actually does

IABot makes **two Wikipedia edits** per article when it finds work to do:
1. First pass — adds archive URLs to all unarchived references
2. Second pass — refines and cleans up the added markup

Both edits appear under your Wikipedia account, tagged `IABotManagementConsole`.

If an article returns `Rescued: 0; Tagged dead: 0; Archived: 0` it means all links were already archived or live — no edit is made.

## Key implementation notes

- The IABot form field for the Wikipedia URL is `pagesearch`
- The `archiveall` checkbox must be explicitly set to `on` in the POST payload — without it IABot only analyzes the page but does not save any changes
- IABot embeds its processing log in an HTML comment at the top of the response; the result line (`Rescued: X...`) is extracted with a regex
- Session cookies are read from Safari via `browser_cookie3`, saved to `~/.iabot_cookie`, and reloaded from that file on subsequent runs (avoids needing Full Disk Access for SSH-started processes)
