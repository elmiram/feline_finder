# db_utils.py
#
# Description:
# This file contains shared configuration variables and database utility functions
# for the FelineFinder data collector services. It is not meant to be run directly,
# but rather imported by the tractive_collector.py and surepet_collector.py scripts.
# Version 3 adds support for the surepet_users table.

import sqlite3
import datetime
from sqlite3 import Error

from config import DATABASE_FILE, CAT_CONFIG

# --- Database Utility Functions ---

def create_connection():
    """Create a database connection to the SQLite database."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
    except Error as e:
        print(f"Error connecting to database: {e}")
    return conn

def get_internal_cat_id(conn, tractive_id=None, surepet_id=None):
    """Get the internal cat ID from a Tractive or SurePet ID."""
    cursor = conn.cursor()
    if tractive_id:
        # Query the assignments table for the tracker ID
        cursor.execute("SELECT internal_cat_id FROM tracker_assignments WHERE tractive_tracker_id = ?", (tractive_id,))
    elif surepet_id:
        # Query the identities table for the pet ID
        cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE surepet_pet_id = ?", (surepet_id,))
    else:
        return None
        
    result = cursor.fetchone()
    return result['internal_cat_id'] if result else None

def get_all_active_trackers(conn):
    """Returns a dict mapping active tractive_tracker_id to internal_cat_id."""
    cursor = conn.cursor()
    # Select trackers that have not been retired
    cursor.execute("SELECT tractive_tracker_id, internal_cat_id FROM tracker_assignments WHERE retired_date IS NULL")
    trackers = {row['tractive_tracker_id']: row['internal_cat_id'] for row in cursor.fetchall()}
    return trackers


def get_latest_gps_timestamp(conn, internal_cat_id):
    """Get the timestamp of the most recent GPS entry for a cat."""
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(timestamp) FROM tractive_gps_positions WHERE internal_cat_id = ?", (internal_cat_id,))
    result = cursor.fetchone()
    return result[0] if result and result[0] else None

def insert_tractive_hw_status(conn, data):
    """Insert a new Tractive hardware status record."""
    sql = '''INSERT INTO tractive_hw_status(internal_cat_id, timestamp, battery_level, is_charging, state, state_reason)
             VALUES(?,?,?,?,?,?)'''
    cursor = conn.cursor()
    cursor.execute(sql, data)
    conn.commit()

def insert_tractive_gps_position(conn, data):
    """Insert a new Tractive GPS position record, avoiding duplicates.

    data tuple: (internal_cat_id, unix_timestamp, lat, lon, accuracy,
                 speed, alt, pos_uncertainty, sensor_used, course)
    """
    cursor = conn.cursor()
    timestamp_dt = datetime.datetime.fromtimestamp(data[1])
    timestamp_str = timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute("SELECT 1 FROM tractive_gps_positions WHERE internal_cat_id = ? AND timestamp = ?", (data[0], timestamp_str))
    if cursor.fetchone():
        print(f"  -> Skipping duplicate GPS point for cat_id {data[0]} at {timestamp_str}")
        return

    speed         = data[5] if len(data) > 5 else None
    alt           = data[6] if len(data) > 6 else None
    pos_uncert    = data[7] if len(data) > 7 else None
    sensor_used   = data[8] if len(data) > 8 else None
    course        = data[9] if len(data) > 9 else None

    sql = '''INSERT INTO tractive_gps_positions
             (internal_cat_id, timestamp, latitude, longitude, accuracy,
              speed, alt, pos_uncertainty, sensor_used, course)
             VALUES(?,?,?,?,?,?,?,?,?,?)'''
    cursor.execute(sql, (data[0], timestamp_str, data[2], data[3], data[4],
                         speed, alt, pos_uncert, sensor_used, course))
    conn.commit()

def insert_surepet_event(conn, data):
    """Insert a new SurePet event record, ignoring duplicates based on the primary key."""
    sql = '''INSERT OR IGNORE INTO surepet_events(surepet_event_id, internal_cat_id, timestamp, event_source, direction, user_id)
             VALUES(?,?,?,?,?,?)'''
    cursor = conn.cursor()
    cursor.execute(sql, data)
    conn.commit()

def insert_surepet_user(conn, data):
    """Insert a new SurePet user if they don't already exist."""
    sql = '''INSERT OR IGNORE INTO surepet_users(surepet_user_id, user_name)
             VALUES(?,?)'''
    cursor = conn.cursor()
    cursor.execute(sql, data)
    conn.commit()

def get_internal_cat_id_by_name(conn, cat_name):
    """Get the internal cat ID from a cat name."""
    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    result = cursor.fetchone()
    return result['internal_cat_id'] if result else None

def get_tracker_history(conn):
    """Returns per-cat tracker history (active and retired assignments)."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ci.cat_name, ci.internal_cat_id,
               ta.tractive_tracker_id, ta.assigned_date, ta.retired_date
        FROM cat_identities ci
        JOIN tracker_assignments ta ON ci.internal_cat_id = ta.internal_cat_id
        ORDER BY ci.cat_name, ta.assigned_date DESC
    """)
    history = {}
    for row in cursor.fetchall():
        name = row['cat_name']
        if name not in history:
            history[name] = {'internal_cat_id': row['internal_cat_id'], 'trackers': []}
        history[name]['trackers'].append({
            'tracker_id': row['tractive_tracker_id'],
            'assigned_date': row['assigned_date'],
            'retired_date': row['retired_date'],
            'active': row['retired_date'] is None
        })
    return history

def retire_active_tracker(conn, internal_cat_id, retired_at=None):
    """Set retired_date on all active trackers for a cat. Returns list of retired tracker IDs.
    retired_at: datetime string override (e.g. when the cat actually lost the tracker)."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT tractive_tracker_id FROM tracker_assignments WHERE internal_cat_id = ? AND retired_date IS NULL",
        (internal_cat_id,)
    )
    active = [row['tractive_tracker_id'] for row in cursor.fetchall()]
    if active:
        date_str = retired_at if retired_at else datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            "UPDATE tracker_assignments SET retired_date = ? WHERE internal_cat_id = ? AND retired_date IS NULL",
            (date_str, internal_cat_id)
        )
        conn.commit()
    return active

def add_tracker_assignment(conn, internal_cat_id, tracker_id):
    """Add a new active tracker assignment for a cat."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tracker_assignments (internal_cat_id, tractive_tracker_id, assigned_date) VALUES (?, ?, ?)",
        (internal_cat_id, tracker_id, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()

def get_retired_tracker_gap_start(conn, internal_cat_id, tracker_id):
    """Get the retired_date for a specific tracker — when the gap to backfill begins."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT retired_date FROM tracker_assignments
           WHERE internal_cat_id = ? AND tractive_tracker_id = ? AND retired_date IS NOT NULL
           ORDER BY retired_date DESC LIMIT 1""",
        (internal_cat_id, tracker_id)
    )
    result = cursor.fetchone()
    return result['retired_date'] if result else None

def initialize_identities_and_assignments(conn):
    """Populate the identities and assignments tables from CAT_CONFIG if they are empty."""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM cat_identities")
    if cursor.fetchone()[0] == 0:
        print("Performing one-time setup: Populating 'cat_identities' and 'tracker_assignments' tables...")
        for name, ids in CAT_CONFIG.items():
            # 1. Populate cat_identities
            cursor.execute(
                "INSERT INTO cat_identities (cat_name, surepet_pet_id) VALUES (?, ?)",
                (name, ids["surepet_id"]),
            )
            internal_id = cursor.lastrowid # Get the ID of the cat we just inserted

            # 2. Populate tracker_assignments for the current tracker
            cursor.execute(
                "INSERT INTO tracker_assignments (internal_cat_id, tractive_tracker_id, assigned_date) VALUES (?, ?, ?)",
                (internal_id, ids["tractive_id"], datetime.datetime.now()),
            )
        conn.commit()
        print("Identity and assignment setup complete.")
        return True # Indicates that setup was performed
    else:
        print("Database already initialized.")
        return False # Indicates setup was not needed
