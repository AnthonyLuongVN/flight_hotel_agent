import html
import os
import requests
from datetime import datetime


def send_telegram(message: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })
    if not resp.ok:
        print(f"[Telegram error] {resp.status_code}: {resp.text}")
    resp.raise_for_status()


# ── Helpers ────────────────────────────────────────────────────────────────

def _fmt_vnd(usd: float, rate: int) -> str:
    vnd = int(usd * rate)
    return f"{vnd:,}".replace(",", ".")


def _fmt_date(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d, %Y")


def _nights(dep: str, ret: str) -> int:
    return (datetime.strptime(ret, "%Y-%m-%d") - datetime.strptime(dep, "%Y-%m-%d")).days


def _trunc(s: str, n: int) -> str:
    """Truncate string to n chars, padding with spaces to exactly n."""
    s = s[:n]
    return s.ljust(n)


def _build_flight_url(config: dict) -> str:
    o, d = config["origin"], config["destination"]
    dep, ret = config["departure_date"], config["return_date"]
    return f"https://www.google.com/travel/flights#flt={o}.{d}.{dep}*{d}.{o}.{ret};c:USD;e:1;sd:1;t:f"


def _build_hotel_url(config: dict) -> str:
    loc = requests.utils.quote(config["hotel_location"])
    checkin, checkout = config["departure_date"], config["return_date"]
    adults = config["travelers"]
    stars = config.get("hotel_min_stars", 3)
    return (
        f"https://www.booking.com/searchresults.html"
        f"?ss={loc}&amp;checkin={checkin}&amp;checkout={checkout}"
        f"&amp;group_adults={adults}&amp;no_rooms=1&amp;nflt=class%3D{stars}"
    )


# ── Section builders ───────────────────────────────────────────────────────

def build_flight_section(flights: list[dict], config: dict) -> str:
    if not flights:
        return "✈️ <b>FLIGHTS</b>\n<i>No flight data available today.</i>"

    threshold = config["flight_alert_threshold_usd"]
    rate = config["usd_to_vnd"]

    lines = [f"✈️ <b>FLIGHTS</b> ({config['travelers']} adults, round trip)"]

    # Narrow table: Dep(5) Arr(5) Airline(13) Price — ~33 chars total, fits Telegram mobile
    # VND shown as note below; ASCII * replaces emoji checkmark (emoji = double-width)
    sep = "-" * 34
    header = f"{'Dep':<5} {'Arr':<5} {'Airline':<13} {'$/pp'}"
    rows = [header, sep]

    for f in flights:
        airline_col = _trunc(f"{f['airline']} {f.get('flight_number', '')}".strip(), 13)
        budget_mark = "*" if f["flight_usd"] <= threshold else " "
        price_col = f"${f['flight_usd']:.0f}{budget_mark}"
        dep = f.get("depart_time", "--:--")
        arr = f.get("arrive_time", "--:--")
        rows.append(f"{dep:<5} {arr:<5} {airline_col} {price_col}")

    lines.append(f"<code>{chr(10).join(rows)}</code>")
    lines.append(f"Rate: {rate:,} VND/USD  (* = under budget)")
    lines.append(f'<a href="{_build_flight_url(config)}">Search on Google Flights</a>')
    return "\n".join(lines)


def build_hotel_section(hotels: list[dict], config: dict) -> str:
    if not hotels:
        return "🏨 <b>HOTELS</b>\n<i>No hotel data available today.</i>"

    threshold = config["hotel_alert_per_night_usd"]
    rate = config["usd_to_vnd"]
    nights = _nights(config["departure_date"], config["return_date"])

    lines = [f"🏨 <b>HOTELS</b> (Seoul, {nights} nights, {config.get('hotel_min_stars',3)}+ stars)"]

    # Narrow table: Hotel(20) Rating(4) Price — ~33 chars total, fits Telegram mobile
    # VND shown as note below; ASCII * replaces emoji; plain "Rt" not star emoji in header
    sep = "-" * 33
    header = f"{'Hotel':<20} {'Rt':>4} {'$/night'}"
    rows = [header, sep]

    for h in hotels:
        name_col = _trunc(h["hotel_name"], 20)
        stars_col = f"{h['hotel_stars']:.1f}" if h.get("hotel_stars") else "N/A"
        budget_mark = "*" if h["hotel_usd"] <= threshold else " "
        price_col = f"${h['hotel_usd']:.0f}{budget_mark}"
        rows.append(f"{name_col} {stars_col:>4} {price_col}")

    lines.append(f"<code>{chr(10).join(rows)}</code>")
    lines.append(f"Rate: {rate:,} VND/USD  (* = under budget)")
    lines.append(f'<a href="{_build_hotel_url(config)}">Search on Booking.com</a>')
    return "\n".join(lines)


def build_history_table(history: list[dict]) -> str:
    if len(history) < 2:
        return ""
    header = f"{'Date':<10} {'Flight':>7} {'Hotel/night':>11}"
    sep = f"{'─'*10}-{'─'*7}-{'─'*11}"
    rows = [header, sep]
    for r in history:
        flight_str = f"${r['flight_usd']:.0f}" if r.get("flight_usd") else "N/A"
        hotel_str = f"${r['hotel_usd']:.0f}" if r.get("hotel_usd") else "N/A"
        rows.append(f"{r['date']:<10} {flight_str:>7} {hotel_str:>11}")
    return "📊 <b>Price history (last 7 days)</b>\n<code>" + "\n".join(rows) + "</code>"


def build_trigger_banner(triggers: list[str]) -> str:
    if not triggers:
        return ""
    return "🚨 <b>ALERTS TRIGGERED</b>\n" + "\n".join(f"• {html.escape(t)}" for t in triggers)


def build_message(
    flights: list[dict],
    hotels: list[dict],
    history: list[dict],
    triggers: list[str],
    config: dict,
    check_date: str,
) -> str:
    dep_fmt = _fmt_date(config["departure_date"])
    ret_fmt = _fmt_date(config["return_date"])
    nights = _nights(config["departure_date"], config["return_date"])

    sections = [
        f'✈️ <b>Korea Trip Tracker</b> — {check_date}',
        "",
        f'📅 <b>{config["origin"]} → {config["destination"]} | {dep_fmt} – {ret_fmt}</b> ({nights} nights)',
        "",
        build_flight_section(flights, config),
        "",
        build_hotel_section(hotels, config),
    ]

    table = build_history_table(history)
    if table:
        sections += ["", table]

    if triggers:
        sections += ["", build_trigger_banner(triggers)]

    return "\n".join(sections)
