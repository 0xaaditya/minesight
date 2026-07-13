import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, Float, ForeignKey, Integer, String, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _enum_column(enum_cls, **kwargs):
    """Enum(...) sends the Python member's .name by default, not .value — this makes it
    send .value so it matches the lowercase Postgres enum values (bit us once already)."""
    return Enum(enum_cls, values_callable=lambda cls: [e.value for e in cls], **kwargs)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VehicleType(str, enum.Enum):
    TIPPER = "tipper"
    EXCAVATOR = "excavator"
    LOADER = "loader"
    BOWSER = "bowser"
    DRILL = "drill"
    SURFACE_MINER = "surface_miner"


# Asset-ID prefix convention from CLAUDE.md.
ASSET_ID_PREFIXES = {
    "S-": VehicleType.TIPPER,
    "EX-": VehicleType.EXCAVATOR,
    "L-": VehicleType.LOADER,
    "BB-": VehicleType.BOWSER,
    "K-": VehicleType.DRILL,
    "CSM-": VehicleType.SURFACE_MINER,
}

# Only these vehicle types run the trip-cycle state machine; excavators are a zone
# anchor (dynamic circle), not a haul-cycle participant. Bowsers/drills/surface miners
# don't do loading/dumping cycles either.
HAUL_CYCLE_VEHICLE_TYPES = {VehicleType.TIPPER, VehicleType.LOADER}


class ZoneType(str, enum.Enum):
    LOADING = "loading"
    DUMPING = "dumping"
    PARKING = "parking"
    NO_GO = "no_go"


class ZoneAuditAction(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    CLOSE = "close"


class TripCycleStatus(str, enum.Enum):
    IDLE = "idle"
    LOADING = "loading"
    HAULING = "hauling"
    DUMPING = "dumping"
    RETURNING = "returning"
    BREAKDOWN = "breakdown"


class TripRowStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABORTED = "aborted"


class VehicleStatus(str, enum.Enum):
    """The Samarth-style 5-state taxonomy. Never persisted or independently detected —
    always derived at read time from trip_engine.compute_vehicle_status(), so it can
    never contradict TripCycleStatus.BREAKDOWN (see CLAUDE.md backend rules)."""

    RUNNING = "running"
    IDLE = "idle"
    BREAKDOWN = "breakdown"
    NO_COMM = "no_comm"
    NOT_INSTALLED = "not_installed"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="organization")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    asset_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    vehicle_type: Mapped[VehicleType] = mapped_column(
        Enum(VehicleType, values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    # Matches Traccar's `id=` unique identifier. Same as asset_id today (our own ESP32 nodes),
    # kept as a separate column since production Teltonika devices may use a different one.
    traccar_unique_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    organization: Mapped["Organization"] = relationship(back_populates="vehicles")
    positions: Mapped[list["Position"]] = relationship(back_populates="vehicle")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (Index("ix_positions_vehicle_event_time", "vehicle_id", "event_time"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)

    # CLAUDE.md: "process by event timestamp, not arrival time" — both are stored explicitly
    # so buffered/delayed positions (store-and-forward) remain visibly distinguishable.
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    speed_knots: Mapped[float] = mapped_column(Float, nullable=True)
    course: Mapped[float] = mapped_column(Float, nullable=True)
    hdop: Mapped[float] = mapped_column(Float, nullable=True)
    satellites: Mapped[int] = mapped_column(Integer, nullable=True)
    # Traccar's cumulative odometer (DistanceHandler's totalDistance attribute, meters).
    # Distance-between-two-moments is a delta of this, not a re-summed breadcrumb —
    # we don't rebuild what Traccar provides (CLAUDE.md).
    total_distance_m: Mapped[float] = mapped_column(Float, nullable=True)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=True)

    vehicle: Mapped["Vehicle"] = relationship(back_populates="positions")


class Zone(Base):
    """Versioned static zone. 'Editing' a zone never mutates a row in place — it closes
    the current version (valid_to=now) and inserts a new one sharing zone_key, so
    historical reports can filter valid_from <= as_of < valid_to. Trip rows reference a
    specific Zone version id directly, which naturally pins them to the zone shape that
    was active at the time, without needing a separate as-of lookup for linked trips."""

    __tablename__ = "zones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    zone_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    zone_type: Mapped[ZoneType] = mapped_column(_enum_column(ZoneType), nullable=False)
    geometry: Mapped[dict] = mapped_column(JSONB, nullable=False)  # GeoJSON Polygon
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class ZoneAuditLog(Base):
    __tablename__ = "zone_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    zone_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    action: Mapped[ZoneAuditAction] = mapped_column(_enum_column(ZoneAuditAction), nullable=False)
    old_value: Mapped[dict] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict] = mapped_column(JSONB, nullable=True)
    # No User model yet (auth is deferred) — left null until wired up, not an FK yet.
    edited_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (
        # Normal trips have exactly one load reference. The exception: reaching DUMPING
        # without ever passing through LOADING (anomalous) has no valid load ref — only
        # allowed when had_anomalous_entry is set, so the flag and the missing reference
        # always travel together rather than looking like silent data loss.
        CheckConstraint(
            "(had_anomalous_entry = true AND load_zone_id IS NULL AND load_excavator_vehicle_id IS NULL) "
            "OR (had_anomalous_entry = false AND "
            "(CASE WHEN load_zone_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN load_excavator_vehicle_id IS NOT NULL THEN 1 ELSE 0 END) = 1)",
            name="ck_trip_load_ref_matches_anomaly_flag",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)

    # Assigned at DUMPING-entry (the cycle++ moment); a per-vehicle lifetime monotonic
    # sequence stored on the row itself, not a resettable counter anywhere. "Cycles today"
    # is a COUNT query filtered by IST day boundaries, not a running total.
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=True)

    load_zone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("zones.id"), nullable=True)
    load_excavator_vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    dump_zone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("zones.id"), nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    dumped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    # Lead distance: path distance actually driven from the load point to the dump point
    # (mining "lead"), summed over the GPS breadcrumb between loaded_at and dumped_at.
    # Set at the cycle++ moment (DUMPING entry). Null for anomalous trips with no load ref.
    haul_distance_m: Mapped[float] = mapped_column(Float, nullable=True)
    # Full trip-row path distance (started_at -> completed_at, i.e. LOADING entry through
    # DUMPING exit). The empty return leg back to the next loading point belongs to the
    # NEXT trip's pre-loading travel, so a full dump-to-dump round trip is this trip's
    # haul + the next trip's approach — reporting can join them later without re-deriving.
    trip_distance_m: Mapped[float] = mapped_column(Float, nullable=True)

    status: Mapped[TripRowStatus] = mapped_column(
        _enum_column(TripRowStatus), nullable=False, default=TripRowStatus.IN_PROGRESS
    )
    # Physical position won during an unexpected zone entry (e.g. reached DUMPING without
    # ever being HAULING) — the transition still happens, but this flags it as a signal
    # worth surfacing rather than silently forcing or ignoring it.
    had_anomalous_entry: Mapped[bool] = mapped_column(Boolean, default=False)


class VehicleTripState(Base):
    """1:1 with Vehicle, kept as a separate table rather than columns on Vehicle: the
    registry table is stable/low-churn and read on nearly every request, while this
    mutates on every ~30s position tick and is meaningless (permanently null) for
    excavator/bowser/drill/surface_miner rows that never run a haul cycle."""

    __tablename__ = "vehicle_trip_state"

    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"), primary_key=True)

    trip_status: Mapped[TripCycleStatus] = mapped_column(_enum_column(TripCycleStatus), nullable=True)
    trip_status_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_moving_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_processed_event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    current_trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id"), nullable=True)
    paired_excavator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    pre_breakdown_status: Mapped[TripCycleStatus] = mapped_column(
        _enum_column(TripCycleStatus), nullable=True
    )
