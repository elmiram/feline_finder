import sqlite3
import math
from datetime import datetime

# --- Configuration ---
DB_PATH = "cat_tracker.db"
TARGET_CAT_NAME = "Trixie"  # Replace with the missing cat's name
RADIUS_METERS = 50           # Radius around the last ping to analyse for local behaviour
MINUTES_TO_PROJECT = 10

# --- Math Helpers ---
def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculates the distance in meters between two GPS points."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def calculate_bearing(lat1, lon1, lat2, lon2):
    """Calculates the bearing (direction) from point 1 to point 2 in degrees."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    lambda1, lambda2 = math.radians(lon1), math.radians(lon2)
    y = math.sin(lambda2 - lambda1) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(lambda2 - lambda1)
    theta = math.atan2(y, x)
    return (math.degrees(theta) + 360) % 360

def bearing_to_compass(bearing):
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    ix = round(bearing / (360. / len(dirs)))
    return dirs[ix % len(dirs)]

# --- Main Logic ---
def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT internal_cat_id FROM cat_identities WHERE cat_name = ?", (TARGET_CAT_NAME,))
    cat_row = cursor.fetchone()
    if not cat_row:
        print(f"Error: Cat '{TARGET_CAT_NAME}' not found in database.")
        return
    cat_id = cat_row['internal_cat_id']

    cursor.execute("""
        SELECT timestamp, latitude, longitude
        FROM tractive_gps_positions
        WHERE internal_cat_id = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (cat_id,))
    last_ping = cursor.fetchone()

    if not last_ping:
        print("No GPS data found for this cat.")
        return

    last_lat, last_lon = last_ping['latitude'], last_ping['longitude']
    print(f"=== Last Known Location for {TARGET_CAT_NAME} ===")
    print(f"Time: {last_ping['timestamp']}")
    print(f"Coordinates: {last_lat}, {last_lon}")
    print(f"Google Maps Link: https://www.google.com/maps/search/?api=1&query={last_lat},{last_lon}")
    print("--------------------------------------------------")

    cursor.execute("""
        SELECT timestamp, latitude, longitude
        FROM tractive_gps_positions
        WHERE internal_cat_id = ?
        ORDER BY timestamp ASC
    """, (cat_id,))
    all_points = cursor.fetchall()

    local_speeds = []
    local_bearings = []

    for i in range(1, len(all_points)):
        prev = all_points[i-1]
        curr = all_points[i]

        dist_to_last_known = haversine_distance(last_lat, last_lon, prev['latitude'], prev['longitude'])
        if dist_to_last_known <= RADIUS_METERS:
            t1 = datetime.strptime(prev['timestamp'], '%Y-%m-%d %H:%M:%S')
            t2 = datetime.strptime(curr['timestamp'], '%Y-%m-%d %H:%M:%S')
            time_diff_seconds = (t2 - t1).total_seconds()

            if 0 < time_diff_seconds < 600:
                move_dist = haversine_distance(prev['latitude'], prev['longitude'], curr['latitude'], curr['longitude'])
                speed_mps = move_dist / time_diff_seconds
                bearing = calculate_bearing(prev['latitude'], prev['longitude'], curr['latitude'], curr['longitude'])
                local_speeds.append(speed_mps)
                local_bearings.append(bearing)

    if not local_speeds:
        print("Not enough historical movement data in this specific area to calculate local speed.")
        return

    avg_speed_mps = sum(local_speeds) / len(local_speeds)
    projected_distance = avg_speed_mps * (MINUTES_TO_PROJECT * 60)

    direction_counts = {}
    for b in local_bearings:
        compass = bearing_to_compass(b)
        direction_counts[compass] = direction_counts.get(compass, 0) + 1

    sorted_directions = sorted(direction_counts.items(), key=lambda item: item[1], reverse=True)

    print(f"=== {MINUTES_TO_PROJECT}-Minute Projection ===")
    print(f"Historical avg speed in this terrain: {avg_speed_mps:.2f} meters/second")
    print(f"Maximum estimated travel distance in {MINUTES_TO_PROJECT} mins: {projected_distance:.0f} meters")
    print("Likely preferred directions from this spot (based on history):")
    for d, count in sorted_directions[:3]:
        print(f" - {d} ({count} historical movements)")


if __name__ == "__main__":
    main()
