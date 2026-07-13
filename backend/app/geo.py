# geo.py — hand-rolled point-in-polygon and haversine distance. No PostGIS/shapely:
# mine-site polygons are small and simple, query volume is low. Revisit only if
# zone complexity/vertex count or query volume grows enough to justify the dependency.
import math

EARTH_RADIUS_M = 6371000.0


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _exterior_ring(polygon: dict) -> list:
    """GeoJSON repeats the first point as the last to close the ring — that duplicate
    must be stripped before edge-list math, or it produces a degenerate zero-length
    edge that confuses both ray-casting and self-intersection checks."""
    ring = polygon["coordinates"][0]
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    return ring


def point_in_polygon(lat: float, lon: float, polygon: dict) -> bool:
    """polygon is a GeoJSON Polygon geometry dict: {"type": "Polygon", "coordinates": [[[lon, lat], ...]]}.
    Only the exterior ring (index 0) is considered — holes are out of scope. Standard
    ray-casting test; boundary-tie-break correctness matters less than the dwell/hysteresis
    that gates real transitions (see trip_engine.py), which is what actually absorbs jitter.
    """
    ring = _exterior_ring(polygon)
    n = len(ring)
    inside = False
    x, y = lon, lat
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        intersect = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi)
        if intersect:
            inside = not inside
        j = i
    return inside


def _orientation(p, q, r) -> int:
    val = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
    if val == 0:
        return 0
    return 1 if val > 0 else 2


def _on_segment(p, q, r) -> bool:
    return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])


def _segments_intersect(p1, q1, p2, q2) -> bool:
    o1, o2 = _orientation(p1, q1, p2), _orientation(p1, q1, q2)
    o3, o4 = _orientation(p2, q2, p1), _orientation(p2, q2, q1)
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and _on_segment(p1, p2, q1):
        return True
    if o2 == 0 and _on_segment(p1, q2, q1):
        return True
    if o3 == 0 and _on_segment(p2, p1, q2):
        return True
    if o4 == 0 and _on_segment(p2, q1, q2):
        return True
    return False


METERS_PER_DEGREE_LAT = 111320.0


def polygon_area_m2(polygon: dict) -> float:
    """Shoelace formula over a local equirectangular projection (flat-earth approximation
    centered on the ring's own latitude) — accurate enough at mine-zone scale (tens to a
    few hundred meters across); no need for full spherical geometry at this size."""
    ring = _exterior_ring(polygon)
    if len(ring) < 3:
        return 0.0
    lat0 = sum(p[1] for p in ring) / len(ring)
    meters_per_degree_lon = METERS_PER_DEGREE_LAT * math.cos(math.radians(lat0))
    xy = [((lon - ring[0][0]) * meters_per_degree_lon, (lat - ring[0][1]) * METERS_PER_DEGREE_LAT) for lon, lat in ring]

    area = 0.0
    n = len(xy)
    for i in range(n):
        x1, y1 = xy[i]
        x2, y2 = xy[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def is_simple_polygon(polygon: dict) -> bool:
    """Rejects self-intersecting rings — point_in_polygon assumes a simple polygon,
    so this must be checked at zone-save time, not left to silently corrupt containment
    results later."""
    ring = _exterior_ring(polygon)
    n = len(ring)
    if n < 3:
        return False
    edges = [(ring[i], ring[(i + 1) % n]) for i in range(n)]
    edge_count = len(edges)
    for i in range(edge_count):
        for j in range(i + 1, edge_count):
            if j == i or j == (i + 1) % edge_count or i == (j + 1) % edge_count:
                continue  # adjacent edges share a vertex by construction; not a self-intersection
            if _segments_intersect(edges[i][0], edges[i][1], edges[j][0], edges[j][1]):
                return False
    return True
