import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, computed_field, field_validator

from app.geo import is_simple_polygon, polygon_area_m2
from app.models import (
    ASSET_ID_PREFIXES,
    EventSeverity,
    EventType,
    TripCycleStatus,
    TripRowStatus,
    VehicleStatus,
    VehicleType,
    ZoneType,
)


class VehicleCreate(BaseModel):
    asset_id: str
    vehicle_type: Optional[VehicleType] = None  # derived from asset_id prefix if omitted
    traccar_unique_id: Optional[str] = None  # defaults to asset_id if omitted
    # Manual for now; a future VAHAN RC-lookup API would auto-fill these from the plate.
    registration_number: Optional[str] = None
    manufacturer: Optional[str] = None
    capacity_tonnes: Optional[float] = None


class VehicleUpdate(BaseModel):
    """All fields optional — PATCH semantics, only supplied fields change. Primary use
    case: correcting a registration typo, or re-pointing traccar_unique_id at a
    replacement device's IMEI when hardware can't be reconfigured to reuse the old ID
    (DIY ESP32 nodes should instead just keep sending the old identifier, no PATCH
    needed — this is for production hardware with a fixed device ID)."""

    asset_id: Optional[str] = None
    vehicle_type: Optional[VehicleType] = None
    traccar_unique_id: Optional[str] = None
    registration_number: Optional[str] = None
    manufacturer: Optional[str] = None
    capacity_tonnes: Optional[float] = None


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_time: datetime
    received_at: datetime
    latitude: float
    longitude: float
    speed_knots: Optional[float]
    course: Optional[float]
    hdop: Optional[float]
    satellites: Optional[int]


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: str
    vehicle_type: VehicleType
    traccar_unique_id: str
    registration_number: Optional[str] = None
    manufacturer: Optional[str] = None
    capacity_tonnes: Optional[float] = None
    created_at: datetime
    deactivated_at: Optional[datetime] = None
    latest_position: Optional[PositionOut] = None
    status: Optional[VehicleStatus] = None  # derived (see trip_engine.compute_vehicle_status)
    trip_status: Optional[TripCycleStatus] = None  # haul-cycle vehicle types only
    # Set on POST/PATCH /vehicles responses only (router-resolved, not ORM — same pattern
    # as TripOut.load_excavator_asset_id): outcome of the side-registration of the device
    # in Traccar, so the UI can warn without failing the vehicle create/update itself.
    traccar_status: Optional[str] = None  # created | exists | failed | skipped
    traccar_detail: Optional[str] = None


class VehicleDeleteResult(BaseModel):
    """DELETE /vehicles/{id} is guarded: a vehicle with zero trip/position history is
    hard-removed (action="deleted"), one with history is soft-deactivated instead
    (action="deactivated", vehicle carries the updated row) — mirrors the Zone
    versioning idiom of never destroying real operational history."""

    action: str  # deleted | deactivated
    vehicle: Optional[VehicleOut] = None


def derive_vehicle_type(asset_id: str) -> Optional[VehicleType]:
    for prefix, vehicle_type in ASSET_ID_PREFIXES.items():
        if asset_id.startswith(prefix):
            return vehicle_type
    return None


# --- Traccar JSON forwarding payload (verified against traccar/traccar source:
# org.traccar.handler.PositionForwardingHandler always sends {"position": ..., "device": ...}) ---


class TraccarDevice(BaseModel):
    id: int
    name: Optional[str] = None
    uniqueId: str


class TraccarPosition(BaseModel):
    deviceId: int
    protocol: Optional[str] = None
    serverTime: datetime
    deviceTime: Optional[datetime] = None
    fixTime: datetime
    valid: Optional[bool] = None
    latitude: float
    longitude: float
    speed: Optional[float] = None  # knots, Traccar's internal unit
    course: Optional[float] = None
    attributes: dict = {}


class TraccarForwardPayload(BaseModel):
    position: TraccarPosition
    device: TraccarDevice


# --- Zones ---


# Below this, real-world GPS jitter (Neo-6M: ~2.5-5m under good HDOP, worse otherwise)
# risks a stationary truck's fix landing outside the zone often enough to silently miss
# real loading/dumping events — a config-validation problem, not a state-machine one.
MIN_ZONE_AREA_M2 = 100.0


class ZoneCreate(BaseModel):
    name: str
    zone_type: ZoneType
    geometry: dict  # GeoJSON Polygon: {"type": "Polygon", "coordinates": [[[lon, lat], ...]]}
    # Consumed by event_engine's zone_overspeed detector. A limit on a mine_boundary
    # zone acts as the site-wide speed limit.
    speed_limit_kmph: Optional[float] = None

    @field_validator("geometry")
    @classmethod
    def must_be_simple_polygon(cls, v: dict) -> dict:
        if v.get("type") != "Polygon" or not v.get("coordinates"):
            raise ValueError("geometry must be a GeoJSON Polygon with coordinates")
        if not is_simple_polygon(v):
            raise ValueError("polygon must be simple (non-self-intersecting, >=3 vertices)")
        area = polygon_area_m2(v)
        if area < MIN_ZONE_AREA_M2:
            raise ValueError(
                f"zone area ({area:.0f} m²) is below the {MIN_ZONE_AREA_M2:.0f} m² minimum — "
                "too small relative to GPS accuracy, real fixes would often land outside it"
            )
        return v

    @field_validator("speed_limit_kmph")
    @classmethod
    def must_be_positive(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("speed_limit_kmph must be positive")
        return v


class ZoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    zone_key: uuid.UUID
    name: str
    zone_type: ZoneType
    geometry: dict
    speed_limit_kmph: Optional[float] = None
    valid_from: datetime
    valid_to: Optional[datetime]


# --- Trips ---


class TripOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vehicle_id: uuid.UUID
    cycle_number: Optional[int]
    load_zone_id: Optional[uuid.UUID]
    load_excavator_vehicle_id: Optional[uuid.UUID]
    dump_zone_id: Optional[uuid.UUID]
    started_at: datetime
    loaded_at: Optional[datetime]
    dumped_at: Optional[datetime]
    completed_at: Optional[datetime]
    haul_distance_m: Optional[float]  # lead distance: loaded -> dumped breadcrumb path
    trip_distance_m: Optional[float]  # full trip-row path: started -> completed
    status: TripRowStatus
    had_anomalous_entry: bool
    # Resolved by the router (not ORM columns): which excavator filled this truck, and —
    # on the excavator-facing /loads view — which truck was filled. Asset IDs, not UUIDs,
    # because that's what the dashboard displays.
    load_excavator_asset_id: Optional[str] = None
    vehicle_asset_id: Optional[str] = None

    @computed_field
    @property
    def cycle_time_seconds(self) -> Optional[float]:
        """How long the cycle took, start to finish. None while still in_progress."""
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()


# --- Events ---


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vehicle_id: uuid.UUID
    event_type: EventType
    severity: EventSeverity
    event_time: datetime
    detected_at: datetime
    ended_at: Optional[datetime]
    latitude: float
    longitude: float
    zone_id: Optional[uuid.UUID]
    details: Optional[dict]
    delayed: bool
    acknowledged_at: Optional[datetime]
    notified_at: Optional[datetime]
    # Resolved by the router (not ORM columns) — same pattern as TripOut.vehicle_asset_id.
    vehicle_asset_id: Optional[str] = None
    zone_name: Optional[str] = None
