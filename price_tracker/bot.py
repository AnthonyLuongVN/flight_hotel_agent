"""
Telegram bot for configuring price_tracker settings and triggering manual runs.

Local usage:
    python bot.py   (from price_tracker/ directory with .env loaded)

GitHub Actions:
    Runs via .github/workflows/bot.yml — exits after MAX_RUNTIME_SECONDS so
    the cron can restart it every 6 hours. Config changes are committed back
    to the repo automatically.

Commands:
    /help                           - Show all commands
    /config                         - Show current config
    /setroute SGN ICN               - Set origin and destination airport codes
    /setdates 2026-05-16 2026-05-23 - Set departure and return dates
    /settravelers 2                 - Set number of travelers
    /setcabin economy               - Set cabin class
    /setflightthreshold 350         - Set flight alert threshold (USD/person)
    /sethotelthreshold 150          - Set hotel alert threshold (USD/night)
    /sethotel Seoul 3               - Set hotel location and minimum star rating
    /setdrop 10                     - Set price drop alert percentage
    /seturgency 14                  - Set deadline urgency days
    /setstreak 3                    - Set price rise streak days
    /setexchange 26300              - Set USD to VND exchange rate
    /togglesummary                  - Toggle daily summary on/off
    /run                            - Run the price tracker immediately
"""

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime

import requests
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"

# Exit cleanly before GitHub Actions 6-hour job limit (default: run forever)
MAX_RUNTIME_SECONDS = int(os.environ.get("MAX_RUNTIME_SECONDS", 0))
_START_TIME = time.monotonic()


# ── Config I/O ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(cfg: dict):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def _git_commit_config(reason: str):
    """Commit and push config.json back to the repo. Only runs in GitHub Actions."""
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    subprocess.run(["git", "add", "config.json"], cwd=SCRIPT_DIR, check=False)
    result = subprocess.run(
        ["git", "commit", "-m", f"config: {reason}"],
        cwd=SCRIPT_DIR, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return  # Nothing to commit (no change)
    push = subprocess.run(["git", "push"], cwd=SCRIPT_DIR, capture_output=True, text=True)
    if push.returncode != 0:
        # Remote may have new commits (e.g. prices.db update) — rebase then retry
        subprocess.run(["git", "pull", "--rebase"], cwd=SCRIPT_DIR, check=False)
        subprocess.run(["git", "push"], cwd=SCRIPT_DIR, check=False)


def apply_config(cfg: dict, reason: str):
    """Save config and commit to repo if running on GitHub Actions."""
    save_config(cfg)
    _git_commit_config(reason)


# ── Telegram helpers ────────────────────────────────────────────────────────

def send(text: str):
    resp = requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=15,
    )
    if not resp.ok:
        print(f"[send error] {resp.status_code}: {resp.text}", file=sys.stderr)


def get_updates(offset: int) -> list[dict]:
    try:
        resp = requests.get(
            f"{TELEGRAM_API}/getUpdates",
            params={"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
            timeout=40,
        )
        if resp.ok:
            return resp.json().get("result", [])
    except requests.RequestException as e:
        print(f"[poll error] {e}", file=sys.stderr)
        time.sleep(5)
    return []


# ── Validators ──────────────────────────────────────────────────────────────

def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _validate_airport(code: str) -> str:
    code = code.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError(f"'{code}' is not a valid 3-letter airport code")
    return code


def _validate_positive_float(s: str, name: str) -> float:
    try:
        v = float(s)
    except ValueError:
        raise ValueError(f"{name} must be a number, got '{s}'")
    if v <= 0:
        raise ValueError(f"{name} must be positive")
    return v


def _validate_positive_int(s: str, name: str) -> int:
    try:
        v = int(s)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got '{s}'")
    if v <= 0:
        raise ValueError(f"{name} must be positive")
    return v


# ── Command handlers ────────────────────────────────────────────────────────

def cmd_help() -> str:
    return (
        "<b>Price Tracker Bot Commands</b>\n\n"
        "<b>View</b>\n"
        "/config — show all current settings\n\n"
        "<b>Flight settings</b>\n"
        "/setroute SGN ICN — origin &amp; destination\n"
        "/setdates 2026-05-16 2026-05-23 — travel dates\n"
        "/settravelers 2 — number of travelers\n"
        "/setcabin economy — cabin class\n"
        "/setflightthreshold 350 — alert when flight ≤ $X/person\n\n"
        "<b>Hotel settings</b>\n"
        "/sethotel Seoul 3 — location &amp; min star rating\n"
        "/sethotelthreshold 150 — alert when hotel ≤ $X/night\n\n"
        "<b>Alert behavior</b>\n"
        "/setdrop 10 — alert on price drop ≥ X%\n"
        "/seturgency 14 — alert daily when departure ≤ X days away\n"
        "/setstreak 3 — alert when price rises X days in a row\n"
        "/togglesummary — toggle daily summary on/off\n\n"
        "<b>Currency</b>\n"
        "/setexchange 26300 — USD → VND exchange rate\n\n"
        "<b>Actions</b>\n"
        "/run — fetch prices and send alert now\n"
        "/help — show this message"
    )


def cmd_config() -> str:
    cfg = load_config()
    nights = (_parse_date(cfg["return_date"]) - _parse_date(cfg["departure_date"])).days
    summary_status = "ON" if cfg.get("send_daily_summary", True) else "OFF"
    return (
        f"<b>Current Config</b>\n\n"
        f"<b>Flight</b>\n"
        f"  Route: {cfg['origin']} → {cfg['destination']}\n"
        f"  Depart: {cfg['departure_date']}\n"
        f"  Return: {cfg['return_date']} ({nights} nights)\n"
        f"  Travelers: {cfg['travelers']}\n"
        f"  Cabin: {cfg['cabin']}\n"
        f"  Alert threshold: ${cfg['flight_alert_threshold_usd']}/person\n\n"
        f"<b>Hotel</b>\n"
        f"  Location: {cfg['hotel_location']}\n"
        f"  Min stars: {cfg['hotel_min_stars']}\n"
        f"  Alert threshold: ${cfg['hotel_alert_per_night_usd']}/night\n\n"
        f"<b>Alerts</b>\n"
        f"  Price drop alert: ≥{cfg.get('alert_on_price_drop_percent', 10)}%\n"
        f"  Urgency window: {cfg.get('deadline_urgency_days', 14)} days before departure\n"
        f"  Rising streak: {cfg.get('price_rise_streak_days', 3)} days\n"
        f"  Daily summary: {summary_status}\n\n"
        f"<b>Currency</b>\n"
        f"  1 USD = {cfg['usd_to_vnd']:,} VND"
    )


def cmd_setroute(args: list[str]) -> str:
    if len(args) != 2:
        return "Usage: /setroute ORIGIN DESTINATION\nExample: /setroute SGN ICN"
    origin = _validate_airport(args[0])
    dest = _validate_airport(args[1])
    cfg = load_config()
    cfg["origin"] = origin
    cfg["destination"] = dest
    apply_config(cfg, f"set route {origin}-{dest}")
    return f"✅ Route updated: {origin} → {dest}"


def cmd_setdates(args: list[str]) -> str:
    if len(args) != 2:
        return "Usage: /setdates DEPARTURE RETURN\nExample: /setdates 2026-05-16 2026-05-23"
    dep = _parse_date(args[0])
    ret = _parse_date(args[1])
    if ret <= dep:
        return "❌ Return date must be after departure date"
    cfg = load_config()
    cfg["departure_date"] = str(dep)
    cfg["return_date"] = str(ret)
    nights = (ret - dep).days
    apply_config(cfg, f"set dates {dep}/{ret}")
    return f"✅ Dates updated: {dep} → {ret} ({nights} nights)"


def cmd_settravelers(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /settravelers N\nExample: /settravelers 2"
    n = _validate_positive_int(args[0], "Travelers")
    cfg = load_config()
    cfg["travelers"] = n
    apply_config(cfg, f"set travelers {n}")
    return f"✅ Travelers set to {n}"


def cmd_setcabin(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /setcabin CLASS\nExample: /setcabin economy"
    cabin = args[0].lower().strip()
    valid = {"economy", "business", "first", "premium_economy"}
    if cabin not in valid:
        return f"❌ Invalid cabin. Choose from: {', '.join(sorted(valid))}"
    cfg = load_config()
    cfg["cabin"] = cabin
    apply_config(cfg, f"set cabin {cabin}")
    return f"✅ Cabin set to {cabin}"


def cmd_setflightthreshold(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /setflightthreshold USD\nExample: /setflightthreshold 350"
    v = _validate_positive_float(args[0], "Threshold")
    cfg = load_config()
    cfg["flight_alert_threshold_usd"] = v
    apply_config(cfg, f"set flight threshold ${v:.0f}")
    return f"✅ Flight alert threshold set to ${v:.0f}/person"


def cmd_sethotelthreshold(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /sethotelthreshold USD\nExample: /sethotelthreshold 150"
    v = _validate_positive_float(args[0], "Threshold")
    cfg = load_config()
    cfg["hotel_alert_per_night_usd"] = v
    apply_config(cfg, f"set hotel threshold ${v:.0f}")
    return f"✅ Hotel alert threshold set to ${v:.0f}/night"


def cmd_sethotel(args: list[str]) -> str:
    if len(args) < 1:
        return "Usage: /sethotel LOCATION [MIN_STARS]\nExample: /sethotel Seoul 3"
    if len(args) >= 2:
        try:
            stars = float(args[-1])
            location = " ".join(args[:-1])
        except ValueError:
            stars = None
            location = " ".join(args)
    else:
        stars = None
        location = args[0]

    cfg = load_config()
    cfg["hotel_location"] = location
    if stars is not None:
        if stars < 0 or stars > 5:
            return "❌ Min stars must be between 0 and 5"
        cfg["hotel_min_stars"] = stars
    apply_config(cfg, f"set hotel {location}")
    stars_msg = f", min {cfg['hotel_min_stars']} stars" if stars is not None else ""
    return f"✅ Hotel location set to {location}{stars_msg}"


def cmd_setdrop(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /setdrop PERCENT\nExample: /setdrop 10"
    v = _validate_positive_float(args[0], "Percent")
    cfg = load_config()
    cfg["alert_on_price_drop_percent"] = v
    apply_config(cfg, f"set drop alert {v:.0f}%")
    return f"✅ Price drop alert set to ≥{v:.0f}%"


def cmd_seturgency(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /seturgency DAYS\nExample: /seturgency 14"
    v = _validate_positive_int(args[0], "Days")
    cfg = load_config()
    cfg["deadline_urgency_days"] = v
    apply_config(cfg, f"set urgency {v}d")
    return f"✅ Deadline urgency set to {v} days before departure"


def cmd_setstreak(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /setstreak DAYS\nExample: /setstreak 3"
    v = _validate_positive_int(args[0], "Days")
    cfg = load_config()
    cfg["price_rise_streak_days"] = v
    apply_config(cfg, f"set streak {v}d")
    return f"✅ Rising price streak alert set to {v} consecutive days"


def cmd_setexchange(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /setexchange RATE\nExample: /setexchange 26300"
    v = _validate_positive_int(args[0], "Exchange rate")
    cfg = load_config()
    cfg["usd_to_vnd"] = v
    apply_config(cfg, f"set exchange rate {v}")
    return f"✅ Exchange rate set to 1 USD = {v:,} VND"


def cmd_togglesummary() -> str:
    cfg = load_config()
    current = cfg.get("send_daily_summary", True)
    cfg["send_daily_summary"] = not current
    state = "ON" if cfg["send_daily_summary"] else "OFF"
    apply_config(cfg, f"toggle daily summary {state}")
    return f"✅ Daily summary turned {state}"


def cmd_run() -> str:
    send("⏳ Running price tracker... (this may take ~30 seconds)")
    result = subprocess.run(
        [sys.executable, "tracker.py"],
        capture_output=True,
        text=True,
        cwd=SCRIPT_DIR,
    )
    if result.returncode == 0:
        return "✅ Price tracker finished. Check above for the alert."
    else:
        stderr_tail = result.stderr[-500:] if result.stderr else "(no output)"
        return f"❌ Tracker failed (exit {result.returncode}):\n<code>{stderr_tail}</code>"


# ── Dispatch ────────────────────────────────────────────────────────────────

def handle(message: dict):
    text = message.get("text", "").strip()
    if not text.startswith("/"):
        return

    # Strip bot mention (e.g. /start@MyBot → /start)
    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    args = parts[1:]

    try:
        if cmd == "/help":
            send(cmd_help())
        elif cmd == "/config":
            send(cmd_config())
        elif cmd == "/setroute":
            send(cmd_setroute(args))
        elif cmd == "/setdates":
            send(cmd_setdates(args))
        elif cmd == "/settravelers":
            send(cmd_settravelers(args))
        elif cmd == "/setcabin":
            send(cmd_setcabin(args))
        elif cmd == "/setflightthreshold":
            send(cmd_setflightthreshold(args))
        elif cmd == "/sethotelthreshold":
            send(cmd_sethotelthreshold(args))
        elif cmd == "/sethotel":
            send(cmd_sethotel(args))
        elif cmd == "/setdrop":
            send(cmd_setdrop(args))
        elif cmd == "/seturgency":
            send(cmd_seturgency(args))
        elif cmd == "/setstreak":
            send(cmd_setstreak(args))
        elif cmd == "/setexchange":
            send(cmd_setexchange(args))
        elif cmd == "/togglesummary":
            send(cmd_togglesummary())
        elif cmd == "/run":
            send(cmd_run())
        else:
            send(f"Unknown command: {cmd}\nSend /help to see all commands.")
    except ValueError as e:
        send(f"❌ {e}")
    except Exception as e:
        send(f"❌ Unexpected error: {e}")
        print(f"[ERROR] {e}", file=sys.stderr)


# ── Main polling loop ───────────────────────────────────────────────────────

def main():
    print(f"[bot] Starting. Authorized chat: {CHAT_ID}")
    if MAX_RUNTIME_SECONDS:
        print(f"[bot] Will exit after {MAX_RUNTIME_SECONDS}s (GitHub Actions mode)")
    offset = 0

    while True:
        if MAX_RUNTIME_SECONDS and (time.monotonic() - _START_TIME) >= MAX_RUNTIME_SECONDS:
            print("[bot] Max runtime reached, exiting cleanly.")
            break

        updates = get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            if not msg:
                continue
            incoming_chat_id = str(msg.get("chat", {}).get("id", ""))
            if incoming_chat_id != str(CHAT_ID):
                continue
            handle(msg)


if __name__ == "__main__":
    main()
