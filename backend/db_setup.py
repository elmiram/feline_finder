# db_setup.py
#
# Description:
# This script creates the SQLite database and all necessary tables for the
# FelineFinder application. It should be run once to initialize the database.
# Version 4 adds the 'surepet_users' table.

import sqlite3
from sqlite3 import Error

from secrets import (DATABASE_FILE)

def create_connection(db_file):
    """ Create a database connection to a SQLite database """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        print(f"Successfully connected to SQLite database: {db_file}")
        return conn
    except Error as e:
        print(e)
    return conn

def create_table(conn, create_table_sql):
    """ Create a table from the create_table_sql statement """
    try:
        c = conn.cursor()
        c.execute(create_table_sql)
    except Error as e:
        print(e)

def setup_database():
    """
    Main function to connect to the DB and create all tables.
    """
    conn = create_connection(DATABASE_FILE)

    if conn is not None:
        # --- Create cat_identities table ---
        sql_create_cat_identities_table = """
        CREATE TABLE IF NOT EXISTS cat_identities (
            internal_cat_id INTEGER PRIMARY KEY AUTOINCREMENT,
            cat_name TEXT NOT NULL UNIQUE,
            surepet_pet_id INTEGER UNIQUE
        );
        """
        create_table(conn, sql_create_cat_identities_table)
        print("Table 'cat_identities' created successfully.")

        # --- Create tracker_assignments table ---
        sql_create_tracker_assignments_table = """
        CREATE TABLE IF NOT EXISTS tracker_assignments (
            assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            internal_cat_id INTEGER NOT NULL,
            tractive_tracker_id TEXT NOT NULL,
            assigned_date DATETIME NOT NULL,
            retired_date DATETIME, -- NULL for the currently active tracker
            FOREIGN KEY (internal_cat_id) REFERENCES cat_identities (internal_cat_id)
        );
        """
        create_table(conn, sql_create_tracker_assignments_table)
        print("Table 'tracker_assignments' created successfully.")

        # --- Create tractive_hw_status table ---
        sql_create_tractive_hw_status_table = """
        CREATE TABLE IF NOT EXISTS tractive_hw_status (
            status_id INTEGER PRIMARY KEY AUTOINCREMENT,
            internal_cat_id INTEGER NOT NULL,
            timestamp DATETIME NOT NULL,
            battery_level INTEGER,
            is_charging INTEGER, -- 0 for False, 1 for True
            state TEXT,
            state_reason TEXT,
            FOREIGN KEY (internal_cat_id) REFERENCES cat_identities (internal_cat_id)
        );
        """
        create_table(conn, sql_create_tractive_hw_status_table)
        print("Table 'tractive_hw_status' created successfully.")

        # --- Create tractive_gps_positions table ---
        sql_create_tractive_gps_positions_table = """
        CREATE TABLE IF NOT EXISTS tractive_gps_positions (
            position_id INTEGER PRIMARY KEY AUTOINCREMENT,
            internal_cat_id INTEGER NOT NULL,
            timestamp DATETIME NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            accuracy REAL,
            FOREIGN KEY (internal_cat_id) REFERENCES cat_identities (internal_cat_id)
        );
        """
        create_table(conn, sql_create_tractive_gps_positions_table)
        print("Table 'tractive_gps_positions' created successfully.")
        
        # --- Create surepet_users table (NEW) ---
        # This table stores the mapping of SurePet user IDs to names.
        sql_create_surepet_users_table = """
        CREATE TABLE IF NOT EXISTS surepet_users (
            surepet_user_id INTEGER PRIMARY KEY,
            user_name TEXT NOT NULL
        );
        """
        create_table(conn, sql_create_surepet_users_table)
        print("Table 'surepet_users' created successfully.")

        # --- Create surepet_events table ---
        # The user_id column now links to the new surepet_users table.
        sql_create_surepet_events_table = """
        CREATE TABLE IF NOT EXISTS surepet_events (
            surepet_event_id INTEGER PRIMARY KEY,
            internal_cat_id INTEGER NOT NULL,
            timestamp DATETIME NOT NULL,
            event_source INTEGER NOT NULL, -- 0:Cat, 1:Manual, 2:Looked
            direction INTEGER NOT NULL, -- 1:Inside, 2:Outside
            user_id INTEGER, -- NULL if not a manual update
            FOREIGN KEY (internal_cat_id) REFERENCES cat_identities (internal_cat_id),
            FOREIGN KEY (user_id) REFERENCES surepet_users (surepet_user_id)
        );
        """
        create_table(conn, sql_create_surepet_events_table)
        print("Table 'surepet_events' created successfully.")

        # --- Create devices table ---
        sql_create_devices_table = """
        CREATE TABLE IF NOT EXISTS devices (
            device_id INTEGER PRIMARY KEY,
            name TEXT,
            type TEXT,
            battery_level INTEGER,
            last_updated DATETIME NOT NULL
        );
        """
        create_table(conn, sql_create_devices_table)
        print("Table 'devices' created successfully.")

        conn.close()
        print("\nDatabase setup complete. All tables are ready.")
    else:
        print("Error! cannot create the database connection.")

if __name__ == '__main__':
    setup_database()
