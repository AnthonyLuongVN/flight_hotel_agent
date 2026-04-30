# Korea Trip Price Tracker

Automated daily tracker for flight (SGN → ICN) and hotel prices in Seoul.
Sends Telegram alerts when prices hit your budget or drop significantly.

**Cost: $0/month** — uses SerpAPI free tier (250 searches/month) + Telegram Bot API (free).

---

## Features

- Checks Google Flights + Google Hotels via SerpAPI every day at 2 PM Vietnam time
- Shows prices in **USD and VND** (configurable exchange rate)
- 5 alert triggers: under budget, sudden drop, new all-time low, deadline urgency, rising trend
- Price history stored in SQLite and shown as a 7-day table in Telegram
- All settings in `config.json` — no code changes needed

---

## Quick Setup (15 minutes)

### 1. Create a Telegram Bot

1. Open Telegram → search `@BotFather` → send `/newbot`
2. Follow prompts, get your **bot token** (looks like `123456789:ABCdef...`)
3. Send any message to your new bot
4. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
5. Find `"chat":{"id":XXXXXXX}` — that number is your **chat ID**

### 2. Get a SerpAPI Key

1. Sign up at [serpapi.com](https://serpapi.com) (free, no credit card needed)
2. Copy your API key from the dashboard
3. Free tier: **250 searches/month** (tracker uses ~60/month)

### 3. Deploy to GitHub

1. Create a new **public** GitHub repository (public = unlimited free Actions minutes)
2. Push this entire `price_tracker/` folder to the repo root
3. Go to **Settings → Secrets and variables → Actions → New repository secret** and add:
   - `SERPAPI_KEY` — your SerpAPI key
   - `TELEGRAM_BOT_TOKEN` — your bot token from BotFather
   - `TELEGRAM_CHAT_ID` — your chat ID from step 1

4. Go to **Actions** tab → enable workflows if prompted

GitHub Actions will now run automatically every day at 2 PM Vietnam time.
You can also trigger it manually with the **"Run workflow"** button in the Actions tab.

---

## Configuration

Edit `config.json` to change any setting — no code changes needed:

| Key | Default | Description |
|-----|---------|-------------|
| `origin` | `SGN` | Departure airport IATA code |
| `destination` | `ICN` | Arrival airport IATA code |
| `departure_date` | `2026-05-16` | Target departure date |
| `return_date` | `2026-05-23` | Target return date |
| `travelers` | `2` | Number of adults |
| `flight_alert_threshold_usd` | `350` | Alert when flight is at or below this (per person, round trip) |
| `hotel_alert_per_night_usd` | `150` | Alert when hotel is at or below this (per night) |
| `hotel_min_stars` | `3` | Minimum star rating for hotels |
| `usd_to_vnd` | `26300` | Fixed USD → VND exchange rate |
| `send_daily_summary` | `true` | Send a Telegram message every day even if no alerts |
| `alert_on_price_drop_percent` | `10` | Alert if price drops this % vs yesterday |
| `deadline_urgency_days` | `14` | Start daily urgency alerts this many days before departure |
| `price_rise_streak_days` | `3` | Alert if price rises this many consecutive days |

---

## Running Locally

```bash
cd price_tracker

# Copy and fill in your secrets
cp .env.example .env
# Edit .env with your SERPAPI_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

pip install -r requirements.txt
python tracker.py
```

---

## Example Telegram Message

```
✈️ Korea Trip Tracker — 2026-05-01

FLIGHTS (SGN → ICN, 2 adults, round trip)
VietJet Air | 1 stop(s) | 5h 30m
Per person: $310 (~8,153,000 VND) — Over budget by $-40 (limit $350 / ~9,205,000 VND) ✅

HOTELS (Seoul, per night) ⭐4.2
Novotel Ambassador Seoul
Per night: $95 (~2,498,500 VND) — Under budget (limit $150 / ~3,945,000 VND) ✅

📊 Price history (last 7 days)
Date         | Flight  | Hotel/night
-------------|---------|------------
2026-04-25   | $340    | $98
2026-04-26   | $335    | $95
...

🚨 ALERTS TRIGGERED
• Hotel under budget: $95/night (<= $150 limit)
• New all-time low hotel price: $95/night!
```
