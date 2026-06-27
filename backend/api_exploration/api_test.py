# api_test.py
#
# Explores Tractive API data fields we're not yet storing.
# Run from the backend/ directory:
#   ~/elya-env/bin/python3 api_exploration/api_test.py

import asyncio
import sys
import os
import traceback
from datetime import datetime
from pprint import pprint

import aiohttp

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import TRACTIVE_EMAIL, TRACTIVE_PASSWORD

from aiotractive import Tractive  # installed in Pi venv

APS_BASE = "https://aps-api.tractive.com/api/1"
GRAPH_BASE = "https://graph.tractive.com/4"
CLIENT_ID = "625e533dc3c3b41c28a669f0"


async def aps_get(session, pet_id, endpoint, auth_headers):
    url = f"{APS_BASE}/pet/{pet_id}/{endpoint}"
    async with session.get(url, headers=auth_headers) as resp:
        print(f"  GET {url}  →  {resp.status}")
        if resp.status == 200:
            return await resp.json()
        return await resp.text()


async def explore():
    async with Tractive(TRACTIVE_EMAIL, TRACTIVE_PASSWORD) as client:
        await client.authenticate()
        auth_headers = await client._api.auth_headers()
        auth_headers["x-tractive-client"] = CLIENT_ID
        print("Authenticated.\n")

        pets = await client.trackable_objects()
        print(f"Found {len(pets)} pet(s).\n")

        async with aiohttp.ClientSession() as session:
            for pet in pets:
                details = await pet.details()
                name = details.get('details', {}).get('name', pet._id)
                print(f"{'='*60}")
                print(f"PET: {name}  (id={pet._id})")
                print(f"{'='*60}\n")

                for ep in ["health/overview", "activity/summary", "wellness", "activity", "sleep"]:
                    try:
                        result = await aps_get(session, pet._id, ep, auth_headers)
                        pprint(result, indent=2)
                    except Exception as e:
                        print(f"    error: {e}")
                    print()

        # ── Sample position entry ─────────────────────────────────────────
        print("\n=== Sample position fields (last 24h) ===")
        try:
            trackers = await client.trackers()
            now = datetime.now().timestamp()
            for t in trackers:
                positions = await t.positions(now - 86400, now, 'json_segments')
                if positions:
                    print(f"Tracker {t._id} — sample position:")
                    pprint(positions[0], indent=2)
                    break
        except Exception:
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(explore())
