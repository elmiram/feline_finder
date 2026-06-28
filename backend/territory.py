"""
territory.py — Alpha shape territory computation for FelineFinder.

Functions:
  grid_filter(pings, cell_size_m=25, min_count=4) -> list of (lat, lon)
  compute_territory(pings, alpha=1500) -> dict or None
"""

import json
import sys
from math import cos, pi

import alphashape
from shapely.geometry import Point, Polygon, MultiPolygon


# Home area reference latitude for equirectangular area projection.
# 47.166 is the approximate centroid latitude for the cats' territory.
_REF_LAT_RAD = 47.166 * pi / 180
_COS_LAT = cos(_REF_LAT_RAD)   # ≈ 0.6820
_M_PER_DEG_LAT = 111320.0
_M_PER_DEG_LON = _COS_LAT * 111320.0


def grid_filter(pings, cell_size_m=25, min_count=4):
    """Filter pings by grid-cell density.

    Divides the lat/lon space into cells of approximately cell_size_m metres
    using an equirectangular approximation at the centroid latitude.  Only
    pings that fall in cells with at least min_count pings are returned.

    Args:
        pings: list of (lat, lon) tuples.
        cell_size_m: approximate cell side length in metres (default 25).
        min_count: minimum number of pings a cell must contain (default 4).

    Returns:
        Filtered list of (lat, lon) tuples.
    """
    if not pings:
        return []

    # Convert cell size from metres to degrees for each axis.
    cell_deg_lat = cell_size_m / _M_PER_DEG_LAT
    cell_deg_lon = cell_size_m / _M_PER_DEG_LON

    # Count pings per cell.
    cell_counts = {}
    for lat, lon in pings:
        cell_key = (int(lat / cell_deg_lat), int(lon / cell_deg_lon))
        cell_counts[cell_key] = cell_counts.get(cell_key, 0) + 1

    # Keep pings whose cell meets the threshold.
    filtered = []
    for lat, lon in pings:
        cell_key = (int(lat / cell_deg_lat), int(lon / cell_deg_lon))
        if cell_counts[cell_key] >= min_count:
            filtered.append((lat, lon))

    return filtered


def _project_to_metres(shapely_polygon):
    """Project a lat/lon Shapely Polygon to an approximate metre-coordinate
    polygon using equirectangular scaling at the reference latitude.

    Returns a new Shapely Polygon with coordinates in metres.
    """
    def project_ring(coords):
        return [(lon * _M_PER_DEG_LON, lat * _M_PER_DEG_LAT) for lon, lat in coords]

    outer = project_ring(shapely_polygon.exterior.coords)
    holes = [project_ring(ring.coords) for ring in shapely_polygon.interiors]
    return Polygon(outer, holes)


def compute_territory(pings, alpha=1500):
    """Compute a concave-hull territory from GPS pings using alpha shape.

    Args:
        pings: list of (lat, lon) tuples (should already be grid-filtered).
        alpha: alpha parameter passed to alphashape (default 1500, validated
               against Tractive's W26 2026 territory for Arthur).

    Returns:
        dict with keys:
            polygon_json  — JSON string of [[lon, lat], ...] outer ring coords
            holes_json    — JSON string of [[[lon, lat], ...], ...] or None
            area_m2       — float, polygon area in square metres
            ping_count    — int, number of input pings
        or None if fewer than 20 pings or the alpha shape is degenerate.
    """
    if len(pings) < 20:
        return None

    # alphashape expects (x, y) = (lon, lat) order.
    points = [(lon, lat) for lat, lon in pings]

    try:
        shape = alphashape.alphashape(points, alpha)
    except Exception as e:
        print(
            f"territory.py: alphashape raised {type(e).__name__}: {e}. "
            "Likely degenerate/collinear input. Returning None.",
            file=sys.stderr,
        )
        return None

    # Normalise MultiPolygon → largest Polygon.
    if isinstance(shape, MultiPolygon):
        print(
            f"territory.py: alphashape returned MultiPolygon with "
            f"{len(list(shape.geoms))} parts; keeping largest.",
            file=sys.stderr,
        )
        shape = max(shape.geoms, key=lambda g: g.area)

    if not isinstance(shape, Polygon):
        # Point, LineString, GeometryCollection, or empty geometry — unusable.
        print(
            f"territory.py: alphashape returned {type(shape).__name__}, expected Polygon. "
            "Returning None.",
            file=sys.stderr,
        )
        return None

    # Extract outer boundary as [[lon, lat], ...].
    # shapely exterior coords are (x, y) = (lon, lat) already.
    outer_coords = [[lon, lat] for lon, lat in shape.exterior.coords]

    # Extract holes (interior rings).
    holes = []
    for ring in shape.interiors:
        holes.append([[lon, lat] for lon, lat in ring.coords])

    try:
        # Compute area via equirectangular projection to metres.
        projected = _project_to_metres(shape)
        area_m2 = projected.area
    except Exception as e:
        print(
            f"territory.py: area projection raised {type(e).__name__}: {e}. "
            "Returning None.",
            file=sys.stderr,
        )
        return None

    return {
        "polygon_json": json.dumps(outer_coords),
        "holes_json": json.dumps(holes) if holes else None,
        "area_m2": float(area_m2),
        "ping_count": len(pings),
    }
