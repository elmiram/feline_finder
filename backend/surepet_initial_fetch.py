# surepet_initial_fetch.py
#
# Description:
# This script performs a one-time, historical data fetch from the SurePet API.
# It uses the get_timeline() method to fetch all available historical flap
# events and populates the surepet_events and surepet_users tables.
# It should be run ONLY ONCE on a new, empty database.

import asyncio
import datetime
import traceback

# --- SurePet Integration ---
from surepy import Surepy

# --- Shared Utilities ---
# Assumes db_utils.py is in the same directory
from db_utils import (
    create_connection,
    initialize_identities_and_assignments,
    get_internal_cat_id,
    insert_surepet_event,
    insert_surepet_user, # Added user insert function
)

from secrets import (SUREPET_EMAIL,
                     SUREPET_PASSWORD)

async def main():
    """
    Main function to connect to the database, perform the one-time setup,
    and fetch historical SurePet timeline data.
    """
    print("--- Starting SurePet Initial History Fetch ---")
    conn = create_connection()
    if not conn:
        print("Fatal: Could not connect to the database. Exiting.")
        return

    # This function will populate the identities and assignments tables
    # only if they are empty.
    initialize_identities_and_assignments(conn)

    try:
        # Initialize the Surepy client directly without 'async with'
        sp = Surepy(SUREPET_EMAIL, SUREPET_PASSWORD)
        print("Successfully authenticated with SurePet API.")
        
        # CORRECTED: The timeline data is inside the 'data' key of the response.
        response = await sp.get_timeline()
        timeline = response.get('data', []) # Default to an empty list if 'data' key is missing
        
        print(f"Found {len(timeline)} total events in the timeline.")
        
        inserted_count = 0
        for event in timeline:
            surepet_event_id = event.get('id')
            
            # Skip if there's no pet or movement associated with the event
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

            # --- New Event Parsing Logic ---
            # 1. Check for Manual Update (indicated by user_id in movement)
            if movement.get('user_id'):
                event_source = 1  # Manual Update
                direction = movement.get('direction') # 1: In, 2: Out
                user_id = movement.get('user_id')
                
                # If it's a manual update, find the user's name and store it
                if event.get('users'):
                    for user in event['users']:
                        if user.get('id') == user_id:
                            user_name = user.get('name', 'Unknown User')
                            # Insert the user into the dedicated users table
                            insert_surepet_user(conn, (user_id, user_name))
                            break # User found, no need to loop further
            
            # 2. Check for "Looked Through" (indicated by direction 0)
            elif movement.get('direction') == 0:
                event_source = 2  # Looked Through
                side = movement.get('side')
                if side == 1: # Looked from outside, so cat is outside
                    direction = 2
                elif side == 0: # Looked from inside, so cat is inside
                    direction = 1
            
            # 3. Otherwise, it's a standard cat movement
            else:
                event_source = 0  # Cat Movement
                direction = movement.get('direction') # 1: In, 2: Out
            # --- End of New Logic ---

            # Only insert if we successfully parsed the event type
            if event_source is not None and direction is not None:
                event_data = (surepet_event_id, internal_id, timestamp, event_source, direction, user_id)
                # The insert function handles ignoring duplicates
                insert_surepet_event(conn, event_data)
                inserted_count += 1

        print(f"-> Processed all events. A total of {inserted_count} movement events were added to the database.")

    except Exception as e:
        print(f"An error occurred during the SurePet API fetch:")
        traceback.print_exc()
    finally:
        conn.close()
        print("\n--- SurePet Initial History Fetch Complete ---")

if __name__ == "__main__":
    asyncio.run(main())
