import json
import os
import sys
from datetime import date, datetime

import requests
from dotenv import load_dotenv

load_dotenv()

import db
import alert

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _parse_flight(f: dict, travelers: int) -> dict:
    legs = f.get("flights", [{}])
    per_person = f.get("price", 0) / travelers if travelers > 0 else f.get("price", 0)

    depart_time = legs[0].get("departure_airport", {}).get("time", "")
    arrive_time = legs[-1].get("arrival_airport", {}).get("time", "")
    depart_time = depart_time.split(" ")[-1] if depart_time else ""
    arrive_time = arrive_time.split(" ")[-1] if arrive_time else ""

    layover_info = ""
    if f.get("layovers"):
        lv = f["layovers"][0]
        dur = lv.get("duration", 0)
        layover_info = f"{lv.get('name', '')} ({dur // 60}h {dur % 60}m)"

    return {
        "flight_usd": round(per_person, 2),
        "airline": legs[0].get("airline", "Unknown"),
        "flight_number": legs[0].get("flight_number", ""),
        "stops": len(legs) - 1,
        "duration_min": f.get("total_duration", 0),
        "depart_time": depart_time,
        "arrive_time": arrive_time,
        "airplane": legs[0].get("airplane", ""),
        "layover_info": layover_info,
        "flight_url": "https://www.google.com/travel/flights",
    }


def fetch_flights(config: dict, top_n: int = 3) -> list[dict]:
    params = {
        "engine": "google_flights",
        "departure_id": config["origin"],
        "arrival_id": config["destination"],
        "outbound_date": config["departure_date"],
        "return_date": config["return_date"],
        "adults": config["travelers"],
        "currency": config["currency"],
        "hl": "en",
        "api_key": os.environ["SERPAPI_KEY"],
    }
    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[ERROR] Flight fetch failed: {e}", file=sys.stderr)
        return []

    flights = data.get("best_flights", []) + data.get("other_flights", [])
    if not flights:
        print("[WARN] No flights returned from SerpAPI", file=sys.stderr)
        return []

    sorted_flights = sorted(flights, key=lambda f: f.get("price", 9_999_999))
    return [_parse_flight(f, config["travelers"]) for f in sorted_flights[:top_n]]


def _parse_hotel(h: dict) -> dict | None:
    rate = h.get("rate_per_night", {})
    raw = rate.get("lowest", rate.get("extracted_lowest", None))
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.replace("$", "").replace(",", "").strip()
        try:
            raw = float(raw)
        except ValueError:
            return None
    price = float(raw)
    if price >= 9_999_999:
        return None
    return {
        "hotel_usd": round(price, 2),
        "hotel_name": h.get("name", "Unknown"),
        "hotel_stars": h.get("overall_rating", 0),
        "hotel_url": h.get("link", ""),
    }


def fetch_hotels(config: dict, top_n: int = 3) -> list[dict]:
    params = {
        "engine": "google_hotels",
        "q": f"hotels in {config['hotel_location']}",
        "check_in_date": config["departure_date"],
        "check_out_date": config["return_date"],
        "adults": config["travelers"],
        "currency": config["currency"],
        "hl": "en",
        "api_key": os.environ["SERPAPI_KEY"],
    }
    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[ERROR] Hotel fetch failed: {e}", file=sys.stderr)
        return []

    properties = data.get("properties", [])
    if not properties:
        print("[WARN] No hotels returned from SerpAPI", file=sys.stderr)
        return []

    min_stars = config.get("hotel_min_stars", 3)
    filtered = [h for h in properties if h.get("overall_rating", 0) >= min_stars] or properties
    parsed = [_parse_hotel(h) for h in filtered]
    parsed = [h for h in parsed if h is not None]
    parsed.sort(key=lambda h: h["hotel_usd"])
    return parsed[:top_n]


def evaluate_triggers(
    flight: dict | None,
    hotel: dict | None,
    prev: dict | None,
    history: list[dict],
    config: dict,
) -> list[str]:
    triggers = []

    # --- Trigger 1: Under budget ---
    if flight and flight["flight_usd"] <= config["flight_alert_threshold_usd"]:
        triggers.append(
            f"Flight under budget: ${flight['flight_usd']:.0f}/person "
            f"(<= ${config['flight_alert_threshold_usd']} limit)"
        )
    if hotel and hotel["hotel_usd"] <= config["hotel_alert_per_night_usd"]:
        triggers.append(
            f"Hotel under budget: ${hotel['hotel_usd']:.0f}/night "
            f"(<= ${config['hotel_alert_per_night_usd']} limit)"
        )

    # --- Trigger 2: Sudden drop vs yesterday ---
    drop_pct = config.get("alert_on_price_drop_percent", 10)
    if flight and prev and prev.get("flight_usd"):
        change = (flight["flight_usd"] - prev["flight_usd"]) / prev["flight_usd"] * 100
        if change <= -drop_pct:
            triggers.append(
                f"Flight price dropped {abs(change):.1f}% vs yesterday "
                f"(${prev['flight_usd']:.0f} to ${flight['flight_usd']:.0f})"
            )
    if hotel and prev and prev.get("hotel_usd"):
        change = (hotel["hotel_usd"] - prev["hotel_usd"]) / prev["hotel_usd"] * 100
        if change <= -drop_pct:
            triggers.append(
                f"Hotel price dropped {abs(change):.1f}% vs yesterday "
                f"(${prev['hotel_usd']:.0f} to ${hotel['hotel_usd']:.0f})"
            )

    # --- Trigger 3: New all-time low ---
    atl_flight = db.get_all_time_low_flight()
    if flight and atl_flight and flight["flight_usd"] < atl_flight:
        triggers.append(f"New all-time low flight: ${flight['flight_usd']:.0f}/person!")
    atl_hotel = db.get_all_time_low_hotel()
    if hotel and atl_hotel and hotel["hotel_usd"] < atl_hotel:
        triggers.append(f"New all-time low hotel: ${hotel['hotel_usd']:.0f}/night!")

    # --- Trigger 4: Deadline urgency ---
    departure = datetime.strptime(config["departure_date"], "%Y-%m-%d").date()
    days_left = (departure - date.today()).days
    urgency_days = config.get("deadline_urgency_days", 14)
    if 0 < days_left <= urgency_days:
        triggers.append(f"Departure in {days_left} day(s) — book soon!")

    # --- Trigger 5: Rising price trend ---
    streak_days = config.get("price_rise_streak_days", 3)
    if len(history) >= streak_days:
        recent = history[-streak_days:]
        flight_prices = [r.get("flight_usd") for r in recent if r.get("flight_usd")]
        if len(flight_prices) == streak_days and all(
            flight_prices[i] < flight_prices[i + 1] for i in range(len(flight_prices) - 1)
        ):
            triggers.append(f"Flight prices rising {streak_days} days in a row — book soon!")
        hotel_prices = [r.get("hotel_usd") for r in recent if r.get("hotel_usd")]
        if len(hotel_prices) == streak_days and all(
            hotel_prices[i] < hotel_prices[i + 1] for i in range(len(hotel_prices) - 1)
        ):
            triggers.append(f"Hotel prices rising {streak_days} days in a row — book soon!")

    return triggers


def main():
    config = load_config()
    today = str(date.today())

    print(f"[{today}] Fetching flights...")
    flights = fetch_flights(config, top_n=3)
    print(f"  Got {len(flights)} flights")

    print(f"[{today}] Fetching hotels...")
    hotels = fetch_hotels(config, top_n=3)
    print(f"  Got {len(hotels)} hotels")

    cheapest_flight = flights[0] if flights else None
    cheapest_hotel = hotels[0] if hotels else None

    # Fetch history before saving (all-time-low check needs prior records)
    prev = db.get_last_price()
    history = db.get_history(days=7)

    # Evaluate triggers on cheapest options
    triggers = evaluate_triggers(cheapest_flight, cheapest_hotel, prev, history, config)

    # Save only the cheapest per day for history tracking
    record = {
        "date": today,
        "flight_usd": cheapest_flight["flight_usd"] if cheapest_flight else None,
        "airline": cheapest_flight["airline"] if cheapest_flight else None,
        "stops": cheapest_flight["stops"] if cheapest_flight else None,
        "duration_min": cheapest_flight["duration_min"] if cheapest_flight else None,
        "flight_url": cheapest_flight["flight_url"] if cheapest_flight else None,
        "depart_time": cheapest_flight["depart_time"] if cheapest_flight else None,
        "arrive_time": cheapest_flight["arrive_time"] if cheapest_flight else None,
        "flight_number": cheapest_flight["flight_number"] if cheapest_flight else None,
        "airplane": cheapest_flight["airplane"] if cheapest_flight else None,
        "layover_info": cheapest_flight["layover_info"] if cheapest_flight else None,
        "hotel_usd": cheapest_hotel["hotel_usd"] if cheapest_hotel else None,
        "hotel_name": cheapest_hotel["hotel_name"] if cheapest_hotel else None,
        "hotel_stars": cheapest_hotel["hotel_stars"] if cheapest_hotel else None,
        "hotel_url": cheapest_hotel["hotel_url"] if cheapest_hotel else None,
    }
    db.save_price(record)

    history = db.get_history(days=7)

    should_send = bool(triggers) or config.get("send_daily_summary", True)

    if should_send:
        message = alert.build_message(
            flights=flights,
            hotels=hotels,
            history=history,
            triggers=triggers,
            config=config,
            check_date=today,
        )
        print("\n--- Telegram message preview ---")
        print(message)
        print("--------------------------------\n")
        alert.send_telegram(message)
        print("[OK] Telegram message sent.")
    else:
        print("[INFO] No triggers fired and daily summary is off — no message sent.")


if __name__ == "__main__":
    main()
