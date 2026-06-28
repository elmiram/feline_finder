"""
territory_compute.py — Backfill weekly and monthly cat territory entries.

Iterates over all historical GPS data for every cat (Arthur, King, Trixie) and
computes alpha-shape territories for every ISO week (Mon–Sun) and calendar month.
Already-computed periods are skipped so the script is safe to re-run.

Run:
    /home/elya/elya-env/bin/python3 ~/projects/feline_finder/backend/territory_compute.py

Log goes to stdout (redirect to file when running in background).
"""

import os
import sys
import json
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
import calendar

# ---------------------------------------------------------------------------
# Path setup — allow "import territory" from the same directory.
# ---------------------------------------------------------------------------
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

from territory import grid_filter, compute_territory  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_PATH = Path.home() / "projects" / "feline_finder" / "backend" / "cat_tracker.db"

# Minimum GPS ping count per period before we even attempt alpha shape.
# Based on observed distribution: nearly all real weeks have ≥50 pings.
# Weeks below this are almost always partial weeks or tracker-offline gaps.
MIN_PINGS = 50

# Commit to DB every N successful insertions.
COMMIT_EVERY = 10


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def monday_of_week(d: date) -> date:
    """Return the Monday of the ISO week containing date d."""
    return d - timedelta(days=d.weekday())


def sunday_of_week(monday: date) -> date:
    """Return the Sunday of the ISO week starting on monday."""
    return monday + timedelta(days=6)


def last_day_of_month(year: int, month: int) -> date:
    """Return the last calendar day of a given month."""
    return date(year, month, calendar.monthrange(year, month)[1])


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_all_cats(conn):
    """Return list of (internal_cat_id, cat_name) for all cats."""
    cur = conn.execute("SELECT internal_cat_id, cat_name FROM cat_identities ORDER BY cat_name")
    return cur.fetchall()


def already_computed(conn, internal_cat_id, period_type, period_start_str):
    """Return True if a territory row already exists for this cat/period."""
    cur = conn.execute(
        "SELECT 1 FROM cat_territories WHERE internal_cat_id = ? AND period_type = ? AND period_start = ?",
        (internal_cat_id, period_type, period_start_str),
    )
    return cur.fetchone() is not None


def fetch_pings(conn, internal_cat_id, ts_start_str, ts_end_exclusive_str):
    """
    Fetch GPS pings for a cat in [ts_start_str, ts_end_exclusive_str).

    tractive_gps_positions.internal_cat_id is a direct FK — no tracker join needed.
    sensor_used NULL is treated same as 'GPS' (real GPS ping).
    """
    cur = conn.execute(
        """
        SELECT latitude, longitude
        FROM tractive_gps_positions
        WHERE internal_cat_id = ?
          AND timestamp >= ?
          AND timestamp < ?
          AND (sensor_used = 'GPS' OR sensor_used IS NULL)
        """,
        (internal_cat_id, ts_start_str, ts_end_exclusive_str),
    )
    return cur.fetchall()


def get_previous_area(conn, internal_cat_id, period_type, period_start_str):
    """
    Return area_m2 of the immediately preceding period of the same type, or None.

    For weeks: the period starting 7 days before period_start.
    For months: the period starting on the 1st of the previous month.
    """
    if period_type == "week":
        prev_date = date.fromisoformat(period_start_str) - timedelta(days=7)
        prev_start_str = prev_date.isoformat()
    else:  # month
        d = date.fromisoformat(period_start_str)
        if d.month == 1:
            prev_date = date(d.year - 1, 12, 1)
        else:
            prev_date = date(d.year, d.month - 1, 1)
        prev_start_str = prev_date.isoformat()

    cur = conn.execute(
        "SELECT area_m2 FROM cat_territories WHERE internal_cat_id = ? AND period_type = ? AND period_start = ?",
        (internal_cat_id, period_type, prev_start_str),
    )
    row = cur.fetchone()
    return row[0] if row else None


def insert_territory(conn, internal_cat_id, period_type, period_start_str, period_end_str, result, area_change_pct):
    """Insert a territory row using INSERT OR IGNORE (safe to re-run)."""
    conn.execute(
        """
        INSERT OR IGNORE INTO cat_territories
            (internal_cat_id, period_type, period_start, period_end,
             polygon_json, holes_json, area_m2, area_change_pct, ping_count, computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            internal_cat_id,
            period_type,
            period_start_str,
            period_end_str,
            result["polygon_json"],
            result["holes_json"],
            result["area_m2"],
            area_change_pct,
            result["ping_count"],
            datetime.utcnow().isoformat(),
        ),
    )


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def process_period(conn, cat_name, internal_cat_id, period_type, period_start_str,
                   period_end_str, ts_end_exclusive_str, insert_count):
    """
    Attempt to compute and insert a territory for one cat/period.

    Returns updated insert_count (and commits if threshold reached).
    """
    label = "(month)" if period_type == "month" else ""

    if already_computed(conn, internal_cat_id, period_type, period_start_str):
        return insert_count  # silent skip

    pings = fetch_pings(conn, internal_cat_id, period_start_str, ts_end_exclusive_str)

    if len(pings) < MIN_PINGS:
        print(
            f"{cat_name} {period_start_str}–{period_end_str}{label}: "
            f"only {len(pings)} pings, skipping"
        )
        return insert_count

    filtered = grid_filter(pings)
    result = compute_territory(filtered)

    if result is None:
        print(
            f"{cat_name} {period_start_str}–{period_end_str}{label}: "
            f"{len(pings)} pings → compute_territory returned None (too few after filter or degenerate)"
        )
        return insert_count

    # area_change_pct vs previous period
    prev_area = get_previous_area(conn, internal_cat_id, period_type, period_start_str)
    if prev_area and prev_area > 0:
        area_change_pct = (result["area_m2"] - prev_area) / prev_area * 100.0
    else:
        area_change_pct = None

    insert_territory(conn, internal_cat_id, period_type, period_start_str, period_end_str,
                     result, area_change_pct)

    insert_count += 1
    if insert_count % COMMIT_EVERY == 0:
        conn.commit()

    change_str = f" ({area_change_pct:+.1f}%)" if area_change_pct is not None else ""
    print(
        f"{cat_name} {period_start_str}–{period_end_str}{label}: "
        f"{result['ping_count']} pings → {result['area_m2']:.0f} m²{change_str}"
    )

    return insert_count


def compute_all(conn):
    cats = get_all_cats(conn)
    print(f"Cats: {[name for _, name in cats]}")

    # Earliest GPS timestamp in the whole DB.
    row = conn.execute("SELECT MIN(timestamp) FROM tractive_gps_positions").fetchone()
    if not row or not row[0]:
        print("No GPS data found. Exiting.")
        return
    earliest_ts = row[0][:10]  # 'YYYY-MM-DD'
    earliest_date = date.fromisoformat(earliest_ts)

    today = date.today()
    insert_count = 0

    # ------------------------------------------------------------------
    # Weekly iteration: Monday–Sunday, from earliest week to last complete week
    # ------------------------------------------------------------------
    print("\n=== Weekly territories ===")
    week_start = monday_of_week(earliest_date)
    # Last complete week is the week BEFORE the current week's Monday.
    last_complete_week_start = monday_of_week(today) - timedelta(days=7)

    while week_start <= last_complete_week_start:
        week_end = sunday_of_week(week_start)
        # ts_end_exclusive: first moment of the Monday after this week
        ts_end_exclusive = (week_end + timedelta(days=1)).isoformat()

        for internal_cat_id, cat_name in cats:
            insert_count = process_period(
                conn,
                cat_name,
                internal_cat_id,
                "week",
                week_start.isoformat(),
                week_end.isoformat(),
                ts_end_exclusive,
                insert_count,
            )

        week_start += timedelta(days=7)

    # ------------------------------------------------------------------
    # Monthly iteration: calendar months, up to (not including) current month
    # ------------------------------------------------------------------
    print("\n=== Monthly territories ===")
    earliest_month = date(earliest_date.year, earliest_date.month, 1)
    # Last complete month: the month before this one.
    if today.month == 1:
        last_complete_month = date(today.year - 1, 12, 1)
    else:
        last_complete_month = date(today.year, today.month - 1, 1)

    month_start = earliest_month
    while month_start <= last_complete_month:
        month_end = last_day_of_month(month_start.year, month_start.month)
        # ts_end_exclusive: first day of next month
        ts_end_exclusive = (month_end + timedelta(days=1)).isoformat()

        for internal_cat_id, cat_name in cats:
            insert_count = process_period(
                conn,
                cat_name,
                internal_cat_id,
                "month",
                month_start.isoformat(),
                month_end.isoformat(),
                ts_end_exclusive,
                insert_count,
            )

        # Advance to next month.
        if month_start.month == 12:
            month_start = date(month_start.year + 1, 1, 1)
        else:
            month_start = date(month_start.year, month_start.month + 1, 1)

    # Final commit for any remainder.
    conn.commit()
    print(f"\nDone. Total insertions: {insert_count}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print(f"territory_compute.py starting — {datetime.utcnow().isoformat()}Z")
    print(f"DB: {DB_PATH}")
    print(f"MIN_PINGS threshold: {MIN_PINGS}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        compute_all(conn)
    finally:
        conn.close()

    print(f"territory_compute.py finished — {datetime.utcnow().isoformat()}Z")


if __name__ == "__main__":
    main()
