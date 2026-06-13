# Flight Price Tracker Bot

Automated daily tracker for flight prices on any route. Sends Telegram alerts when prices hit your budget, drop significantly, or show other patterns worth acting on.

Supports up to **2 independent routes** — each with its own dates, thresholds, and price history. Routes can be one-way or round-trip.

**Cost: $0/month** — uses SerpAPI free tier (250 searches/month) + Telegram Bot API (free).

---

## Features

- Checks Google Flights (and Google Hotels for round-trip routes) via SerpAPI every day
- Monitors **up to 2 routes independently** — one-way or round-trip, any airports
- Shows prices in **USD and VND** (configurable exchange rate)
- **5 alert triggers:** under budget, sudden drop, new all-time low, deadline urgency, rising trend
- Price history stored in SQLite, shown as a 7-day table per route in Telegram
- Control everything via **Telegram bot commands** — no code or file edits needed

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
3. Free tier: **250 searches/month** (tracker uses ~2/day per route)

### 3. Deploy to GitHub

1. Fork or push this repo to your own GitHub account
2. Go to **Settings → Secrets and variables → Actions → New repository secret** and add:
   - `SERPAPI_KEY` — your SerpAPI key
   - `TELEGRAM_BOT_TOKEN` — your bot token from BotFather
   - `TELEGRAM_CHAT_ID` — your chat ID from step 1
3. Go to **Actions** tab → enable workflows if prompted

GitHub Actions runs the tracker automatically every day at 2 PM Vietnam time (07:00 UTC). You can also trigger it manually with the **"Run workflow"** button.

---

## Telegram Bot Commands

### Route management

| Command | Description |
|---------|-------------|
| `/listroutes` | Show all tracked routes |
| `/addroute SGN ICN 2026-07-01` | Add a one-way route |
| `/addroute SGN ICN 2026-07-01 2026-07-08 Seoul` | Add a round-trip route with hotel location |
| `/delroute SGN-ICN` | Delete a route and its price history |
| `/setactive SGN-ICN` | Switch which route other commands target |

### Active route settings

| Command | Example | Description |
|---------|---------|-------------|
| `/config` | | Show active route settings |
| `/setroute` | `/setroute SGN ICN` | Change origin/destination |
| `/setdates` | `/setdates 2026-07-01` | Set one-way departure date |
| `/setdates` | `/setdates 2026-07-01 2026-07-08` | Set round-trip dates |
| `/setflightthreshold` | `/setflightthreshold 53` | Alert when flight ≤ $X/person |
| `/sethotel` | `/sethotel Seoul 3` | Set hotel location and min star rating |
| `/sethotelthreshold` | `/sethotelthreshold 80` | Alert when hotel ≤ $X/night |

### Global settings (apply to all routes)

| Command | Example | Description |
|---------|---------|-------------|
| `/settravelers` | `/settravelers 2` | Number of adults |
| `/setcabin` | `/setcabin economy` | Cabin class |
| `/setdrop` | `/setdrop 10` | Alert on price drop ≥ X% |
| `/seturgency` | `/seturgency 14` | Daily alert when departure ≤ X days away |
| `/setstreak` | `/setstreak 3` | Alert when price rises X days in a row |
| `/setexchange` | `/setexchange 26300` | USD → VND exchange rate |
| `/togglesummary` | | Toggle daily summary on/off |
| `/run` | | Trigger a price check immediately |

---

## config.json Structure

All settings are stored in `config.json`. The bot keeps this file up to date automatically — you rarely need to edit it by hand.

```json
{
  "active_route": "SGN-HUI",
  "routes": {
    "SGN-HUI": {
      "origin": "SGN",
      "destination": "HUI",
      "departure_date": "2026-07-01",
      "return_date": null,
      "flight_alert_threshold_usd": 53,
      "hotel_location": "",
      "hotel_alert_per_night_usd": 150,
      "hotel_min_stars": 3
    }
  },
  "travelers": 2,
  "cabin": "economy",
  "currency": "USD",
  "usd_to_vnd": 26300,
  "send_daily_summary": true,
  "alert_on_price_drop_percent": 10,
  "deadline_urgency_days": 14,
  "price_rise_streak_days": 3
}
```

`return_date: null` means one-way (hotel tracking disabled for that route).

---

## Running Locally

```bash
cd price_tracker

# Copy and fill in your secrets
cp .env.example .env
# Edit .env: SERPAPI_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

pip install -r requirements.txt
python tracker.py   # run price check once
python bot.py       # start the Telegram command bot
```

---

## Example Telegram Message

```
✈️ Price Tracker — 2026-06-15

══ SGN → HUI ══
📅 Jul 1, 2026 (one-way)

✈️ FLIGHTS (2 adults)
Dep   Arr   Airline        $/pp
----------------------------------
06:00 07:10 VJ VJ123       $48*
07:30 08:40 VN VN456       $55
Rate: 26,300 VND/USD  (* = under budget)

📊 Price history (last 7 days)
Date         Flight   Hotel/night
──────────────────────────────────
2026-06-08      $52           N/A
2026-06-09      $49           N/A
...

══ DAD → SGN ══
📅 Jul 5, 2026 (one-way)
...

🚨 ALERTS TRIGGERED
• Flight under budget: $48/person (<= $53 limit)
```
