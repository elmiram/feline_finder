# Zone labelling helper using Shapely prepared geometry.
# Reads KNOWN_ZONES from config; labels a list of (lat, lon) pings with zone names.

from shapely.geometry import Point, Polygon as ShapelyPolygon
from shapely.prepared import prep

def label_pings(pings, known_zones):
    """
    pings: list of (lat, lon) tuples
    known_zones: dict of {zone_name: [[lat, lon], ...]} — polygon vertices
    Returns: list of zone_name strings (same length as pings); None if ping is in no zone.
    """
    # Build prepared polygons once
    prepared = {}
    for name, coords in known_zones.items():
        if len(coords) < 3:
            continue
        # KNOWN_ZONES coords are [lat, lon]; Shapely expects (x=lon, y=lat)
        poly = ShapelyPolygon([(lon, lat) for lat, lon in coords])
        if poly.is_valid:
            prepared[name] = prep(poly)

    labels = []
    for lat, lon in pings:
        pt = Point(lon, lat)
        label = None
        for name, ppoly in prepared.items():
            if ppoly.contains(pt):
                label = name
                break
        labels.append(label)
    return labels
