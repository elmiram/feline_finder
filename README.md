# FelineFinder

**A self-hosted, full-stack application for advanced cat tracking and behavioral analysis.**

FelineFinder integrates data from Tractive GPS trackers and SurePet smart cat flaps to provide a high-confidence, real-time dashboard of your cat's location and status. It's designed to run 24/7 on a low-power local server, like a Raspberry Pi.

---

## ✨ Features

-   **Live Dashboard**: At-a-glance status for each cat ("At Home", "Outside", "In Driveway Zone"), including battery levels, recent flap events, and recent zone changes. Amber alert when a cat has been outside longer than their recent historical norm.
-   **Confidence Engine**: A smart backend engine that analyzes conflicting data from multiple sources (GPS, WiFi, cat flap events) to determine the most probable, accurate status.
-   **Territory Analysis**: Pre-computed alpha shape territory polygons (weekly + monthly) stored in the DB. View all cats' territories simultaneously on the same map. Territory area trend chart and Arthur ∩ King overlap stat.
-   **Favourite Spots Heatmap**: GPS ping density map using `leaflet.heat`, showing where each cat actually spends time within their territory.
-   **Zone Dwell Time**: Time spent per named zone for any date range, with monthly trend charts showing how zone preferences evolve across seasons.
-   **Farthest Point from Home**: All-time record excursion distance per cat, with configurable exclusion dates (e.g. vet visits).
-   **Activity Patterns**: 24-hour activity chart, seasonal outdoor hours trend (rolling 7-day average), and temperature/weather correlation scatter plot.
-   **Trip Statistics**: 16,000+ outdoor trips detected by merging SurePet flap events and GPS signals. Survival curve analysis ("what's the probability King is still out after 2 hours?").
-   **Weather Correlation**: Historical weather (Open-Meteo, free, no API key) joined with trip data. See whether your cats stay in when it rains.
-   **Event Log**: A real-time log of cat flap entries/exits, manual location settings, and GPS zone transitions.
-   **Zone Mapping**: Define custom zones (e.g., "Garden", "Neighbor's Yard") and see them visualized on the map.
-   **Tracker Management**: A Settings tab for reassigning a new tracker ID when a collar is lost or replaced. Automatically backfills historical GPS data in the background.
-   **Self-Hosted & Private**: All your data is stored locally in a SQLite database. No reliance on third-party cloud services for data aggregation.
-   **Robust & Autonomous**: Core components run as auto-restarting system services for maximum uptime.

## 🛠️ Tech Stack

-   **Backend**: Python, Flask
-   **Frontend**: React, Tailwind CSS
-   **Database**: SQLite
-   **Deployment**: systemd on a Linux-based system (e.g., Raspberry Pi OS)

## 🏗️ Architecture

The system is split into two main parts: a Python backend and a React frontend.

1.  **Data Collectors (`tractive_collector.py`, `surepet_collector.py`)**: Two independent Python scripts run as background services. They continuously poll their respective APIs for new data and store it in the central `cat_tracker.db` database.
2.  **API Server (`api_server.py`)**: A Flask server that reads from the database, runs the "Confidence Engine" logic, and exposes a clean JSON API for the frontend. It also serves the built React application.
3.  **Frontend (`feline-finder-frontend/`)**: A modern React single-page application that consumes the Flask API and presents the data in a user-friendly dashboard.
