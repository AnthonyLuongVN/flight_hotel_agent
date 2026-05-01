import json
import os
import sys
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

import db
import alert

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def fetch_flight_price(config: dict) -> dict | None:
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
        return None

    flights = data.get("best_flights", []) + data.get("other_flights", [])
    if not flights:
        print("[WARN] No flights returned from SerpAPI", file=sys.stderr)
        return None

    cheapest = min(flights, key=lambda f: f.get("price", 9_999_999))
    legs = cheapest.get("flights", [{}])
    total_price = cheapest.get("price", 0)
    per_person = total_price / config["travelers"] if config["travelers"] > 0 else total_price

    return {
        "flight_usd": round(per_person, 2),
        "airline": legs[0].get("airline", "Unknown"),
        "stops": len(legs) - 1,
        "duration_min": cheapest.get("total_duration", 0),
        "flight_url": "https://www.google.com/travel/flights",
    }


def fetch_hotel_price(config: dict) -> dict | None:
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
        return None

    properties = data.get("properties", [])
    if not properties:
        print("[WARN] No hotels returned from SerpAPI", file=sys.stderr)
        return None

    def get_price(h):
        rate = h.get("rate_per_night", {})
        # SerpAPI may return a string like "$95" or a numeric field
        raw = rate.get("lowest", rate.get("extracted_lowest", None))
        if raw is None:
            return 9_999_999
        if isinstance(raw, str):
            raw = raw.replace("$", "").replace(",", "").strip()
            try:
                return float(raw)
            except ValueError:
                return 9_999_999
        return float(raw)

    # Filter by minimum star rating in code (SerpAPI doesn't support rating filter)
    min_stars = config.get("hotel_min_stars", 3)
    filtered = [h for h in properties if h.get("overall_rating", 0) >= min_stars]
    if not filtered:
        filtered = properties  # fall back to all results if none match

    cheapest = min(filtered, key=get_price)
    price = get_price(cheapest)
    if price >= 9_999_999:
        return None

    return {
        "hotel_usd": round(price, 2),
        "hotel_name": cheapest.get("name", "Unknown"),
        "hotel_stars": cheapest.get("overall_rating", 0),
        "hotel_url": cheapest.get("link", ""),
    }


def evaluate_triggers(
    flight: dict | None,
    hotel: dict | None,
    prev: dict | None,
    history: list[dict],
    config: dict,
) -> list[str]:
    triggers = []
    today_str = str(date.today())

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
                f"(${prev['flight_usd']:.0f} → ${flight['flight_usd']:.0f})"
            )
    if hotel and prev and prev.get("hotel_usd"):
        change = (hotel["hotel_usd"] - prev["hotel_usd"]) / prev["hotel_usd"] * 100
        if change <= -drop_pct:
            triggers.append(
                f"Hotel price dropped {abs(change):.1f}% vs yesterday "
                f"(${prev['hotel_usd']:.0f} → ${hotel['hotel_usd']:.0f})"
            )

    # --- Trigger 3: New all-time low ---
    atl_flight = db.get_all_time_low_flight()
    if flight and atl_flight and flight["flight_usd"] < atl_flight:
        triggers.append(
            f"New all-time low flight price: ${flight['flight_usd']:.0f}/person!"
        )
    atl_hotel = db.get_all_time_low_hotel()
    if hotel and atl_hotel and hotel["hotel_usd"] < atl_hotel:
        triggers.append(
            f"New all-time low hotel price: ${hotel['hotel_usd']:.0f}/night!"
        )

    # --- Trigger 4: Deadline urgency ---
    departure = datetime.strptime(config["departure_date"], "%Y-%m-%d").date()
    days_left = (departure - date.today()).days
    urgency_days = config.get("deadline_urgency_days", 14)
    if 0 < days_left <= urgency_days:
        triggers.append(
            f"Departure in {days_left} day(s) — book soon!"
        )

    # --- Trigger 5: Rising price trend ---
    streak_days = config.get("price_rise_streak_days", 3)
    if len(history) >= streak_days:
        recent = history[-streak_days:]
        flight_prices = [r.get("flight_usd") for r in recent if r.get("flight_usd")]
        if len(flight_prices) == streak_days and all(
            flight_prices[i] < flight_prices[i + 1]
            for i in range(len(flight_prices) - 1)
        ):
            triggers.append(
                f"Flight prices have risen {streak_days} days in a row — "
                f"consider booking soon!"
            )
        hotel_prices = [r.get("hotel_usd") for r in recent if r.get("hotel_usd")]
        if len(hotel_prices) == streak_days and all(
            hotel_prices[i] < hotel_prices[i + 1]
            for i in range(len(hotel_prices) - 1)
        ):
            triggers.append(
                f"Hotel prices have risen {streak_days} days in a row — "
                f"consider booking soon!"
            )

    return triggers


def main():
    config = load_config()
    today = str(date.today())

    print(f"[{today}] Fetching flight prices...")
    flight = fetch_flight_price(config)
    print(f"  Flight: {flight}")

    print(f"[{today}] Fetching hotel prices...")
    hotel = fetch_hotel_price(config)
    print(f"  Hotel: {hotel}")

    # Fetch history before saving today (so all-time-low check is accurate)
    prev = db.get_last_price()
    history = db.get_history(days=7)

    # Evaluate triggers before saving (all-time-low needs the old records)
    triggers = evaluate_triggers(flight, hotel, prev, history, config)

    # Save today's record
    record = {
        "date": today,
        "flight_usd": flight["flight_usd"] if flight else None,
        "airline": flight["airline"] if flight else None,
        "stops": flight["stops"] if flight else None,
        "duration_min": flight["duration_min"] if flight else None,
        "flight_url": flight["flight_url"] if flight else None,
        "hotel_usd": hotel["hotel_usd"] if hotel else None,
        "hotel_name": hotel["hotel_name"] if hotel else None,
        "hotel_stars": hotel["hotel_stars"] if hotel else None,
        "hotel_url": hotel["hotel_url"] if hotel else None,
    }
    db.save_price(record)

    # Refresh history after save for the table display
    history = db.get_history(days=7)

    # Decide whether to send a message
    should_send = bool(triggers) or config.get("send_daily_summary", True)

    if should_send:
        message = alert.build_message(
            flight=flight,
            hotel=hotel,
            prev=prev,
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
