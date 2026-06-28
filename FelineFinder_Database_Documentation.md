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

## 8. `cat_territories`

Pre-computed alpha shape territory polygons for each cat, per week and per calendar month. Populated by `territory_compute.py` (batch backfill) and updated by the daily collector.

| Column Name      | Data Type | Constraints                                          | Description |
|------------------|-----------|------------------------------------------------------|-------------|
| id               | INTEGER   | PRIMARY KEY AUTOINCREMENT                            | Unique row ID. |
| internal_cat_id  | INTEGER   | NOT NULL                                             | Foreign key to `cat_identities.internal_cat_id`. |
| period_type      | TEXT      | NOT NULL                                             | `'week'` or `'month'`. |
| period_start     | TEXT      | NOT NULL                                             | ISO date: Monday for weeks, 1st for months. |
| period_end       | TEXT      | NOT NULL                                             | ISO date: Sunday for weeks, last day for months. |
| polygon_json     | TEXT      | NOT NULL                                             | JSON string of `[[lon, lat], ...]` — outer boundary ring. Coordinates in GeoJSON `[lon, lat]` order. |
| holes_json       | TEXT      |                                                      | JSON string of list of rings (each `[[lon, lat], ...]`) for inner holes, or NULL. |
| area_m2          | REAL      |                                                      | Territory area in m² (outer polygon minus holes), using equirectangular projection at lat 47.166. |
| area_change_pct  | REAL      |                                                      | % change vs previous period of same type. NULL for the first period. |
| ping_count       | INTEGER   |                                                      | Number of GPS pings used to compute this territory. |
| computed_at      | TEXT      | NOT NULL                                             | UTC datetime when this row was computed. |
| UNIQUE           |           | (internal_cat_id, period_type, period_start)         | One territory per cat per period. |

**Alpha parameter**: α=1500, validated against Tractive's W26 2026 territory for Arthur. **Min ping threshold**: 50 pings — weeks below this are skipped. Degenerate/collinear inputs (qhull errors) are caught and skipped.

---

## 9. `farthest_point_exclusions`

Per-cat date ranges to exclude from the farthest-point-from-home calculation (e.g. vet visits).

| Column Name     | Data Type | Constraints               | Description |
|-----------------|-----------|---------------------------|-------------|
| id              | INTEGER   | PRIMARY KEY AUTOINCREMENT | Unique row ID. |
| internal_cat_id | INTEGER   | NOT NULL                  | Foreign key to `cat_identities.internal_cat_id`. |
| date_from       | TEXT      | NOT NULL                  | Start of exclusion range (YYYY-MM-DD). |
| date_to         | TEXT      | NOT NULL                  | End of exclusion range (YYYY-MM-DD, inclusive). |
| reason          | TEXT      |                           | Optional label (e.g. "Vet visit"). |

Managed via `GET/POST/DELETE /api/stats/farthest/exclusions` and the Settings tab UI.

---

## 10. `weather_daily`

One row per calendar date with daily weather summary for Finstersee (lat 47.166, lon 8.628), fetched from Open-Meteo archive API. Used for weather correlation analysis.

| Column Name   | Data Type | Constraints    | Description |
|---------------|-----------|----------------|-------------|
| date          | TEXT      | PRIMARY KEY    | Local date in `YYYY-MM-DD` format (Europe/Zurich timezone). |
| temp_max      | REAL      |                | Daily maximum temperature in °C. |
| temp_min      | REAL      |                | Daily minimum temperature in °C. |
| precipitation | REAL      |                | Precipitation sum in mm. |
| snowfall      | REAL      |                | Snowfall sum in cm. |
| weathercode   | INTEGER   |                | WMO weather code (0=clear sky, 3=overcast, 61=rain, 71=snow, etc.). Stored raw; decode in frontend. |
| sunrise       | TEXT      |                | Sunrise datetime string (ISO, Europe/Zurich). |
| sunset        | TEXT      |                | Sunset datetime string (ISO, Europe/Zurich). |

Backfilled 2024-03-01 → present (850 rows) by `weather_backfill.py`. Updated daily at 07:00 by `weather_collector.py` via systemd user timer.

---

## 11. `cat_trips`

One row per detected outdoor trip, computed by merging SurePet flap events and GPS signals. Used by all activity pattern analysis endpoints.

| Column Name      | Data Type | Constraints                              | Description |
|------------------|-----------|------------------------------------------|-------------|
| id               | INTEGER   | PRIMARY KEY AUTOINCREMENT                | Unique row ID. |
| internal_cat_id  | INTEGER   | NOT NULL                                 | Foreign key to `cat_identities.internal_cat_id`. |
| start_time       | TEXT      | NOT NULL                                 | UTC datetime when the cat went outside. |
| end_time         | TEXT      |                                          | UTC datetime when the cat returned home. NULL if trip is still open. |
| duration_minutes | REAL      |                                          | Stored for query convenience. NULL if trip is open. |
| start_source     | TEXT      |                                          | How the trip start was detected: `'surepet_exit'`, `'gps_outdoor'`, or `'inferred'`. |
| end_source       | TEXT      |                                          | How the trip end was detected: `'surepet_entry'`, `'wifi_home'`, `'gps_home'`, or `'inferred'`. |
| confidence       | TEXT      |                                          | `'high'` (both ends SurePet flap), `'medium'` (one end flap), `'low'` (both ends GPS/WiFi inferred). |
| UNIQUE           |           | (internal_cat_id, start_time)            | One trip per cat per start time. |

**Important**: Trips with `duration_minutes > 1440` (24h) are tracker-offline data gaps misinterpreted as open trips — filter these out in queries. Use `AND duration_minutes <= 1440` for analysis. Backfilled by `trip_compute.py` (16,875 trips: Arthur 5,088 / King 7,842 / Trixie 3,945).

---

## 12. `surepet_events`

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

## 13. `devices`

Stores the status of SurePet hardware (flap, hub, etc.).

| Column Name   | Data Type | Constraints | Description                                  |
|----------------|-----------|-------------|----------------------------------------------|
| device_id      | INTEGER   | PRIMARY KEY | Unique device ID from SurePet API.           |
| name           | TEXT      |             | Human-readable device name.                  |
| type           | TEXT      |             | Type of device (e.g., `CAT_FLAP`, `HUB`).    |
| battery_level  | INTEGER   |             | Battery percentage (0–100).                  |
| last_updated   | DATETIME  | NOT NULL    | Last status fetch timestamp.                 |

---

## 14. `surepet_users`

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
