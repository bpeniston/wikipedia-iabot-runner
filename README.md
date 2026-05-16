# Wikipedia IABot Runner

Reads your Wikipedia watchlist and submits each article to [IABot](https://iabot.wmcloud.org)'s "run bot on single page" tool, one page per minute. IABot finds unarchived URLs in article references, archives them with the Internet Archive, and updates the citations.

Progress is saved so the script can be interrupted and resumed. A live status page is uploaded to your web server after each submission.

## Requirements

- Python 3.9+
- A Wikipedia account with a [bot password](https://en.wikipedia.org/wiki/Special:BotPasswords) (needs **Edit watchlist** permission)
- An IABot account (log in at [iabot.wmcloud.org](https://iabot.wmcloud.org) via Wikimedia OAuth)
- Safari (macOS) — the script reads your IABot session cookie automatically

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests beautifulsoup4 browser-cookie3
```

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

On macOS, grant **Terminal** Full Disk Access (System Settings → Privacy & Security → Full Disk Access) so the script can read Safari's cookies automatically.

## Usage

```bash
.venv/bin/python3 iabot_runner.py          # run / resume
.venv/bin/python3 iabot_runner.py --reset  # start over from full watchlist
```

Run in the background (survives closing the terminal):

```bash
nohup .venv/bin/python3 iabot_runner.py > ~/iabot_runner_out.txt 2>&1 &
```

## Status page

The script uploads `status.json` to your web server after each submission. Pair it with `wp_status.html` (rename to `index.html`) for a live progress page that auto-refreshes every 60 seconds.

## Rate limiting

- One submission per minute (well within IABot's 5/min limit)
- Automatically waits 1 hour if IABot reports heavy load
