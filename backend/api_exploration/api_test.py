# api_test.py
#
# Description:
# This script is a proof-of-concept to test the connection to the Tractive
# and SurePet APIs using community-developed Python libraries.
#
# It will:
# 1. Authenticate with both services using your credentials.
# 2. Fetch a list of your registered trackers (Tractive) and pets (SurePet).
# 3. Print the most recent status data for the first tracker and pet found.
#
# Installation:
# You must install the required libraries before running this script.
# pip install aiotractive surepy

import asyncio
from datetime import datetime

from pprint import pprint

# --- Tractive Integration (using aiotractive) ---
from aiotractive import Tractive

# --- SurePet Integration ---
from surepy import Surepy

from backend.secrets import TRACTIVE_EMAIL, TRACTIVE_PASSWORD, SUREPET_EMAIL, SUREPET_PASSWORD


async def test_tractive_api():
    """
    Connects to the Tractive API, fetches trackers, and prints their status.
    This version is updated for the 'aiotractive' library.
    """
    print("--- Testing Tractive API ---")
    try:
        # Use 'async with' to handle login and session closing automatically.
        async with Tractive(TRACTIVE_EMAIL, TRACTIVE_PASSWORD) as client:
            await client.authenticate()
            print("Tractive: Successfully authenticated.")

            # Get all trackable objects (trackers)
            trackers = await client.trackers()
            if not trackers:
                print("Tractive: No trackers found on this account.")
                return

            print(f"Tractive: Found {len(trackers)} tracker(s).")




            # Get details for the first tracker
            first_tracker = trackers[1]
            print(f"Tractive: Found first tracker.")
            details = await first_tracker.details() # Includes device capabilities, battery status(not level), charging state and so on
            hw = await first_tracker.hw_info() # Includes battery level, firmware version, model and so on
            position = await first_tracker.pos_report() 
            print(f"\n--- Details for Tracker:", details)

            # Hardware status and position are attributes on the trackable object
            print(f"  - HW:", hw)
            
            print(f"  - position: ", position)
            
            cats = await client.trackable_objects()
        
            # Retrieve details
            #cat = await cats[0].details() 
            #print("first cat", cat)
            
            now = datetime.now().timestamp()
            time_from = now - 3600 * 2
            time_to = now
            positions = await first_tracker.positions(time_from, time_to, 'json_segments')
            print(positions)


    except Exception as e:
        print(f"An unexpected error occurred with Tractive: {e}")
    finally:
        print("-" * 28 + "\n")


async def test_surepet_api():
    """
    Connects to the SurePet API, fetches pets, and prints their status.
    This version is updated for the latest 'surepy' library API.
    """
    print("--- Testing SurePet API ---")
    sp = None
    try:
        # Initialize the client directly.
        sp = Surepy(SUREPET_EMAIL, SUREPET_PASSWORD)
        print("SurePet: Successfully authenticated.")

        # list with all pets
        pets: List[Pet] = await sp.get_pets()
        for pet in pets:
            print(f"\n\n{pet.name}: {pet.state} | {pet.location}\n")
            pprint(pet.raw_data())

        print(f"\n\n - - - - - - - - - - - - - - - - - - - -\n\n")

        # all entities as id-indexed dict
        entities: Dict[int, SurepyEntity] = await sp.get_entities()

        # list with alldevices
        devices: List[SurepyDevice] = await sp.get_devices()
        for device in devices:
            print(f"{device.name = } | {device.serial = } | {device.battery_level = }")
            print(f"{device.type = } | {device.unique_id = } | {device.id = }")
            print(f"{entities[device.parent_id].full_name = } | {entities[device.parent_id] = }\n")


    except Exception as e:
        print(f"An unexpected error occurred with SurePet: {e}")
    finally:
        # The Surepy object does not need an explicit close method in this context.
        print("-" * 27 + "\n")


async def main():
    """
    Main function to run both API tests.
    """
    await test_tractive_api()
    #await test_surepet_api()


if __name__ == "__main__":
    # Python's asyncio is used to run the asynchronous functions
    asyncio.run(main())
