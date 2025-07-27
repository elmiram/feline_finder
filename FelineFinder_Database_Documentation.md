# FelineFinder Database Schema

This document outlines the structure of the `cat_tracker.db` SQLite database. The database is designed to store and organize data fetched from the Tractive and SurePet APIs, providing a permanent archive for real-time status updates and long-term behavioral analysis of your cats.

## Table Relationships

The core of the database consists of two tables: `cat_identities` and `tracker_assignments`.

- `cat_identities` creates a single, permanent profile for each cat.
- `tracker_assignments` creates a historical log of which physical Tractive tracker was assigned to which cat and when. This allows for seamless history tracking even if a cat loses a tracker and gets a new one.

All other data tables (GPS positions, hardware status, flap events) link back to the `cat_identities` table using the `internal_cat_id`.

---

## 1. `cat_identities`

Stores the primary, permanent profile for each cat.

| Column Name      | Data Type | Constraints              | Description                                      |
|------------------|-----------|--------------------------|--------------------------------------------------|
| internal_cat_id  | INTEGER   | PRIMARY KEY AUTOINCREMENT| A unique, auto-generated ID for each cat.        |
| cat_name         | TEXT      | NOT NULL UNIQUE          | The human-readable name of the cat (e.g., "Trixie"). |
| surepet_pet_id   | INTEGER   | UNIQUE                   | The unique ID from the SurePet system.           |

---

## 2. `tracker_assignments`

Stores the assignment history of Tractive trackers to cats.

| Column Name         | Data Type | Constraints               | Description                                        |
|---------------------|-----------|---------------------------|----------------------------------------------------|
| assignment_id       | INTEGER   | PRIMARY KEY AUTOINCREMENT | A unique ID for each assignment record.            |
| internal_cat_id     | INTEGER   | NOT NULL                  | Foreign key to `cat_identities.internal_cat_id`.   |
| tractive_tracker_id | TEXT      | NOT NULL                  | The ID string of the physical Tractive device.     |
| assigned_date       | DATETIME  | NOT NULL                  | The timestamp the tracker was assigned.            |
| retired_date        | DATETIME  | NULLABLE                  | When the tracker was lost/replaced. NULL if active.|

---

## 3. `tractive_hw_status`

Stores periodic hardware status reports from each Tractive tracker.

| Column Name    | Data Type | Constraints               | Description                                      |
|----------------|-----------|---------------------------|--------------------------------------------------|
| status_id      | INTEGER   | PRIMARY KEY AUTOINCREMENT | A unique ID for each status record.              |
| internal_cat_id| INTEGER   | NOT NULL                  | Foreign key to `cat_identities.internal_cat_id`. |
| timestamp      | DATETIME  | NOT NULL                  | Time this status was fetched and saved.          |
| battery_level  | INTEGER   |                           | Battery percentage (0–100).                      |
| is_charging    | INTEGER   |                           | Boolean: 1 = charging, 0 = not.                   |
| state          | TEXT      |                           | Operational state (e.g., `NOT_REPORTING`).       |
| state_reason   | TEXT      |                           | Reason for the state (e.g., `OUT_OF_BATTERY`).   |

---

## 4. `tractive_gps_positions`

Stores the historical GPS data from Tractive.

| Column Name    | Data Type | Constraints               | Description                                      |
|----------------|-----------|---------------------------|--------------------------------------------------|
| position_id    | INTEGER   | PRIMARY KEY AUTOINCREMENT | A unique ID for each GPS record.                |
| internal_cat_id| INTEGER   | NOT NULL                  | Foreign key to `cat_identities.internal_cat_id`. |
| timestamp      | DATETIME  | NOT NULL                  | Timestamp of the GPS reading.                    |
| latitude       | REAL      | NOT NULL                  | Latitude coordinate.                             |
| longitude      | REAL      | NOT NULL                  | Longitude coordinate.                            |
| accuracy       | REAL      |                           | Accuracy in meters.                              |

---

## 5. `surepet_events`

Stores event data from the SurePet timeline.

| Column Name     | Data Type | Constraints   | Description                                                                            |
|------------------|-----------|----------------|----------------------------------------------------------------------------------------|
| surepet_event_id | INTEGER   | PRIMARY KEY    | Unique event ID from SurePet API. Prevents duplicates.                                 |
| internal_cat_id  | INTEGER   | NOT NULL       | Foreign key to `cat_identities.internal_cat_id`.                                       |
| timestamp        | DATETIME  | NOT NULL       | Timestamp of the event.                                                                |
| event_source     | INTEGER   | NOT NULL       | 0 = Cat Movement, 1 = Manual Update, 2 = Looked Through.                              |
| direction        | INTEGER   | NOT NULL       | 1 = Inside, 2 = Outside (meaning depends on event_source).                             |
| user_id          | INTEGER   | NULLABLE       | ID of user who made the change (only for manual updates).                              |

---

## 6. `devices`

Stores the status of SurePet hardware (flap, hub, etc.).

| Column Name   | Data Type | Constraints | Description                                  |
|----------------|-----------|-------------|----------------------------------------------|
| device_id      | INTEGER   | PRIMARY KEY | Unique device ID from SurePet API.           |
| name           | TEXT      |             | Human-readable device name.                  |
| type           | TEXT      |             | Type of device (e.g., `CAT_FLAP`, `HUB`).    |
| battery_level  | INTEGER   |             | Battery percentage (0–100).                  |
| last_updated   | DATETIME  | NOT NULL    | Last status fetch timestamp.                 |

---

## 7. `users`

Stores information about SurePet users.

| Column Name | Data Type | Constraints | Description                       |
|--------------|-----------|-------------|-----------------------------------|
| user_id      | INTEGER   | PRIMARY KEY | User ID from SurePet              |
| name         | TEXT      |             | Human-readable name               |

---

## Size Estimates

Assuming each of your three cats is pinging GPS for 10 hours per day (every 10 seconds):

- **Pings per cat per day**:  
  `10 hours * 3600 seconds/hour / 10 = 3,600`

- **Rows per year for 3 cats**:  
  `3,600 pings/day * 365 days/year * 3 cats ≈ 3.94 million`

- **Estimated storage**:  
  `3.94 million rows * 64 bytes ≈ 252 MB`

Thus, even at high activity levels, one year of GPS data for 3 cats fits within 250–300 MB—well within the capacity of a standard SD card on a Raspberry Pi.
