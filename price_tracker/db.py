import sqlite3
import os
from datetime import date

DB_PATH = os.path.join(os.path.dirname(__file__), "prices.db")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                date        TEXT PRIMARY KEY,
                flight_usd  REAL,
                airline     TEXT,
                stops       INTEGER,
                duration_min INTEGER,
                flight_url  TEXT,
                hotel_usd   REAL,
                hotel_name  TEXT,
                hotel_stars REAL,
                hotel_url   TEXT
            )
        """)


def save_price(record: dict):
    init_db()
    with _connect() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO prices
                (date, flight_usd, airline, stops, duration_min, flight_url,
                 hotel_usd, hotel_name, hotel_stars, hotel_url)
            VALUES
                (:date, :flight_usd, :airline, :stops, :duration_min, :flight_url,
                 :hotel_usd, :hotel_name, :hotel_stars, :hotel_url)
        """, {**record, "date": record.get("date", str(date.today()))})


def get_last_price() -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM prices ORDER BY date DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def get_history(days: int = 7) -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM prices ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def get_all_time_low_flight() -> float | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT MIN(flight_usd) as min_price FROM prices WHERE flight_usd IS NOT NULL"
        ).fetchone()
        return row["min_price"] if row else None


def get_all_time_low_hotel() -> float | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT MIN(hotel_usd) as min_price FROM prices WHERE hotel_usd IS NOT NULL"
        ).fetchone()
        return row["min_price"] if row else None
