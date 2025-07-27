# surepet_collector.py
#
# Description:
# This script runs as a continuous service to keep the SurePet data up-to-date.
# It fetches the timeline and inserts any new events into the database.

import asyncio
import datetime
import traceback

# --- SurePet Integration ---
from surepy import Surepy

# --- Shared Utilities ---
# Assumes db_utils.py is in the same directory
from db_utils import (
    create_connection,
    get_internal_cat_id,
    insert_surepet_event,
    insert_surepet_user,
)

from secrets import (SUREPET_EMAIL,
                     SUREPET_PASSWORD)


# --- Configuration ---
FETCH_INTERVAL_SECONDS = 300  # 5 minutes

async def fetch_and_store_surepet_updates():
    """
    Fetches the latest timeline events from SurePet and stores them.
    """
    conn = create_connection()
    if not conn:
        print("Collector: Could not connect to the database.")
        return

    try:
        # Initialize the Surepy client directly
        sp = Surepy(SUREPET_EMAIL, SUREPET_PASSWORD)
        
        response = await sp.get_timeline()
        timeline = response.get('data', [])
        
        if not timeline:
            print("Collector: No timeline events found.")
            conn.close()
            return
            
        inserted_count = 0
        for event in timeline:
            surepet_event_id = event.get('id')
            
            if not event.get('pets') or not event.get('movements'):
                continue
            
            pet_id = event['pets'][0].get('id')
            internal_id = get_internal_cat_id(conn, surepet_id=pet_id)
            if not internal_id:
                continue

            timestamp = datetime.datetime.fromisoformat(event.get('created_at'))
            
            movement = event['movements'][0]
            event_source = None
            direction = None
            user_id = None

            # --- Event Parsing Logic ---
            if movement.get('user_id'):
                event_source = 1  # Manual Update
                direction = movement.get('direction')
                user_id = movement.get('user_id')
                if event.get('users'):
                    for user in event['users']:
                        if user.get('id') == user_id:
                            user_name = user.get('name', 'Unknown User')
                            insert_surepet_user(conn, (user_id, user_name))
                            break
            elif movement.get('direction') == 0:
                event_source = 2  # Looked Through
                side = movement.get('side')
                direction = 2 if side == 1 else 1
            else:
                event_source = 0  # Cat Movement
                direction = movement.get('direction')
            
            if event_source is not None and direction is not None:
                event_data = (surepet_event_id, internal_id, timestamp, event_source, direction, user_id)
                # The db_utils function uses INSERT OR IGNORE, so it's safe to call every time.
                insert_surepet_event(conn, event_data)
                
    except Exception as e:
        print(f"Collector: An unhandled error occurred in the SurePet fetch cycle:")
        traceback.print_exc()
    finally:
        conn.close()

async def main():
    """Main service loop."""
    while True:
        print(f"\n--- SurePet Collector: Starting data fetch cycle at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
        await fetch_and_store_surepet_updates()
        print(f"--- SurePet Collector: Cycle complete. Sleeping for {FETCH_INTERVAL_SECONDS} seconds. ---")
        await asyncio.sleep(FETCH_INTERVAL_SECONDS)

if __name__ == "__main__":
    try:
        print("Starting SurePet Collector Service... Press Ctrl+C to stop.")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSurePet Collector Service stopped by user.")
