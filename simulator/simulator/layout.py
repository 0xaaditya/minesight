# layout.py — synthetic site geometry. Deliberately placed away from the real dev/demo
# data already sitting in the local DB (existing zones cluster around lat~18.61,
# lon~73.74 from manual testing) so simulator runs never spatially collide with it.
#
# Dynamic loading (excavator circles) needs no Zone row at all — trip_engine derives it
# live from EXCAVATOR vehicles' own positions (CLAUDE.md: "Dynamic excavator zones...
# Implemented in FastAPI (haversine), not Traccar"). Only DUMPING/PARKING/NO_GO/
# MINE_BOUNDARY are real Zone rows here, matching what the backend actually models.
import math

from simulator.identity import EXCAVATOR, VehicleSpec

SITE_CENTER_LAT = 18.5000
SITE_CENTER_LON = 73.6500

METERS_PER_DEGREE_LAT = 111320.0


def meters_per_degree_lon(lat: float) -> float:
    return METERS_PER_DEGREE_LAT * math.cos(math.radians(lat))


def offset_latlon(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    """Local equirectangular offset — same flat-earth approximation backend/app/geo.py
    uses for polygon_area_m2, accurate enough at mine-zone scale."""
    new_lat = lat + north_m / METERS_PER_DEGREE_LAT
    new_lon = lon + east_m / meters_per_degree_lon(lat)
    return new_lat, new_lon


def make_rectangle(center_lat: float, center_lon: float, half_north_m: float, half_east_m: float) -> dict:
    """GeoJSON Polygon, [lon, lat] pairs (matches backend/app/geo.py's coordinate order),
    ring closed by repeating the first point, corners well clear of MIN_ZONE_AREA_M2."""
    corners_offsets = [
        (-half_north_m, -half_east_m),
        (-half_north_m, half_east_m),
        (half_north_m, half_east_m),
        (half_north_m, -half_east_m),
    ]
    ring = [offset_latlon(center_lat, center_lon, n, e) for n, e in corners_offsets]
    coords = [[lon, lat] for lat, lon in ring]
    coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


class ZoneSpec:
    def __init__(self, name: str, zone_type: str, geometry: dict, speed_limit_kmph: float | None = None):
        self.name = name
        self.zone_type = zone_type
        self.geometry = geometry
        self.speed_limit_kmph = speed_limit_kmph

    def center_latlon(self) -> tuple[float, float]:
        """Centroid of the exterior ring (dedup the closing point GeoJSON repeats) —
        good enough for navigation targets; zones here are simple rectangles."""
        ring = self.geometry["coordinates"][0]
        if len(ring) > 1 and ring[0] == ring[-1]:
            ring = ring[:-1]
        lon = sum(p[0] for p in ring) / len(ring)
        lat = sum(p[1] for p in ring) / len(ring)
        return lat, lon


class SiteLayout:
    def __init__(self, zones: list[ZoneSpec], excavator_anchors: dict[str, tuple[float, float]]):
        self.zones = zones
        self.excavator_anchors = excavator_anchors  # asset_id -> (lat, lon)

    def zone_by_name(self, name: str) -> ZoneSpec:
        for z in self.zones:
            if z.name == name:
                return z
        raise KeyError(f"no zone named {name!r} in layout")

    def zone_by_type(self, zone_type: str) -> ZoneSpec:
        """Preferred over zone_by_name for scenario code: each site has exactly one
        zone per type, and this doesn't need to know the site_index-suffixed name a
        multi-site layout actually assigned it (see build_layout's site_index docstring)."""
        for z in self.zones:
            if z.zone_type == zone_type:
                return z
        raise KeyError(f"no zone of type {zone_type!r} in layout")


def build_layout(roster: list[VehicleSpec], site_index: int = 0) -> SiteLayout:
    """site_index isolates ENTIRELY SEPARATE runs (e.g. each seed in aggregate.py's
    sweep) from one another physically, not just by vehicle ID. Every excavator anchor
    used to be assigned purely by roster index (north=250, east=-300+i*180 from a fixed
    SITE_CENTER), so every separate simulator invocation's "first excavator" landed at
    the IDENTICAL physical spot — confirmed live: two excavators from unrelated runs
    sitting ~3m apart, each with real (and therefore cross-contaminated) load counts,
    because trip_engine's nearest-excavator attribution has no notion of "which
    simulator run this position came from" — it only sees stored Positions, and
    multiple runs sharing both site geometry AND simulated time range (aggregate.py's
    sweep always reuses the same --date/--shift-start-ist across seeds) can and do
    pair a truck from one run with an excavator from a completely different one.
    5km spacing per site_index guarantees zero overlap given the ~1600m boundary span."""
    site_lat, site_lon = offset_latlon(SITE_CENTER_LAT, SITE_CENTER_LON, north_m=site_index * 5000.0, east_m=0.0)
    suffix = f" #{site_index}" if site_index else ""

    boundary = make_rectangle(site_lat, site_lon, half_north_m=650, half_east_m=800)
    dump_center = offset_latlon(site_lat, site_lon, north_m=-350, east_m=350)
    parking_center = offset_latlon(site_lat, site_lon, north_m=450, east_m=-500)
    no_go_center = offset_latlon(site_lat, site_lon, north_m=-450, east_m=-600)

    zones = [
        ZoneSpec(
            f"Sim Mine Boundary{suffix}", "mine_boundary", boundary, speed_limit_kmph=40.0
        ),
        ZoneSpec(f"Sim Dumping Pad{suffix}", "dumping", make_rectangle(*dump_center, half_north_m=35, half_east_m=35)),
        ZoneSpec(f"Sim Parking Yard{suffix}", "parking", make_rectangle(*parking_center, half_north_m=30, half_east_m=30)),
        ZoneSpec(f"Sim No-Go Zone{suffix}", "no_go", make_rectangle(*no_go_center, half_north_m=25, half_east_m=25)),
    ]

    excavators = [v for v in roster if v.vehicle_type == EXCAVATOR]
    anchors: dict[str, tuple[float, float]] = {}
    # Spread benches ~180m apart along an east-west line north of center — far enough
    # apart that they're independent by default; a dedicated close-pair scenario
    # (two_excavators_close_near_equidistant) relocates two anchors within 40m instead.
    for i, ex in enumerate(excavators):
        anchors[ex.asset_id] = offset_latlon(site_lat, site_lon, north_m=250, east_m=-300 + i * 180)

    return SiteLayout(zones=zones, excavator_anchors=anchors)


def dump_zone_name(site_index: int = 0) -> str:
    return f"Sim Dumping Pad #{site_index}" if site_index else "Sim Dumping Pad"


def parking_zone_name(site_index: int = 0) -> str:
    return f"Sim Parking Yard #{site_index}" if site_index else "Sim Parking Yard"


def mine_boundary_name(site_index: int = 0) -> str:
    return f"Sim Mine Boundary #{site_index}" if site_index else "Sim Mine Boundary"


# Back-compat defaults (site_index=0, i.e. the original single site) for call sites
# that don't need multi-site isolation.
DUMP_ZONE_NAME = "Sim Dumping Pad"
PARKING_ZONE_NAME = "Sim Parking Yard"
MINE_BOUNDARY_NAME = "Sim Mine Boundary"
