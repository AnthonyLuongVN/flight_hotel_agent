"""
Telegram bot for configuring price_tracker settings and triggering manual runs.

Local usage:
    python bot.py   (from price_tracker/ directory with .env loaded)

GitHub Actions:
    Runs via .github/workflows/bot.yml — exits after MAX_RUNTIME_SECONDS so
    the cron can restart it every 6 hours. Config changes are committed back
    to the repo automatically.

Commands:
    /help                                     - Show all commands
    /config                                   - Show current config (active route)
    /listroutes                               - List all tracked routes
    /addroute SGN NRT 2026-06-10 2026-06-17 [Tokyo] - Add a new route (max 2)
    /delroute SGN-NRT                         - Delete a route and its history
    /setactive SGN-ICN                        - Switch the active route
    /setroute SGN ICN                         - Set origin and destination of active route
    /setdates 2026-05-16 2026-05-23           - Set departure and return dates of active route
    /settravelers 2                           - Set number of travelers (global)
    /setcabin economy                         - Set cabin class (global)
    /setflightthreshold 350                   - Set flight alert threshold for active route
    /sethotelthreshold 150                    - Set hotel alert threshold for active route
    /sethotel Seoul 3                         - Set hotel location and min stars for active route
    /setdrop 10                               - Set price drop alert percentage (global)
    /seturgency 14                            - Set deadline urgency days (global)
    /setstreak 3                              - Set price rise streak days (global)
    /setexchange 26300                        - Set USD to VND exchange rate (global)
    /togglesummary                            - Toggle daily summary on/off (global)
    /run                                      - Run the price tracker immediately
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

MAX_RUNTIME_SECONDS = int(os.environ.get("MAX_RUNTIME_SECONDS", 0))
_START_TIME = time.monotonic()

_ROUTE_KEYS = ["origin", "destination", "departure_date", "return_date",
               "hotel_location", "hotel_min_stars", "flight_alert_threshold_usd",
               "hotel_alert_per_night_usd"]

MAX_ROUTES = 2


# ── Config I/O ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    return _maybe_migrate_config(cfg)


def _maybe_migrate_config(cfg: dict) -> dict:
    """Convert old flat config to multi-route format."""
    if "routes" in cfg:
        return cfg
    route_id = f"{cfg['origin']}-{cfg['destination']}"
    cfg["routes"] = {
        route_id: {k: cfg.pop(k) for k in _ROUTE_KEYS if k in cfg}
    }
    cfg["active_route"] = route_id
    save_config(cfg)
    return cfg


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
        return
    push = subprocess.run(["git", "push"], cwd=SCRIPT_DIR, capture_output=True, text=True)
    if push.returncode != 0:
        subprocess.run(["git", "pull", "--rebase"], cwd=SCRIPT_DIR, check=False)
        subprocess.run(["git", "push"], cwd=SCRIPT_DIR, check=False)


def apply_config(cfg: dict, reason: str):
    save_config(cfg)
    _git_commit_config(reason)


def _active_route(cfg: dict) -> dict:
    """Return the active route's settings dict (mutable reference)."""
    return cfg["routes"][cfg["active_route"]]


def _get_merged_cfg(cfg: dict, route_id: str | None = None) -> dict:
    """Merge global + route-specific settings into a flat dict."""
    rid = route_id or cfg["active_route"]
    merged = {k: v for k, v in cfg.items() if k not in ("routes", "active_route")}
    merged.update(cfg["routes"][rid])
    return merged


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
        "<b>Routes (max 2)</b>\n"
        "/listroutes — list all tracked routes\n"
        "/addroute SGN ICN 2026-05-28 — add one-way route\n"
        "/addroute SGN ICN 2026-05-28 2026-06-05 Seoul — add round-trip\n"
        "/delroute SGN-NRT — delete route &amp; its history\n"
        "/setactive SGN-ICN — switch active route\n\n"
        "<b>Active route settings</b>\n"
        "/config — show active route settings\n"
        "/setroute SGN ICN — origin &amp; destination\n"
        "/setdates 2026-05-28 [2026-06-05] — departure (+ optional return)\n"
        "/setflightthreshold 350 — alert when flight ≤ $X/person\n"
        "/sethotel Seoul 3 — location &amp; min star rating\n"
        "/sethotelthreshold 150 — alert when hotel ≤ $X/night\n\n"
        "<b>Global settings</b>\n"
        "/settravelers 2 — number of travelers\n"
        "/setcabin economy — cabin class\n"
        "/setdrop 10 — alert on price drop ≥ X%\n"
        "/seturgency 14 — alert daily when departure ≤ X days away\n"
        "/setstreak 3 — alert when price rises X days in a row\n"
        "/togglesummary — toggle daily summary on/off\n"
        "/setexchange 26300 — USD → VND exchange rate\n\n"
        "<b>Actions</b>\n"
        "/run — fetch prices and send alert now\n"
        "/help — show this message"
    )


def cmd_config() -> str:
    cfg = load_config()
    active_id = cfg["active_route"]
    route = cfg["routes"][active_id]

    dep = route["departure_date"]
    ret = route.get("return_date")
    date_str = f"{dep} – {ret} ({(_parse_date(ret) - _parse_date(dep)).days} nights)" if ret else f"{dep} (one-way)"
    summary_status = "ON" if cfg.get("send_daily_summary", True) else "OFF"

    lines = [
        f"<b>Active Route: {active_id}</b>\n",
        f"<b>Flight</b>",
        f"  Route: {route['origin']} → {route['destination']}",
        f"  Date(s): {date_str}",
        f"  Travelers: {cfg['travelers']}",
        f"  Cabin: {cfg['cabin']}",
        f"  Alert threshold: ${route['flight_alert_threshold_usd']}/person",
        f"",
        f"<b>Hotel</b>",
        f"  Location: {route.get('hotel_location', '—')}",
        f"  Min stars: {route.get('hotel_min_stars', 3)}",
        f"  Alert threshold: ${route['hotel_alert_per_night_usd']}/night",
        f"",
        f"<b>Alerts (global)</b>",
        f"  Price drop alert: ≥{cfg.get('alert_on_price_drop_percent', 10)}%",
        f"  Urgency window: {cfg.get('deadline_urgency_days', 14)} days before departure",
        f"  Rising streak: {cfg.get('price_rise_streak_days', 3)} days",
        f"  Daily summary: {summary_status}",
        f"",
        f"<b>Currency</b>",
        f"  1 USD = {cfg['usd_to_vnd']:,} VND",
    ]

    other_routes = [rid for rid in cfg["routes"] if rid != active_id]
    if other_routes:
        lines += ["", "<b>Other routes</b>"]
        for rid in other_routes:
            r = cfg["routes"][rid]
            ret_str = f" – {r['return_date']}" if r.get("return_date") else " (one-way)"
            lines.append(f"  {rid}: {r['origin']}→{r['destination']}, {r['departure_date']}{ret_str}")
        lines.append("Use /setactive to switch.")

    return "\n".join(lines)


def cmd_listroutes() -> str:
    cfg = load_config()
    if not cfg["routes"]:
        return "No routes configured."
    active_id = cfg["active_route"]
    lines = ["<b>Tracked Routes</b>\n"]
    for rid, r in cfg["routes"].items():
        marker = "★ " if rid == active_id else "  "
        ret_str = f" – {r['return_date']}" if r.get("return_date") else " (one-way)"
        hotel_str = r.get("hotel_location", "—") if r.get("return_date") else "—"
        lines.append(
            f"{marker}<b>{rid}</b>: {r['origin']}→{r['destination']}\n"
            f"     {r['departure_date']}{ret_str}\n"
            f"     Hotel: {hotel_str} | ✈ ≤${r['flight_alert_threshold_usd']} | 🏨 ≤${r['hotel_alert_per_night_usd']}/night"
        )
    lines.append(f"\n★ = active route  ({len(cfg['routes'])}/{MAX_ROUTES} slots used)")
    return "\n".join(lines)


def _is_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def cmd_addroute(args: list[str]) -> str:
    if len(args) < 3:
        return (
            "Usage: /addroute ORIGIN DEST DEPARTURE [RETURN] [HOTEL_LOCATION]\n"
            "One-way:    /addroute SGN ICN 2026-05-28\n"
            "Round-trip: /addroute SGN ICN 2026-05-28 2026-06-05 Seoul"
        )
    origin = _validate_airport(args[0])
    dest = _validate_airport(args[1])
    dep = _parse_date(args[2])

    # args[3] is return date only if it looks like YYYY-MM-DD
    ret = None
    hotel_location = ""
    if len(args) > 3 and _is_date(args[3]):
        ret = _parse_date(args[3])
        if ret <= dep:
            return "❌ Return date must be after departure date"
        hotel_location = " ".join(args[4:]) if len(args) > 4 else ""
    else:
        hotel_location = " ".join(args[3:]) if len(args) > 3 else ""

    cfg = load_config()
    if len(cfg["routes"]) >= MAX_ROUTES:
        existing = ", ".join(cfg["routes"].keys())
        return f"❌ Max {MAX_ROUTES} routes allowed. Current routes: {existing}\nUse /delroute to remove one first."

    route_id = f"{origin}-{dest}"
    if route_id in cfg["routes"]:
        return f"❌ Route {route_id} already exists. Use /delroute {route_id} to remove it first."

    cfg["routes"][route_id] = {
        "origin": origin,
        "destination": dest,
        "departure_date": str(dep),
        "return_date": str(ret) if ret else None,
        "hotel_location": hotel_location,
        "hotel_min_stars": 3,
        "flight_alert_threshold_usd": cfg["routes"][cfg["active_route"]]["flight_alert_threshold_usd"],
        "hotel_alert_per_night_usd": cfg["routes"][cfg["active_route"]]["hotel_alert_per_night_usd"],
    }
    cfg["active_route"] = route_id
    apply_config(cfg, f"add route {route_id}")
    trip_type = "round-trip" if ret else "one-way"
    hotel_msg = f", hotel: {hotel_location}" if hotel_location else (" (set hotel with /sethotel)" if ret else "")
    return f"✅ Route {route_id} added ({trip_type}), set as active{hotel_msg}"


def cmd_delroute(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /delroute ROUTE_ID\nExample: /delroute SGN-NRT"
    route_id = args[0].upper()
    cfg = load_config()
    if route_id not in cfg["routes"]:
        existing = ", ".join(cfg["routes"].keys())
        return f"❌ Route {route_id} not found. Routes: {existing}"
    if len(cfg["routes"]) == 1:
        return "❌ Can't delete the only route."

    del cfg["routes"][route_id]
    if cfg["active_route"] == route_id:
        cfg["active_route"] = next(iter(cfg["routes"]))

    # Delete price history from DB
    import db as _db
    _db.delete_route_history(route_id)

    apply_config(cfg, f"delete route {route_id}")
    return f"✅ Route {route_id} deleted (history cleared). Active route: {cfg['active_route']}"


def cmd_setactive(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /setactive ROUTE_ID\nExample: /setactive SGN-ICN"
    route_id = args[0].upper()
    cfg = load_config()
    if route_id not in cfg["routes"]:
        existing = ", ".join(cfg["routes"].keys())
        return f"❌ Route {route_id} not found. Routes: {existing}"
    cfg["active_route"] = route_id
    apply_config(cfg, f"set active route {route_id}")
    return f"✅ Active route set to {route_id}"


def cmd_setroute(args: list[str]) -> str:
    if len(args) != 2:
        return "Usage: /setroute ORIGIN DESTINATION\nExample: /setroute SGN ICN"
    origin = _validate_airport(args[0])
    dest = _validate_airport(args[1])
    cfg = load_config()
    route = _active_route(cfg)
    route["origin"] = origin
    route["destination"] = dest
    apply_config(cfg, f"set route {origin}-{dest} on {cfg['active_route']}")
    return f"✅ Route [{cfg['active_route']}] updated: {origin} → {dest}"


def cmd_setdates(args: list[str]) -> str:
    if len(args) not in (1, 2):
        return "Usage: /setdates DEPARTURE [RETURN]\nOne-way:    /setdates 2026-05-28\nRound-trip: /setdates 2026-05-16 2026-05-23"
    dep = _parse_date(args[0])
    cfg = load_config()
    route = _active_route(cfg)
    route["departure_date"] = str(dep)
    if len(args) == 2:
        ret = _parse_date(args[1])
        if ret <= dep:
            return "❌ Return date must be after departure date"
        route["return_date"] = str(ret)
        nights = (ret - dep).days
        apply_config(cfg, f"set dates {dep}/{ret} on {cfg['active_route']}")
        return f"✅ [{cfg['active_route']}] Dates updated: {dep} → {ret} ({nights} nights)"
    else:
        route["return_date"] = None
        apply_config(cfg, f"set date {dep} (one-way) on {cfg['active_route']}")
        return f"✅ [{cfg['active_route']}] Departure set to {dep} (one-way)"


def cmd_settravelers(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /settravelers N\nExample: /settravelers 2"
    n = _validate_positive_int(args[0], "Travelers")
    cfg = load_config()
    cfg["travelers"] = n
    apply_config(cfg, f"set travelers {n}")
    return f"✅ Travelers set to {n} (all routes)"


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
    return f"✅ Cabin set to {cabin} (all routes)"


def cmd_setflightthreshold(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /setflightthreshold USD\nExample: /setflightthreshold 350"
    v = _validate_positive_float(args[0], "Threshold")
    cfg = load_config()
    _active_route(cfg)["flight_alert_threshold_usd"] = v
    apply_config(cfg, f"set flight threshold ${v:.0f} on {cfg['active_route']}")
    return f"✅ [{cfg['active_route']}] Flight alert threshold set to ${v:.0f}/person"


def cmd_sethotelthreshold(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /sethotelthreshold USD\nExample: /sethotelthreshold 150"
    v = _validate_positive_float(args[0], "Threshold")
    cfg = load_config()
    _active_route(cfg)["hotel_alert_per_night_usd"] = v
    apply_config(cfg, f"set hotel threshold ${v:.0f} on {cfg['active_route']}")
    return f"✅ [{cfg['active_route']}] Hotel alert threshold set to ${v:.0f}/night"


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
    route = _active_route(cfg)
    route["hotel_location"] = location
    if stars is not None:
        if stars < 0 or stars > 5:
            return "❌ Min stars must be between 0 and 5"
        route["hotel_min_stars"] = stars
    apply_config(cfg, f"set hotel {location} on {cfg['active_route']}")
    stars_msg = f", min {route.get('hotel_min_stars', 3)} stars" if stars is not None else ""
    return f"✅ [{cfg['active_route']}] Hotel location set to {location}{stars_msg}"


def cmd_setdrop(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /setdrop PERCENT\nExample: /setdrop 10"
    v = _validate_positive_float(args[0], "Percent")
    cfg = load_config()
    cfg["alert_on_price_drop_percent"] = v
    apply_config(cfg, f"set drop alert {v:.0f}%")
    return f"✅ Price drop alert set to ≥{v:.0f}% (all routes)"


def cmd_seturgency(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /seturgency DAYS\nExample: /seturgency 14"
    v = _validate_positive_int(args[0], "Days")
    cfg = load_config()
    cfg["deadline_urgency_days"] = v
    apply_config(cfg, f"set urgency {v}d")
    return f"✅ Deadline urgency set to {v} days before departure (all routes)"


def cmd_setstreak(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /setstreak DAYS\nExample: /setstreak 3"
    v = _validate_positive_int(args[0], "Days")
    cfg = load_config()
    cfg["price_rise_streak_days"] = v
    apply_config(cfg, f"set streak {v}d")
    return f"✅ Rising price streak alert set to {v} consecutive days (all routes)"


def cmd_setexchange(args: list[str]) -> str:
    if len(args) != 1:
        return "Usage: /setexchange RATE\nExample: /setexchange 26300"
    v = _validate_positive_int(args[0], "Exchange rate")
    cfg = load_config()
    cfg["usd_to_vnd"] = v
    apply_config(cfg, f"set exchange rate {v}")
    return f"✅ Exchange rate set to 1 USD = {v:,} VND (all routes)"


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

    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    args = parts[1:]

    try:
        if cmd == "/help":
            send(cmd_help())
        elif cmd == "/config":
            send(cmd_config())
        elif cmd == "/listroutes":
            send(cmd_listroutes())
        elif cmd == "/addroute":
            send(cmd_addroute(args))
        elif cmd == "/delroute":
            send(cmd_delroute(args))
        elif cmd == "/setactive":
            send(cmd_setactive(args))
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
