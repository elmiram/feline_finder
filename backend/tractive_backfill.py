# tractive_backfill.py
#
# Description:
# Backfills historical GPS data for a single Tractive tracker.
# Designed to be called from api_server.py when a tracker is assigned or reactivated.
# Runs in a background thread so the API response is immediate.

import asyncio
import datetime
import threading
import traceback

from aiotractive import Tractive
from aiotractive.exceptions import TractiveError

from db_utils import create_connection, get_latest_gps_timestamp, insert_tractive_gps_position
from config import TRACTIVE_EMAIL, TRACTIVE_PASSWORD

CHUNK_SIZE_DAYS = 14
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 30


async def backfill_single_tracker(tracker_id, internal_cat_id, start_from=None):
    """
    Fetch historical GPS data for one tracker and write it to the DB.
    start_from: datetime to begin from (gap fill on reactivation). If None, resumes from last known point or goes back 365 days.
    """
    print(f"[backfill] Starting for tracker {tracker_id} (cat_id={internal_cat_id})")
    conn = create_connection()
    if not conn:
        print("[backfill] Could not connect to database.")
        return

    try:
        end_date = datetime.datetime.now()

        if start_from:
            fetch_start = start_from
            print(f"[backfill] Gap fill: {fetch_start} → {end_date}")
        else:
            latest_ts_str = get_latest_gps_timestamp(conn, internal_cat_id)
            if latest_ts_str:
                fetch_start = datetime.datetime.fromisoformat(latest_ts_str)
                print(f"[backfill] Resuming from last point at {fetch_start}")
            else:
                fetch_start = end_date - datetime.timedelta(days=365)
                print(f"[backfill] No existing data — full year fetch")

        async with Tractive(TRACTIVE_EMAIL, TRACTIVE_PASSWORD) as client:
            await client.authenticate()
            api_trackers = await client.trackers()

            target = next((t for t in api_trackers if t._id == tracker_id), None)
            if not target:
                print(f"[backfill] Tracker {tracker_id} not found in Tractive account.")
                return

            current = fetch_start
            while current < end_date:
                chunk_end = min(current + datetime.timedelta(days=CHUNK_SIZE_DAYS), end_date)
                time_from = int(current.timestamp())
                time_to = int(chunk_end.timestamp())
                print(f"[backfill] Chunk {current.strftime('%Y-%m-%d')} → {chunk_end.strftime('%Y-%m-%d')}")

                history = None
                for attempt in range(MAX_RETRIES):
                    try:
                        history = await target.positions(time_from, time_to, "json_segments")
                        break
                    except TractiveError:
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_DELAY_SECONDS)
                        else:
                            print(f"[backfill] Chunk failed after {MAX_RETRIES} attempts, skipping.")

                if history:
                    count = 0
                    for segment in history:
                        for point in segment:
                            gps_data = (
                                internal_cat_id,
                                point['time'],
                                point['latlong'][0],
                                point['latlong'][1],
                                point['pos_uncertainty']
                            )
                            insert_tractive_gps_position(conn, gps_data)
                            count += 1
                    print(f"[backfill] Inserted {count} points.")

                current = chunk_end
                await asyncio.sleep(1)

    except Exception:
        traceback.print_exc()
    finally:
        conn.close()
        print(f"[backfill] Done for tracker {tracker_id}.")


def run_backfill_in_background(tracker_id, internal_cat_id, start_from=None):
    """Spawn a daemon thread to run the async backfill without blocking the API."""
    def _thread():
        asyncio.run(backfill_single_tracker(tracker_id, internal_cat_id, start_from))
    threading.Thread(target=_thread, daemon=True).start()
