"""
Backfill historical weather data from Open-Meteo archive API into weather_daily.
Fetches from 2024-03-01 to today. Safe to re-run (INSERT OR IGNORE).
Coordinates are loaded from config.py (LAT, LON) to avoid leaking location to git.
"""
import requests
import sqlite3
from datetime import date
from pathlib import Path

try:
    from config import LAT, LON
except ImportError:
    raise SystemExit(
        "config.py must define LAT and LON (location coordinates). "
        "Add them to config.py on the Pi — they are not committed to git."
    )

DB_PATH = Path.home() / "projects/feline_finder/backend/cat_tracker.db"
START_DATE = "2024-03-01"


def fetch_weather(start_date: str, end_date: str) -> dict:
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={LAT}&longitude={LON}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
        f"snowfall_sum,weathercode,sunrise,sunset"
        f"&timezone=Europe%2FZurich"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()["daily"]


def main():
    today = date.today().isoformat()
    print(f"Fetching weather from {START_DATE} to {today}...")

    data = fetch_weather(START_DATE, today)

    dates = data["time"]
    temp_max = data["temperature_2m_max"]
    temp_min = data["temperature_2m_min"]
    precipitation = data["precipitation_sum"]
    snowfall = data["snowfall_sum"]
    weathercode = data["weathercode"]
    sunrise = data["sunrise"]
    sunset = data["sunset"]

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    inserted = 0
    skipped = 0
    batch = []

    for i, d in enumerate(dates):
        row = (
            d,
            temp_max[i],
            temp_min[i],
            precipitation[i],
            snowfall[i],
            weathercode[i],
            sunrise[i],
            sunset[i],
        )
        batch.append(row)

        if len(batch) >= 100:
            cur = conn.executemany(
                "INSERT OR IGNORE INTO weather_daily "
                "(date, temp_max, temp_min, precipitation, snowfall, weathercode, sunrise, sunset) "
                "VALUES (?,?,?,?,?,?,?,?)",
                batch,
            )
            inserted += cur.rowcount
            skipped += len(batch) - cur.rowcount
            conn.commit()
            batch = []

    if batch:
        cur = conn.executemany(
            "INSERT OR IGNORE INTO weather_daily "
            "(date, temp_max, temp_min, precipitation, snowfall, weathercode, sunrise, sunset) "
            "VALUES (?,?,?,?,?,?,?,?)",
            batch,
        )
        inserted += cur.rowcount
        skipped += len(batch) - cur.rowcount
        conn.commit()

    conn.close()
    print(f"Done. Inserted {inserted} rows, skipped {skipped} existing.")


if __name__ == "__main__":
    main()
