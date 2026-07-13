# trip_engine.py — the proprietary logic CLAUDE.md's architecture says lives in FastAPI,
# not Traccar: per-vehicle trip-cycle state machine (IDLE/LOADING/HAULING/DUMPING/
# RETURNING/BREAKDOWN), zone + dynamic-excavator-circle membership, cycle counting.
#
# Design notes:
# - LOADING entry uses an Amnex-style rule (per real-world reference behavior): a truck is
#   only considered loaded after sitting continuously stationary inside the same loading
#   zone/excavator circle for LOADING_DWELL (3 minutes) — see _confirm_loading_dwell(). A
#   looser "2 consecutive reads agree" check would also pass for a truck merely driving
#   through without actually being loaded, so this transition specifically needs a real
#   time-based dwell, not just jitter-filtering.
# - Every OTHER transition (LOADING-exit, DUMPING-entry, DUMPING-exit) uses a lighter
#   two-consecutive-readings agreement instead of a duration: the firmware's smart trigger
#   sends roughly every 30s, which already exceeds any sensible sub-minute dwell window, so
#   a duration check would rarely see more than one sample inside it anyway. Requiring the
#   previous AND current position to agree achieves the same anti-flap/anti-gaming goal (a
#   driver can't get a cycle credited by clipping the dump-zone edge for one packet) without
#   needing extra persisted "pending transition" state.
# - The 5-state vehicle status (Running/Idle/Breakdown/No-comm/Not-installed) is NOT computed
#   here — it's derived at read time in compute_vehicle_status() from trip_status plus position
#   recency, so it can never independently contradict this engine's own BREAKDOWN detection.
import logging
import uuid
from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.geo import haversine_meters, point_in_polygon
from app.models import (
    HAUL_CYCLE_VEHICLE_TYPES,
    Position,
    Trip,
    TripCycleStatus,
    TripRowStatus,
    Vehicle,
    VehicleStatus,
    VehicleTripState,
    VehicleType,
    Zone,
    ZoneType,
)

logger = logging.getLogger(__name__)

BREAKDOWN_AFTER = timedelta(minutes=15)
STATIONARY_KNOTS_THRESHOLD = 0.5
STATIONARY_DEBOUNCE_READINGS = 2  # consecutive above-threshold reads before counting as "moving"
LOADING_DWELL = timedelta(minutes=1)  # Amnex-style: stationary in the same zone/circle this long
# NOTE: shortened from the reference 3 minutes for field-testing convenience — revert to
# timedelta(minutes=3) once done testing; 1 min is too quick to reliably filter out a
# truck merely pausing briefly (e.g. at a stop sign) in production.
EXCAVATOR_ENTER_RADIUS_M = 50.0
EXCAVATOR_SUSTAIN_RADIUS_M = 75.0  # kept at 1.5x enter, same hysteresis ratio as before
EXCAVATOR_LIVENESS = timedelta(minutes=2)
NO_COMM_AFTER = timedelta(minutes=10)

# A membership is either ("static", Zone) or ("dynamic_excavator", vehicle_id) or None.
Membership = Optional[tuple]


def process_position(db: Session, position_id: uuid.UUID) -> None:
    position = db.get(Position, position_id)
    if position is None:
        return
    vehicle = db.get(Vehicle, position.vehicle_id)
    if vehicle is None or vehicle.vehicle_type not in HAUL_CYCLE_VEHICLE_TYPES:
        return  # excavators/bowsers/drills/surface miners don't run a haul cycle

    state = db.execute(
        select(VehicleTripState).where(VehicleTripState.vehicle_id == vehicle.id).with_for_update()
    ).scalar_one_or_none()
    if state is None:
        state = VehicleTripState(
            vehicle_id=vehicle.id,
            trip_status=TripCycleStatus.IDLE,
            trip_status_since=position.event_time,
        )
        db.add(state)
        db.flush()

    if state.last_processed_event_time is not None and position.event_time <= state.last_processed_event_time:
        # True reordering/duplicate timestamp — not the verified store-and-forward late-delivery
        # path (that's always strictly increasing, just delayed, and is processed normally).
        logger.warning(
            "Skipping out-of-order position %s for vehicle %s (event_time=%s <= last_processed=%s)",
            position.id, vehicle.id, position.event_time, state.last_processed_event_time,
        )
        return

    _update_stationary_state(db, vehicle, position, state)

    if state.trip_status == TripCycleStatus.BREAKDOWN:
        _maybe_resume_from_breakdown(state, position)
    else:
        zones = _active_zones(db, vehicle.org_id)
        excavators = _fresh_excavator_positions(db, vehicle.org_id, position.event_time)

        membership = _determine_membership(
            position.latitude, position.longitude, zones, excavators, state.paired_excavator_id
        )
        prev_position = db.execute(
            select(Position)
            .where(Position.vehicle_id == vehicle.id, Position.event_time < position.event_time)
            .order_by(Position.event_time.desc())
            .limit(1)
        ).scalar_one_or_none()
        prev_membership = (
            _determine_membership(
                prev_position.latitude, prev_position.longitude, zones, excavators, state.paired_excavator_id
            )
            if prev_position is not None
            else None
        )

        # _determine_membership already applied the sustain-radius hysteresis for any
        # existing pairing — if it didn't return "dynamic_excavator", that pairing (if any)
        # has genuinely lapsed and must be cleared, not preserved.
        if membership and membership[0] == "dynamic_excavator":
            state.paired_excavator_id = membership[1].id
        else:
            state.paired_excavator_id = None

        confirmed = membership is not None and prev_membership is not None and _same_membership(membership, prev_membership)
        confirmed_none = membership is None and prev_membership is None

        _apply_zone_transition(
            db, vehicle, state, position,
            raw_membership=membership,
            confirmed_2reads_membership=membership if confirmed else None,
            confirmed_2reads_outside=confirmed_none,
            zones=zones,
            excavators=excavators,
        )

        # _determine_membership already scans zones of every type (not just LOADING/DUMPING —
        # that filtering happens later in _zone_target_status), so membership itself already
        # tells us "inside some zone, of any kind, or an excavator circle" for this check.
        is_inside_any_zone = membership is not None
        if state.last_moving_at is not None and (position.event_time - state.last_moving_at) > BREAKDOWN_AFTER and not is_inside_any_zone:
            state.pre_breakdown_status = state.trip_status
            state.trip_status = TripCycleStatus.BREAKDOWN
            state.trip_status_since = position.event_time

    state.last_processed_event_time = position.event_time
    db.commit()


def _update_stationary_state(db: Session, vehicle: Vehicle, position: Position, state: VehicleTripState) -> None:
    recent = db.execute(
        select(Position)
        .where(Position.vehicle_id == vehicle.id, Position.event_time <= position.event_time)
        .order_by(Position.event_time.desc())
        .limit(STATIONARY_DEBOUNCE_READINGS)
    ).scalars().all()
    if len(recent) >= STATIONARY_DEBOUNCE_READINGS and all(
        p.speed_knots is not None and p.speed_knots > STATIONARY_KNOTS_THRESHOLD for p in recent
    ):
        state.last_moving_at = position.event_time


def _maybe_resume_from_breakdown(state: VehicleTripState, position: Position) -> None:
    if state.last_moving_at == position.event_time:  # this reading is what confirmed "moving" again
        state.trip_status = state.pre_breakdown_status or TripCycleStatus.IDLE
        state.pre_breakdown_status = None
        state.trip_status_since = position.event_time


def _active_zones(db: Session, org_id: uuid.UUID) -> list[Zone]:
    return list(
        db.execute(
            select(Zone).where(Zone.org_id == org_id, Zone.valid_to.is_(None))
        ).scalars()
    )


def _fresh_excavator_positions(db: Session, org_id: uuid.UUID, as_of) -> list[tuple[Vehicle, Position]]:
    cutoff = as_of - EXCAVATOR_LIVENESS
    excavators = db.execute(
        select(Vehicle).where(Vehicle.org_id == org_id, Vehicle.vehicle_type == VehicleType.EXCAVATOR)
    ).scalars().all()
    result = []
    for ex in excavators:
        latest = db.execute(
            select(Position)
            .where(Position.vehicle_id == ex.id, Position.event_time >= cutoff, Position.event_time <= as_of)
            .order_by(Position.event_time.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest is not None:
            result.append((ex, latest))
    return result


def _determine_membership(
    lat: float,
    lon: float,
    zones: list[Zone],
    excavators: list[tuple[Vehicle, Position]],
    currently_paired_excavator_id: Optional[uuid.UUID],
) -> Membership:
    # Dynamic excavator circles take precedence over static polygons (more operationally
    # specific). Hysteresis: if already paired with an excavator, use the wider sustain
    # radius for THAT excavator so its own repositioning mid-load doesn't drop the pairing;
    # otherwise use the tighter enter radius and pick the nearest.
    if currently_paired_excavator_id is not None:
        for ex, ex_pos in excavators:
            if ex.id == currently_paired_excavator_id:
                if haversine_meters(lat, lon, ex_pos.latitude, ex_pos.longitude) <= EXCAVATOR_SUSTAIN_RADIUS_M:
                    return ("dynamic_excavator", ex)
                break

    nearest_excavator, nearest_dist = None, None
    for ex, ex_pos in excavators:
        dist = haversine_meters(lat, lon, ex_pos.latitude, ex_pos.longitude)
        if dist <= EXCAVATOR_ENTER_RADIUS_M and (nearest_dist is None or dist < nearest_dist):
            nearest_excavator, nearest_dist = ex, dist
    if nearest_excavator is not None:
        return ("dynamic_excavator", nearest_excavator)

    for zone in zones:
        if point_in_polygon(lat, lon, zone.geometry):
            return ("static", zone)

    return None


def _same_membership(a: Membership, b: Membership) -> bool:
    if a is None or b is None:
        return a is b
    if a[0] != b[0]:
        return False
    return a[1].id == b[1].id


def _zone_target_status(membership: Membership) -> Optional[TripCycleStatus]:
    if membership is None:
        return None
    kind, ref = membership
    if kind == "dynamic_excavator":
        return TripCycleStatus.LOADING
    if kind == "static":
        zone: Zone = ref
        if zone.zone_type == ZoneType.LOADING:
            return TripCycleStatus.LOADING
        if zone.zone_type == ZoneType.DUMPING:
            return TripCycleStatus.DUMPING
    return None  # PARKING / NO_GO don't drive the haul-cycle state machine


def _confirm_loading_dwell(
    db: Session,
    vehicle: Vehicle,
    position: Position,
    target_membership: Membership,
    zones: list[Zone],
    excavators: list[tuple[Vehicle, Position]],
) -> bool:
    """Amnex-style rule: a truck is only considered loaded after sitting continuously
    stationary inside the same loading zone/excavator circle for LOADING_DWELL (3 min).
    Re-evaluates membership with currently_paired_excavator_id=None throughout — this is
    the entry check (not yet paired), so only the tighter enter radius applies uniformly;
    the sustain-radius hysteresis is a separate mechanism for maintaining an existing
    pairing once LOADING is already confirmed.

    Scans backward from the current position for the start of the continuous
    stationary + same-membership streak, then checks whether that start predates the
    3-minute window — i.e. the streak didn't just begin, it's been going on for at
    least that long. (A naive "every position within the window matches" check would
    always look satisfied right as the streak begins, since the window itself is what
    bounds the query — it can't distinguish "just arrived" from "been here 3+ minutes.")
    """
    window_start = position.event_time - LOADING_DWELL
    # Bounded lookback: at ~30s reporting cadence this is ~30 minutes of history, far
    # more than needed to prove or disprove a 3-minute streak in any realistic case.
    candidates = db.execute(
        select(Position)
        .where(Position.vehicle_id == vehicle.id, Position.event_time <= position.event_time)
        .order_by(Position.event_time.desc())
        .limit(60)
    ).scalars().all()

    streak_start = None
    for p in candidates:
        if p.speed_knots is None or p.speed_knots > STATIONARY_KNOTS_THRESHOLD:
            break
        p_membership = _determine_membership(p.latitude, p.longitude, zones, excavators, None)
        if not _same_membership(p_membership, target_membership):
            break
        streak_start = p.event_time

    return streak_start is not None and streak_start <= window_start


def _open_loading_trip(
    db: Session, vehicle: Vehicle, state: VehicleTripState, position: Position, membership: Membership
) -> None:
    if state.current_trip_id is not None:
        open_trip = db.get(Trip, state.current_trip_id)
        if open_trip is not None and open_trip.status == TripRowStatus.IN_PROGRESS:
            # Re-entering LOADING before ever reaching DUMPING — the previous attempt
            # never completed; abort it rather than leave a phantom open row.
            open_trip.status = TripRowStatus.ABORTED

    kind, ref = membership
    trip = Trip(
        vehicle_id=vehicle.id,
        org_id=vehicle.org_id,
        load_zone_id=ref.id if kind == "static" else None,
        load_excavator_vehicle_id=ref.id if kind == "dynamic_excavator" else None,
        started_at=position.event_time,
        status=TripRowStatus.IN_PROGRESS,
    )
    db.add(trip)
    db.flush()
    state.current_trip_id = trip.id
    state.trip_status = TripCycleStatus.LOADING
    state.trip_status_since = position.event_time


def _apply_zone_transition(
    db: Session,
    vehicle: Vehicle,
    state: VehicleTripState,
    position: Position,
    raw_membership: Membership,
    confirmed_2reads_membership: Membership,
    confirmed_2reads_outside: bool,
    zones: list[Zone],
    excavators: list[tuple[Vehicle, Position]],
) -> None:
    # LOADING entry uses its own, stronger dwell+stationary confirmation (Amnex-style) —
    # not the generic 2-consecutive-reads check used for every other transition, since a
    # truck merely driving through a loading zone would otherwise pass that looser check.
    raw_target = _zone_target_status(raw_membership)
    if raw_target == TripCycleStatus.LOADING and state.trip_status != TripCycleStatus.LOADING:
        if _confirm_loading_dwell(db, vehicle, position, raw_membership, zones, excavators):
            _open_loading_trip(db, vehicle, state, position, raw_membership)
        return

    target = (
        _zone_target_status(confirmed_2reads_membership)
        if confirmed_2reads_membership
        else (None if confirmed_2reads_outside else "unconfirmed")
    )
    if target == "unconfirmed":
        return  # not enough consecutive agreement yet — no transition this tick

    if target is None and state.trip_status == TripCycleStatus.LOADING:
        if state.current_trip_id is not None:
            trip = db.get(Trip, state.current_trip_id)
            if trip is not None:
                trip.loaded_at = position.event_time
        state.trip_status = TripCycleStatus.HAULING
        state.trip_status_since = position.event_time

    elif target == TripCycleStatus.DUMPING and state.trip_status != TripCycleStatus.DUMPING:
        kind, ref = confirmed_2reads_membership  # static DUMPING zone (dynamic circles are always LOADING)
        trip = db.get(Trip, state.current_trip_id) if state.current_trip_id else None
        if trip is not None and trip.status == TripRowStatus.IN_PROGRESS and state.trip_status == TripCycleStatus.HAULING:
            # Normal path: loaded -> hauled -> now dumping. This is the cycle++ moment.
            next_cycle = (db.scalar(select(func.max(Trip.cycle_number)).where(Trip.vehicle_id == vehicle.id)) or 0) + 1
            trip.cycle_number = next_cycle
            trip.dumped_at = position.event_time
            trip.dump_zone_id = ref.id
        else:
            # Anomalous: reached DUMPING without a valid in-progress load (e.g. skipped
            # LOADING entirely). Physical position wins — still record it — but with no
            # load reference to assign a cycle to.
            logger.warning("Vehicle %s reached DUMPING with no matching load trip (anomalous)", vehicle.id)
            trip = Trip(
                vehicle_id=vehicle.id,
                org_id=vehicle.org_id,
                dump_zone_id=ref.id,
                started_at=position.event_time,
                dumped_at=position.event_time,
                status=TripRowStatus.IN_PROGRESS,
                had_anomalous_entry=True,
            )
            db.add(trip)
            db.flush()
        state.current_trip_id = trip.id
        state.trip_status = TripCycleStatus.DUMPING
        state.trip_status_since = position.event_time

    elif target is None and state.trip_status == TripCycleStatus.DUMPING:
        if state.current_trip_id is not None:
            trip = db.get(Trip, state.current_trip_id)
            if trip is not None:
                trip.completed_at = position.event_time
                trip.status = TripRowStatus.COMPLETED
        state.trip_status = TripCycleStatus.RETURNING
        state.trip_status_since = position.event_time
        state.current_trip_id = None


def compute_vehicle_status(
    latest_position: Optional[Position], trip_state: Optional[VehicleTripState], now
) -> VehicleStatus:
    """The Samarth-style 5-state taxonomy — derived, never independently detected, so it
    can never contradict this engine's own BREAKDOWN determination. Priority order:
    Not-installed -> No-comm -> Breakdown -> Running -> Idle."""
    if latest_position is None:
        return VehicleStatus.NOT_INSTALLED
    if (now - latest_position.received_at) > NO_COMM_AFTER:
        return VehicleStatus.NO_COMM
    if trip_state is not None and trip_state.trip_status == TripCycleStatus.BREAKDOWN:
        return VehicleStatus.BREAKDOWN
    if latest_position.speed_knots is not None and latest_position.speed_knots > STATIONARY_KNOTS_THRESHOLD:
        return VehicleStatus.RUNNING
    return VehicleStatus.IDLE
