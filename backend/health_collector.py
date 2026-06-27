# health_collector.py
#
# Fetches yesterday's activity and sleep data for Arthur and King from the Tractive API
# and stores it in tractive_health_daily, tractive_hourly_activity, tractive_sleep_phases.
# Run daily via health_collector.timer at 06:00.

import asyncio
import datetime
import sqlite3
import traceback

import aiohttp
from aiotractive import Tractive

from config import TRACTIVE_EMAIL, TRACTIVE_PASSWORD, DATABASE_FILE

GRAPH_BASE  = "https://graph.tractive.com/4"
CLIENT_ID   = "625e533dc3c3b41c28a669f0"

# Tractive pet IDs (not tracker IDs — these are the pet/animal object IDs)
CATS = {
    'Arthur': '636e91bd34bfae0d74840184',
    'King':   '634d543fcb865d8f66cc5efe',
}


def get_internal_cat_id(conn, cat_name):
    c = conn.cursor()
    c.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    row = c.fetchone()
    return row['internal_cat_id'] if row else None


async def fetch_day(session, pet_id, endpoint, day, month, year, headers):
    url = f"{GRAPH_BASE}/pet/{pet_id}/{endpoint}"
    params = {'local_day': day, 'local_month': month, 'local_year': year}
    async with session.get(url, params=params, headers=headers) as resp:
        if resp.status == 200:
            return await resp.json()
        print(f"  Warning: {endpoint} returned {resp.status} for {year}-{month:02d}-{day:02d}")
        return None


def upsert_day(conn, internal_cat_id, date_str, activity, sleep):
    c = conn.cursor()

    # Parse activity
    active_minutes = None
    resting_hours  = None
    calories       = None
    hourly_dist    = []

    if activity:
        active_minutes = activity.get('progress', {}).get('achieved_minutes')
        hourly_dist    = activity.get('hourly_distribution', [])
        dist_list = activity.get('activity_distribution', [])
        if isinstance(dist_list, list):
            dist_map = {item.get('type'): item for item in dist_list if isinstance(item, dict)}
        else:
            dist_map = dist_list if isinstance(dist_list, dict) else {}
        resting_hours = dist_map.get('resting', {}).get('current')   # already in hours
        calories      = dist_map.get('calories', {}).get('current')

    # Parse sleep
    min_day_sleep   = None
    min_night_sleep = None
    min_calm        = None
    phases          = []

    if sleep:
        ov = sleep.get('overview', {})
        min_day_sleep   = ov.get('minutes_day_sleep')
        min_night_sleep = ov.get('minutes_night_sleep')
        min_calm        = ov.get('minutes_calm')
        phases = sleep.get('sleep_phases', {}).get('phases', [])

    # Skip days with no data at all
    if (active_minutes == 0 or active_minutes is None) and (calories == 0 or calories is None):
        print(f"  Skipping {date_str}: zero active_minutes and zero calories")
        return False

    # Upsert: delete then reinsert
    c.execute("DELETE FROM tractive_health_daily WHERE internal_cat_id=? AND date=?",
              (internal_cat_id, date_str))
    c.execute("""
        INSERT INTO tractive_health_daily
            (internal_cat_id, date, active_minutes, resting_hours, calories,
             minutes_day_sleep, minutes_night_sleep, minutes_calm)
        VALUES (?,?,?,?,?,?,?,?)
    """, (internal_cat_id, date_str, active_minutes, resting_hours, calories,
          min_day_sleep, min_night_sleep, min_calm))

    c.execute("DELETE FROM tractive_hourly_activity WHERE internal_cat_id=? AND date=?",
              (internal_cat_id, date_str))
    for hour, mins in enumerate(hourly_dist[:24]):
        c.execute("""
            INSERT INTO tractive_hourly_activity (internal_cat_id, date, hour, active_minutes)
            VALUES (?,?,?,?)
        """, (internal_cat_id, date_str, hour, mins))

    c.execute("DELETE FROM tractive_sleep_phases WHERE internal_cat_id=? AND date=?",
              (internal_cat_id, date_str))
    for phase in phases:
        c.execute("""
            INSERT INTO tractive_sleep_phases
                (internal_cat_id, date, time_offset, time_span, type)
            VALUES (?,?,?,?,?)
        """, (internal_cat_id, date_str, phase.get('time_offset'), phase.get('time_span'), phase.get('type')))

    conn.commit()
    return True


async def collect():
    yesterday  = datetime.date.today() - datetime.timedelta(days=1)
    date_str   = yesterday.isoformat()
    day, month, year = yesterday.day, yesterday.month, yesterday.year

    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row

    print(f"Health collector: fetching {date_str}")

    try:
        async with Tractive(TRACTIVE_EMAIL, TRACTIVE_PASSWORD) as client:
            await client.authenticate()
            auth_headers = await client._api.auth_headers()
            auth_headers['x-tractive-client'] = CLIENT_ID

            async with aiohttp.ClientSession() as session:
                for cat_name, pet_id in CATS.items():
                    internal_cat_id = get_internal_cat_id(conn, cat_name)
                    if internal_cat_id is None:
                        print(f"  Warning: {cat_name} not found in cat_identities, skipping")
                        continue

                    try:
                        activity = await fetch_day(session, pet_id, 'activity/day_overview',
                                                   day, month, year, auth_headers)
                        sleep = await fetch_day(session, pet_id, 'sleep/day_overview',
                                                day, month, year, auth_headers)
                        stored = upsert_day(conn, internal_cat_id, date_str, activity, sleep)
                        if stored:
                            print(f"  {cat_name}: stored {date_str} OK")
                    except Exception:
                        print(f"  Error processing {cat_name}:")
                        traceback.print_exc()
    finally:
        conn.close()

    print("Health collector: done")


if __name__ == "__main__":
    asyncio.run(collect())
