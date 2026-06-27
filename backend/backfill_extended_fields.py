# backfill_extended_fields.py
#
# Re-fetches Tractive position history to populate speed, alt, pos_uncertainty,
# sensor_used, and course for existing rows that currently have NULL in those columns.
#
# Resumable: skips chunks where all rows already have sensor_used IS NOT NULL.
# Resilient: wraps each chunk in try/except; exponential backoff on API errors.
# Run on Pi: nohup /home/elya/elya-env/bin/python3 /tmp/backfill_extended_fields.py > /tmp/backfill_gps.log 2>&1 &

import asyncio
import datetime
import os
import sqlite3
import sys
import traceback

# When run from /tmp, change to backend dir so config.py + relative DB path resolve correctly
BACKEND_DIR = '/home/elya/projects/feline_finder/backend'
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

from aiotractive import Tractive
from aiotractive.exceptions import TractiveError
from config import TRACTIVE_EMAIL, TRACTIVE_PASSWORD, DATABASE_FILE

CHUNK_SIZE_DAYS = 14
MAX_RETRIES = 5


def log(msg):
    ts = datetime.datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


def get_conn():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def get_null_range(conn, cat_id, range_start, range_end):
    """Return (min_ts, max_ts, count) for NULL-sensor_used rows within the tracker's active period."""
    c = conn.cursor()
    params = [cat_id]
    where = "WHERE internal_cat_id = ? AND sensor_used IS NULL"
    if range_start:
        where += " AND timestamp >= ?"
        params.append(range_start)
    if range_end:
        where += " AND timestamp < ?"
        params.append(range_end)
    c.execute(f"SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM tractive_gps_positions {where}", params)
    row = c.fetchone()
    return row[0], row[1], row[2]


async def run():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        SELECT ta.internal_cat_id, ta.tractive_tracker_id, ta.assigned_date, ta.retired_date,
               ci.cat_name
        FROM tracker_assignments ta
        JOIN cat_identities ci ON ci.internal_cat_id = ta.internal_cat_id
        ORDER BY ci.cat_name, ta.assigned_date
    """)
    assignments = c.fetchall()
    log(f"Processing {len(assignments)} tracker assignment(s)")

    async with Tractive(TRACTIVE_EMAIL, TRACTIVE_PASSWORD) as client:
        await client.authenticate()
        api_tracker_map = {t._id: t for t in await client.trackers()}
        log(f"Authenticated. {len(api_tracker_map)} tracker(s) visible in API.")

        for asgn in assignments:
            cat_id     = asgn['internal_cat_id']
            tracker_id = asgn['tractive_tracker_id']
            cat_name   = asgn['cat_name']

            first_null, last_null, null_count = get_null_range(
                conn, cat_id, asgn['assigned_date'], asgn['retired_date'])

            if null_count == 0:
                log(f"[{cat_name}/{tracker_id[:8]}] No NULL rows in this assignment period — skipping")
                continue

            if tracker_id not in api_tracker_map:
                log(f"[{cat_name}/{tracker_id[:8]}] Not in API (likely retired tracker). "
                    f"{null_count} rows remain NULL in {first_null[:10]} → {last_null[:10]}")
                continue

            tracker = api_tracker_map[tracker_id]
            start_dt = datetime.datetime.fromisoformat(first_null)
            end_dt   = datetime.datetime.fromisoformat(last_null) + datetime.timedelta(hours=1)

            log(f"\n[{cat_name}] {null_count} NULL rows for tracker {tracker_id[:8]}, "
                f"range {first_null[:10]} → {last_null[:10]}")

            current = start_dt
            total_updated = 0

            while current < end_dt:
                chunk_end = min(current + datetime.timedelta(days=CHUNK_SIZE_DAYS), end_dt)
                cur_str   = current.strftime('%Y-%m-%d %H:%M:%S')
                end_str   = chunk_end.strftime('%Y-%m-%d %H:%M:%S')

                c.execute("""
                    SELECT COUNT(*) FROM tractive_gps_positions
                    WHERE internal_cat_id=? AND sensor_used IS NULL AND timestamp>=? AND timestamp<?
                """, (cat_id, cur_str, end_str))
                null_in_chunk = c.fetchone()[0]

                if null_in_chunk == 0:
                    log(f"  [skip] {current.date()} → {chunk_end.date()} already populated")
                    current = chunk_end
                    continue

                log(f"  [fetch] {current.date()} → {chunk_end.date()} ({null_in_chunk} NULL rows)")

                try:
                    history = None
                    for attempt in range(MAX_RETRIES):
                        try:
                            history = await tracker.positions(
                                int(current.timestamp()), int(chunk_end.timestamp()), "json_segments")
                            break
                        except (TractiveError, Exception) as e:
                            wait = min(2 ** attempt * 2, 120)
                            log(f"    Attempt {attempt+1} failed: {e}. Waiting {wait}s...")
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(wait)
                            else:
                                log(f"    All {MAX_RETRIES} retries exhausted — skipping chunk.")

                    if not history:
                        log(f"  [gap] API returned no data for {current.date()} → {chunk_end.date()}")
                        current = chunk_end
                        await asyncio.sleep(2)
                        continue

                    api_pts = {}
                    for segment in history:
                        for pt in segment:
                            ts_str = datetime.datetime.fromtimestamp(pt['time']).strftime('%Y-%m-%d %H:%M:%S')
                            api_pts[ts_str] = pt

                    chunk_updated = 0
                    for ts_str, pt in api_pts.items():
                        c.execute("""
                            UPDATE tractive_gps_positions
                            SET speed=?, alt=?, pos_uncertainty=?, sensor_used=?, course=?
                            WHERE internal_cat_id=? AND timestamp=? AND sensor_used IS NULL
                        """, (pt.get('speed'), pt.get('alt'), pt.get('pos_uncertainty'),
                              pt.get('sensor_used'), pt.get('course'), cat_id, ts_str))
                        chunk_updated += c.rowcount

                    conn.commit()
                    total_updated += chunk_updated
                    log(f"    Updated {chunk_updated} rows ({len(api_pts)} API positions in chunk)")

                except Exception:
                    log(f"  [error] Unexpected error in chunk {current.date()} → {chunk_end.date()}:")
                    traceback.print_exc()

                current = chunk_end
                await asyncio.sleep(1)

            log(f"[{cat_name}] Done. Total updated this assignment: {total_updated}")

    conn.close()
    log("\nBackfill complete!")


if __name__ == "__main__":
    asyncio.run(run())
