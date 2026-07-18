# scenarios/zone_conditions.py — BehaviorScenarios stressing zone/geofence boundary
# logic specifically: trip_engine.py's 2-consecutive-reads anti-flap, the LOADING dwell
# gate, and the enter/sustain radius distinction for dynamic excavator circles.
import random

from simulator.layout import SiteLayout, offset_latlon
from simulator.motion import delta_m
from simulator.scenarios.base import BehaviorScenario, StepResult, VehiclePhysicalState
from simulator.scenarios.trip_cycle import _drive_toward

EDGE_STRADDLE_M = 4.0  # within Neo-6M's real-world CEP (2.5-5m) per schemas.py's own comment


class BoundaryEdgeFlapping(BehaviorScenario):
    """Sits with its GPS fix straddling a zone edge — a stopped truck whose noise floor
    (a few meters of CEP) crosses a polygon boundary tick to tick. The single
    highest-value case in the taxonomy: proves trip_engine._apply_zone_transition's
    2-consecutive-reads requirement actually absorbs this instead of flapping the
    trip open/closed every tick."""

    name = "boundary_edge_flapping"
    applicable_vehicle_types = {"tipper", "loader"}
    APPROACH, FLAPPING, DEPARTING = "approach_edge", "flapping", "departing"
    DURATION_S = 300.0

    def __init__(self, rng: random.Random, layout: SiteLayout, vehicle_asset_id: str):
        super().__init__(rng, layout, vehicle_asset_id)
        dump_zone = layout.zone_by_type("dumping")
        center_lat, center_lon = dump_zone.center_latlon()
        ring = dump_zone.geometry["coordinates"][0]
        # Midpoint of one edge (first two ring vertices) as the straddle point.
        edge_lon = (ring[0][0] + ring[1][0]) / 2
        edge_lat = (ring[0][1] + ring[1][1]) / 2
        # Unit vector from edge midpoint toward zone center, then step exactly
        # EDGE_STRADDLE_M along/against it — real GPS-CEP scale, not a fraction of
        # whatever this particular zone's size happens to be.
        north_m, east_m, dist_m, _ = delta_m(edge_lat, edge_lon, center_lat, center_lon)
        unit_n, unit_e = north_m / dist_m, east_m / dist_m
        self.inside_lat, self.inside_lon = offset_latlon(edge_lat, edge_lon, unit_n * EDGE_STRADDLE_M, unit_e * EDGE_STRADDLE_M)
        self.outside_lat, self.outside_lon = offset_latlon(edge_lat, edge_lon, -unit_n * EDGE_STRADDLE_M, -unit_e * EDGE_STRADDLE_M)
        self.phase = self.APPROACH
        self.elapsed_s = 0.0
        self.tick_parity = 0
        _, (ex_lat, ex_lon) = rng.choice(list(layout.excavator_anchors.items()))
        self.depart_lat, self.depart_lon = offset_latlon(ex_lat, ex_lon, north_m=rng.uniform(-60, 60), east_m=rng.uniform(-60, 60))

    def step(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        if self.phase == self.APPROACH:
            if _drive_toward(state, dt_s, self.inside_lat, self.inside_lon, kmph=20.0):
                self.phase = self.FLAPPING
            return StepResult(expected={"detector": "trip_engine", "outcome": "approaching_edge"})

        if self.phase == self.FLAPPING:
            self.tick_parity = 1 - self.tick_parity
            if self.tick_parity == 0:
                state.lat, state.lon = self.inside_lat, self.inside_lon
            else:
                state.lat, state.lon = self.outside_lat, self.outside_lon
            state.speed_knots = 0.0
            self.elapsed_s += dt_s
            if self.elapsed_s >= self.DURATION_S:
                self.phase = self.DEPARTING
            return StepResult(
                expected={"detector": "trip_engine/event_engine", "outcome": "stationary_no_transition",
                          "threshold_ref": "2-consecutive-reads anti-flap"},
            )

        if self.phase == self.DEPARTING:
            # Repeats the flapping window's own outcome rather than a generic
            # "departing" label — episode rollup keeps the LATEST tick's `expected`
            # (see ground_truth.py), so a distinct final-phase label here would silently
            # overwrite the actual assertion by the time the episode closes and eval.py
            # scores it. Caught via a real run: this scenario scored OBSERVED instead of
            # PASS/FAIL until fixed.
            arrived = _drive_toward(state, dt_s, self.depart_lat, self.depart_lon, kmph=20.0)
            return StepResult(
                finished=arrived,
                expected={"detector": "trip_engine/event_engine", "outcome": "stationary_no_transition",
                          "threshold_ref": "2-consecutive-reads anti-flap"},
            )

        raise AssertionError(f"unreachable phase {self.phase}")


class DriveThroughNoStop(BehaviorScenario):
    """Crosses straight through the dump zone at haul speed without stopping — a
    shortcut route, not a real dump. Proves trip_engine never credits a dump from
    transit alone (DUMPING entry has no dwell gate today, only the 2-read agreement —
    which a continuously-moving vehicle can still satisfy by geometry alone if the
    zone is wide relative to its speed, so this is a real check, not a given)."""

    name = "drive_through_no_stop"
    applicable_vehicle_types = {"tipper", "loader"}

    def __init__(self, rng: random.Random, layout: SiteLayout, vehicle_asset_id: str):
        super().__init__(rng, layout, vehicle_asset_id)
        zone = layout.zone_by_type("dumping")
        center_lat, center_lon = zone.center_latlon()
        ring = zone.geometry["coordinates"][0]
        span_lat = max(p[1] for p in ring) - min(p[1] for p in ring)
        span_lon = max(p[0] for p in ring) - min(p[0] for p in ring)
        # Enter/exit points well clear of the zone on either side, along a line through it.
        self.entry_lat, self.entry_lon = center_lat - span_lat * 2, center_lon - span_lon * 2
        self.exit_lat, self.exit_lon = center_lat + span_lat * 2, center_lon + span_lon * 2
        self.started = False

    def step(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        if not self.started:
            state.lat, state.lon = self.entry_lat, self.entry_lon
            self.started = True
        arrived = _drive_toward(state, dt_s, self.exit_lat, self.exit_lon, kmph=35.0)  # deliberately brisk transit
        return StepResult(
            finished=arrived,
            expected={"detector": "trip_engine", "outcome": "no_load", "threshold_ref": "no dump credited from transit"},
        )


class ShortQueuedStopBelowDwell(BehaviorScenario):
    """Stops right at the excavator (inside the enter radius) but for well under
    LOADING_DWELL before moving off again — a truck briefly queued that gets waved
    forward before the excavator is actually free. Must never confirm LOADING.

    Departs on the very next tick after arrival, with no extra dwell tick in between:
    at the 30s tick cadence, the arrival tick itself already counts as one
    stationary-at-excavator sample, so even a single additional dwell tick produces a
    60s streak — sitting exactly AT trip_engine's current 60s LOADING_DWELL, not safely
    below it. One tick of stationary contact (30s) is the only value that reliably
    stays under the threshold with margin."""

    name = "short_queued_stop_below_dwell"
    applicable_vehicle_types = {"tipper", "loader"}
    STAGE, APPROACH, DEPARTING = "stage", "approach", "departing"

    def __init__(self, rng: random.Random, layout: SiteLayout, vehicle_asset_id: str):
        super().__init__(rng, layout, vehicle_asset_id)
        _, (ex_lat, ex_lon) = rng.choice(list(layout.excavator_anchors.items()))
        self.excavator_lat, self.excavator_lon = ex_lat, ex_lon
        # STAGE first: drive to ~150m out before approaching. Without this, the truck
        # frequently starts the scenario already standing AT this excavator (the
        # previous scenario's handoff position), which makes the whole episode a
        # degenerate 2 ticks — and worse, its stationary-streak and pairing state
        # carry across the scenario boundary, so the "brief fresh stop" premise this
        # scenario asserts about is simply false. A few moving ticks at >100m reset
        # both (pairing lapses past the 40m sustain radius; the stationary streak
        # breaks the moment speed rises).
        bearing_n = rng.uniform(-1, 1)
        bearing_e = rng.uniform(-1, 1) or 0.5
        norm = (bearing_n**2 + bearing_e**2) ** 0.5
        stage_dist = rng.uniform(140, 180)
        self.stage_lat, self.stage_lon = offset_latlon(
            ex_lat, ex_lon, north_m=stage_dist * bearing_n / norm, east_m=stage_dist * bearing_e / norm
        )
        self.depart_lat, self.depart_lon = offset_latlon(ex_lat, ex_lon, north_m=rng.uniform(40, 70), east_m=rng.uniform(40, 70))
        self.phase = self.STAGE

    def step(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        if self.phase == self.STAGE:
            if _drive_toward(state, dt_s, self.stage_lat, self.stage_lon, kmph=20.0):
                self.phase = self.APPROACH
            return StepResult(expected={"detector": "none", "outcome": "staging"})

        if self.phase == self.APPROACH:
            if _drive_toward(state, dt_s, self.excavator_lat, self.excavator_lon, kmph=20.0):
                self.phase = self.DEPARTING
            return StepResult(
                expected={"detector": "trip_engine", "outcome": "no_load_yet",
                          "threshold_ref": "trip_engine.LOADING_DWELL not satisfied (single-tick contact)"},
            )

        if self.phase == self.DEPARTING:
            arrived = _drive_toward(state, dt_s, self.depart_lat, self.depart_lon, kmph=20.0)
            return StepResult(
                finished=arrived,
                expected={"detector": "trip_engine", "outcome": "no_load_yet",
                          "threshold_ref": "trip_engine.LOADING_DWELL not satisfied (single-tick contact)"},
            )

        raise AssertionError(f"unreachable phase {self.phase}")


class TruckQueuedOutsideEnterRadius(BehaviorScenario):
    """Idles 25-35m from the excavator — inside the 40m sustain radius but outside the
    tighter 20m enter radius — the queuing-truck case EXCAVATOR_ENTER_RADIUS_M's
    comment explicitly calls out: must never confirm LOADING no matter how long it
    waits there."""

    name = "truck_queued_outside_enter_radius"
    applicable_vehicle_types = {"tipper", "loader"}
    STAGE, APPROACH, QUEUED, DEPARTING = "stage", "approach", "queued_outside_enter_radius", "departing"
    DURATION_S = 240.0

    def __init__(self, rng: random.Random, layout: SiteLayout, vehicle_asset_id: str):
        super().__init__(rng, layout, vehicle_asset_id)
        _, (ex_lat, ex_lon) = rng.choice(list(layout.excavator_anchors.items()))
        # STAGE first, same rationale as ShortQueuedStopBelowDwell: the previous
        # scenario often ends AT this excavator, and residual pairing (the 40m sustain
        # radius holds an existing pairing at the 25-35m queue distance) plus a
        # carried-over stationary streak would falsify the "arrives fresh, never pairs"
        # premise. A staged approach from ~150m guarantees the truck queues unpaired.
        stage_dist = rng.uniform(140, 180)
        self.stage_lat, self.stage_lon = offset_latlon(ex_lat, ex_lon, north_m=stage_dist, east_m=rng.uniform(-40, 40))
        self.queue_lat, self.queue_lon = offset_latlon(ex_lat, ex_lon, north_m=rng.uniform(25, 35), east_m=0)
        self.depart_lat, self.depart_lon = offset_latlon(ex_lat, ex_lon, north_m=rng.uniform(60, 90), east_m=rng.uniform(-40, 40))
        self.elapsed_s = 0.0
        self.phase = self.STAGE

    def step(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        if self.phase == self.STAGE:
            if _drive_toward(state, dt_s, self.stage_lat, self.stage_lon, kmph=20.0):
                self.phase = self.APPROACH
            return StepResult(expected={"detector": "none", "outcome": "staging"})

        if self.phase == self.APPROACH:
            if _drive_toward(state, dt_s, self.queue_lat, self.queue_lon, kmph=20.0):
                self.phase = self.QUEUED
            return StepResult(expected={"detector": "trip_engine", "outcome": "approaching_queue"})

        if self.phase == self.QUEUED:
            state.speed_knots = 0.0
            self.elapsed_s += dt_s
            if self.elapsed_s >= self.DURATION_S:
                self.phase = self.DEPARTING
            return StepResult(
                expected={"detector": "trip_engine", "outcome": "not_loading",
                          "threshold_ref": "EXCAVATOR_ENTER_RADIUS_M (queued at 25-35m)"},
            )

        if self.phase == self.DEPARTING:
            # Repeats the queued-window outcome rather than a generic "departing" label
            # — see BoundaryEdgeFlapping's comment: episode rollup keeps the LATEST
            # tick's `expected`, so a distinct final-phase label silently overwrites the
            # real assertion by the time eval.py scores the closed episode.
            arrived = _drive_toward(state, dt_s, self.depart_lat, self.depart_lon, kmph=20.0)
            return StepResult(
                finished=arrived,
                expected={"detector": "trip_engine", "outcome": "not_loading",
                          "threshold_ref": "EXCAVATOR_ENTER_RADIUS_M (queued at 25-35m)"},
            )

        raise AssertionError(f"unreachable phase {self.phase}")
