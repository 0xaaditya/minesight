# event_engine.py — theft/safety event detection, run alongside (not inside)
# trip_engine.py so every vehicle type participates: trip_engine early-returns for
# excavators/bowsers/drills/surface miners (they don't run a haul cycle), but a bowser
# moving off-site at 2am is exactly the theft signature this pipeline exists to catch.
#
# Design notes (mirrors trip_engine.py idioms deliberately):
# - One row per EPISODE (open on trigger, ended_at set on close), not one row per
#   position tick — that IS the dedup mechanism (CLAUDE.md: "one event = one alert").
# - Independent VehicleEventState + last_processed_event_time out-of-order guard, same
#   shape as VehicleTripState, but a separate table so this engine never depends on
#   trip_engine having run (it hasn't, for non-haul vehicle types).
# - Openers require 2 consecutive agreeing reads (same anti-flap convention as
#   trip_engine's non-LOADING transitions) except night_movement/quiet-hours-over and
#   breakdown, which close on a single confirming read since there's nothing to debounce
#   (time monotonically leaving the window; trip_engine's own state already debounced).
# - A transient failure here just skips one tick — level-based openers naturally
#   re-satisfy on the next fix while the underlying condition persists (see webhook.py).
import logging
import uuid
from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.geo import point_in_polygon
from app.models import (
    Event,
    EventSeverity,
    EventType,
    Position,
    TripCycleStatus,
    Vehicle,
    VehicleEventState,
    VehicleTripState,
    Zone,
    ZoneType,
)
from app.time_utils import in_quiet_hours
from app.trip_engine import ADJACENT_READS_MAX_GAP

logger = logging.getLogger(__name__)

DELAYED_THRESHOLD = timedelta(minutes=5)  # CLAUDE.md: late-fired alerts marked "delayed"
MOVING_KNOTS_THRESHOLD = 0.5  # same bar as trip_engine's stationary threshold
KNOTS_TO_KMPH = 1.852


def process_position_events(db: Session, position_id: uuid.UUID) -> None:
    position = db.get(Position, position_id)
    if position is None:
        return
    vehicle = db.get(Vehicle, position.vehicle_id)
    if vehicle is None or vehicle.deactivated_at is not None:
        return  # a retired vehicle should never page anyone

    state = db.execute(
        select(VehicleEventState).where(VehicleEventState.vehicle_id == vehicle.id).with_for_update()
    ).scalar_one_or_none()
    if state is None:
        state = VehicleEventState(vehicle_id=vehicle.id)
        db.add(state)
        try:
            db.flush()
        except IntegrityError:
            # Same race as trip_engine.process_position: FOR UPDATE can't lock a row
            # that doesn't exist yet, so two concurrent deliveries for the same
            # brand-new vehicle can both try to insert. Re-fetch the winner's row
            # (guaranteed committed by the time Postgres raises this) instead of
            # dropping this tick's event detection entirely.
            db.rollback()
            state = db.execute(
                select(VehicleEventState).where(VehicleEventState.vehicle_id == vehicle.id).with_for_update()
            ).scalar_one()

    if state.last_processed_event_time is not None and position.event_time <= state.last_processed_event_time:
        logger.warning(
            "Skipping out-of-order position %s for vehicle %s event detection (event_time=%s <= last_processed=%s)",
            position.id, vehicle.id, position.event_time, state.last_processed_event_time,
        )
        return

    recent = db.execute(
        select(Position)
        .where(Position.vehicle_id == vehicle.id, Position.event_time < position.event_time)
        .order_by(Position.event_time.desc())
        .limit(2)
    ).scalars().all()
    prev_position = recent[0] if len(recent) > 0 else None
    prev_prev_position = recent[1] if len(recent) > 1 else None

    delayed = (position.received_at - position.event_time) > DELAYED_THRESHOLD
    zones = _current_zones(db, vehicle.org_id)

    _detect_night_movement(db, vehicle, position, prev_position, delayed)
    _detect_boundary_exit(db, vehicle, position, prev_position, prev_prev_position, zones, delayed)
    _detect_zone_overspeed(db, vehicle, position, prev_position, zones, delayed)
    _detect_breakdown(db, vehicle, position, delayed)

    state.last_processed_event_time = position.event_time
    db.commit()


def _current_zones(db: Session, org_id: uuid.UUID) -> list[Zone]:
    """Unlike trip_engine._active_zones, this INCLUDES mine_boundary — the boundary
    itself is what boundary_exit detects, and a speed limit on it is the site-wide
    limit for zone_overspeed."""
    return list(db.execute(select(Zone).where(Zone.org_id == org_id, Zone.valid_to.is_(None))).scalars())


def _is_moving(p: Position) -> bool:
    return p.speed_knots is not None and p.speed_knots > MOVING_KNOTS_THRESHOLD


def _reads_adjacent(a: Optional[Position], b: Optional[Position]) -> bool:
    """Same fix as trip_engine.ADJACENT_READS_MAX_GAP, same reason: a 2-consecutive-
    reads check only actually debounces jitter if the two STORED reads are temporally
    adjacent. A tick lost in transit (dropout, WiFi gap) can leave two agreeing reads
    that straddle a missing sample the truck genuinely flapped across in between."""
    if a is None or b is None:
        return False
    return abs(a.event_time - b.event_time) <= ADJACENT_READS_MAX_GAP


def _get_open_event(db: Session, vehicle_id: uuid.UUID, event_type: EventType) -> Optional[Event]:
    return db.scalar(
        select(Event).where(
            Event.vehicle_id == vehicle_id, Event.event_type == event_type, Event.ended_at.is_(None)
        )
    )


def _open_event(
    db: Session,
    vehicle: Vehicle,
    position: Position,
    event_type: EventType,
    severity: EventSeverity,
    delayed: bool,
    zone: Optional[Zone] = None,
    details: Optional[dict] = None,
    event_time=None,
) -> Event:
    event = Event(
        org_id=vehicle.org_id,
        vehicle_id=vehicle.id,
        event_type=event_type,
        severity=severity,
        event_time=event_time or position.event_time,
        latitude=position.latitude,
        longitude=position.longitude,
        zone_id=zone.id if zone is not None else None,
        details=details,
        delayed=delayed,
    )
    db.add(event)
    return event


def _close_event(event: Event, position: Position) -> None:
    event.ended_at = position.event_time


# --- night_movement: theft signature, applies to every vehicle type ------------------


def _detect_night_movement(
    db: Session, vehicle: Vehicle, position: Position, prev_position: Optional[Position], delayed: bool
) -> None:
    open_event = _get_open_event(db, vehicle.id, EventType.NIGHT_MOVEMENT)
    now_in_window = in_quiet_hours(position.event_time, settings.quiet_hours_start, settings.quiet_hours_end)
    moving_now = _is_moving(position)
    adjacent = _reads_adjacent(position, prev_position)

    if open_event is None:
        moving_prev = prev_position is not None and _is_moving(prev_position)
        if now_in_window and moving_now and moving_prev and adjacent:
            _open_event(
                db, vehicle, position, EventType.NIGHT_MOVEMENT, EventSeverity.CRITICAL, delayed,
                details={"speed_kmph": round(position.speed_knots * KNOTS_TO_KMPH, 1)},
            )
    else:
        # Closes on quiet-hours-over immediately (time only moves forward, no debounce
        # needed there); stationary close still wants 2 ADJACENT agreeing reads.
        stationary_now = not moving_now
        stationary_prev = prev_position is not None and not _is_moving(prev_position)
        if not now_in_window or (stationary_now and stationary_prev and adjacent):
            _close_event(open_event, position)


# --- boundary_exit: theft signature ---------------------------------------------------


def _inside_any(lat: float, lon: float, zones: list[Zone]) -> bool:
    return any(point_in_polygon(lat, lon, z.geometry) for z in zones)


def _detect_boundary_exit(
    db: Session,
    vehicle: Vehicle,
    position: Position,
    prev_position: Optional[Position],
    prev_prev_position: Optional[Position],
    zones: list[Zone],
    delayed: bool,
) -> None:
    boundary_zones = [z for z in zones if z.zone_type == ZoneType.MINE_BOUNDARY]
    open_event = _get_open_event(db, vehicle.id, EventType.BOUNDARY_EXIT)

    if not boundary_zones:
        # Boundary deleted mid-episode — don't leave the episode open forever.
        if open_event is not None:
            _close_event(open_event, position)
            open_event.details = {**(open_event.details or {}), "closed_reason": "boundary_removed"}
        return

    inside_now = _inside_any(position.latitude, position.longitude, boundary_zones)

    if open_event is None:
        # 2 consecutive outside reads with the reading before them inside — avoids
        # false-firing for a vehicle that was already outside when the boundary was
        # first drawn (e.g. sitting at an off-site workshop). Both adjacent pairs
        # (position/prev, prev/prev_prev) must be temporally adjacent too, or a lost
        # tick could make an in-out-in flap look like a clean exit.
        inside_prev = prev_position is not None and _inside_any(prev_position.latitude, prev_position.longitude, boundary_zones)
        inside_prev_prev = prev_prev_position is not None and _inside_any(
            prev_prev_position.latitude, prev_prev_position.longitude, boundary_zones
        )
        if (
            not inside_now
            and not inside_prev
            and inside_prev_prev
            and _reads_adjacent(position, prev_position)
            and _reads_adjacent(prev_position, prev_prev_position)
        ):
            _open_event(
                db, vehicle, position, EventType.BOUNDARY_EXIT, EventSeverity.CRITICAL, delayed,
                zone=boundary_zones[0],
                details={"zone_names": [z.name for z in boundary_zones]},
            )
    else:
        inside_prev = prev_position is not None and _inside_any(prev_position.latitude, prev_position.longitude, boundary_zones)
        if inside_now and inside_prev and _reads_adjacent(position, prev_position):
            _close_event(open_event, position)


# --- zone_overspeed -------------------------------------------------------------------


def _detect_zone_overspeed(
    db: Session,
    vehicle: Vehicle,
    position: Position,
    prev_position: Optional[Position],
    zones: list[Zone],
    delayed: bool,
) -> None:
    speed_kmph = position.speed_knots * KNOTS_TO_KMPH if position.speed_knots is not None else None
    open_event = _get_open_event(db, vehicle.id, EventType.ZONE_OVERSPEED)

    if open_event is not None:
        zone = next((z for z in zones if z.id == open_event.zone_id), None)
        if zone is None or zone.speed_limit_kmph is None:
            _close_event(open_event, position)
            return
        if not point_in_polygon(position.latitude, position.longitude, zone.geometry):
            _close_event(open_event, position)
            return
        under_now = speed_kmph is not None and speed_kmph <= zone.speed_limit_kmph
        under_prev = (
            prev_position is not None
            and prev_position.speed_knots is not None
            and prev_position.speed_knots * KNOTS_TO_KMPH <= zone.speed_limit_kmph
        )
        if under_now and under_prev and _reads_adjacent(position, prev_position):
            _close_event(open_event, position)
        elif speed_kmph is not None:
            details = dict(open_event.details or {})
            details["speed_kmph"] = round(speed_kmph, 1)
            details["max_speed_kmph"] = max(details.get("max_speed_kmph", 0.0), round(speed_kmph, 1))
            open_event.details = details
        return

    if speed_kmph is None or prev_position is None or prev_position.speed_knots is None:
        return
    prev_speed_kmph = prev_position.speed_knots * KNOTS_TO_KMPH

    limited = [z for z in zones if z.speed_limit_kmph is not None]
    # Non-boundary zones win attribution over the site-wide boundary limit — a stricter
    # pit-zone limit is the more specific, more useful signal.
    ordered = [z for z in limited if z.zone_type != ZoneType.MINE_BOUNDARY] + [
        z for z in limited if z.zone_type == ZoneType.MINE_BOUNDARY
    ]
    for zone in ordered:
        if (
            speed_kmph > zone.speed_limit_kmph
            and prev_speed_kmph > zone.speed_limit_kmph
            and _reads_adjacent(position, prev_position)
        ):
            if point_in_polygon(position.latitude, position.longitude, zone.geometry) and point_in_polygon(
                prev_position.latitude, prev_position.longitude, zone.geometry
            ):
                _open_event(
                    db, vehicle, position, EventType.ZONE_OVERSPEED, EventSeverity.WARNING, delayed,
                    zone=zone,
                    details={
                        "speed_kmph": round(speed_kmph, 1),
                        "limit_kmph": zone.speed_limit_kmph,
                        "zone_name": zone.name,
                        "max_speed_kmph": round(speed_kmph, 1),
                    },
                )
                return


# --- breakdown: piggybacks on trip_engine's own state, run after it in the webhook ---


def _detect_breakdown(db: Session, vehicle: Vehicle, position: Position, delayed: bool) -> None:
    trip_state = db.scalar(select(VehicleTripState).where(VehicleTripState.vehicle_id == vehicle.id))
    open_event = _get_open_event(db, vehicle.id, EventType.BREAKDOWN)
    is_breakdown = trip_state is not None and trip_state.trip_status == TripCycleStatus.BREAKDOWN

    if is_breakdown and open_event is None:
        _open_event(
            db, vehicle, position, EventType.BREAKDOWN, EventSeverity.WARNING, delayed,
            details={
                "pre_breakdown_status": trip_state.pre_breakdown_status.value
                if trip_state.pre_breakdown_status
                else None
            },
            event_time=trip_state.trip_status_since or position.event_time,
        )
    elif not is_breakdown and open_event is not None:
        _close_event(open_event, position)
