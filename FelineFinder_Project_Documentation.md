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
- `tractive_backfill.py`: Backfills historical GPS data for a single tracker. Used by `api_server.py` when a tracker is assigned or reactivated via the Settings UI. Runs in a background daemon thread so the API response is immediate.
- `tractive_collector.py` & `surepet_collector.py`: Long-running data collection services. Each runs in a continuous loop fetching new data from its respective API. `tractive_collector` re-reads active trackers from the database each cycle, so tracker changes take effect without a restart.
- `api_server.py`: A Flask web server with two roles:
  - **API Provider**: Exposes JSON endpoints the frontend calls. Contains the Confidence Engine, zone detection, territory polygon calculation (DBSCAN + convex hull), and tracker management logic.
  - **Web Server**: Serves the built React application from `../feline-finder-frontend/build/`.

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

- Core components (`tractive_collector`, `surepet_collector`, `api_server`) are managed as systemd services.

**Checking Service Status**
```bash
sudo systemctl status tractive_collector.service
sudo systemctl status surepet_collector.service
sudo systemctl status api_server.service
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

- **Functionality**: Status card per cat (e.g., "At Home", "Outside"), battery level, confidence level, last 5 SurePet flap events, and last 5 GPS zone transitions. Grid layout adapts to the number of active cats.
- **API Endpoints**: `GET /api/status`, `GET /api/cats`

#### Historical Analysis

- **Functionality**: Select any cat (including inactive ones) and a time window. Use a timeline slider to explore the past year. Includes:
  - **Territory Map**: Plots GPS points over known zones, with DBSCAN-computed convex hull territory polygon.
  - **Time Allocation Chart**: Shows time spent indoors vs. outdoors.
- **API Endpoints**: `GET /api/history/gps`, `GET /api/history/events`, `GET /api/zones`

**Note**: Once data is fetched, all subsequent interaction is handled locally in-browser.

#### Settings — Tracker Management

- **Functionality**: Per-cat cards showing full tracker history (active and retired). Assign a new tracker ID when a collar is replaced; optionally provide the date it was lost to set the correct retirement date and backfill start. Re-activate a previously retired tracker with an optional gap-start date override.
- **API Endpoints**:
  - `GET /api/trackers` — returns per-cat tracker history
  - `POST /api/trackers/assign` — body: `{cat_name, tracker_id, lost_date?}` — retires current tracker, assigns new one, triggers background backfill
  - `POST /api/trackers/reactivate` — body: `{cat_name, tracker_id, lost_date?}` — retires current tracker, re-activates old one, backfills the gap only

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
