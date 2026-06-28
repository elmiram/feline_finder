"""
Fetches yesterday's weather from Open-Meteo and upserts into weather_daily.
Runs daily via systemd timer (weather_collector.timer).
Coordinates are loaded from config.py (LAT, LON) to avoid leaking location to git.
"""
import requests
import sqlite3
from datetime import date, timedelta
from pathlib import Path

try:
    from config import LAT, LON
except ImportError:
    raise SystemExit(
        "config.py must define LAT and LON (location coordinates). "
        "Add them to config.py on the Pi — they are not committed to git."
    )

DB_PATH = Path.home() / "projects/feline_finder/backend/cat_tracker.db"


def fetch_and_store():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={LAT}&longitude={LON}"
        f"&start_date={yesterday}&end_date={yesterday}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
        f"snowfall_sum,weathercode,sunrise,sunset"
        f"&timezone=Europe%2FZurich"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()["daily"]
    row = (
        data["time"][0],
        data["temperature_2m_max"][0],
        data["temperature_2m_min"][0],
        data["precipitation_sum"][0],
        data["snowfall_sum"][0],
        data["weathercode"][0],
        data["sunrise"][0],
        data["sunset"][0],
    )
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "INSERT OR REPLACE INTO weather_daily "
        "(date, temp_max, temp_min, precipitation, snowfall, weathercode, sunrise, sunset) "
        "VALUES (?,?,?,?,?,?,?,?)",
        row,
    )
    conn.commit()
    conn.close()
    print(f"Stored weather for {row[0]}: max={row[1]}°C, precip={row[3]}mm")


if __name__ == "__main__":
    fetch_and_store()
