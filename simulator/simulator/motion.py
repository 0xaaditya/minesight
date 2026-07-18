# motion.py — local flat-earth movement math, same equirectangular approximation
# backend/app/geo.py uses for polygon_area_m2 (accurate enough at mine-zone/haul-road
# scale, no need for full spherical geometry).
import math

from simulator.layout import METERS_PER_DEGREE_LAT, meters_per_degree_lon


def delta_m(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> tuple[float, float, float, float]:
    """Returns (north_m, east_m, distance_m, bearing_deg). Bearing is compass convention
    (0=north, 90=east) to match the `course`/`bearing` OsmAnd field."""
    north = (to_lat - from_lat) * METERS_PER_DEGREE_LAT
    east = (to_lon - from_lon) * meters_per_degree_lon(from_lat)
    distance = math.hypot(north, east)
    bearing = math.degrees(math.atan2(east, north)) % 360.0
    return north, east, distance, bearing


def move_toward(
    lat: float, lon: float, target_lat: float, target_lon: float, max_distance_m: float
) -> tuple[float, float, bool, float]:
    """Advance from (lat, lon) toward (target_lat, target_lon) by up to max_distance_m.
    Returns (new_lat, new_lon, arrived, bearing_deg). Snaps exactly to the target instead
    of overshooting when max_distance_m covers the remaining gap."""
    north, east, distance, bearing = delta_m(lat, lon, target_lat, target_lon)
    if distance <= max_distance_m or distance < 1e-6:
        return target_lat, target_lon, True, bearing
    frac = max_distance_m / distance
    new_lat = lat + (north * frac) / METERS_PER_DEGREE_LAT
    new_lon = lon + (east * frac) / meters_per_degree_lon(lat)
    return new_lat, new_lon, False, bearing
