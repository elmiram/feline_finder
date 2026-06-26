# cat_stats.py
#
# Prints lifetime statistics for each cat in the database.
# Run from the backend/ directory:
#   python3 cat_stats.py              # all cats
#   python3 cat_stats.py Arthur King  # specific cats

import sys, math
from collections import Counter
import numpy as np
from sklearn.cluster import DBSCAN

from db_utils import create_connection
from config import KNOWN_ZONES


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p = math.pi / 180
    a = math.sin((lat2-lat1)*p/2)**2 + math.cos(lat1*p)*math.cos(lat2*p)*math.sin((lon2-lon1)*p/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def is_point_in_polygon(point, polygon):
    lat, lon = point
    n, inside = len(polygon), False
    p1lat, p1lon = polygon[0]
    for i in range(n + 1):
        p2lat, p2lon = polygon[i % n]
        if min(p1lon, p2lon) < lon <= max(p1lon, p2lon):
            if lat <= max(p1lat, p2lat):
                if p1lon != p2lon:
                    lat_i = (lon-p1lon)*(p2lat-p1lat)/(p2lon-p1lon) + p1lat
                if p1lat == p2lat or lat <= lat_i:
                    inside = not inside
        p1lat, p1lon = p2lat, p2lon
    return inside

def get_zone(lat, lon):
    for name, poly in KNOWN_ZONES.items():
        if is_point_in_polygon((lat, lon), poly):
            return name
    return None

def convex_hull(points):
    points = np.array(points)
    if len(points) <= 3: return points.tolist()
    def cross(p1, p2, p3):
        return (p2[0]-p1[0])*(p3[1]-p1[1]) - (p2[1]-p1[1])*(p3[0]-p1[0])
    sp = sorted(points, key=lambda p: (p[0], p[1]))
    upper, lower = [], []
    for p in sp:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0: upper.pop()
        upper.append(p)
    for p in reversed(sp):
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0: lower.pop()
        lower.append(p)
    return [p.tolist() for p in upper[:-1] + lower[:-1]]

def polygon_area_km2(hull):
    if len(hull) < 3: return 0
    lat0 = sum(p[0] for p in hull) / len(hull)
    lat_m, lon_m = 111000, 111000 * math.cos(math.radians(lat0))
    pts = [(p[0]*lat_m, p[1]*lon_m) for p in hull]
    n = len(pts)
    return abs(sum(pts[i][0]*pts[(i+1)%n][1] - pts[(i+1)%n][0]*pts[i][1] for i in range(n))) / 2 / 1e6

def print_stats(conn, cat_id, cat_name):
    c = conn.cursor()
    days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

    print(f"\n{'═'*55}")
    print(f"  {cat_name.upper()}")
    print(f"{'═'*55}")

    c.execute("SELECT latitude, longitude, timestamp FROM tractive_gps_positions WHERE internal_cat_id=? ORDER BY timestamp", (cat_id,))
    rows = c.fetchall()
    if not rows:
        print("  No GPS data.")
        return

    pts = [(r[0], r[1]) for r in rows]
    timestamps = [r[2] for r in rows]
    home_lat, home_lon = pts[0]
    total_pings = len(rows)

    # Period & pings
    c.execute("SELECT MIN(timestamp), MAX(timestamp) FROM tractive_gps_positions WHERE internal_cat_id=?", (cat_id,))
    first, last = c.fetchone()
    print(f"\n  GPS period:        {first[:10]}  →  {last[:10]}")
    print(f"  Total pings:       {total_pings:,}")
    print(f"    How: MIN/MAX timestamp and COUNT from tractive_gps_positions.")

    # Total distance
    dist = sum(haversine(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1])
               for i in range(len(pts)-1)
               if haversine(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1]) < 500)
    print(f"\n  Total distance:    {dist/1000:.1f} km")
    print(f"    How: haversine between consecutive GPS pings, summed. Jumps >500m discarded as noise.")

    # Farthest point
    farthest_dist, farthest_pt, farthest_ts = 0, None, None
    for (lat, lon), ts in zip(pts, timestamps):
        d = haversine(home_lat, home_lon, lat, lon)
        if d > farthest_dist:
            farthest_dist, farthest_pt, farthest_ts = d, (lat, lon), ts
    zone_hit = get_zone(*farthest_pt)
    print(f"\n  Farthest from home: {farthest_dist:.0f} m")
    print(f"    When: {farthest_ts[:16]}")
    print(f"    Zone: {zone_hit or 'outside all named zones'}")
    print(f"    How: haversine from first GPS ping (home proxy) to every ping; max taken.")

    # Most active hours
    c.execute("SELECT strftime('%H', timestamp) hr, COUNT(*) n FROM tractive_gps_positions WHERE internal_cat_id=? GROUP BY hr ORDER BY n DESC LIMIT 3", (cat_id,))
    hours = ', '.join(f"{hr}:00" for hr, n in c.fetchall())
    print(f"\n  Most active hours: {hours}")
    print(f"    How: pings grouped by hour. More pings = more time active outdoors.")

    # Total outdoor trips
    c.execute("SELECT COUNT(*) FROM surepet_events WHERE internal_cat_id=? AND event_source=0 AND direction=2", (cat_id,))
    exits = c.fetchone()[0]
    print(f"\n  Total outdoor trips: {exits}")
    print(f"    How: SurePet flap exits (event_source=0, direction=2).")

    # Longest outdoor session
    c.execute("SELECT timestamp FROM surepet_events WHERE internal_cat_id=? AND event_source=0 AND direction=2 ORDER BY timestamp", (cat_id,))
    out_times = [r[0] for r in c.fetchall()]
    best_h, best_out, best_in = 0, None, None
    for out_t in out_times:
        c.execute("SELECT timestamp FROM surepet_events WHERE internal_cat_id=? AND direction=1 AND timestamp>? ORDER BY timestamp LIMIT 1", (cat_id, out_t))
        row = c.fetchone()
        if row:
            c.execute("SELECT (julianday(?)-julianday(?))*24", (row[0], out_t))
            h = c.fetchone()[0]
            if h and h > best_h:
                best_h, best_out, best_in = h, out_t, row[0]
    print(f"\n  Longest session:   {best_h:.1f} hours")
    print(f"    Out: {best_out[:16] if best_out else '?'}  |  Back: {best_in[:16] if best_in else '?'}")
    print(f"    How: each flap exit paired with next IN event of any type (flap or manual).")

    # Most active day
    c.execute("SELECT strftime('%w', timestamp) d, COUNT(*) n FROM surepet_events WHERE internal_cat_id=? AND event_source=0 AND direction=2 GROUP BY d ORDER BY n DESC", (cat_id,))
    print(f"\n  Trips by day of week:")
    for d, n in c.fetchall():
        print(f"    {days[int(d)]}: {n}")
    print(f"    How: flap exits grouped by day of week over full dataset.")

    # Looks without entering
    c.execute("SELECT COUNT(*) FROM surepet_events WHERE internal_cat_id=? AND event_source=2", (cat_id,))
    print(f"\n  Looked without entering: {c.fetchone()[0]}")
    print(f"    How: SurePet event_source=2 (looked through flap, both directions).")

    # Territory area
    coords = np.array([[p[0], p[1]] for p in pts])
    db = DBSCAN(eps=30/6371000, min_samples=5, algorithm='ball_tree', metric='haversine').fit(np.radians(coords))
    clustered = coords[db.labels_ != -1]
    hull = convex_hull(clustered)
    area = polygon_area_km2(hull)
    print(f"\n  Territory area:    {area:.4f} km²  ({area*100:.1f} hectares)")
    print(f"    How: DBSCAN (eps=30m) removes outliers, convex hull of {len(clustered):,} core points,")
    print(f"         shoelace formula with local flat-earth projection.")

    # Favourite zones
    zone_counts = Counter()
    unzoned = 0
    for lat, lon in pts:
        z = get_zone(lat, lon)
        if z: zone_counts[z] += 1
        else: unzoned += 1
    print(f"\n  Favourite zones (top 5):")
    for zone, count in zone_counts.most_common(5):
        print(f"    {zone:<35} {count:>6,}  ({count/total_pings*100:.1f}%)")
    print(f"    {'(outside named zones)':<35} {unzoned:>6,}  ({unzoned/total_pings*100:.1f}%)")
    print(f"    How: every ping ray-cast against all named zone polygons. Count ≈ time spent.")


if __name__ == '__main__':
    conn = create_connection()
    c = conn.cursor()
    if len(sys.argv) > 1:
        placeholders = ','.join('?' * len(sys.argv[1:]))
        c.execute(f"SELECT internal_cat_id, cat_name FROM cat_identities WHERE cat_name IN ({placeholders}) ORDER BY cat_name", sys.argv[1:])
    else:
        c.execute("SELECT internal_cat_id, cat_name FROM cat_identities ORDER BY cat_name")
    for cat_id, cat_name in c.fetchall():
        print_stats(conn, cat_id, cat_name)
    conn.close()
