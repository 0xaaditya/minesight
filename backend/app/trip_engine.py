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
from sqlalchemy.exc import IntegrityError
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
# Fill radius, not "work area": a truck is only credited as being filled when it's
# practically alongside the excavator. Trucks are 7.5-10 m long and the boom reaches
# ~7 m, so the true machine-to-machine gap during a fill is under ~15 m; 20 m adds the
# combined GPS error of both devices (~5 m CEP each). Kept deliberately tight so that
# (a) trucks queuing 30-50 m from the bench don't confirm LOADING while waiting, and
# (b) when two excavators work close enough that wider circles would overlap (common
# on one bench), attribution ambiguity only starts below ~40 m separation — and
# nearest-wins in _determine_membership resolves what little remains.
EXCAVATOR_ENTER_RADIUS_M = 20.0
EXCAVATOR_SUSTAIN_RADIUS_M = 40.0  # 2x enter: tolerates the excavator walking along the face mid-load
EXCAVATOR_LIVENESS = timedelta(minutes=2)
NO_COMM_AFTER = timedelta(minutes=10)
# The generic 2-consecutive-reads anti-flap check (everything except LOADING entry,
# which has its own dwell gate) implicitly assumed "consecutive" means adjacent in time
# too — untrue when a tick is lost in transit (dropout, WiFi gap): the two STORED reads
# that agree may actually straddle a missing sample, e.g. a truck jittering in/out/in
# across a zone edge where the middle "out" tick never arrived, leaving two "in" reads
# that agree despite the truck having genuinely flapped. Verified mechanism (simulator
# sweep, boundary_edge_flapping): a wifi_gap_store_forward modifier suppressed exactly
# the alternating tick, and the surviving pair confirmed a phantom transition. 3x the
# nominal 30s cadence gives room for one merely-slow tick without opening the anti-flap
# hole back up for a real multi-minute gap.
ADJACENT_READS_MAX_GAP = timedelta(seconds=90)

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
        try:
            db.flush()
        except IntegrityError:
            # FOR UPDATE above can't lock a row that doesn't exist yet — two concurrent
            # webhook deliveries for the same brand-new vehicle can both observe "no row"
            # and both try to insert. Postgres blocks the loser on the unique constraint
            # until the winner commits, so by the time we get here the winner's row is
            # guaranteed visible — re-fetch it instead of dropping this tick.
            db.rollback()
            state = db.execute(
                select(VehicleTripState).where(VehicleTripState.vehicle_id == vehicle.id).with_for_update()
            ).scalar_one()

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
        # Re-derive what membership WAS at prev_position using excavator freshness as of
        # prev_position's own event_time, not the current tick's. Reusing `excavators`
        # (fetched relative to `position.event_time`) here is wrong whenever an excavator
        # goes stale (>EXCAVATOR_LIVENESS) between the two ticks — a truck's own prior
        # LOADING reading would retroactively re-evaluate to "no membership" even though
        # it genuinely was inside the circle when recorded, letting a single subsequent
        # "outside" reading masquerade as 2-consecutive-reads agreement and confirm a
        # transition one full read early. Verified via direct webhook repro: an excavator
        # gap spanning >2min around a truck's LOADING exit let one "outside" tick alone
        # flip trip_status to HAULING, bypassing the anti-flap entirely.
        prev_excavators = (
            _fresh_excavator_positions(db, vehicle.org_id, prev_position.event_time)
            if prev_position is not None
            else excavators
        )
        prev_membership = (
            _determine_membership(
                prev_position.latitude, prev_position.longitude, zones, prev_excavators, state.paired_excavator_id
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

        reads_adjacent = (
            prev_position is not None and (position.event_time - prev_position.event_time) <= ADJACENT_READS_MAX_GAP
        )
        confirmed = (
            reads_adjacent
            and membership is not None
            and prev_membership is not None
            and _same_membership(membership, prev_membership)
        )
        confirmed_none = reads_adjacent and membership is None and prev_membership is None

        if (confirmed or confirmed_none) and _is_stationary(position) and _is_stationary(prev_position):
            # A vehicle that never moved cannot have genuinely crossed a zone boundary —
            # if both confirming reads show ~0 speed, 2 agreeing reads can still happen by
            # pure GPS jitter (verified: simulator sweep, boundary_edge_flapping, zero
            # suppressed ticks, all reads adjacent — jitter alone produced 2 agreeing
            # "inside" reads and opened a phantom trip). The adjacency gate above only
            # catches jitter masked by a *dropped* tick; this catches jitter with nothing
            # dropped at all. Demand a 3rd adjacent, same-side stationary read before
            # trusting it. A genuinely moving vehicle (either read above threshold) skips
            # this — real transitions during actual driving are unaffected.
            if not _third_read_agrees(db, vehicle, prev_position, membership, confirmed_none, zones, state):
                confirmed = False
                confirmed_none = False

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
    # MINE_BOUNDARY is excluded here — the single choke point where zones enter the
    # engine. A site perimeter contains every vehicle by definition, so letting it into
    # membership would make is_inside_any_zone always true and silently disable the
    # breakdown detection above (stationary >15 min outside any zone). Display-only.
    return list(
        db.execute(
            select(Zone).where(
                Zone.org_id == org_id,
                Zone.valid_to.is_(None),
                Zone.zone_type != ZoneType.MINE_BOUNDARY,
            )
        ).scalars()
    )


def _fresh_excavator_positions(db: Session, org_id: uuid.UUID, as_of) -> list[tuple[Vehicle, Position]]:
    cutoff = as_of - EXCAVATOR_LIVENESS
    excavators = db.execute(
        # deactivated_at filter: a retired excavator must not keep projecting a dynamic
        # loading circle. Normally its positions age out within EXCAVATOR_LIVENESS
        # anyway, but if the hardware keeps transmitting after the vehicle record is
        # retired (device moved to another machine, or deactivation raced a live
        # device), trucks could still pair with — and credit loads to — a vehicle the
        # owner deleted. Same convention as event_engine's deactivated-vehicle skip.
        select(Vehicle).where(
            Vehicle.org_id == org_id,
            Vehicle.vehicle_type == VehicleType.EXCAVATOR,
            Vehicle.deactivated_at.is_(None),
        )
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


def _is_stationary(position: Optional[Position]) -> bool:
    return position is not None and position.speed_knots is not None and position.speed_knots <= STATIONARY_KNOTS_THRESHOLD


def _third_read_agrees(
    db: Session,
    vehicle: Vehicle,
    prev_position: Position,
    membership: Membership,
    confirmed_none: bool,
    zones: list[Zone],
    state: VehicleTripState,
) -> bool:
    """One more adjacent, agreeing read before trusting a transition that both confirming
    reads showed as stationary — see the ADJACENT_READS_MAX_GAP-adjacent call site for why.
    Excavator freshness is re-derived as of THIS read's own event_time (same reasoning as
    the prev_membership fix above), not the current tick's, to avoid reintroducing that bug."""
    prev_prev_position = db.execute(
        select(Position)
        .where(Position.vehicle_id == vehicle.id, Position.event_time < prev_position.event_time)
        .order_by(Position.event_time.desc())
        .limit(1)
    ).scalar_one_or_none()
    if prev_prev_position is None:
        return False
    if (prev_position.event_time - prev_prev_position.event_time) > ADJACENT_READS_MAX_GAP:
        return False
    prev_prev_excavators = _fresh_excavator_positions(db, vehicle.org_id, prev_prev_position.event_time)
    prev_prev_membership = _determine_membership(
        prev_prev_position.latitude, prev_prev_position.longitude, zones, prev_prev_excavators,
        state.paired_excavator_id,
    )
    if confirmed_none:
        return prev_prev_membership is None
    return prev_prev_membership is not None and _same_membership(prev_prev_membership, membership)


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


def _path_distance_m(db: Session, vehicle_id: uuid.UUID, start, end) -> Optional[float]:
    """Distance driven between two event times. Primary source: delta of Traccar's own
    cumulative odometer (DistanceHandler's totalDistance, carried on each position) —
    we don't rebuild what Traccar provides (CLAUDE.md). Fallback for positions missing
    the attribute (e.g. rows ingested before it was captured): sum haversine legs over
    the stored breadcrumb, which slightly underestimates on sparse reporting."""
    rows = db.execute(
        select(Position.latitude, Position.longitude, Position.total_distance_m)
        .where(
            Position.vehicle_id == vehicle_id,
            Position.event_time >= start,
            Position.event_time <= end,
        )
        .order_by(Position.event_time.asc())
    ).all()
    if len(rows) < 2:
        return None
    first_odo, last_odo = rows[0][2], rows[-1][2]
    if first_odo is not None and last_odo is not None and last_odo >= first_odo:
        return last_odo - first_odo
    return sum(
        haversine_meters(rows[i - 1][0], rows[i - 1][1], rows[i][0], rows[i][1])
        for i in range(1, len(rows))
    )


def _open_loading_trip(
    db: Session, vehicle: Vehicle, state: VehicleTripState, position: Position, membership: Membership
) -> None:
    if state.current_trip_id is not None:
        open_trip = db.get(Trip, state.current_trip_id)
        if open_trip is not None and open_trip.status == TripRowStatus.IN_PROGRESS:
            if open_trip.dumped_at is not None:
                # It already dumped — the cycle genuinely finished, and only the
                # RETURNING-confirmation tick(s) went missing (verified mechanism: a
                # GPS dropout spanning the truck's exit from the dump zone swallows the
                # "2 consecutive reads outside" pair that would normally close this out
                # — see simulator/README.md finding #3). Re-entering LOADING is itself
                # proof the vehicle made it back, so complete the trip here rather than
                # mislabel a successful cycle as aborted.
                open_trip.status = TripRowStatus.COMPLETED
                open_trip.completed_at = position.event_time
                open_trip.trip_distance_m = _path_distance_m(
                    db, vehicle.id, open_trip.started_at, position.event_time
                )
            else:
                # Never reached DUMPING at all — the previous attempt genuinely never
                # completed; abort it rather than leave a phantom open row.
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
            # Lead distance, measured from started_at (LOADING confirm) rather than
            # loaded_at (HAULING confirm): the truck sits stationary between the two so
            # started_at adds ~nothing, while loaded_at systematically clips the first
            # stretch of the haul — it only confirms once the truck is already past the
            # sustain radius plus two reads clear of the load zone.
            trip.haul_distance_m = _path_distance_m(db, vehicle.id, trip.started_at, position.event_time)
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
                trip.trip_distance_m = _path_distance_m(
                    db, vehicle.id, trip.started_at, position.event_time
                )
        state.trip_status = TripCycleStatus.RETURNING
        state.trip_status_since = position.event_time
        state.current_trip_id = None


def excavator_is_paired(db: Session, excavator_id: uuid.UUID, now) -> bool:
    """Whether a truck is currently active inside this excavator's loading circle. An
    excavator swings/digs but barely translates, so its own GPS speed reads ~0 whether
    it's mid-cycle loading trucks or genuinely idle — speed can't tell those apart the
    way it can for a truck. Truck-pairing (already computed for the dynamic excavator
    zone, see _determine_membership) is the only signal available today, pending real
    ignition sensing (CLAUDE.md hardware table lists this as a later firmware milestone).

    Gated to a recent last_processed_event_time: paired_excavator_id is only ever
    cleared by the PAIRED TRUCK's next tick, so a truck that goes no-comm mid-pairing
    would otherwise freeze this excavator as "Running" forever.
    """
    cutoff = now - EXCAVATOR_LIVENESS
    return (
        db.scalar(
            select(VehicleTripState.vehicle_id)
            .where(
                VehicleTripState.paired_excavator_id == excavator_id,
                VehicleTripState.last_processed_event_time >= cutoff,
            )
            .limit(1)
        )
        is not None
    )


def compute_vehicle_status(
    latest_position: Optional[Position],
    trip_state: Optional[VehicleTripState],
    now,
    is_paired_excavator: bool = False,
) -> VehicleStatus:
    """The Samarth-style 5-state taxonomy — derived, never independently detected, so it
    can never contradict this engine's own BREAKDOWN determination. Priority order:
    Not-installed -> No-comm -> Breakdown -> Running -> Idle.

    is_paired_excavator (see excavator_is_paired): the fallback "is it working" signal
    for excavators, which speed alone can't answer.
    """
    if latest_position is None:
        return VehicleStatus.NOT_INSTALLED
    if (now - latest_position.received_at) > NO_COMM_AFTER:
        return VehicleStatus.NO_COMM
    if trip_state is not None and trip_state.trip_status == TripCycleStatus.BREAKDOWN:
        return VehicleStatus.BREAKDOWN
    if latest_position.speed_knots is not None and latest_position.speed_knots > STATIONARY_KNOTS_THRESHOLD:
        return VehicleStatus.RUNNING
    if is_paired_excavator:
        return VehicleStatus.RUNNING
    return VehicleStatus.IDLE
