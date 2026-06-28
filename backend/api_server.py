# api_server.py
#
# Description
# This script runs a Flask web server that provides API endpoints and serves the frontend.
# It now uses DBSCAN for clustering to remove outliers before computing the territory polygon.

import os
import math
import datetime
import requests
import numpy as np
from sklearn.cluster import DBSCAN
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS

from db_utils import (
    create_connection,
    get_internal_cat_id_by_name,
    get_tracker_history,
    retire_active_tracker,
    add_tracker_assignment,
    get_retired_tracker_gap_start,
)
from tractive_backfill import run_backfill_in_background

# --- Configuration ---
# KNOWN_ZONES = {
#     "HOME": [
#         [lat1, lon1], [lat2, lon2], ..., [latN, lonN]
#     ],
# }
from config import KNOWN_ZONES

# --- Farthest-point constants (home centroid, computed from KNOWN_ZONES["Home"] polygon) ---
HOME_LAT = 47.166391786

# --- Zone label cache (ping→zone labels, invalidated by ping count change) ---
_zone_label_cache = {}  # {internal_cat_id: {'labels': [...], 'timestamps': [...], 'count': int}}
HOME_LON = 8.629922381

def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# --- New Helper Functions ---

def calculate_territory(points):
    """
    Calculates the core territory from a list of GPS points using DBSCAN and Convex Hull.
    points: list of dicts with 'lat' and 'lon' keys.
    """
    if len(points) < 5: # Not enough points to form a meaningful cluster
        return []

    coords = np.array([[p['lat'], p['lon']] for p in points])
    
    # DBSCAN parameters
    # eps is the max distance between points to be considered neighbors.
    # ~30 meters in radians for haversine metric.
    eps = 30 / 6371000 
    min_samples = 5 # Min number of points to form a dense region.

    # Run DBSCAN
    db = DBSCAN(eps=eps, min_samples=min_samples, algorithm='ball_tree', metric='haversine').fit(np.radians(coords))
    
    # Get the core samples (points in clusters, excluding outliers)
    core_samples_mask = np.zeros_like(db.labels_, dtype=bool)
    core_samples_mask[db.core_sample_indices_] = True
    
    labels = db.labels_
    
    # Select only points that are part of a cluster (label != -1)
    clustered_points = coords[labels != -1]
    
    if len(clustered_points) < 3:
        return []

    # Compute the convex hull of the clustered points
    hull_points = convex_hull(clustered_points)
    return hull_points


def convex_hull(points):
    """Computes the convex hull of a set of 2D points."""
    points = np.array(points)
    if len(points) <= 3: return points.tolist()
    def cross_product(p1, p2, p3):
        return (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])
    sorted_points = sorted(points, key=lambda p: (p[0], p[1]))
    upper_hull, lower_hull = [], []
    for p in sorted_points:
        while len(upper_hull) >= 2 and cross_product(upper_hull[-2], upper_hull[-1], p) <= 0: upper_hull.pop()
        upper_hull.append(p)
    for p in reversed(sorted_points):
        while len(lower_hull) >= 2 and cross_product(lower_hull[-2], lower_hull[-1], p) <= 0: lower_hull.pop()
        lower_hull.append(p)
    
    hull = upper_hull[:-1] + lower_hull[:-1]
    return [p.tolist() for p in hull]

def is_point_in_polygon(point, polygon):
    lat, lon = point
    n = len(polygon)
    inside = False
    p1lat, p1lon = polygon[0]
    for i in range(n + 1):
        p2lat, p2lon = polygon[i % n]
        if min(p1lon, p2lon) < lon <= max(p1lon, p2lon):
            if lat <= max(p1lat, p2lat):
                if p1lon != p2lon:
                    lat_intersection = (lon - p1lon) * (p2lat - p1lat) / (p2lon - p1lon) + p1lat
                if p1lat == p2lat or lat <= lat_intersection:
                    inside = not inside
        p1lat, p1lon = p2lat, p2lon
    return inside

def get_zone_for_point(lat, lon):
    """Returns the zone name for a point, or None if outside all known zones."""
    for zone_name, polygon in KNOWN_ZONES.items():
        if is_point_in_polygon((lat, lon), polygon):
            return zone_name
    return None

def get_recent_zone_changes(positions, limit=5):
    """
    Given GPS positions (newest first), return the most recent zone transitions.
    Each entry: {to_zone, from_zone, entered_at}
    """
    changes = []
    prev_zone = None
    prev_time = None

    for pos in positions:
        current_zone = get_zone_for_point(pos['lat'], pos['lon'])
        if prev_zone is not None and current_zone != prev_zone:
            changes.append({
                'to_zone': prev_zone,
                'from_zone': current_zone,
                'entered_at': prev_time,
            })
            if len(changes) >= limit:
                break
        prev_zone = current_zone
        prev_time = pos['time']

    return changes

def get_human_readable_address(lat, lon):
    try:
        headers = {'User-Agent': 'FelineFinder/1.0 (Personal Project)'}
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18"
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        address = data.get('address', {})
        road = address.get('road', '')
        suburb = address.get('suburb', '')
        if road: return f"Near {road}"
        elif suburb: return f"In {suburb}"
        return "Unknown Area"
    except Exception as e:
        print(f"Reverse geocoding failed: {e}")
        return None

# --- Flask App Setup & Existing Functions ---

app = Flask(__name__, static_folder='../feline-finder-frontend/build')
CORS(app)

# ---------------------------------------------------------------------------
# Rolling P95 cache — computed once at startup, used by anomaly flag
# ---------------------------------------------------------------------------

def _compute_rolling_p95(conn, internal_cat_id, days):
    """Return the 95th-percentile trip duration (minutes) over the last `days` days.

    Returns None if fewer than 10 completed trips exist in the window.
    """
    cursor = conn.cursor()
    cursor.execute(
        """SELECT duration_minutes FROM cat_trips
           WHERE internal_cat_id = ?
             AND end_time IS NOT NULL
             AND duration_minutes IS NOT NULL
             AND duration_minutes <= 1440
             AND start_time >= datetime('now', ?)
           ORDER BY duration_minutes""",
        (internal_cat_id, f'-{days} days'),
    )
    rows = cursor.fetchall()
    durations = [r[0] for r in rows]
    n = len(durations)
    if n < 10:
        return None
    p95_idx = int(0.95 * n)
    return durations[p95_idx]


_rolling_p95 = {}  # {internal_cat_id: {'p95_28d': float|None, 'p95_7d': float|None}}


def _refresh_rolling_p95():
    conn = create_connection()
    if not conn:
        return
    for cat_name in ['Arthur', 'King']:
        row = conn.execute(
            "SELECT internal_cat_id FROM cat_identities WHERE cat_name=?", (cat_name,)
        ).fetchone()
        if not row:
            continue
        cat_id = row[0]
        _rolling_p95[cat_id] = {
            'p95_28d': _compute_rolling_p95(conn, cat_id, 28),
            'p95_7d': _compute_rolling_p95(conn, cat_id, 7),
        }
    conn.close()


_refresh_rolling_p95()

def get_latest_data_for_cats():
    conn = create_connection()
    if not conn: return None
    cats_data = {}
    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id, cat_name FROM cat_identities WHERE active = 1")
    cats = cursor.fetchall()
    for cat in cats:
        internal_cat_id, cat_name = cat['internal_cat_id'], cat['cat_name']
        cats_data[cat_name] = {'internal_id': internal_cat_id}
        cursor.execute("SELECT * FROM surepet_events WHERE internal_cat_id = ? ORDER BY timestamp DESC LIMIT 1", (internal_cat_id,))
        cats_data[cat_name]['surepet_event'] = cursor.fetchone()
        cursor.execute("SELECT * FROM surepet_events WHERE internal_cat_id = ? ORDER BY timestamp DESC LIMIT 5", (internal_cat_id,))
        cats_data[cat_name]['recent_events'] = [dict(row) for row in cursor.fetchall()]
        cursor.execute("SELECT * FROM tractive_hw_status WHERE internal_cat_id = ? ORDER BY timestamp DESC LIMIT 1", (internal_cat_id,))
        cats_data[cat_name]['tractive_status'] = cursor.fetchone()
        cursor.execute("SELECT * FROM tractive_gps_positions WHERE internal_cat_id = ? ORDER BY timestamp DESC LIMIT 1", (internal_cat_id,))
        cats_data[cat_name]['tractive_position'] = cursor.fetchone()
        cursor.execute("SELECT latitude, longitude, timestamp FROM tractive_gps_positions WHERE internal_cat_id = ? ORDER BY timestamp DESC LIMIT 500", (internal_cat_id,))
        cats_data[cat_name]['recent_positions'] = [{'lat': r['latitude'], 'lon': r['longitude'], 'time': r['timestamp']} for r in cursor.fetchall()]
        # Fetch open trip (end_time IS NULL) for anomaly detection
        cursor.execute(
            "SELECT start_time FROM cat_trips WHERE internal_cat_id = ? AND end_time IS NULL ORDER BY start_time DESC LIMIT 1",
            (internal_cat_id,),
        )
        cats_data[cat_name]['open_trip'] = cursor.fetchone()
    conn.close()
    return cats_data

def run_confidence_engine(cats_data):
    final_status = {}
    for cat_name, data in cats_data.items():
        status, confidence, evidence, location, location_detail = "Unknown", "Low", "Not enough data available.", None, None
        hw, flap, pos = data.get('tractive_status'), data.get('surepet_event'), data.get('tractive_position')
        if hw:
            if hw['state'] == 'NOT_REPORTING' and hw['state_reason'] == 'OUT_OF_BATTERY':
                status, confidence = "Location Unknown (Tracker Battery Dead)", "Low"
                evidence = f"Tracker offline. Last flap event was at {flap['timestamp']}." if flap else "Tracker offline."
            elif hw['is_charging'] == 1:
                status, confidence = "Tracker Charging", "Low"
                evidence = f"Tracker is charging at home. Last flap event was at {flap['timestamp']}." if flap else "Tracker is charging at home."
            elif hw['state'] == 'OPERATIONAL' and 'state_reason' in hw.keys() and hw['state_reason'] is not None and 'POWER_SAVING' in hw['state_reason']:
                if flap and flap['direction'] == 2:
                    status, confidence, evidence = "Near Home", "Medium", "Tracker in WiFi zone, but last flap event was an exit."
                else:
                    status, confidence, evidence = "At Home", "High", "Tracker connected to home WiFi."
            else:
                status, confidence = "Outside", "High"
                evidence = f"Last GPS ping at {pos['timestamp']}." if pos else "Tracker is outside but no recent GPS data."
                if flap and flap['direction'] == 1:
                    confidence, evidence = "Medium", evidence + " Note: Last flap event was an entry (suspected unlogged exit)."
        elif flap:
            status = "At Home (Presumed)" if flap['direction'] == 1 else "Outside (Presumed)"
            evidence = f"Last seen {'entering' if flap['direction'] == 1 else 'exiting'} via flap at {flap['timestamp']}."
            confidence = "Low"
        if pos:
            location = {'lat': pos['latitude'], 'lon': pos['longitude']}
            point = (pos['latitude'], pos['longitude'])
            in_zone = False
            for zone_name, polygon in KNOWN_ZONES.items():
                if is_point_in_polygon(point, polygon):
                    location_detail = f"Last seen in Zone: {zone_name}"
                    in_zone = True
                    break
            if not in_zone:
                address = get_human_readable_address(pos['latitude'], pos['longitude'])
                if address:
                    location_detail = f"Last seen {address}"
        zone_changes = get_recent_zone_changes(data.get('recent_positions', []))

        # --- Compute current outdoor duration and anomaly flag ---
        is_outside = status.lower().startswith('outside')
        current_outdoor_duration_minutes = None

        if is_outside:
            # Prefer open trip start time from cat_trips
            open_trip = data.get('open_trip')
            trip_start_str = open_trip['start_time'] if open_trip else None

            # Fallback: if no open trip, use last surepet exit timestamp
            if trip_start_str is None and flap and flap['direction'] == 2:
                trip_start_str = flap['timestamp']

            # Fallback 2: use the last GPS ping time (cat is known outside)
            if trip_start_str is None and pos:
                trip_start_str = pos['timestamp']

            if trip_start_str is not None:
                try:
                    # Parse trip start (strip timezone, treat as UTC naive)
                    ts = trip_start_str.strip().rstrip('Z')
                    for sep in ('+', '-'):
                        idx = ts.rfind(sep, 10)
                        if idx != -1 and len(ts) - idx == 6:
                            ts = ts[:idx]
                            break
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                                "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f"):
                        try:
                            trip_start_dt = datetime.datetime.strptime(ts, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        trip_start_dt = None
                    if trip_start_dt:
                        now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                        current_outdoor_duration_minutes = (now_utc - trip_start_dt).total_seconds() / 60.0
                except Exception:
                    pass

        # Anomaly flag: only if both P95 windows agree and current duration exceeds both
        long_absence_flag = False
        internal_cat_id_for_flag = data.get('internal_id')
        if (is_outside and current_outdoor_duration_minutes is not None
                and internal_cat_id_for_flag is not None):
            p95_data = _rolling_p95.get(internal_cat_id_for_flag, {})
            p95_28d = p95_data.get('p95_28d')
            p95_7d = p95_data.get('p95_7d')
            if (p95_28d is not None and p95_7d is not None
                    and current_outdoor_duration_minutes > p95_28d
                    and current_outdoor_duration_minutes > p95_7d):
                long_absence_flag = True

        final_status[cat_name] = {
            "name": cat_name, "status": status, "confidence": confidence,
            "evidence": evidence, "location": location, "location_detail": location_detail,
            "tractive_update_time": hw['timestamp'] if hw else None,
            "surepet_update_time": flap['timestamp'] if flap else None,
            "battery_level": hw['battery_level'] if hw else None,
            "is_charging": hw['is_charging'] == 1 if hw else None,
            "recent_events": data.get('recent_events', []),
            "recent_zone_changes": zone_changes,
            "current_outdoor_duration_minutes": round(current_outdoor_duration_minutes, 1) if current_outdoor_duration_minutes is not None else None,
            "long_absence_flag": long_absence_flag,
        }
    return final_status

@app.route('/api/status')
def get_status():
    latest_data = get_latest_data_for_cats()
    if not latest_data: return jsonify({"error": "Could not retrieve data from database"}), 500
    final_statuses = run_confidence_engine(latest_data)
    return jsonify(final_statuses)

@app.route('/api/zones')
def get_zones():
    return jsonify(KNOWN_ZONES)

@app.route('/api/cats')
def get_cats():
    conn = create_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    cursor.execute("SELECT cat_name FROM cat_identities ORDER BY cat_name")
    names = [row['cat_name'] for row in cursor.fetchall()]
    conn.close()
    return jsonify(names)

@app.route('/api/history/gps')
def get_gps_history():
    cat_name = request.args.get('cat_name')
    # The frontend will send ISO format strings for dates
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    conn = create_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    cat_row = cursor.fetchone()
    if not cat_row: return jsonify({"error": "Cat not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']
    
    cursor.execute("""
        SELECT latitude, longitude, timestamp FROM tractive_gps_positions
        WHERE internal_cat_id = ? AND timestamp BETWEEN ? AND ?
        ORDER BY timestamp ASC
    """, (internal_cat_id, start_date_str, end_date_str))
    
    positions = [{'lat': r['latitude'], 'lon': r['longitude'], 'time': r['timestamp']} for r in cursor.fetchall()]
    
    # Calculate territory polygon using DBSCAN and Convex Hull on the filtered data
    territory_polygon = calculate_territory(positions)

    conn.close()
    return jsonify({"positions": positions, "territory_polygon": territory_polygon})


@app.route('/api/history/events')
def get_event_history():
    cat_name = request.args.get('cat_name')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    conn = create_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    cat_row = cursor.fetchone()
    if not cat_row: return jsonify({"error": "Cat not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']
    
    cursor.execute("""
        SELECT timestamp, event_source, direction, user_id FROM surepet_events
        WHERE internal_cat_id = ? AND timestamp BETWEEN ? AND ?
        ORDER BY timestamp ASC
    """, (internal_cat_id, start_date_str, end_date_str))
    events = [{'time': r['timestamp'], 'source': r['event_source'], 'direction': r['direction'], 'user_id': r['user_id']} for r in cursor.fetchall()]
    conn.close()
    return jsonify(events)

@app.route('/api/trackers')
def get_trackers():
    conn = create_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    history = get_tracker_history(conn)
    conn.close()
    return jsonify(history)

@app.route('/api/trackers/assign', methods=['POST'])
def assign_tracker():
    """Retire the current tracker for a cat, assign a new one, and kick off a full backfill.
    Optional lost_date (YYYY-MM-DD) marks when the cat actually lost the old tracker —
    it becomes the retired_date on the old assignment and the backfill start for the new one."""
    data = request.get_json()
    cat_name = data.get('cat_name')
    new_tracker_id = data.get('tracker_id', '').strip().upper()
    lost_date_str = data.get('lost_date')  # optional YYYY-MM-DD

    if not cat_name or not new_tracker_id:
        return jsonify({"error": "cat_name and tracker_id are required"}), 400

    conn = create_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500

    internal_cat_id = get_internal_cat_id_by_name(conn, cat_name)
    if not internal_cat_id:
        conn.close()
        return jsonify({"error": f"Cat '{cat_name}' not found"}), 404

    retired = retire_active_tracker(conn, internal_cat_id, retired_at=lost_date_str)
    add_tracker_assignment(conn, internal_cat_id, new_tracker_id)
    conn.close()

    start_from = datetime.datetime.fromisoformat(lost_date_str) if lost_date_str else None
    run_backfill_in_background(new_tracker_id, internal_cat_id, start_from=start_from)

    return jsonify({
        "success": True,
        "retired": retired,
        "new_tracker_id": new_tracker_id,
        "lost_date": lost_date_str,
        "message": "Tracker assigned. Historical backfill running in background."
    })

@app.route('/api/trackers/reactivate', methods=['POST'])
def reactivate_tracker():
    """Re-activate a previously retired tracker, backfilling only the gap since it was retired.
    Optional lost_date (YYYY-MM-DD) overrides the gap start (useful when the DB retired_date is wrong)."""
    data = request.get_json()
    cat_name = data.get('cat_name')
    tracker_id = data.get('tracker_id', '').strip().upper()
    lost_date_str = data.get('lost_date')  # optional YYYY-MM-DD override

    if not cat_name or not tracker_id:
        return jsonify({"error": "cat_name and tracker_id are required"}), 400

    conn = create_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500

    internal_cat_id = get_internal_cat_id_by_name(conn, cat_name)
    if not internal_cat_id:
        conn.close()
        return jsonify({"error": f"Cat '{cat_name}' not found"}), 404

    gap_start_str = lost_date_str or get_retired_tracker_gap_start(conn, internal_cat_id, tracker_id)
    retired = retire_active_tracker(conn, internal_cat_id)
    add_tracker_assignment(conn, internal_cat_id, tracker_id)
    conn.close()

    start_from = datetime.datetime.fromisoformat(gap_start_str) if gap_start_str else None
    run_backfill_in_background(tracker_id, internal_cat_id, start_from=start_from)

    return jsonify({
        "success": True,
        "retired": retired,
        "reactivated_tracker_id": tracker_id,
        "gap_start": gap_start_str,
        "message": "Tracker reactivated. Gap backfill running in background."
    })

@app.route('/api/territory/trend')
def get_territory_trend():
    cat_name = request.args.get('cat_name')
    if not cat_name:
        return jsonify({"error": "cat_name is required"}), 400

    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    cat_row = cursor.fetchone()
    if not cat_row:
        conn.close()
        return jsonify({"error": f"Cat '{cat_name}' not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']

    cursor.execute("""
        SELECT period_start, period_type, area_m2, area_change_pct
        FROM cat_territories
        WHERE internal_cat_id = ?
        ORDER BY period_type, period_start
    """, (internal_cat_id,))
    rows = cursor.fetchall()
    conn.close()

    trend = [
        {
            "period_start": r['period_start'],
            "period_type": r['period_type'],
            "area_m2": r['area_m2'],
            "area_change_pct": r['area_change_pct'],
        }
        for r in rows
    ]
    return jsonify({"cat_name": cat_name, "trend": trend})


@app.route('/api/territory/weekly')
def get_territory_weekly():
    cat_name = request.args.get('cat_name')
    if not cat_name:
        return jsonify({"error": "cat_name is required"}), 400
    try:
        limit = int(request.args.get('limit', 52))
    except ValueError:
        limit = 52

    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    cat_row = cursor.fetchone()
    if not cat_row:
        conn.close()
        return jsonify({"error": f"Cat '{cat_name}' not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']

    cursor.execute("""
        SELECT period_start, period_end, polygon_json, holes_json, area_m2, ping_count
        FROM cat_territories
        WHERE internal_cat_id = ? AND period_type = 'week'
        ORDER BY period_start DESC
        LIMIT ?
    """, (internal_cat_id, limit))
    rows = cursor.fetchall()
    conn.close()

    territories = [
        {
            "period_start": r['period_start'],
            "period_end": r['period_end'],
            "polygon_json": r['polygon_json'],
            "holes_json": r['holes_json'],
            "area_m2": r['area_m2'],
            "ping_count": r['ping_count'],
        }
        for r in rows
    ]
    return jsonify({"cat_name": cat_name, "territories": territories})


@app.route('/api/territory/overlap')
def get_territory_overlap():
    import json as _json
    import math
    import shapely.geometry

    period_start = request.args.get('period_start')
    period_type = request.args.get('period_type')
    if not period_start or not period_type:
        return jsonify({"error": "period_start and period_type are required"}), 400

    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()

    # Look up Arthur and King internal IDs
    cat_ids = {}
    for name in ('Arthur', 'King'):
        cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (name,))
        row = cursor.fetchone()
        if row:
            cat_ids[name] = row['internal_cat_id']

    # Fetch territory rows for each cat
    cat_data = {}
    for name, internal_cat_id in cat_ids.items():
        cursor.execute("""
            SELECT polygon_json, holes_json, area_m2
            FROM cat_territories
            WHERE internal_cat_id = ? AND period_start = ? AND period_type = ?
        """, (internal_cat_id, period_start, period_type))
        row = cursor.fetchone()
        if row:
            cat_data[name] = dict(row)

    conn.close()

    missing = [name for name in ('Arthur', 'King') if name not in cat_data]

    def build_shapely_poly(poly_json_str, holes_json_str):
        outer = [tuple(pt) for pt in _json.loads(poly_json_str)]
        holes = []
        if holes_json_str:
            for ring in _json.loads(holes_json_str):
                holes.append([tuple(pt) for pt in ring])
        return shapely.geometry.Polygon(outer, holes)

    response = {
        "period_start": period_start,
        "period_type": period_type,
        "arthur": None,
        "king": None,
        "overlap": None,
        "missing": missing,
    }

    for name in ('Arthur', 'King'):
        if name in cat_data:
            d = cat_data[name]
            response[name.lower()] = {
                "area_m2": d['area_m2'],
                "polygon_json": d['polygon_json'],
                "holes_json": d['holes_json'],
            }

    if not missing:
        arthur_poly = build_shapely_poly(cat_data['Arthur']['polygon_json'], cat_data['Arthur']['holes_json'])
        king_poly = build_shapely_poly(cat_data['King']['polygon_json'], cat_data['King']['holes_json'])
        intersection = arthur_poly.intersection(king_poly)

        # Overlap percentage: ratio of intersection to smaller territory (in degree² — projection cancels)
        overlap_pct = 0.0
        if min(arthur_poly.area, king_poly.area) > 0:
            overlap_pct = intersection.area / min(arthur_poly.area, king_poly.area) * 100

        # Convert intersection area from degrees² to m² using local scale factor
        cos_lat = math.cos(47.166 * math.pi / 180)
        area_m2 = intersection.area * (111320 ** 2) * cos_lat

        response['overlap'] = {
            "area_m2": area_m2,
            "overlap_pct": overlap_pct,
            "geometry_json": _json.dumps(shapely.geometry.mapping(intersection)),
        }

    return jsonify(response)


@app.route('/api/history/heatmap')
def get_gps_heatmap():
    cat_name = request.args.get('cat_name')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    try:
        grid_size = int(request.args.get('grid_size', 20))
    except ValueError:
        grid_size = 20

    # Default to 90-day window if not provided
    now = datetime.datetime.now(datetime.timezone.utc)
    if not end_date_str:
        end_date_str = now.isoformat()
    if not start_date_str:
        start_date_str = (now - datetime.timedelta(days=90)).isoformat()

    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    cat_row = cursor.fetchone()
    if not cat_row:
        conn.close()
        return jsonify({"error": "Cat not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']

    cursor.execute("""
        SELECT latitude, longitude FROM tractive_gps_positions
        WHERE internal_cat_id = ?
          AND timestamp >= ? AND timestamp <= ?
          AND (sensor_used IS NULL OR sensor_used = 'GPS')
    """, (internal_cat_id, start_date_str, end_date_str))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return jsonify({"cells": [], "max_count": 0})

    lats = [r['latitude'] for r in rows]
    lons = [r['longitude'] for r in rows]

    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    lat_range = max_lat - min_lat or 1e-6
    lon_range = max_lon - min_lon or 1e-6

    counts = {}
    for r in rows:
        ci = min(int((r['latitude'] - min_lat) / lat_range * grid_size), grid_size - 1)
        cj = min(int((r['longitude'] - min_lon) / lon_range * grid_size), grid_size - 1)
        counts[(ci, cj)] = counts.get((ci, cj), 0) + 1

    max_count = max(counts.values())
    cells = []
    for (ci, cj), count in counts.items():
        centroid_lat = min_lat + (ci + 0.5) / grid_size * lat_range
        centroid_lon = min_lon + (cj + 0.5) / grid_size * lon_range
        cells.append({"lat": centroid_lat, "lon": centroid_lon, "count": count})

    return jsonify({"cells": cells, "max_count": max_count})


@app.route('/api/stats/farthest')
def get_farthest_point():
    cat_name = request.args.get('cat_name')
    if not cat_name:
        return jsonify({"error": "cat_name is required"}), 400

    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    cat_row = cursor.fetchone()
    if not cat_row:
        conn.close()
        return jsonify({"error": f"Cat '{cat_name}' not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']

    cursor.execute("""
        SELECT date_from, date_to FROM farthest_point_exclusions
        WHERE internal_cat_id = ?
    """, (internal_cat_id,))
    exclusions = [(row['date_from'], row['date_to']) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT latitude, longitude, timestamp FROM tractive_gps_positions
        WHERE internal_cat_id = ? AND (sensor_used IS NULL OR sensor_used = 'GPS')
    """, (internal_cat_id,))
    rows = cursor.fetchall()
    conn.close()

    best_dist = -1
    best_row = None
    for row in rows:
        ts = row['timestamp']
        ping_date = ts[:10]  # YYYY-MM-DD
        excluded = any(df <= ping_date <= dt for df, dt in exclusions)
        if excluded:
            continue
        dist = _haversine_km(HOME_LAT, HOME_LON, row['latitude'], row['longitude'])
        if dist > best_dist:
            best_dist = dist
            best_row = row

    if best_row is None:
        return jsonify({"distance_km": None, "lat": None, "lon": None, "timestamp": None})

    return jsonify({
        "distance_km": round(best_dist, 4),
        "lat": best_row['latitude'],
        "lon": best_row['longitude'],
        "timestamp": best_row['timestamp'],
    })


@app.route('/api/stats/farthest/exclusions', methods=['GET'])
def get_farthest_exclusions():
    cat_name = request.args.get('cat_name')
    if not cat_name:
        return jsonify({"error": "cat_name is required"}), 400

    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    cat_row = cursor.fetchone()
    if not cat_row:
        conn.close()
        return jsonify({"error": f"Cat '{cat_name}' not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']

    cursor.execute("""
        SELECT id, date_from, date_to, reason FROM farthest_point_exclusions
        WHERE internal_cat_id = ?
        ORDER BY date_from
    """, (internal_cat_id,))
    exclusions = [
        {"id": r['id'], "date_from": r['date_from'], "date_to": r['date_to'], "reason": r['reason']}
        for r in cursor.fetchall()
    ]
    conn.close()
    return jsonify({"exclusions": exclusions})


@app.route('/api/stats/farthest/exclusions', methods=['POST'])
def add_farthest_exclusion():
    cat_name = request.args.get('cat_name')
    if not cat_name:
        return jsonify({"error": "cat_name is required"}), 400

    body = request.get_json()
    date_from = body.get('date_from')
    date_to = body.get('date_to')
    reason = body.get('reason', '')
    if not date_from or not date_to:
        return jsonify({"error": "date_from and date_to are required"}), 400

    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    cat_row = cursor.fetchone()
    if not cat_row:
        conn.close()
        return jsonify({"error": f"Cat '{cat_name}' not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']

    cursor.execute("""
        INSERT INTO farthest_point_exclusions (internal_cat_id, date_from, date_to, reason)
        VALUES (?, ?, ?, ?)
    """, (internal_cat_id, date_from, date_to, reason))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return jsonify({"id": new_id, "status": "created"}), 201


@app.route('/api/stats/farthest/exclusions/<int:exclusion_id>', methods=['DELETE'])
def delete_farthest_exclusion(exclusion_id):
    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    cursor.execute("DELETE FROM farthest_point_exclusions WHERE id = ?", (exclusion_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


@app.route('/api/zones/dwell')
def get_zone_dwell():
    import sys as _sys
    import os as _os
    _sys.path.insert(0, _os.path.dirname(__file__))
    from zone_utils import label_pings

    cat_name = request.args.get('cat_name')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    if not cat_name:
        return jsonify({"error": "cat_name is required"}), 400

    now = datetime.datetime.now(datetime.timezone.utc)
    if not end_date_str:
        end_date_str = now.isoformat()
    if not start_date_str:
        start_date_str = (now - datetime.timedelta(days=30)).isoformat()

    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    cat_row = cursor.fetchone()
    if not cat_row:
        conn.close()
        return jsonify({"error": f"Cat '{cat_name}' not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']

    cursor.execute("""
        SELECT latitude, longitude, timestamp FROM tractive_gps_positions
        WHERE internal_cat_id = ?
          AND timestamp >= ? AND timestamp <= ?
          AND (sensor_used IS NULL OR sensor_used = 'GPS')
        ORDER BY timestamp
    """, (internal_cat_id, start_date_str, end_date_str))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return jsonify([])

    pings = [(r['latitude'], r['longitude']) for r in rows]
    timestamps_raw = [r['timestamp'] for r in rows]

    zone_labels = label_pings(pings, KNOWN_ZONES)

    # Parse timestamps
    def parse_ts(s):
        s = s.replace('Z', '+00:00')
        try:
            return datetime.datetime.fromisoformat(s)
        except ValueError:
            # Fallback: strip trailing fractional seconds beyond 6 digits
            return datetime.datetime.fromisoformat(s[:26])

    timestamps = [parse_ts(t) for t in timestamps_raw]

    # Accumulate dwell per zone using consecutive deltas
    zone_seconds = {}
    zone_visits = {}
    prev_zone = None

    for i in range(len(pings) - 1):
        delta = (timestamps[i + 1] - timestamps[i]).total_seconds()
        # Cap at 300 s (5 min) to avoid inflating dwell during GPS gaps
        delta = min(delta, 300)
        if delta <= 0:
            continue

        z = zone_labels[i]
        if z is None:
            prev_zone = None
            continue

        zone_seconds[z] = zone_seconds.get(z, 0) + delta

        # Count visit: transition into zone
        if z != prev_zone:
            zone_visits[z] = zone_visits.get(z, 0) + 1

        prev_zone = z

    if not zone_seconds:
        return jsonify([])

    total_zone_seconds = sum(zone_seconds.values())

    result = []
    for zone_name, secs in zone_seconds.items():
        minutes = secs / 60.0
        visits = zone_visits.get(zone_name, 1)
        result.append({
            "zone_name": zone_name,
            "total_minutes": round(minutes, 1),
            "pct_of_total": round(secs / total_zone_seconds * 100, 1) if total_zone_seconds > 0 else 0,
            "visit_count": visits,
            "avg_visit_minutes": round(minutes / visits, 1) if visits > 0 else 0,
        })

    result.sort(key=lambda x: x['total_minutes'], reverse=True)
    return jsonify(result)


@app.route('/api/zones/trend')
def get_zone_trend():
    import sys as _sys
    import os as _os
    _sys.path.insert(0, _os.path.dirname(__file__))
    from zone_utils import label_pings

    cat_name = request.args.get('cat_name')
    zone_name = request.args.get('zone_name')

    if not cat_name or not zone_name:
        return jsonify({"error": "cat_name and zone_name are required"}), 400

    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    cat_row = cursor.fetchone()
    if not cat_row:
        conn.close()
        return jsonify({"error": f"Cat '{cat_name}' not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']

    cursor.execute("""
        SELECT latitude, longitude, timestamp FROM tractive_gps_positions
        WHERE internal_cat_id = ?
          AND (sensor_used IS NULL OR sensor_used = 'GPS')
        ORDER BY timestamp
    """, (internal_cat_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return jsonify([])

    def parse_ts(s):
        s = s.replace('Z', '+00:00')
        try:
            return datetime.datetime.fromisoformat(s)
        except ValueError:
            return datetime.datetime.fromisoformat(s[:26])

    # Bulk-label all pings, then aggregate dwell per zone per month
    from collections import defaultdict

    # Cache zone labels by cat — invalidated when ping count changes
    cached = _zone_label_cache.get(internal_cat_id)
    if cached is not None and cached['count'] == len(rows):
        zone_labels = cached['labels']
        timestamps_cached = cached['timestamps']
    else:
        pings = [(r['latitude'], r['longitude']) for r in rows]
        zone_labels = label_pings(pings, KNOWN_ZONES)
        timestamps_cached = [r['timestamp'] for r in rows]
        _zone_label_cache[internal_cat_id] = {
            'labels': zone_labels,
            'timestamps': timestamps_cached,
            'count': len(rows),
        }

    month_zone_seconds2 = defaultdict(lambda: defaultdict(float))
    month_total_seconds2 = defaultdict(float)
    month_ping_counts2 = defaultdict(int)

    for i in range(len(timestamps_cached) - 1):
        ts_cur = parse_ts(timestamps_cached[i])
        ts_next = parse_ts(timestamps_cached[i + 1])
        month = ts_cur.strftime('%Y-%m')
        month_ping_counts2[month] += 1

        delta = (ts_next - ts_cur).total_seconds()
        delta = min(delta, 300)
        if delta <= 0:
            continue

        z = zone_labels[i]
        if z is not None:
            month_zone_seconds2[month][z] += delta
            month_total_seconds2[month] += delta

    # Build result for requested zone_name — only months with >= 100 pings
    result = []
    for month in sorted(month_ping_counts2.keys()):
        if month_ping_counts2[month] < 100:
            continue
        total = month_total_seconds2.get(month, 0)
        if total <= 0:
            continue
        zone_secs = month_zone_seconds2[month].get(zone_name, 0)
        pct = zone_secs / total * 100 if total > 0 else 0
        result.append({
            "month": month,
            "pct_of_total": round(pct, 1),
        })

    return jsonify(result)


@app.route('/api/trips')
def get_trips():
    """Return trips from cat_trips table plus aggregate stats.

    Query params:
      cat_name   (required)
      start_date (optional, YYYY-MM-DD or ISO)
      end_date   (optional, YYYY-MM-DD or ISO)
    """
    cat_name = request.args.get('cat_name')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    if not cat_name:
        return jsonify({"error": "cat_name is required"}), 400

    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    cursor.execute(
        "SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,)
    )
    cat_row = cursor.fetchone()
    if not cat_row:
        conn.close()
        return jsonify({"error": f"Cat '{cat_name}' not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']

    # Build query with optional date filters
    params = [internal_cat_id]
    where_clauses = ["internal_cat_id = ?"]
    if start_date:
        where_clauses.append("start_time >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("start_time <= ?")
        params.append(end_date)

    query = (
        "SELECT id, start_time, end_time, duration_minutes, start_source, end_source, confidence "
        "FROM cat_trips WHERE " + " AND ".join(where_clauses) + " ORDER BY start_time DESC"
    )
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    trips = [
        {
            "id": r['id'],
            "start_time": r['start_time'],
            "end_time": r['end_time'],
            "duration_minutes": r['duration_minutes'],
            "start_source": r['start_source'],
            "end_source": r['end_source'],
            "confidence": r['confidence'],
        }
        for r in rows
    ]

    # Aggregate stats over completed trips only
    completed = [t["duration_minutes"] for t in trips if t["duration_minutes"] is not None]
    stats = {"count": len(completed), "median_minutes": None, "max_minutes": None, "min_minutes": None}
    if completed:
        completed_sorted = sorted(completed)
        n = len(completed_sorted)
        mid = n // 2
        stats["median_minutes"] = (
            completed_sorted[mid]
            if n % 2 == 1
            else (completed_sorted[mid - 1] + completed_sorted[mid]) / 2.0
        )
        stats["max_minutes"] = completed_sorted[-1]
        stats["min_minutes"] = completed_sorted[0]

    return jsonify({"trips": trips, "stats": stats})


@app.route('/api/activity/hourly')
def get_activity_hourly():
    """Return fraction of days in range where the cat was outside during each hour 0-23.

    Query params:
      cat_name   (required)
      start_date (optional, defaults to 90 days ago)
      end_date   (optional, defaults to now)
    """
    cat_name = request.args.get('cat_name')
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')

    if not cat_name:
        return jsonify({"error": "cat_name is required"}), 400

    now = datetime.datetime.now(datetime.timezone.utc)
    if not end_date_str:
        end_date_str = now.isoformat()
    if not start_date_str:
        start_date_str = (now - datetime.timedelta(days=90)).isoformat()

    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    cat_row = cursor.fetchone()
    if not cat_row:
        conn.close()
        return jsonify({"error": f"Cat '{cat_name}' not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']

    cursor.execute("""
        SELECT start_time, end_time FROM cat_trips
        WHERE internal_cat_id = ?
          AND start_time >= ?
          AND end_time <= ?
          AND duration_minutes <= 1440
          AND end_time IS NOT NULL
    """, (internal_cat_id, start_date_str, end_date_str))
    rows = cursor.fetchall()
    conn.close()

    def _parse_dt(s):
        s = s.replace('Z', '+00:00')
        try:
            return datetime.datetime.fromisoformat(s)
        except ValueError:
            return datetime.datetime.fromisoformat(s[:26] + '+00:00')

    # For each hour 0-23: set of distinct dates that had outdoor activity
    hour_days = {h: set() for h in range(24)}
    all_dates = set()

    for row in rows:
        start_dt = _parse_dt(row['start_time'])
        end_dt = _parse_dt(row['end_time'])
        all_dates.add(start_dt.date())
        # Walk hour-by-hour from floor(start) to past end
        cursor_dt = start_dt.replace(minute=0, second=0, microsecond=0)
        while cursor_dt <= end_dt:
            hour_days[cursor_dt.hour].add(cursor_dt.date())
            cursor_dt += datetime.timedelta(hours=1)

    total_days = len(all_dates) or 1

    result = [
        {"hour": h, "outdoor_fraction": round(len(hour_days[h]) / total_days, 4)}
        for h in range(24)
    ]
    return jsonify(result)


@app.route('/api/activity/seasonal')
def get_activity_seasonal():
    """Return daily outdoor hours across all history for a rolling trend line.

    Query params:
      cat_name (required)
    """
    cat_name = request.args.get('cat_name')
    if not cat_name:
        return jsonify({"error": "cat_name is required"}), 400

    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    cat_row = cursor.fetchone()
    if not cat_row:
        conn.close()
        return jsonify({"error": f"Cat '{cat_name}' not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']

    cursor.execute("""
        SELECT start_time, end_time, duration_minutes FROM cat_trips
        WHERE internal_cat_id = ?
          AND end_time IS NOT NULL
          AND duration_minutes <= 1440
        ORDER BY start_time
    """, (internal_cat_id,))
    rows = cursor.fetchall()
    conn.close()

    # Group by date of start_time, sum duration_minutes
    from collections import defaultdict
    daily_minutes = defaultdict(float)
    for row in rows:
        date_str = row['start_time'][:10]  # YYYY-MM-DD
        daily_minutes[date_str] += row['duration_minutes']

    result = [
        {"date": d, "outdoor_hours": round(mins / 60.0, 3)}
        for d, mins in sorted(daily_minutes.items())
    ]
    return jsonify(result)


@app.route('/api/activity/weather_correlation')
def get_activity_weather_correlation():
    """Join daily outdoor hours with weather data.

    Query params:
      cat_name (required)
    """
    cat_name = request.args.get('cat_name')
    if not cat_name:
        return jsonify({"error": "cat_name is required"}), 400

    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,))
    cat_row = cursor.fetchone()
    if not cat_row:
        conn.close()
        return jsonify({"error": f"Cat '{cat_name}' not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']

    # Join cat daily outdoor hours with weather_daily in one query
    cursor.execute("""
        SELECT
            DATE(t.start_time) AS trip_date,
            SUM(t.duration_minutes) / 60.0 AS outdoor_hours,
            w.temp_max,
            w.precipitation,
            w.weathercode
        FROM cat_trips t
        JOIN weather_daily w ON DATE(t.start_time) = w.date
        WHERE t.internal_cat_id = ?
          AND t.end_time IS NOT NULL
          AND t.duration_minutes <= 1440
        GROUP BY trip_date
        ORDER BY trip_date
    """, (internal_cat_id,))
    rows = cursor.fetchall()
    conn.close()

    result = [
        {
            "date": row['trip_date'],
            "outdoor_hours": round(row['outdoor_hours'], 3),
            "temp_max": row['temp_max'],
            "precipitation": row['precipitation'],
            "weathercode": row['weathercode'],
        }
        for row in rows
    ]
    return jsonify(result)


@app.route('/api/activity/survival')
def get_activity_survival():
    """Return the empirical survival curve P(duration > t) for a cat's outdoor trips.

    Query params:
      cat_name (required)

    Returns a list of {minutes, probability} points sampled at:
      every 5 min up to 120 min, every 15 min up to 360 min, every 30 min beyond.
    """
    cat_name = request.args.get('cat_name')
    if not cat_name:
        return jsonify({"error": "cat_name is required"}), 400

    conn = create_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    cursor.execute(
        "SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (cat_name,)
    )
    cat_row = cursor.fetchone()
    if not cat_row:
        conn.close()
        return jsonify({"error": f"Cat '{cat_name}' not found"}), 404
    internal_cat_id = cat_row['internal_cat_id']

    cursor.execute(
        """SELECT duration_minutes FROM cat_trips
           WHERE internal_cat_id = ?
             AND end_time IS NOT NULL
             AND duration_minutes IS NOT NULL
             AND duration_minutes <= 1440
           ORDER BY duration_minutes""",
        (internal_cat_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    durations = [r['duration_minutes'] for r in rows]
    n = len(durations)
    if n == 0:
        return jsonify([])

    max_duration = int(durations[-1])

    # Build sample points: every 5 min to 120, every 15 to 360, every 30 beyond
    sample_points = []
    t = 0
    while t <= max_duration:
        sample_points.append(t)
        if t < 120:
            t += 5
        elif t < 360:
            t += 15
        else:
            t += 30

    # For each t: P(duration > t) = count(d > t) / n
    # durations is sorted — use bisect for efficiency
    import bisect
    result = []
    for t in sample_points:
        # bisect_right gives index of first element > t
        count_above = n - bisect.bisect_right(durations, t)
        result.append({"minutes": t, "probability": round(count_above / n, 4)})

    return jsonify(result)


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
