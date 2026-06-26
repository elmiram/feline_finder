# FelineFinder

**A self-hosted, full-stack application for advanced cat tracking and behavioral analysis.**

FelineFinder integrates data from Tractive GPS trackers and SurePet smart cat flaps to provide a high-confidence, real-time dashboard of your cat's location and status. It's designed to run 24/7 on a low-power local server, like a Raspberry Pi.

---

## ✨ Features

-   **Live Dashboard**: At-a-glance status for each cat ("At Home", "Outside", "In Driveway Zone"), including battery levels, recent flap events, and recent zone changes.
-   **Confidence Engine**: A smart backend engine that analyzes conflicting data from multiple sources to determine the most probable, accurate status.
-   **Historical Analysis**: An interactive map view to explore your cat's GPS history and territory over custom time windows.
-   **Event Log**: A real-time log of cat flap entries/exits, manual location settings, and GPS zone transitions.
-   **Zone Mapping**: Define custom zones (e.g., "Garden", "Neighbor's Yard") and see them visualized on the map.
-   **Tracker Management**: A Settings tab for reassigning a new tracker ID when a collar is lost or replaced. Automatically backfills historical GPS data in the background. Supports re-activating a recovered tracker with gap-only backfill.
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
