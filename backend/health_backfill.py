# health_backfill.py
#
# Fetches full health & sleep history for Arthur and King from Tractive,
# starting from 2024-03-01 to today. Stores in tractive_health_daily,
# tractive_hourly_activity, and tractive_sleep_phases.
#
# Resumable: skips dates already in tractive_health_daily.
# Resilient: exponential backoff (min(2^attempt * 2, 120)s) per date; never aborts on one error.
# Zero rows are NOT stored but do NOT stop the scan.
#
# Run on Pi:
#   nohup /home/elya/elya-env/bin/python3 /tmp/health_backfill.py > /tmp/backfill_health.log 2>&1 &

import asyncio
import datetime
import os
import sqlite3
import sys
import traceback

import aiohttp
from aiotractive import Tractive
from aiotractive.exceptions import TractiveError

# Allow running from /tmp
BACKEND_DIR = '/home/elya/projects/feline_finder/backend'
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

from config import TRACTIVE_EMAIL, TRACTIVE_PASSWORD, DATABASE_FILE

GRAPH_BASE = "https://graph.tractive.com/4"
CLIENT_ID  = "625e533dc3c3b41c28a669f0"

CATS = {
    'Arthur': {'pet_id': '636e91bd34bfae0d74840184'},
    'King':   {'pet_id': '634d543fcb865d8f66cc5efe'},
}

BACKFILL_START = datetime.date(2024, 3, 1)
MAX_RETRIES    = 5


def log(msg):
    ts = datetime.datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


def get_conn():
    conn = sqlite3.connect(DATABASE_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def get_internal_cat_id(conn, cat_name):
    c = conn.cursor()
    c.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name=?", (cat_name,))
    row = c.fetchone()
    return row['internal_cat_id'] if row else None


def date_already_stored(conn, internal_cat_id, date_str):
    c = conn.cursor()
    c.execute("SELECT 1 FROM tractive_health_daily WHERE internal_cat_id=? AND date=?",
              (internal_cat_id, date_str))
    return c.fetchone() is not None


async def fetch_with_backoff(session, url, params, headers, cat_name, date_str):
    for attempt in range(MAX_RETRIES):
        try:
            async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    return await resp.json()
                if resp.status in (429, 500, 502, 503, 504):
                    wait = min(2 ** attempt * 2, 120)
                    log(f"  [{cat_name}/{date_str}] HTTP {resp.status}, waiting {wait}s (attempt {attempt+1})")
                    await asyncio.sleep(wait)
                    continue
                log(f"  [{cat_name}/{date_str}] HTTP {resp.status} — skipping")
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            wait = min(2 ** attempt * 2, 120)
            log(f"  [{cat_name}/{date_str}] Network error attempt {attempt+1}: {e}. Waiting {wait}s...")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(wait)
            else:
                log(f"  [{cat_name}/{date_str}] All retries exhausted, skipping date.")
                return None
        except Exception as e:
            log(f"  [{cat_name}/{date_str}] Unexpected error: {e}")
            return None
    return None


def store_day(conn, internal_cat_id, date_str, activity, sleep):
    """Parse and store one day's data. Returns True if stored, False if skipped (zero data)."""
    active_minutes = None
    resting_hours  = None
    calories       = None
    hourly_dist    = []

    if activity:
        active_minutes = activity.get('progress', {}).get('achieved_minutes')
        hourly_dist    = activity.get('hourly_distribution', [])
        dist = activity.get('activity_distribution', {})
        resting_hours  = dist.get('resting', {}).get('current')
        calories       = dist.get('calories', {}).get('current')

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

    # Skip all-zero rows — tracker wasn't worn; do NOT stop the run
    am = active_minutes or 0
    cal = calories or 0
    if am == 0 and cal == 0:
        return False

    c = conn.cursor()
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


async def run():
    conn = get_conn()

    # Resolve internal IDs
    cat_info = {}
    for cat_name, info in CATS.items():
        internal_id = get_internal_cat_id(conn, cat_name)
        if internal_id is None:
            log(f"Warning: {cat_name} not found in DB — skipping")
            continue
        cat_info[cat_name] = {**info, 'internal_cat_id': internal_id}

    today = datetime.date.today()
    log(f"Backfill: {BACKFILL_START} → {today} for {list(cat_info.keys())}")

    async with Tractive(TRACTIVE_EMAIL, TRACTIVE_PASSWORD) as client:
        await client.authenticate()
        auth_headers = await client._api.auth_headers()
        auth_headers['x-tractive-client'] = CLIENT_ID
        log("Authenticated with Tractive")

        async with aiohttp.ClientSession() as session:
            for cat_name, info in cat_info.items():
                pet_id      = info['pet_id']
                cat_id      = info['internal_cat_id']
                stored      = 0
                skipped_zero = 0
                skipped_dup  = 0

                log(f"\n[{cat_name}] Starting backfill (pet_id={pet_id})")

                current = BACKFILL_START
                while current <= today:
                    date_str = current.isoformat()

                    if date_already_stored(conn, cat_id, date_str):
                        skipped_dup += 1
                        current += datetime.timedelta(days=1)
                        continue

                    day, month, year = current.day, current.month, current.year
                    params = {'local_day': day, 'local_month': month, 'local_year': year}

                    try:
                        activity_url = f"{GRAPH_BASE}/pet/{pet_id}/activity/day_overview"
                        sleep_url    = f"{GRAPH_BASE}/pet/{pet_id}/sleep/day_overview"

                        activity, sleep = await asyncio.gather(
                            fetch_with_backoff(session, activity_url, params, auth_headers, cat_name, date_str),
                            fetch_with_backoff(session, sleep_url,    params, auth_headers, cat_name, date_str),
                        )

                        ok = store_day(conn, cat_id, date_str, activity, sleep)
                        if ok:
                            stored += 1
                            if stored % 30 == 0:
                                log(f"  [{cat_name}] {date_str} — {stored} days stored so far")
                        else:
                            skipped_zero += 1
                            log(f"  [{cat_name}] {date_str} — zero data (tracker off?), skipping")

                    except Exception:
                        log(f"  [{cat_name}] Unexpected error on {date_str}:")
                        traceback.print_exc()

                    current += datetime.timedelta(days=1)
                    await asyncio.sleep(0.3)

                log(f"[{cat_name}] Done. Stored: {stored}, zeros skipped: {skipped_zero}, "
                    f"already present: {skipped_dup}")

    conn.close()
    log("\nHealth backfill complete!")


if __name__ == "__main__":
    asyncio.run(run())
