# tractive_initial_fetch.py
#
# Description:
# This script performs a one-time, historical data fetch from the Tractive API.
# It fetches the last year of data in small, safe chunks.
# This script is RESUMABLE and includes a retry mechanism for network errors.

import asyncio
import datetime
import traceback # Added for detailed error logging

# --- Tractive Integration ---
from aiotractive import Tractive
from aiotractive.exceptions import TractiveError

# --- Shared Utilities ---
# Assumes db_utils.py is in the same directory
from db_utils import (
    create_connection,
    initialize_identities_and_assignments,
    get_all_active_trackers,
    get_latest_gps_timestamp,
    insert_tractive_gps_position,
)

from config import (TRACTIVE_EMAIL,
                     TRACTIVE_PASSWORD,)

# --- Configuration ---
TOTAL_HISTORY_DAYS = 365
CHUNK_SIZE_DAYS = 14 # Fetch history in 14-day chunks
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 30

async def main():
    """
    Main function to connect to the database, perform the one-time setup,
    and fetch historical Tractive GPS data in chunks.
    """
    print("--- Starting Tractive Initial History Fetch (Chunked & Resumable) ---")
    conn = create_connection()
    if not conn:
        print("Fatal: Could not connect to the database. Exiting.")
        return

    initialize_identities_and_assignments(conn)
    active_trackers = get_all_active_trackers(conn)
    if not active_trackers:
        print("No active trackers found. Please check CAT_CONFIG in db_utils.py")
        conn.close()
        return

    print(f"Found {len(active_trackers)} active tracker(s) to fetch.")

    try:
        async with Tractive(TRACTIVE_EMAIL, TRACTIVE_PASSWORD) as client:
            await client.authenticate()
            print("Successfully authenticated with Tractive API.")
            
            api_trackers = await client.trackers()

            for tracker in api_trackers:
                if tracker._id not in active_trackers:
                    details = await tracker.details()
                    # Added this print statement for debugging unmanaged trackers.
                    print(f"  -> Found unmanaged tracker with ID: {tracker._id}. Data: {details}.\n    Skipping.")
                    continue

                internal_cat_id = active_trackers[tracker._id]
                
                # --- Fetch cat name for logging ---
                cursor = conn.cursor()
                cursor.execute("SELECT cat_name FROM cat_identities WHERE internal_cat_id = ?", (internal_cat_id,))
                cat_name_row = cursor.fetchone()
                cat_name = cat_name_row['cat_name'] if cat_name_row else "Unknown Cat"
                # --- End fetch cat name ---

                print(f"\nFetching history for tracker: {tracker._id} (Cat: {cat_name}, ID: {internal_cat_id})")

                # --- RESUMABLE LOGIC ---
                latest_ts_str = get_latest_gps_timestamp(conn, internal_cat_id)
                end_date = datetime.datetime.now()

                if latest_ts_str:
                    start_date = datetime.datetime.fromisoformat(latest_ts_str)
                    print(f"  -> Resuming fetch from last known position at {start_date.strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    start_date = end_date - datetime.timedelta(days=TOTAL_HISTORY_DAYS)
                    print(f"  -> No existing data found. Starting full history fetch.")
                
                current_chunk_start = start_date
                while current_chunk_start < end_date:
                    current_chunk_end = current_chunk_start + datetime.timedelta(days=CHUNK_SIZE_DAYS)
                    if current_chunk_end > end_date:
                        current_chunk_end = end_date

                    print(f"  -> Fetching chunk: {current_chunk_start.strftime('%Y-%m-%d')} to {current_chunk_end.strftime('%Y-%m-%d')}")

                    time_from = int(current_chunk_start.timestamp())
                    time_to = int(current_chunk_end.timestamp())

                    # --- RETRY LOGIC ---
                    history = None
                    for attempt in range(MAX_RETRIES):
                        try:
                            history = await tracker.positions(time_from, time_to, "json_segments")
                            break # Success, exit retry loop
                        except TractiveError as e:
                            print(f"    -> Attempt {attempt + 1}/{MAX_RETRIES} failed with a network error.")
                            if attempt < MAX_RETRIES - 1:
                                print(f"    -> Retrying in {RETRY_DELAY_SECONDS} seconds...")
                                await asyncio.sleep(RETRY_DELAY_SECONDS)
                            else:
                                print(f"    -> All {MAX_RETRIES} attempts failed for this chunk. Skipping.")
                    
                    if history is None:
                        # Move to the next chunk if all retries failed
                        current_chunk_start = current_chunk_end
                        await asyncio.sleep(1)
                        continue
                    # --- END RETRY LOGIC ---
                    
                    point_count = 0
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
                            point_count += 1
                    
                    print(f"     ...inserted {point_count} points.")
                    current_chunk_start = current_chunk_end
                    await asyncio.sleep(1) # Be polite to the API

    except Exception as e:
        print(f"An unhandled error occurred during the Tractive API fetch:")
        traceback.print_exc()
    finally:
        conn.close()
        print("\n--- Tractive Initial History Fetch Complete ---")

if __name__ == "__main__":
    asyncio.run(main())
