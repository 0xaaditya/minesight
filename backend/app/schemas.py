import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, computed_field, field_validator

from app.geo import is_simple_polygon, polygon_area_m2
from app.models import (
    ASSET_ID_PREFIXES,
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
    created_at: datetime
    latest_position: Optional[PositionOut] = None
    status: Optional[VehicleStatus] = None  # derived (see trip_engine.compute_vehicle_status)
    trip_status: Optional[TripCycleStatus] = None  # haul-cycle vehicle types only


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


class ZoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    zone_key: uuid.UUID
    name: str
    zone_type: ZoneType
    geometry: dict
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
    status: TripRowStatus
    had_anomalous_entry: bool

    @computed_field
    @property
    def cycle_time_seconds(self) -> Optional[float]:
        """How long the cycle took, start to finish. None while still in_progress."""
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()
