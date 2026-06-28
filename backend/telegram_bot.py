#!/usr/bin/env python3
"""FelineFinder Telegram bot — sends 12h cat activity summaries and handles /summary."""

import datetime as dt
import json
import logging
import os
import sqlite3
from zoneinfo import ZoneInfo

import anthropic
import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from config import ANTHROPIC_API_KEY, KNOWN_ZONES, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# ── Constants ─────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("CAT_DB_PATH", "cat_tracker.db")
TZ = ZoneInfo("Europe/Zurich")
TIMEZONE = pytz.timezone("Europe/Zurich")  # for PTB job scheduling

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# ── Zone lookup ───────────────────────────────────────────────────────────────
def _point_in_poly(lat, lon, polygon_ll):
    x, y = lon, lat
    inside = False
    n = len(polygon_ll)
    for i in range(n):
        lat1, lon1 = polygon_ll[i]
        lat2, lon2 = polygon_ll[(i + 1) % n]
        x1, y1 = lon1, lat1
        x2, y2 = lon2, lat2
        denom = (y2 - y1) or 1e-12
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / denom + x1):
            inside = not inside
    return inside


class _ZoneIndex:
    def __init__(self, zones_dict):
        self._zones = [(name, [(p[0], p[1]) for p in pts]) for name, pts in zones_dict.items()]

    def locate(self, lat, lon):
        for name, poly in self._zones:
            if _point_in_poly(lat, lon, poly):
                return name
        return None


_ZONE_INDEX = _ZoneIndex(KNOWN_ZONES)


# ── Timestamp parsing ─────────────────────────────────────────────────────────
def _parse_ts(s):
    if s is None:
        return None
    s = s.strip()
    if s.endswith("Z"):
        return dt.datetime.fromisoformat(s[:-1]).replace(tzinfo=dt.timezone.utc).astimezone(TZ)
    try:
        d = dt.datetime.fromisoformat(s)
        return d.replace(tzinfo=TZ) if d.tzinfo is None else d.astimezone(TZ)
    except Exception:
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)


# ── Data collection ───────────────────────────────────────────────────────────
def get_activity_summary(start_dt, end_dt):
    """Returns a dict with activity data for Arthur and King for [start_dt, end_dt]."""
    result = {}

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute(
            "SELECT internal_cat_id, cat_name FROM cat_identities WHERE cat_name IN ('Arthur', 'King')"
        )
        cats = {str(r["internal_cat_id"]): r["cat_name"] for r in cur.fetchall()}

        for cat_id, cat_name in cats.items():
            # Stateful flap/manual events in the window
            cur.execute(
                """
                SELECT event_source, direction, timestamp
                FROM surepet_events
                WHERE internal_cat_id = ? AND timestamp >= ? AND timestamp <= ?
                  AND event_source IN (0, 1)
                ORDER BY timestamp ASC
                """,
                (cat_id, start_dt.isoformat(), end_dt.isoformat()),
            )
            events = [
                {"t": _parse_ts(r["timestamp"]), "src": r["event_source"], "dir": r["direction"]}
                for r in cur.fetchall()
            ]

            exits = sum(1 for e in events if e["dir"] == 2)
            entries = sum(1 for e in events if e["dir"] == 1)

            # State just before the window
            cur.execute(
                """
                SELECT direction FROM surepet_events
                WHERE internal_cat_id = ? AND timestamp < ?
                  AND event_source IN (0, 1)
                ORDER BY timestamp DESC LIMIT 1
                """,
                (cat_id, start_dt.isoformat()),
            )
            prev = cur.fetchone()
            state = ("inside" if prev["direction"] == 1 else "outside") if prev else "unknown"

            # Accumulate time outside and track last transition
            time_outside_sec = 0.0
            ptr = start_dt
            last_transition = None

            for ev in events:
                t = ev["t"]
                if state == "outside":
                    time_outside_sec += (t - ptr).total_seconds()
                new_state = "inside" if ev["dir"] == 1 else "outside"
                if new_state != state:
                    last_transition = {
                        "time": t.strftime("%H:%M"),
                        "event": "came inside" if new_state == "inside" else "went outside",
                    }
                state = new_state
                ptr = t

            if state == "outside":
                time_outside_sec += (end_dt - ptr).total_seconds()

            # How long continuously outside (if currently outside)?
            continuously_outside_h = None
            if state == "outside":
                last_exit_t = next((e["t"] for e in reversed(events) if e["dir"] == 2), None)
                outside_since = last_exit_t or start_dt
                continuously_outside_h = round(
                    (end_dt - outside_since).total_seconds() / 3600, 1
                )

            # All GPS points in window
            cur.execute(
                """
                SELECT latitude, longitude, timestamp FROM tractive_gps_positions
                WHERE internal_cat_id = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
                """,
                (cat_id, start_dt.isoformat(), end_dt.isoformat()),
            )
            gps_points = [
                (float(r["latitude"]), float(r["longitude"]), _parse_ts(r["timestamp"]))
                for r in cur.fetchall()
            ]

            # Zone visit sequence with durations
            zone_segments = []
            total_distance_km = 0.0
            if gps_points:
                def _add_seg(zone, secs):
                    if not zone or secs <= 0:
                        return
                    if zone_segments and zone_segments[-1]["zone"] == zone:
                        zone_segments[-1]["duration_min"] += secs / 60
                    else:
                        zone_segments.append({"zone": zone, "duration_min": secs / 60})

                for (lat1, lon1, t1), (lat2, lon2, t2) in zip(gps_points, gps_points[1:]):
                    secs = max(0, (t2 - t1).total_seconds())
                    dlat = abs(lat2 - lat1) * 111000
                    dlon = abs(lon2 - lon1) * 111000 * 0.7
                    total_distance_km += ((dlat**2 + dlon**2) ** 0.5) / 1000
                    za = _ZONE_INDEX.locate(lat1, lon1)
                    zb = _ZONE_INDEX.locate(lat2, lon2)
                    if za == zb:
                        _add_seg(za, secs)
                    else:
                        _add_seg(za, secs // 2)
                        _add_seg(zb, secs - secs // 2)

                for seg in zone_segments:
                    seg["duration_min"] = round(seg["duration_min"])

                # Last known position
                last_lat, last_lon, last_ts = gps_points[-1]
                last_known_zone = _ZONE_INDEX.locate(last_lat, last_lon) or "Unknown area"
                last_gps_at = last_ts.strftime("%H:%M")
            else:
                last_known_zone = None
                last_gps_at = None

            notable = []
            if continuously_outside_h is not None and continuously_outside_h > 3:
                notable.append(f"Continuously outside for {continuously_outside_h}h")

            result[cat_name] = {
                "exits": exits,
                "entries": entries,
                "time_outside_minutes": int(time_outside_sec / 60),
                "current_state": state,
                "last_known_zone": last_known_zone,
                "last_gps_at": last_gps_at,
                "last_transition": last_transition,
                "zones_visited": zone_segments,
                "total_distance_km": round(total_distance_km, 2),
                "notable_events": notable,
            }

    return result


# ── AI summary ────────────────────────────────────────────────────────────────
def generate_summary(window_hours=12):
    """Collects data for the past window_hours and returns {cat_name: summary_text}."""
    tz = pytz.timezone("Europe/Zurich")
    end = dt.datetime.now(tz)
    start = end - dt.timedelta(hours=window_hours)
    data = get_activity_summary(start, end)
    window = {
        "from": start.strftime("%Y-%m-%d %H:%M"),
        "to": end.strftime("%Y-%m-%d %H:%M"),
    }

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    summaries = {}

    for cat_name, cat_data in data.items():
        payload = {cat_name: cat_data, "_window": window}
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=(
                "You write activity summaries for a cat monitoring app. "
                "Be warm and specific — mention actual zones, durations, transitions, "
                "and anything that might interest the owner (e.g. an unusually long outing, "
                "a cat that hasn't gone out at all, repeated trips in quick succession, "
                "time spent in a favourite or unusual spot). Include everything genuinely "
                "useful; don't cut detail just to be brief."
            ),
            messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
        )
        summaries[cat_name] = response.content[0].text

    return summaries


# ── Telegram handlers ─────────────────────────────────────────────────────────
async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status = await update.message.reply_text("Fetching summary...")
    try:
        summaries = generate_summary()
        await status.delete()
        for text in summaries.values():
            await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Error in /summary: {e}")
        await status.edit_text("Sorry, couldn't generate the summary right now.")


async def scheduled_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        summaries = generate_summary()
        for text in summaries.values():
            await context.bot.send_message(chat_id=int(TELEGRAM_CHAT_ID), text=text)
        logger.info("Scheduled summary sent.")
    except Exception as e:
        logger.error(f"Error in scheduled summary: {e}")
        await context.bot.send_message(
            chat_id=int(TELEGRAM_CHAT_ID),
            text="Sorry, couldn't generate the scheduled summary right now.",
        )


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    user_filter = filters.User(user_id=int(TELEGRAM_CHAT_ID))
    application.add_handler(CommandHandler("summary", summary_command, filters=user_filter))

    job_queue = application.job_queue
    job_queue.run_daily(
        scheduled_summary,
        dt.time(hour=8, minute=0, tzinfo=TIMEZONE),
        name="morning_summary",
    )
    job_queue.run_daily(
        scheduled_summary,
        dt.time(hour=20, minute=0, tzinfo=TIMEZONE),
        name="evening_summary",
    )

    logger.info("FelineFinder Telegram bot started.")
    application.run_polling(timeout=30)


if __name__ == "__main__":
    main()
