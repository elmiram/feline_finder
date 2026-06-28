#!/usr/bin/env python3
"""
Build per-cat timelines for the past 24h by merging SurePet events and
Tractive GPS positions from a local SQLite DB (cat_tracker.db).

- Uses your schema:
    cat_identities(internal_cat_id, cat_name)
    tractive_gps_positions(internal_cat_id, timestamp, latitude, longitude, accuracy?)
    surepet_events(surepet_event_id, internal_cat_id, timestamp, event_source, direction, surepet_user_id)
    surepet_users(surepet_user_id, user_name)

- SurePet interpretation:
    source 0: direction 1 -> "Entered flap" (Came Inside), 2 -> "Exited flap" (Went Outside)
    source 1: direction 1 -> "Set to Inside", 2 -> "Set to Outside"
    source 2: direction 1 -> "Looked from Inside", 2 -> "Looked from Outside"

- Output: timelines_YYYY-MM-DD.json
  {
    "Trixie": [
      {"time":"08:02 AM","event":"Went Outside"},
      {
        "time":"08:02 AM - 10:15 AM",
        "event":"Outdoor Adventure",
        "distance_km":1.204,
        "zones_visited":[
          {"zone":"Back Garden","duration_min":12},
          {"zone":"Big Field","duration_min":34},
          {"zone":"Back Garden","duration_min":5}
        ]
      },
      ...
    ],
    "Arthur": [...],
    "King": [...]
  }
"""

import os
import sqlite3
import json
import math
import datetime as dt
from collections import defaultdict, namedtuple
from zoneinfo import ZoneInfo

from config import KNOWN_ZONES

# ----------------- CONFIG -----------------
DB_PATH = os.getenv("CAT_DB_PATH", "cat_tracker.db")

TZ = ZoneInfo("Europe/Zurich")
NOW = dt.datetime.now(TZ)
SINCE = NOW - dt.timedelta(hours=24)

# ---- Tables/columns ----
CAT_TABLE = "cat_identities"
CAT_COL_ID = "internal_cat_id"
CAT_COL_NAME = "cat_name"

TRACTIVE_TABLE = "tractive_gps_positions"
TP_COL_CAT_ID = "internal_cat_id"
TP_COL_TIME = "timestamp"
TP_COL_LAT = "latitude"
TP_COL_LON = "longitude"

SUREPET_TABLE = "surepet_events"
SP_COL_ID = "surepet_event_id"
SP_COL_CAT_ID = "internal_cat_id"
SP_COL_TIME = "timestamp"
SP_COL_SRC = "event_source"   # 0 movement, 1 manual set, 2 looked
SP_COL_DIR = "direction"      # 1 inside, 2 outside
SP_COL_USER = "user_id"

USERS_TABLE = "surepet_users"
USERS_COL_ID = "surepet_user_id"
USERS_COL_NAME = "user_name"
# ------------------------------------------


# --------- Time formatting helpers (date-aware) ----------
def fmt_clock(t: dt.datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")

def fmt_day(t: dt.datetime) -> str:
    return t.strftime("%b %d").replace(" 0", " ")

def fmt_range(a: dt.datetime, b: dt.datetime) -> str:
    if a.date() == b.date():
        return f"{fmt_clock(a)} - {fmt_clock(b)}"
    return f"{fmt_day(a)} {fmt_clock(a)} - {fmt_day(b)} {fmt_clock(b)}"


# --------- Parsing & geometry ----------
def parse_ts(s: str) -> dt.datetime:
    """
    Parse SQLite timestamp strings. Accepts ISO8601 with/without timezone and 'Z' suffix.
    Returns TZ-aware (Europe/Zurich).
    """
    if s is None:
        return None
    s = s.strip()
    if s.endswith("Z"):
        base = dt.datetime.fromisoformat(s[:-1]).replace(tzinfo=dt.timezone.utc)
        return base.astimezone(TZ)
    try:
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            return d.replace(tzinfo=TZ)
        return d.astimezone(TZ)
    except Exception:
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

def point_in_poly(lat, lon, polygon_ll):
    """Ray-casting point-in-polygon. polygon_ll is list of (lat, lon) tuples."""
    x, y = lon, lat
    inside = False
    n = len(polygon_ll)
    for i in range(n):
        lat1, lon1 = polygon_ll[i]
        lat2, lon2 = polygon_ll[(i + 1) % n]
        x1, y1 = lon1, lat1
        x2, y2 = lon2, lat2
        denom = (y2 - y1) if (y2 - y1) != 0 else 1e-12
        intersects = ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / denom + x1)
        if intersects:
            inside = not inside
    return inside

class ZoneIndex:
    """
    Zones dict format:
      { "Zone Name": [[lat, lon], [lat, lon], ...], ... }
    """
    def __init__(self, zones_dict):
        self.zones = []
        for name, pts in zones_dict.items():
            poly_ll = [(p[0], p[1]) for p in pts]
            self.zones.append((name, poly_ll))

    def locate(self, lat, lon):
        for name, poly_ll in self.zones:
            if point_in_poly(lat, lon, poly_ll):
                return name
        return None


# --------- SurePet mapping ----------
def label_surepet(src: int, direction: int) -> str:
    if src == 0:
        return "Entered flap" if direction == 1 else "Exited flap"
    if src == 1:
        return "Set to Inside" if direction == 1 else "Set to Outside"
    if src == 2:
        return "Looked from Inside" if direction == 1 else "Looked from Outside"
    return "Door Event"

def is_stateful(src: int) -> bool:
    return src in (0, 1)

def new_state_from(src: int, direction: int) -> str | None:
    if not is_stateful(src):
        return None
    return "inside" if direction == 1 else "outside"


# --------- DB IO ----------
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def load_cat_names(conn) -> dict:
    cur = conn.cursor()
    cur.execute(f"SELECT {CAT_COL_ID}, {CAT_COL_NAME} FROM {CAT_TABLE}")
    out = {str(r[CAT_COL_ID]): r[CAT_COL_NAME] for r in cur.fetchall()}
    cur.close()
    return out

def load_users(conn) -> dict:
    cur = conn.cursor()
    cur.execute(f"SELECT {USERS_COL_ID}, {USERS_COL_NAME} FROM {USERS_TABLE}")
    out = {r[USERS_COL_ID]: r[USERS_COL_NAME] for r in cur.fetchall()}
    cur.close()
    return out

def load_last_state_before(conn, since: dt.datetime) -> dict:
    """Determine initial inside/outside per cat from the last stateful surepet event before since."""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT {SP_COL_CAT_ID} AS cid, {SP_COL_SRC} AS src, {SP_COL_DIR} AS dir, {SP_COL_TIME} AS t
        FROM {SUREPET_TABLE}
        WHERE {SP_COL_TIME} < ?
        ORDER BY {SP_COL_TIME} DESC
    """, (since.isoformat(),))
    initial = {}
    seen = set()
    for r in cur.fetchall():
        cid = str(r["cid"])
        if cid in seen:
            continue
        src = r["src"]
        direction = r["dir"]
        if src in (0, 1):
            initial[cid] = "inside" if direction == 1 else "outside"
            seen.add(cid)
    cur.close()
    return initial

def load_surepet_events(conn, since: dt.datetime, now: dt.datetime):
    cur = conn.cursor()
    cur.execute(f"""
        SELECT
            {SP_COL_CAT_ID} AS cat_id,
            {SP_COL_TIME}   AS t,
            {SP_COL_SRC}    AS src,
            {SP_COL_DIR}    AS dir,
            {SP_COL_USER}   AS user_id
        FROM {SUREPET_TABLE}
        WHERE {SP_COL_TIME} >= ? AND {SP_COL_TIME} <= ?
        ORDER BY {SP_COL_TIME} ASC
    """, (since.isoformat(), now.isoformat()))
    out = []
    for r in cur.fetchall():
        out.append({
            "cat_id": str(r["cat_id"]),
            "time": parse_ts(r["t"]),
            "src": r["src"],
            "dir": r["dir"],
            "user_id": r["user_id"]
        })
    cur.close()
    return out

def load_tractive_points(conn, since: dt.datetime, now: dt.datetime):
    TP = namedtuple("TP", "t lat lon")
    cur = conn.cursor()
    cur.execute(f"""
        SELECT
            {TP_COL_CAT_ID} AS cat_id,
            {TP_COL_TIME}   AS t,
            {TP_COL_LAT}    AS lat,
            {TP_COL_LON}    AS lon
        FROM {TRACTIVE_TABLE}
        WHERE {TP_COL_TIME} >= ? AND {TP_COL_TIME} <= ?
        ORDER BY {TP_COL_CAT_ID} ASC, {TP_COL_TIME} ASC
    """, (since.isoformat(), now.isoformat()))
    per_cat = defaultdict(list)
    for r in cur.fetchall():
        per_cat[str(r["cat_id"])].append(
            TP(t=parse_ts(r["t"]), lat=float(r["lat"]), lon=float(r["lon"]))
        )
    cur.close()
    return per_cat


# --------- Outdoor summary (distance + zone sequence with durations) ----------
def summarize_outdoor(points, zone_index: ZoneIndex):
    """
    Given ordered GPS points, compute total distance (km) and ordered zone sequence
    with durations in minutes.
    """
    if not points:
        return 0.0, []

    distance = 0.0
    for a, b in zip(points, points[1:]):
        distance += haversine_km(a.lat, a.lon, b.lat, b.lon)

    segments = []

    def add_segment(zone, seconds):
        if zone is None or seconds <= 0:
            return
        if segments and segments[-1][0] == zone:
            z, s = segments[-1]
            segments[-1] = (z, s + seconds)
        else:
            segments.append((zone, seconds))

    for a, b in zip(points, points[1:]):
        dt_sec = max(0, int((b.t - a.t).total_seconds()))
        if dt_sec == 0:
            continue
        za = zone_index.locate(a.lat, a.lon)
        zb = zone_index.locate(b.lat, b.lon)
        if za == zb:
            add_segment(za, dt_sec)
        else:
            half = dt_sec // 2
            add_segment(za, half)
            add_segment(zb, dt_sec - half)

    zones_sequence = [
        {"zone": z, "duration_min": int(round(s / 60.0))}
        for (z, s) in segments
        if z is not None
    ]

    return round(distance, 3), zones_sequence


# --------- Timeline builder ----------
def build_timelines(surepet_rows, gps_by_cat, zone_index, cats_map, users_map, initial_state, since=None, now=None):
    if since is None:
        since = SINCE
    if now is None:
        now = NOW

    per_cat_sp = defaultdict(list)
    for e in surepet_rows:
        per_cat_sp[e["cat_id"]].append(e)

    cats = set(per_cat_sp.keys()) | set(gps_by_cat.keys()) | set(initial_state.keys())
    timelines = {}

    for cid in sorted(cats):
        cat_name = cats_map.get(cid, cid)
        events = per_cat_sp.get(cid, [])
        gps = gps_by_cat.get(cid, [])

        instants = []
        standalone = []
        for e in events:
            t = e["time"]
            src, direction = e["src"], e["dir"]
            lbl = label_surepet(src, direction)
            if is_stateful(src):
                instants.append((t, src, direction, e.get("user_id")))
            else:
                standalone.append({"_ts": t, "event": lbl})

        instants.sort(key=lambda x: x[0])

        state = initial_state.get(cid, "unknown")
        ptr = since

        timeline = []

        def gps_between(t0, t1):
            return [p for p in gps if t0 <= p.t <= t1]

        for t, src, direction, user_id in instants:
            if t < since or t > now:
                continue

            if ptr < t:
                if state == "outside":
                    pts = gps_between(ptr, t)
                    dist, zones_seq = summarize_outdoor(pts, zone_index)
                    timeline.append({
                        "_start": ptr,
                        "_end": t,
                        "event": "Outdoor Adventure",
                        "distance_km": dist,
                        "zones_visited": zones_seq
                    })
                elif state == "inside":
                    timeline.append({"_start": ptr, "_end": t, "event": "At Home"})

            lbl = label_surepet(src, direction)
            if src == 1:
                actor = users_map.get(user_id)
                if actor:
                    lbl = f"{lbl} by {actor}"
            elif src == 0:
                lbl = "Came Inside" if direction == 1 else "Went Outside"

            timeline.append({"_ts": t, "event": lbl})

            ns = new_state_from(src, direction)
            if ns:
                state = ns
            ptr = t

        if ptr < now:
            if state == "outside":
                pts = gps_between(ptr, now)
                dist, zones_seq = summarize_outdoor(pts, zone_index)
                timeline.append({
                    "_start": ptr,
                    "_end": now,
                    "event": "Outdoor Adventure",
                    "distance_km": dist,
                    "zones_visited": zones_seq
                })
            elif state == "inside":
                timeline.append({"_start": ptr, "_end": now, "event": "At Home"})

        merged = timeline + standalone

        def sort_key(item):
            return item["_ts"] if "_ts" in item else item["_start"]

        merged.sort(key=sort_key)

        rendered = []
        for it in merged:
            if "_ts" in it:
                rendered.append({"time": fmt_clock(it["_ts"]), "event": it["event"]})
            else:
                out = {"time": fmt_range(it["_start"], it["_end"]), "event": it["event"]}
                if "distance_km" in it:
                    out["distance_km"] = it["distance_km"]
                if "zones_visited" in it:
                    out["zones_visited"] = it["zones_visited"]
                rendered.append(out)

        timelines[cat_name] = rendered

    return timelines


# --------- Public API ---------
def get_timelines(start_dt: dt.datetime, end_dt: dt.datetime, active_cats: set | None = None) -> dict:
    """
    Build event-log timelines for an arbitrary time window.
    Returns {cat_name: [event_list]} in the same rendered format as build_timelines.
    active_cats: optional set of cat names to include (e.g. {"Arthur", "King"}).
    """
    zone_index = ZoneIndex(KNOWN_ZONES)
    with connect() as conn:
        cats_map = load_cat_names(conn)
        users_map = load_users(conn)
        initial = load_last_state_before(conn, start_dt)
        sp_rows = load_surepet_events(conn, start_dt, end_dt)
        gps_by_cat = load_tractive_points(conn, start_dt, end_dt)

    timelines = build_timelines(
        sp_rows, gps_by_cat, zone_index, cats_map, users_map, initial,
        since=start_dt, now=end_dt,
    )

    if active_cats:
        timelines = {name: events for name, events in timelines.items() if name in active_cats}

    return timelines


# --------- Main ---------
def main():
    zone_index = ZoneIndex(KNOWN_ZONES)
    with connect() as conn:
        cats_map = load_cat_names(conn)
        users_map = load_users(conn)
        initial = load_last_state_before(conn, SINCE)
        sp_rows = load_surepet_events(conn, SINCE, NOW)
        gps_by_cat = load_tractive_points(conn, SINCE, NOW)

    timelines = build_timelines(sp_rows, gps_by_cat, zone_index, cats_map, users_map, initial)

    for cat in timelines:
        print(cat)
        print(timelines[cat])
        print()

    # out_name = f"timelines_{NOW.date().isoformat()}.json"
    # with open(out_name, "w", encoding="utf-8") as f:
    #     json.dump(timelines, f, indent=2, ensure_ascii=False)
    # print(f"Wrote {out_name}")


if __name__ == "__main__":
    main()
