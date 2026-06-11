import sqlite3
import os
from datetime import date

DB_PATH = os.path.join(os.path.dirname(__file__), "prices.db")

_COLUMNS = [
    ("flight_usd", "REAL"),
    ("airline", "TEXT"),
    ("stops", "INTEGER"),
    ("duration_min", "INTEGER"),
    ("flight_url", "TEXT"),
    ("depart_time", "TEXT"),
    ("arrive_time", "TEXT"),
    ("flight_number", "TEXT"),
    ("airplane", "TEXT"),
    ("layover_info", "TEXT"),
    ("hotel_usd", "REAL"),
    ("hotel_name", "TEXT"),
    ("hotel_stars", "REAL"),
    ("hotel_url", "TEXT"),
]

_COL_NAMES = [c for c, _ in _COLUMNS]


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _col_defs() -> str:
    return "\n".join(f"    {name}   {typ}," for name, typ in _COLUMNS)


def init_db():
    with _connect() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        if "prices" in tables:
            existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(prices)")}
            if "route_id" not in existing_cols:
                # Migrate old single-route schema to new (date, route_id) composite PK
                col_list = ", ".join(_COL_NAMES)
                conn.execute(f"""
                    CREATE TABLE prices_new (
                        route_id     TEXT NOT NULL,
                        date         TEXT NOT NULL,
                        {_col_defs()}
                        PRIMARY KEY (date, route_id)
                    )
                """)
                conn.execute(f"""
                    INSERT INTO prices_new (route_id, date, {col_list})
                    SELECT 'SGN-ICN', date, {col_list} FROM prices
                """)
                conn.execute("DROP TABLE prices")
                conn.execute("ALTER TABLE prices_new RENAME TO prices")
        else:
            conn.execute(f"""
                CREATE TABLE prices (
                    route_id     TEXT NOT NULL,
                    date         TEXT NOT NULL,
                    {_col_defs()}
                    PRIMARY KEY (date, route_id)
                )
            """)


def save_price(record: dict, route_id: str):
    init_db()
    col_list = ", ".join(_COL_NAMES)
    placeholders = ", ".join(f":{c}" for c in _COL_NAMES)
    with _connect() as conn:
        conn.execute(f"""
            INSERT OR REPLACE INTO prices
                (route_id, date, {col_list})
            VALUES
                (:route_id, :date, {placeholders})
        """, {**record, "route_id": route_id, "date": record.get("date", str(date.today()))})


def get_last_price(route_id: str) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM prices WHERE route_id = ? ORDER BY date DESC LIMIT 1",
            (route_id,),
        ).fetchone()
        return dict(row) if row else None


def get_history(route_id: str, days: int = 7) -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM prices WHERE route_id = ? ORDER BY date DESC LIMIT ?",
            (route_id, days),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def get_all_time_low_flight(route_id: str) -> float | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT MIN(flight_usd) as min_price FROM prices WHERE route_id = ? AND flight_usd IS NOT NULL",
            (route_id,),
        ).fetchone()
        return row["min_price"] if row else None


def get_all_time_low_hotel(route_id: str) -> float | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT MIN(hotel_usd) as min_price FROM prices WHERE route_id = ? AND hotel_usd IS NOT NULL",
            (route_id,),
        ).fetchone()
        return row["min_price"] if row else None


def delete_route_history(route_id: str):
    init_db()
    with _connect() as conn:
        conn.execute("DELETE FROM prices WHERE route_id = ?", (route_id,))
