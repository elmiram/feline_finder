# FelineFinder: Complete Project Documentation

## 1. Project Overview

FelineFinder is a self-hosted, full-stack application designed to provide comprehensive tracking and behavioral analysis for cats. It runs on a Raspberry Pi and consists of a backend data pipeline and a frontend web dashboard.

The backend continuously fetches data from two sources: Tractive GPS trackers and a SurePet smart cat flap. This data is permanently archived in a local SQLite database. The backend processes this raw data through a "Confidence Engine" to determine a high-confidence, real-time status for each cat.

The frontend is a single-page web application that provides an intuitive, interactive dashboard accessible from any device on the local network. It displays both the live status of the cats and a detailed historical analysis view for exploring long-term patterns.

The entire system is designed to be robust and autonomous, with its core components running as independent, auto-restarting services.

## 2. Backend Documentation

The backend is responsible for all data collection, storage, and processing. It is built with Python.

### 2.1. File Structure & Purpose

- `db_setup.py`: A one-time setup script that creates the `cat_tracker.db` SQLite database file and all necessary tables with the correct schema. It should only be run once on a new setup.
- `db_utils.py`: A shared utility library. It contains central configuration (API credentials, cat-to-ID mappings) and all database functions (connecting, inserting data, querying). It is not run directly but is imported by other scripts.
- `tractive_initial_fetch.py` & `surepet_initial_fetch.py`: One-time scripts for performing a large, historical data download from each service to populate the database with a baseline of data. They are resumable and can handle network interruptions.
- `tractive_collector.py` & `surepet_collector.py`: The main, long-running data collection services. Each script runs in a continuous loop, fetching only the newest data from its respective API to keep the database up-to-date.
- `api_server.py`: A Flask web server that acts as the bridge between the data and the user. It has two primary roles:
  - **API Provider**: Exposes JSON API endpoints (e.g., `/api/status`, `/api/history/gps`) that the frontend calls. It contains the "Confidence Engine" logic.
  - **Web Server**: Serves the final, built version of the React frontend application.

### 2.2. Deployment & Execution

- The backend runs within a dedicated Python virtual environment to keep its dependencies isolated.
- **Environment Location**: `~/elya-env/`
- **Installing Modules**: All Python modules must be installed using the virtual environment's pip:
  ```bash
  ~/elya-env/bin/pip install Flask
  ```
- **Running One-Time Scripts**: Use the virtual environment's Python interpreter:
  ```bash
  ~/elya-env/bin/python3 /home/elya/projects/cat_project/tractive_initial_fetch.py
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

- **Directory**: `feline-finder-frontend`
- `package.json`: Defines JavaScript dependencies and npm scripts.
- `public/index.html`: Main HTML page. Loads Tailwind CSS from a CDN.
- `src/index.js`: Entry point for the React app.
- `src/App.js`: Main React component with all UI and logic.
- `build/`: Final, optimized static files served by the Flask server.

### 3.2. Features & API Dependencies

#### Live Dashboard

- **Functionality**: Status card per cat (e.g., "At Home", "Outside"), battery level, confidence level, last 5 flap events.
- **API Endpoint**: `/api/status`

#### Historical Analysis

- **Functionality**: Select a cat and a time window (7, 14, or 30 days). Use a timeline slider to explore the past year. Includes:
  - **Territory Map**: Plots GPS points over known zones.
  - **Time Allocation Chart**: Shows time spent indoors vs. outdoors.
- **API Endpoints**:
  - `/api/history/gps?days=365`
  - `/api/history/events?days=365`
  - `/api/zones`

**Note**: Once data is fetched, all subsequent interaction is handled locally in-browser.

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
