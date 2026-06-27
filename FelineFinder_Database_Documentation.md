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
| cat_name         | TEXT      | NOT NULL UNIQUE          | The human-readable name of the cat (e.g., "Arthur"). |
| surepet_pet_id   | INTEGER   | UNIQUE                   | The unique ID from the SurePet system.           |
| active           | INTEGER   | NOT NULL DEFAULT 1       | 1 = shown on live dashboard; 0 = hidden (e.g. deceased). Historical data is always preserved. |

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

| Column Name      | Data Type | Constraints               | Description                                                    |
|------------------|-----------|---------------------------|----------------------------------------------------------------|
| position_id      | INTEGER   | PRIMARY KEY AUTOINCREMENT | A unique ID for each GPS record.                              |
| internal_cat_id  | INTEGER   | NOT NULL                  | Foreign key to `cat_identities.internal_cat_id`.              |
| timestamp        | DATETIME  | NOT NULL                  | Timestamp of the GPS reading.                                  |
| latitude         | REAL      | NOT NULL                  | Latitude coordinate.                                           |
| longitude        | REAL      | NOT NULL                  | Longitude coordinate.                                          |
| accuracy         | REAL      |                           | GPS accuracy radius in metres (legacy column, same as pos_uncertainty). |
| speed            | REAL      |                           | Instantaneous speed in m/s from tracker firmware (may be NULL). |
| alt              | INTEGER   |                           | GPS altitude in metres.                                        |
| pos_uncertainty  | INTEGER   |                           | GPS accuracy radius in metres. Filter to ≤ 50m for precision queries. |
| sensor_used      | TEXT      |                           | `GPS` or `KNOWN_WIFI`. WiFi positions are cell-tower-level (100–500m); filter `sensor_used = 'GPS'` for territory/distance calculations. |
| course           | REAL      |                           | Heading/direction of travel in degrees (may be NULL).          |

**Note**: `speed`, `alt`, `pos_uncertainty`, `sensor_used`, and `course` were added June 2026. Rows collected before the migration have NULL in these columns; `backfill_extended_fields.py` retroactively populates them for active-tracker periods.

---

## 5. `tractive_health_daily`

Day-level summary of activity and sleep for fast dashboard queries and trend charts. Populated by `health_collector.py` (daily at 06:00) and `health_backfill.py` (historical).

| Column Name        | Data Type | Constraints               | Description                                                   |
|--------------------|-----------|---------------------------|---------------------------------------------------------------|
| id                 | INTEGER   | PRIMARY KEY AUTOINCREMENT | Unique row ID.                                                |
| internal_cat_id    | INTEGER   | NOT NULL                  | Foreign key to `cat_identities.internal_cat_id`.             |
| date               | TEXT      | NOT NULL                  | Local date in `YYYY-MM-DD` format.                            |
| active_minutes     | INTEGER   |                           | Total active minutes (`progress.achieved_minutes`).           |
| resting_hours      | REAL      |                           | Resting time in **hours** (`activity_distribution[resting].current`). |
| calories           | REAL      |                           | Estimated calories burned.                                    |
| minutes_day_sleep  | INTEGER   |                           | Day-sleep minutes from sleep overview.                        |
| minutes_night_sleep| INTEGER   |                           | Night-sleep minutes from sleep overview.                      |
| minutes_calm       | INTEGER   |                           | Calm/other minutes from sleep overview.                       |
| UNIQUE             |           | (internal_cat_id, date)   | One row per cat per day.                                      |

---

## 6. `tractive_hourly_activity`

One row per cat × day × hour; enables time-of-day analysis directly in SQL.

| Column Name     | Data Type | Constraints               | Description                                         |
|-----------------|-----------|---------------------------|-----------------------------------------------------|
| id              | INTEGER   | PRIMARY KEY AUTOINCREMENT | Unique row ID.                                      |
| internal_cat_id | INTEGER   | NOT NULL                  | Foreign key to `cat_identities.internal_cat_id`.   |
| date            | TEXT      | NOT NULL                  | Local date in `YYYY-MM-DD` format.                  |
| hour            | INTEGER   | NOT NULL                  | Clock hour 0–23 (0 = midnight).                     |
| active_minutes  | INTEGER   |                           | Active minutes in this hour (from hourly_distribution). |
| UNIQUE          |           | (internal_cat_id, date, hour) | One row per cat per day per hour.               |

Example query — average activity by hour of day:
```sql
SELECT hour, ROUND(AVG(active_minutes), 1) FROM tractive_hourly_activity WHERE internal_cat_id=? GROUP BY hour ORDER BY hour;
```

---

## 7. `tractive_sleep_phases`

One row per sleep phase span; enables sleep pattern and fragmentation analysis.

| Column Name     | Data Type | Constraints | Description                                                    |
|-----------------|-----------|-------------|----------------------------------------------------------------|
| id              | INTEGER   | PRIMARY KEY AUTOINCREMENT | Unique row ID.                                   |
| internal_cat_id | INTEGER   | NOT NULL    | Foreign key to `cat_identities.internal_cat_id`.              |
| date            | TEXT      | NOT NULL    | Local date in `YYYY-MM-DD` format.                             |
| time_offset     | INTEGER   | NOT NULL    | Minutes from midnight when this phase started.                 |
| time_span       | INTEGER   | NOT NULL    | Duration of this phase in minutes.                             |
| type            | TEXT      | NOT NULL    | Phase type: `NIGHT`, `DAY`, or `OTHER`.                        |

Example query — when does deep sleep (NIGHT) typically start?
```sql
SELECT ROUND(AVG(time_offset) / 60.0, 1) || 'h' FROM tractive_sleep_phases WHERE type='NIGHT' AND internal_cat_id=?;
```

---

## 9. `surepet_events`

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

## 10. `devices`

Stores the status of SurePet hardware (flap, hub, etc.).

| Column Name   | Data Type | Constraints | Description                                  |
|----------------|-----------|-------------|----------------------------------------------|
| device_id      | INTEGER   | PRIMARY KEY | Unique device ID from SurePet API.           |
| name           | TEXT      |             | Human-readable device name.                  |
| type           | TEXT      |             | Type of device (e.g., `CAT_FLAP`, `HUB`).    |
| battery_level  | INTEGER   |             | Battery percentage (0–100).                  |
| last_updated   | DATETIME  | NOT NULL    | Last status fetch timestamp.                 |

---

## 11. `surepet_users`

Stores information about SurePet users.

| Column Name | Data Type | Constraints | Description                       |
|--------------|-----------|-------------|-----------------------------------|
| user_id      | INTEGER   | PRIMARY KEY | User ID from SurePet              |
| name         | TEXT      |             | Human-readable name               |

---

## Size Estimates

Assuming each active cat is pinging GPS for 10 hours per day (every 10 seconds):

- **Pings per cat per day**:  
  `10 hours * 3600 seconds/hour / 10 = 3,600`

- **Rows per year for 2 active cats**:  
  `3,600 pings/day * 365 days/year * 2 cats ≈ 2.63 million`

- **Estimated storage**:  
  `2.63 million rows * 64 bytes ≈ 168 MB`

Thus, even at high activity levels, one year of GPS data fits well within the capacity of a standard SD card on a Raspberry Pi.
