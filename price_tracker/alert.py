import os
import requests


def send_telegram(message: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })
    resp.raise_for_status()


def _fmt_vnd(usd: float, rate: int) -> str:
    vnd = int(usd * rate)
    # Vietnamese number format: dots as thousands separator
    return f"{vnd:,}".replace(",", ".") + " VND"


def _change_arrow(current: float, previous: float) -> str:
    if previous is None or previous == 0:
        return ""
    diff = current - previous
    pct = (diff / previous) * 100
    symbol = "📉" if diff < 0 else "📈"
    sign = "+" if diff > 0 else ""
    return f"{symbol} {sign}${diff:.0f} ({sign}{pct:.1f}%) vs yesterday"


def _threshold_line(label: str, value: float, threshold: float, vnd_rate: int, unit: str = "person") -> str:
    vnd_val = _fmt_vnd(value, vnd_rate)
    vnd_thresh = _fmt_vnd(threshold, vnd_rate)
    if value <= threshold:
        status = f"Under budget (limit ${threshold:.0f} / ~{vnd_thresh}) ✅"
    else:
        over = value - threshold
        status = f"Over budget by ${over:.0f} (limit ${threshold:.0f} / ~{vnd_thresh}) ❌"
    return f"💰 {label}: ${value:.0f}/{unit} (~{vnd_val}) — {status}"


def build_flight_section(flight: dict, prev_flight: dict | None, config: dict) -> str:
    if not flight:
        return "*FLIGHTS*\n_No flight data available today._"

    rate = config["usd_to_vnd"]
    stops_str = "non-stop" if flight["stops"] == 0 else f"{flight['stops']} stop(s)"
    dur_h = flight["duration_min"] // 60
    dur_m = flight["duration_min"] % 60
    duration_str = f"{dur_h}h {dur_m}m" if flight["duration_min"] else ""

    prev_price = prev_flight["flight_usd"] if prev_flight else None
    change = _change_arrow(flight["flight_usd"], prev_price) if prev_price else ""

    lines = [
        f"*FLIGHTS* (SGN → ICN, {config['travelers']} adults, round trip)",
        f"{flight['airline']} | {stops_str}" + (f" | {duration_str}" if duration_str else ""),
        _threshold_line("Per person", flight["flight_usd"], config["flight_alert_threshold_usd"], rate),
    ]
    if change:
        lines.append(change)
    if flight.get("flight_url"):
        lines.append(f"[Search flights]({flight['flight_url']})")
    return "\n".join(lines)


def build_hotel_section(hotel: dict, prev_hotel: dict | None, config: dict) -> str:
    if not hotel:
        return "*HOTELS*\n_No hotel data available today._"

    rate = config["usd_to_vnd"]
    stars = f"⭐{hotel['hotel_stars']:.1f}" if hotel.get("hotel_stars") else ""
    prev_price = prev_hotel["hotel_usd"] if prev_hotel else None
    change = _change_arrow(hotel["hotel_usd"], prev_price) if prev_price else ""

    lines = [
        f"*HOTELS* (Seoul, per night) {stars}",
        f"{hotel['hotel_name']}",
        _threshold_line("Per night", hotel["hotel_usd"], config["hotel_alert_per_night_usd"], rate, unit="night"),
    ]
    if change:
        lines.append(change)
    if hotel.get("hotel_url"):
        lines.append(f"[View hotel]({hotel['hotel_url']})")
    return "\n".join(lines)


def build_history_table(history: list[dict]) -> str:
    if len(history) < 2:
        return ""
    header = "📊 *Price history (last 7 days)*"
    rows = ["Date         | Flight  | Hotel/night"]
    rows.append("-------------|---------|------------")
    for r in history:
        flight_str = f"${r['flight_usd']:.0f}" if r.get("flight_usd") else "N/A"
        hotel_str = f"${r['hotel_usd']:.0f}" if r.get("hotel_usd") else "N/A"
        rows.append(f"{r['date']} | {flight_str:<7} | {hotel_str}")
    return header + "\n```\n" + "\n".join(rows) + "\n```"


def build_trigger_banner(triggers: list[str]) -> str:
    if not triggers:
        return ""
    return "🚨 *ALERTS TRIGGERED*\n" + "\n".join(f"• {t}" for t in triggers)


def build_message(
    flight: dict | None,
    hotel: dict | None,
    prev: dict | None,
    history: list[dict],
    triggers: list[str],
    config: dict,
    check_date: str,
) -> str:
    sections = [
        f"✈️ *Korea Trip Tracker* — {check_date}",
        "",
        build_flight_section(flight, prev, config),
        "",
        build_hotel_section(hotel, prev, config),
    ]

    if history:
        table = build_history_table(history)
        if table:
            sections += ["", table]

    if triggers:
        sections += ["", build_trigger_banner(triggers)]

    return "\n".join(sections)
