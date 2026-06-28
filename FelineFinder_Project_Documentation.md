# FelineFinder: Complete Project Documentation

## 1. Project Overview

FelineFinder is a self-hosted, full-stack application designed to provide comprehensive tracking and behavioral analysis for cats. It runs on a Raspberry Pi and consists of a backend data pipeline and a frontend web dashboard.

The backend continuously fetches data from two sources: Tractive GPS trackers and a SurePet smart cat flap. This data is permanently archived in a local SQLite database. The backend processes this raw data through a "Confidence Engine" to determine a high-confidence, real-time status for each cat.

The frontend is a single-page web application that provides an intuitive, interactive dashboard accessible from any device on the local network. It displays both the live status of the cats and a detailed historical analysis view for exploring long-term patterns.

The entire system is designed to be robust and autonomous, with its core components running as independent, auto-restarting services.

## 2. Backend Documentation

The backend is responsible for all data collection, storage, and processing. It is built with Python.

### 2.1. File Structure & Purpose

- `config.py` *(gitignored)*: Holds all secrets and site-specific configuration — API credentials, `CAT_CONFIG`, and `KNOWN_ZONES`. Must be created manually on each deployment; never committed to the repo.
- `db_setup.py`: A one-time setup script that creates the `cat_tracker.db` SQLite database file and all necessary tables. Should only be run once on a new setup.
- `db_utils.py`: A shared utility library for all database access. Contains functions for querying and writing cat identities, tracker assignments, GPS positions, and flap events. Imported by other scripts; not run directly.
- `tractive_initial_fetch.py` & `surepet_initial_fetch.py`: One-time scripts for performing a large historical data download from each service to populate the database. Resumable and retry-safe.
- `tractive_backfill.py`: Backfills historical GPS data for a single tracker. Used by `api_server.py` when a tracker is assigned or reactivated via the Settings UI. Runs in a background daemon thread so the API response is immediate. Updated June 2026 to also write the extended GPS fields (speed, alt, pos_uncertainty, sensor_used, course).
- `backfill_extended_fields.py`: One-off script that retroactively populates the five new GPS columns (speed, alt, pos_uncertainty, sensor_used, course) for existing rows by re-fetching from the Tractive API. Chunked in 14-day windows with exponential backoff; resumable. Only affects rows where `sensor_used IS NULL`.
- `health_collector.py`: Daily collector (run by `health_collector.timer` at 06:00) that fetches yesterday's activity and sleep data for Arthur and King from `graph.tractive.com/4`. Writes to `tractive_health_daily`, `tractive_hourly_activity`, and `tractive_sleep_phases`.
- `health_backfill.py`: One-off script that fetches full health/sleep history from 2024-03-01 to today for Arthur and King. Resumable, zero-tolerant, exponential backoff per date.
- `tractive_collector.py` & `surepet_collector.py`: Long-running data collection services. Each runs in a continuous loop fetching new data from its respective API. `tractive_collector` re-reads active trackers from the database each cycle, so tracker changes take effect without a restart.
- `territory.py`: Alpha shape territory computation library. `grid_filter(pings, cell_size_m, min_count)` removes sparse pings; `compute_territory(pings, alpha=1500)` returns outer polygon + holes + area. Used by `territory_compute.py` and can be called on demand.
- `territory_compute.py`: Batch backfill script. Computes weekly (Mon–Sun) and monthly territory polygons for all cats and inserts into `cat_territories`. Resumable via `INSERT OR IGNORE`. Safe to re-run.
- `zone_utils.py`: Shared zone-labelling helper using Shapely prepared geometry. `label_pings(pings, known_zones)` is ~10× faster than a naive ray-cast loop, making it viable for 130k+ ping datasets.
- `location_state.py`: Shared "is the cat home?" confidence engine. Merges SurePet flap events and GPS/WiFi signals into a unified timeline, applies 10-minute bounce suppression, and extracts trips. Used by `trip_compute.py` and the live dashboard refresh logic in `api_server.py`.
- `trip_compute.py`: Batch backfill script. Runs `location_state.compute_trips()` for all cats and inserts results into `cat_trips`. Resumable.
- `weather_backfill.py`: One-off script that fetches all historical weather from Open-Meteo archive API (2024-03-01 → today). Free, no API key required. Inserts into `weather_daily`.
- `weather_collector.py`: Daily script (run by `weather_collector.timer` at 07:00) that fetches yesterday's weather and upserts into `weather_daily`.
- `api_server.py`: A Flask web server with two roles:
  - **API Provider**: Exposes JSON endpoints the frontend calls. Contains the Confidence Engine, zone detection, territory polygon calculation, tracker management, and all analysis endpoints listed in §3.2.
  - **Web Server**: Serves the built React application from `../feline-finder-frontend/build/`.
  - **Startup**: Must be launched from `~/projects/feline_finder/backend/` — `config.py` uses a relative path for the DB. Rolling P95 trip durations for the anomaly flag are computed at startup.

### 2.2. Deployment & Execution

- The backend runs within a dedicated Python virtual environment to keep its dependencies isolated.
- **Environment Location**: `~/elya-env/`
- **Project Location**: `~/projects/feline_finder/backend/`
- **Installing Modules**: All Python modules must be installed using the virtual environment's pip:
  ```bash
  ~/elya-env/bin/pip install Flask
  ```
- **Running One-Time Scripts**: Use the virtual environment's Python interpreter from the backend directory:
  ```bash
  cd ~/projects/feline_finder/backend
  ~/elya-env/bin/python3 tractive_initial_fetch.py
  ```

### 2.3. System Health & Monitoring

- Core components (`tractive_collector`, `surepet_collector`, `api_server`) are managed as systemd services. `health_collector` runs as a one-shot service triggered daily by `health_collector.timer`.

**Checking Service Status**
```bash
sudo systemctl status tractive_collector.service
sudo systemctl status surepet_collector.service
sudo systemctl status api_server.service
sudo systemctl status health_collector.timer
systemctl --user status weather_collector.timer   # runs as user, not root
```

**Viewing Logs**
```bash
journalctl -u <service_name>.service          # View all logs
journalctl -f -u <service_name>.service       # Follow logs in real-time
```

### 2.4. Database Debugging

- Open the database:
  ```bash
  sqlite3 cat_tracker.db
  ```

**Useful Queries**
```sql

-- List all tables
.tables

-- Count GPS points
SELECT COUNT(*) FROM tractive_gps_positions;

SELECT ci.cat_name, tgp.timestamp, tgp.latitude, tgp.longitude
FROM tractive_gps_positions AS tgp
JOIN cat_identities AS ci ON tgp.internal_cat_id = ci.internal_cat_id
WHERE tgp.rowid IN (SELECT MAX(rowid) FROM tractive_gps_positions GROUP BY internal_cat_id);

-- Get the last 5 flap events for "Trixie" with interpretations
SELECT
    T1.timestamp,
    CASE T1.event_source WHEN 0 THEN 'Cat Movement' WHEN 1 THEN 'Manual Update' WHEN 2 THEN 'Looked Through' ELSE 'Unknown' END AS event_type,
    CASE T1.direction WHEN 1 THEN 'Inside' WHEN 2 THEN 'Outside' ELSE 'Unknown' END AS direction
FROM surepet_events AS T1
JOIN cat_identities AS T2 ON T1.internal_cat_id = T2.internal_cat_id
WHERE T2.cat_name = 'Trixie'
ORDER BY T1.timestamp DESC
LIMIT 5;
```

- Exit SQLite:
  ```bash
  .quit
  ```

## 3. Frontend Documentation

The frontend is a modern single-page application (SPA) built with React. It runs in the user's web browser and communicates with `api_server.py` to get the data it displays.

### 3.1. File Structure & Purpose

The frontend code is organized into a modular structure to improve maintainability and readability.

- **`feline-finder-frontend/`**: The root directory for the React project.
  - **`package.json`**: Defines JavaScript dependencies and `npm` scripts for development and building.
  - **`public/`**: Contains the main `index.html` template and other static assets.
  - **`build/`**: The output directory for the final, optimized static files that are served by the Flask server. This directory is generated by the `npm run build` command.
  - **`src/`**: Contains all the application's source code.
    - **`components/`**: Holds small, reusable UI components that are the building blocks of the application. Examples include `StatusCard.js`, `TerritoryMap.js`, and `LoadingSpinner.js`.
    - **`views/`**: Contains larger components that represent a major section or "page" of the application, like the `DashboardView.js` and `HistoryView.js` tabs. These views assemble smaller components into a complete user interface.
    - **`utils/`**: A directory for helper functions that do not render any UI, such as date formatting (`time.js`).
    - **`App.js`**: The main application component. Manages top-level state (active view, cat status, zones, all cat names) and renders `DashboardView`, `HistoryView`, or `SettingsView` based on the active tab.
    - **`constants.js`**: Centralizes application-wide constants such as `API_BASE_URL`.
    - **`index.js`**: Main entry point that renders the `App` component into the DOM.

### 3.2. Features & API Dependencies

#### Live Dashboard

- **Functionality**: Status card per cat ("At Home", "Outside"), battery level, confidence level, last 5 SurePet flap events, last 5 GPS zone transitions. If a cat has been outside longer than the rolling 95th-percentile trip duration (computed over both 28-day and 7-day windows), the card shows an amber border and "Outside longer than usual" warning.
- **API Endpoints**: `GET /api/status` (includes `long_absence_flag`, `current_outdoor_duration_minutes`), `GET /api/cats`

#### Historical Analysis

Opens with **"All Cats"** selected in **Territory** view by default. Cat selector includes Arthur, King, Trixie, and "All Cats". All-Cats mode is only available in Territory view (auto-reverts to Arthur in Points/Heatmap).

- **Territory Map** (default view): Renders pre-computed alpha shape polygons from `cat_territories` DB table. In All-Cats mode, shows all three cats' territories simultaneously (amber / purple / teal). 300ms slider debounce. Falls back to "No territory data" if none computed for the period.
- **Heatmap view**: GPS ping density grid via `leaflet.heat`. Excludes KNOWN_WIFI pings.
- **Points view**: Raw GPS dots over known zone polygons.
- **Territory Area Trend**: Line chart of territory area (km²) over time for Arthur and King, from pre-computed weekly/monthly rows.
- **Territory Overlap**: Arthur ∩ King overlap % for the most recent shared period.
- **Record Distance from Home**: Per-cat all-time farthest GPS ping from home centroid (excluding configured exclusion dates), shown with date.
- **Zone Dwell Time**: Horizontal bar chart of time spent per zone in the selected window. Click any bar to open a monthly % trend modal.
- **Activity Patterns** (Arthur/King/Trixie selector):
  - 24-hour activity bar chart (fraction of days with outdoor time per hour)
  - Seasonal outdoor hours line chart (rolling 7-day average across full history)
  - Temperature vs outdoor hours scatter (dots coloured by weathercode bucket)
- **API Endpoints**: `GET /api/history/gps`, `GET /api/history/events`, `GET /api/history/heatmap`, `GET /api/zones`, `GET /api/territory/trend`, `GET /api/territory/weekly`, `GET /api/territory/overlap`, `GET /api/stats/farthest`, `GET /api/zones/dwell`, `GET /api/zones/trend`, `GET /api/trips`, `GET /api/activity/hourly`, `GET /api/activity/seasonal`, `GET /api/activity/weather_correlation`, `GET /api/activity/survival`

#### Settings

- **Tracker Management**: Per-cat tracker history, assign/reactivate trackers with background backfill.
- **Farthest Point Exclusions**: Per-cat table of date ranges to exclude from the record distance calculation (e.g. vet trips). Add/remove via form.
- **API Endpoints**:
  - `GET /api/trackers`, `POST /api/trackers/assign`, `POST /api/trackers/reactivate`
  - `GET /api/stats/farthest/exclusions`, `POST /api/stats/farthest/exclusions`, `DELETE /api/stats/farthest/exclusions/<id>`

### 3.3. Deployment & Execution

- **Installing Dependencies**:
  ```bash
  npm install
  ```

- **Development Mode**:
  ```bash
  npm start
  ```

- **Production Build**:
  ```bash
  npm run build
  ```

- **Restart API Server to Apply Changes**:
  ```bash
  sudo systemctl restart api_server.service
  ```
