# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the tracker

```bash
# Create and activate virtualenv (first time only)
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the tracker (requires .env with secrets)
python tracker.py
```

Copy `.env.example` to `.env` and fill in `SERPAPI_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` before running.

## Testing without real API keys

```python
# Quick smoke test — no API calls, no Telegram message sent
python3 -c "
import json, os, db, alert
os.environ.update({'SERPAPI_KEY':'x','TELEGRAM_BOT_TOKEN':'x','TELEGRAM_CHAT_ID':'x'})
config = json.load(open('config.json'))
db.init_db()
msg = alert.build_message(
    flight={'flight_usd':310,'airline':'VietJet','stops':1,'duration_min':330,'flight_url':''},
    hotel={'hotel_usd':95,'hotel_name':'Test Hotel','hotel_stars':4.0,'hotel_url':''},
    prev=None, history=[], triggers=['Test trigger'], config=config, check_date='2026-01-01'
)
print(msg)
"
```

## Architecture

All user-facing settings live in `config.json` — change thresholds, dates, or the VND exchange rate there without touching code.

**Data flow:**
1. `tracker.py` — entry point. Calls SerpAPI twice (Google Flights + Google Hotels), runs the 5-trigger alert evaluation, saves to SQLite, sends Telegram if needed.
2. `db.py` — thin SQLite wrapper. One row per date in the `prices` table (PRIMARY KEY on `date`, so re-running the same day overwrites). `get_all_time_low_*()` must be called **before** `save_price()` in the same run so the all-time-low trigger compares against prior history, not today's value.
3. `alert.py` — pure message building + Telegram HTTP call. `build_message()` composes sections from `build_flight_section()`, `build_hotel_section()`, `build_history_table()`, and `build_trigger_banner()`. Messages use Telegram Markdown (single `*bold*`, backtick code blocks). VND conversion uses a fixed rate from `config["usd_to_vnd"]`.

**5 alert triggers** (evaluated in `evaluate_triggers()` in `tracker.py`):
1. Price ≤ configured threshold
2. Price dropped ≥ `alert_on_price_drop_percent` vs yesterday
3. New all-time low in DB
4. Days until departure ≤ `deadline_urgency_days`
5. Price rose for `price_rise_streak_days` consecutive days

**Scheduling:** GitHub Actions runs `.github/workflows/price_check.yml` daily at 07:00 UTC (14:00 Vietnam time). After each run, the workflow commits the updated `prices.db` back to the repo so history persists across runs. Secrets (`SERPAPI_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) are stored in GitHub Actions secrets, not in code.

## SerpAPI response shape

- Flights: `data["best_flights"] + data["other_flights"]` — each item has `price` (total for all travelers), `flights` (list of legs), `total_duration`.
- Hotels: `data["properties"]` — each item has `rate_per_night.lowest` which may be a string (`"$95"`) or float; `get_price()` in `tracker.py` handles both.

## Key constraints

- Python 3.12+ required (uses `dict | None` union type syntax).
- `prices.db` is committed to the repo (gitignored locally via `.venv/` and `.env` only). This is intentional — it's the persistent price history store.
- The SerpAPI free tier provides 250 searches/month. The tracker uses 2/day, so ~60/month. Do not add additional SerpAPI calls without checking quota impact.
