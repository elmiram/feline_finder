# tractive_collector.py
#
# Description:
# This script runs as a continuous service to keep the Tractive data up-to-date.
# It fetches only the newest data since the last run, making it lightweight
# and efficient.

import asyncio
import datetime
import time
import traceback

# --- Tractive Integration ---
from aiotractive import Tractive
from aiotractive.exceptions import TractiveError

# --- Shared Utilities ---
# Assumes db_utils.py is in the same directory
from db_utils import (
    create_connection,
    get_all_active_trackers,
    get_latest_gps_timestamp,
    insert_tractive_hw_status,
    insert_tractive_gps_position,
)

from config import (TRACTIVE_EMAIL,
                     TRACTIVE_PASSWORD)

# --- Configuration ---
FETCH_INTERVAL_SECONDS = 300  # 5 minutes
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 30

async def fetch_and_store_tractive_updates():
    """
    Fetches the latest hardware status and any new GPS positions for all active trackers.
    """
    conn = create_connection()
    if not conn:
        print("Collector: Could not connect to the database.")
        return

    active_trackers = get_all_active_trackers(conn)
    if not active_trackers:
        print("Collector: No active trackers found in the database.")
        conn.close()
        return

    try:
        async with Tractive(TRACTIVE_EMAIL, TRACTIVE_PASSWORD) as client:
            await client.authenticate()
            api_trackers = await client.trackers()

            for tracker in api_trackers:
                if tracker._id not in active_trackers:
                    continue

                internal_cat_id = active_trackers[tracker._id]
                
                # --- 1. Fetch and Store Current Hardware Status ---
                try:
                    details = await tracker.details()
                    hw_info = await tracker.hw_info()
                    hw_data = (
                        internal_cat_id,
                        datetime.datetime.now(),
                        hw_info.get('battery_level'),
                        1 if details.get('charging_state') == 'CHARGING' else 0,
                        details.get('state'),
                        details.get('state_reason')
                    )
                    insert_tractive_hw_status(conn, hw_data)
                except Exception as e:
                    print(f"Collector: Error fetching HW status for {tracker._id}: {e}")


                # --- 2. Fetch and Store NEW GPS Positions ---
                latest_ts_str = get_latest_gps_timestamp(conn, internal_cat_id)
                time_from = int(datetime.datetime.fromisoformat(latest_ts_str).timestamp()) if latest_ts_str else int(time.time() - 3600)
                time_to = int(time.time())

                history = None
                for attempt in range(MAX_RETRIES):
                    try:
                        history = await tracker.positions(time_from, time_to, "json_segments")
                        break
                    except TractiveError as e:
                        print(f"Collector: Network error on attempt {attempt + 1} for {tracker._id}. Retrying...")
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_DELAY_SECONDS)
                        else:
                            print(f"Collector: All retries failed for {tracker._id}.")
                
                if history:
                    point_count = 0
                    for segment in history:
                        for point in segment:
                            gps_data = (
                                internal_cat_id,
                                point['time'],
                                point['latlong'][0],
                                point['latlong'][1],
                                point.get('pos_uncertainty'),
                                point.get('speed'),
                                point.get('alt'),
                                point.get('pos_uncertainty'),
                                point.get('sensor_used'),
                                point.get('course'),
                            )
                            insert_tractive_gps_position(conn, gps_data)
                            point_count += 1
                    if point_count > 0:
                        print(f"Collector: Inserted {point_count} new GPS points for tracker {tracker._id}.")

    except TractiveError as e:
        # This specifically catches API/network errors during authentication or other calls.
        print("Collector: A Tractive API error occurred (likely a temporary network issue). Will retry in the next cycle.")
        print(f"    > Error details: {e}")
    except Exception as e:
        # This catches any other unexpected errors.
        print(f"Collector: An unhandled error occurred in the main fetch cycle:")
        traceback.print_exc()
    finally:
        conn.close()

async def main():
    """Main service loop."""
    while True:
        print(f"\n--- Tractive Collector: Starting data fetch cycle at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
        await fetch_and_store_tractive_updates()
        print(f"--- Tractive Collector: Cycle complete. Sleeping for {FETCH_INTERVAL_SECONDS} seconds. ---")
        await asyncio.sleep(FETCH_INTERVAL_SECONDS)

if __name__ == "__main__":
    try:
        print("Starting Tractive Collector Service... Press Ctrl+C to stop.")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTractive Collector Service stopped by user.")
