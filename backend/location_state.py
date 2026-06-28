"""
Shared location state logic for FelineFinder.
Merges SurePet flap events + GPS signals to determine if a cat is home or outside.

Used by both the live dashboard and historical trip computation so that both
consumers apply identical rules.
"""
from datetime import datetime, timedelta


def _parse_dt(s):
    """Parse a datetime string from the DB.

    Handles:
      - 'YYYY-MM-DD HH:MM:SS'           (GPS timestamps, no tz)
      - 'YYYY-MM-DD HH:MM:SS.ffffff'    (with fractional seconds)
      - 'YYYY-MM-DDTHH:MM:SS'           (ISO without tz)
      - 'YYYY-MM-DD HH:MM:SS+HH:MM'     (SurePet timestamps with tz offset)
      - 'YYYY-MM-DDTHH:MM:SS+HH:MM'     (ISO with tz offset)

    All returned datetimes are naive UTC — timezone info is stripped so that
    GPS and SurePet events can be compared on the same timeline.
    """
    if s is None:
        raise ValueError("Cannot parse None as datetime")

    # Strip timezone suffix (+HH:MM or -HH:MM or Z) before parsing so we
    # always get a naive datetime.  SurePet events are stored as UTC+00:00.
    s = s.strip()
    # Remove trailing Z
    if s.endswith('Z'):
        s = s[:-1]
    # Remove +HH:MM or -HH:MM timezone offset
    for sep in ('+', '-'):
        # Find the last occurrence that looks like a tz offset (after position 10)
        idx = s.rfind(sep, 10)
        if idx != -1 and len(s) - idx in (6,):   # exactly +HH:MM = 6 chars
            s = s[:idx]
            break

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {s!r}")


def _build_home_polygon(known_zones):
    """Build a Shapely polygon for the Home zone from KNOWN_ZONES.
    Returns a shapely.geometry.Polygon or None if shapely is unavailable.
    """
    try:
        from shapely.geometry import Polygon as ShPoly
        coords = known_zones.get("Home", [])
        if len(coords) < 3:
            return None
        # KNOWN_ZONES stores [lat, lon]; Shapely wants (lon, lat)
        return ShPoly([(lon, lat) for lat, lon in coords])
    except ImportError:
        return None


def _is_home_gps(lat, lon, home_poly, known_zones):
    """Return True if the GPS point is inside the Home zone.

    Primary method: Shapely polygon test (accurate).
    Fallback if Shapely is unavailable: manual ray-casting using the
    same is_point_in_polygon logic that api_server.py uses.
    """
    if home_poly is not None:
        try:
            from shapely.geometry import Point
            return home_poly.contains(Point(lon, lat))
        except Exception:
            pass

    # Fallback: manual ray-casting (mirrors api_server.py)
    polygon = known_zones.get("Home", [])
    if not polygon:
        return False
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


def compute_trips(conn, internal_cat_id, known_zones, start_dt=None, end_dt=None):
    """Compute outdoor trips for one cat over an optional date range.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open DB connection (must use row_factory = sqlite3.Row or dict-like).
    internal_cat_id : int
    known_zones : dict
        KNOWN_ZONES from config — used to check if GPS pings are inside Home.
    start_dt : datetime or None
        If given, only events/pings at or after this time are considered.
    end_dt : datetime or None
        If given, only events/pings at or before this time are considered.

    Returns
    -------
    list of dict with keys:
        start_time (str, ISO), end_time (str or None), duration_minutes (float or None),
        start_source (str), end_source (str or None), confidence (str)
    """
    cursor = conn.cursor()
    home_poly = _build_home_polygon(known_zones)

    # --- 1. Fetch SurePet events ---
    if start_dt and end_dt:
        cursor.execute(
            """SELECT timestamp, direction, event_source
               FROM surepet_events
               WHERE internal_cat_id = ?
                 AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp""",
            (internal_cat_id, start_dt.isoformat(), end_dt.isoformat()),
        )
    elif start_dt:
        cursor.execute(
            """SELECT timestamp, direction, event_source
               FROM surepet_events
               WHERE internal_cat_id = ?
                 AND timestamp >= ?
               ORDER BY timestamp""",
            (internal_cat_id, start_dt.isoformat()),
        )
    elif end_dt:
        cursor.execute(
            """SELECT timestamp, direction, event_source
               FROM surepet_events
               WHERE internal_cat_id = ?
                 AND timestamp <= ?
               ORDER BY timestamp""",
            (internal_cat_id, end_dt.isoformat()),
        )
    else:
        cursor.execute(
            """SELECT timestamp, direction, event_source
               FROM surepet_events
               WHERE internal_cat_id = ?
               ORDER BY timestamp""",
            (internal_cat_id,),
        )
    flap_rows = cursor.fetchall()

    # --- 2. Fetch GPS pings ---
    if start_dt and end_dt:
        cursor.execute(
            """SELECT timestamp, latitude, longitude, sensor_used
               FROM tractive_gps_positions
               WHERE internal_cat_id = ?
                 AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp""",
            (internal_cat_id, start_dt.strftime("%Y-%m-%d %H:%M:%S"),
             end_dt.strftime("%Y-%m-%d %H:%M:%S")),
        )
    elif start_dt:
        cursor.execute(
            """SELECT timestamp, latitude, longitude, sensor_used
               FROM tractive_gps_positions
               WHERE internal_cat_id = ?
                 AND timestamp >= ?
               ORDER BY timestamp""",
            (internal_cat_id, start_dt.strftime("%Y-%m-%d %H:%M:%S")),
        )
    elif end_dt:
        cursor.execute(
            """SELECT timestamp, latitude, longitude, sensor_used
               FROM tractive_gps_positions
               WHERE internal_cat_id = ?
                 AND timestamp <= ?
               ORDER BY timestamp""",
            (internal_cat_id, end_dt.strftime("%Y-%m-%d %H:%M:%S")),
        )
    else:
        cursor.execute(
            """SELECT timestamp, latitude, longitude, sensor_used
               FROM tractive_gps_positions
               WHERE internal_cat_id = ?
               ORDER BY timestamp""",
            (internal_cat_id,),
        )
    gps_rows = cursor.fetchall()

    # --- 3. Build unified timeline ---
    # Each entry: (datetime, state, source, confidence, is_flap_entry)
    # is_flap_entry=True means this is a SurePet flap entry — immune to smoothing.
    timeline = []

    for row in flap_rows:
        try:
            dt = _parse_dt(row['timestamp'] if hasattr(row, 'keys') else row[0])
        except ValueError:
            continue
        ts = row['timestamp'] if hasattr(row, 'keys') else row[0]
        direction = row['direction'] if hasattr(row, 'keys') else row[1]
        event_source = row['event_source'] if hasattr(row, 'keys') else row[2]

        flap = (event_source == 0)
        conf = "high" if flap else "medium"

        if direction == 2:
            # Exited
            src = "surepet_exit"
            timeline.append((dt, "outside", src, conf, False))
        elif direction == 1:
            # Entered
            src = "surepet_entry"
            # Flap entries are immune to smoothing — cat is definitively home
            timeline.append((dt, "home", src, conf, flap))

    for row in gps_rows:
        try:
            dt = _parse_dt(row['timestamp'] if hasattr(row, 'keys') else row[0])
        except ValueError:
            continue
        lat = row['latitude'] if hasattr(row, 'keys') else row[1]
        lon = row['longitude'] if hasattr(row, 'keys') else row[2]
        sensor = row['sensor_used'] if hasattr(row, 'keys') else row[3]

        if sensor == 'KNOWN_WIFI':
            timeline.append((dt, "home", "wifi_home", "high", False))
        else:
            # sensor is 'GPS' or NULL — check if inside Home polygon
            if _is_home_gps(lat, lon, home_poly, known_zones):
                timeline.append((dt, "home", "gps_home", "medium", False))
            else:
                timeline.append((dt, "outside", "gps_outdoor", "medium", False))

    # Sort by time
    timeline.sort(key=lambda x: x[0])

    if not timeline:
        return []

    # --- 4. Smooth the timeline ---
    # Rule: a single "home" signal sandwiched between "outside" signals within
    # a 10-minute window does NOT count as a true return home — it's a GPS
    # bounce.  Exception: SurePet flap entry (is_flap_entry=True) always counts.
    BOUNCE_WINDOW = timedelta(minutes=10)

    smoothed = []  # (datetime, state, source, confidence)
    n = len(timeline)
    for i, (dt, state, source, conf, is_flap_entry) in enumerate(timeline):
        if state == "home" and not is_flap_entry:
            # Look ahead and behind for context
            # Check if this is a lone "home" blip surrounded by "outside" within 10 min
            prev_outside = None
            next_outside = None
            next_home = None

            for j in range(i - 1, -1, -1):
                if timeline[j][1] == "outside":
                    if dt - timeline[j][0] <= BOUNCE_WINDOW:
                        prev_outside = timeline[j]
                    break

            for j in range(i + 1, n):
                if timeline[j][0] - dt > BOUNCE_WINDOW:
                    break
                if timeline[j][1] == "outside":
                    next_outside = timeline[j]
                    break
                if timeline[j][1] == "home":
                    next_home = timeline[j]
                    break

            # If surrounded by outside signals within 10 min and no sustained home signal
            if prev_outside is not None and next_outside is not None and next_home is None:
                # This is a GPS bounce — skip it (treat as outside)
                smoothed.append((dt, "outside", source + "_bounce_suppressed", conf))
                continue

        smoothed.append((dt, state, source, conf))

    # --- 5. Extract trips ---
    # Scan smoothed timeline for state transitions.
    # Trip starts on first "outside" after "home" (or from the beginning if unknown).
    # Trip ends on next "home" signal.
    trips = []
    current_trip_start = None
    current_trip_start_source = None
    current_trip_start_conf = None
    current_state = None  # None = unknown at start

    for dt, state, source, conf in smoothed:
        if current_state is None:
            # Bootstrap: set initial state without creating a trip
            current_state = state
            if state == "outside":
                # Cat was already outside at the first signal — open trip
                current_trip_start = dt
                current_trip_start_source = source
                current_trip_start_conf = conf
            continue

        if state == "outside" and current_state == "home":
            # Cat went outside
            current_trip_start = dt
            current_trip_start_source = source
            current_trip_start_conf = conf
            current_state = "outside"

        elif state == "home" and current_state == "outside":
            # Cat came home — close the trip
            if current_trip_start is not None:
                duration = (dt - current_trip_start).total_seconds() / 60.0
                # Assign confidence based on sources
                trip_conf = _trip_confidence(current_trip_start_source, source)
                trips.append({
                    "start_time": current_trip_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "end_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "duration_minutes": round(duration, 2),
                    "start_source": current_trip_start_source,
                    "end_source": source,
                    "confidence": trip_conf,
                })
                current_trip_start = None
                current_trip_start_source = None
                current_trip_start_conf = None
            current_state = "home"

        # If same state continues, no trip boundary

    # If cat is still outside at the end, record open trip
    if current_state == "outside" and current_trip_start is not None:
        trips.append({
            "start_time": current_trip_start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": None,
            "duration_minutes": None,
            "start_source": current_trip_start_source,
            "end_source": None,
            "confidence": "low",
        })

    return trips


def _trip_confidence(start_source, end_source):
    """Assign overall trip confidence from the start and end sources."""
    flap_sources = {"surepet_exit", "surepet_entry"}
    start_high = start_source in flap_sources
    end_high = end_source in flap_sources if end_source else False
    if start_high and end_high:
        return "high"
    elif start_high or end_high:
        return "medium"
    else:
        return "low"


def get_current_state(conn, internal_cat_id, known_zones):
    """Return the cat's current location state based on the most recent signals.

    Looks at the last 24 hours of SurePet events and GPS pings (capped at
    50 pings) and returns the most recent non-ambiguous state.

    Returns
    -------
    dict with keys:
        state: 'home' | 'outside' | 'unknown'
        since: datetime (UTC naive)
        source: str
    """
    from datetime import datetime, timedelta

    cursor = conn.cursor()
    home_poly = _build_home_polygon(known_zones)

    # Last SurePet event
    cursor.execute(
        """SELECT timestamp, direction, event_source
           FROM surepet_events
           WHERE internal_cat_id = ?
           ORDER BY timestamp DESC LIMIT 1""",
        (internal_cat_id,),
    )
    flap = cursor.fetchone()

    # Last GPS ping
    cursor.execute(
        """SELECT timestamp, latitude, longitude, sensor_used
           FROM tractive_gps_positions
           WHERE internal_cat_id = ?
           ORDER BY timestamp DESC LIMIT 1""",
        (internal_cat_id,),
    )
    gps = cursor.fetchone()

    def _row(row, key, idx):
        if row is None:
            return None
        try:
            return row[key]
        except (TypeError, IndexError, KeyError):
            return row[idx]

    signals = []

    if flap is not None:
        try:
            dt = _parse_dt(_row(flap, 'timestamp', 0))
            direction = _row(flap, 'direction', 1)
            event_source = _row(flap, 'event_source', 2)
            state = "home" if direction == 1 else "outside"
            conf = "high" if event_source == 0 else "medium"
            source = ("surepet_entry" if direction == 1 else "surepet_exit")
            signals.append((dt, state, source, conf))
        except ValueError:
            pass

    if gps is not None:
        try:
            dt = _parse_dt(_row(gps, 'timestamp', 0))
            lat = _row(gps, 'latitude', 1)
            lon = _row(gps, 'longitude', 2)
            sensor = _row(gps, 'sensor_used', 3)
            if sensor == 'KNOWN_WIFI':
                signals.append((dt, "home", "wifi_home", "high"))
            elif _is_home_gps(lat, lon, home_poly, known_zones):
                signals.append((dt, "home", "gps_home", "medium"))
            else:
                signals.append((dt, "outside", "gps_outdoor", "medium"))
        except ValueError:
            pass

    if not signals:
        return {"state": "unknown", "since": None, "source": "no_data"}

    # Pick most recent signal
    signals.sort(key=lambda x: x[0], reverse=True)
    dt, state, source, conf = signals[0]
    return {"state": state, "since": dt, "source": source}
