# api_server.py
#
# Description
# This script runs a Flask web server that provides API endpoints and serves the frontend.
# It now uses DBSCAN for clustering to remove outliers before computing the territory polygon.

import os
import requests
import numpy as np
from sklearn.cluster import DBSCAN # New dependency for clustering
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS

from db_utils import create_connection

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

app = Flask(__name__, static_folder='feline-finder-frontend/build')
CORS(app)

def get_latest_data_for_cats():
    conn = create_connection()
    if not conn: return None
    cats_data = {}
    cursor = conn.cursor()
    cursor.execute("SELECT internal_cat_id, cat_name FROM cat_identities")
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
        final_status[cat_name] = {
            "name": cat_name, "status": status, "confidence": confidence,
            "evidence": evidence, "location": location, "location_detail": location_detail,
            "tractive_update_time": hw['timestamp'] if hw else None,
            "surepet_update_time": flap['timestamp'] if flap else None,
            "battery_level": hw['battery_level'] if hw else None,
            "is_charging": hw['is_charging'] == 1 if hw else None,
            "recent_events": data.get('recent_events', [])
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

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
