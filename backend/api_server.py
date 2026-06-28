# api_server.py
#
# Description
# This script runs a Flask web server that provides API endpoints and serves the frontend.
# It now uses DBSCAN for clustering to remove outliers before computing the territory polygon.

import os
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
        final_status[cat_name] = {
            "name": cat_name, "status": status, "confidence": confidence,
            "evidence": evidence, "location": location, "location_detail": location_detail,
            "tractive_update_time": hw['timestamp'] if hw else None,
            "surepet_update_time": flap['timestamp'] if flap else None,
            "battery_level": hw['battery_level'] if hw else None,
            "is_charging": hw['is_charging'] == 1 if hw else None,
            "recent_events": data.get('recent_events', []),
            "recent_zone_changes": zone_changes,
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


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
