"""
trip_compute.py — Backfill cat_trips table from all historical data.

Run once (or re-run safely — existing rows are skipped via INSERT OR IGNORE).

Usage:
    /home/elya/elya-env/bin/python3 ~/projects/feline_finder/backend/trip_compute.py
"""
import sqlite3
import sys
from pathlib import Path

# DB path (Pi)
DB_PATH = Path.home() / "projects/feline_finder/backend/cat_tracker.db"

# Add backend dir to path so we can import local modules
sys.path.insert(0, str(DB_PATH.parent))

from location_state import compute_trips
from config import KNOWN_ZONES


def create_connection(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrency
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def run_backfill():
    print(f"Connecting to {DB_PATH}")
    conn = create_connection(DB_PATH)
    cursor = conn.cursor()

    # Fetch all cats (including Trixie)
    cursor.execute("SELECT internal_cat_id, cat_name FROM cat_identities ORDER BY internal_cat_id")
    cats = cursor.fetchall()
    print(f"Found {len(cats)} cats: {[r['cat_name'] for r in cats]}")

    total_inserted = 0
    total_skipped = 0

    for cat_row in cats:
        internal_cat_id = cat_row['internal_cat_id']
        cat_name = cat_row['cat_name']

        print(f"\n--- {cat_name} (id={internal_cat_id}) ---")
        print("  Computing trips over all history...")

        trips = compute_trips(conn, internal_cat_id, KNOWN_ZONES)
        print(f"  {len(trips)} trips computed")

        inserted = 0
        skipped = 0
        for trip in trips:
            try:
                cursor.execute(
                    """INSERT OR IGNORE INTO cat_trips
                       (internal_cat_id, start_time, end_time, duration_minutes,
                        start_source, end_source, confidence)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        internal_cat_id,
                        trip["start_time"],
                        trip["end_time"],
                        trip["duration_minutes"],
                        trip["start_source"],
                        trip["end_source"],
                        trip["confidence"],
                    ),
                )
                if cursor.rowcount == 1:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"  ERROR inserting trip {trip['start_time']}: {e}")

        conn.commit()
        print(f"  {inserted} inserted, {skipped} skipped (already existed)")
        total_inserted += inserted
        total_skipped += skipped

    conn.close()
    print(f"\n=== Backfill complete: {total_inserted} trips inserted, {total_skipped} skipped ===")


if __name__ == "__main__":
    run_backfill()
