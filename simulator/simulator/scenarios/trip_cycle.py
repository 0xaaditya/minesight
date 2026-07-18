# scenarios/trip_cycle.py — BehaviorScenarios for haul-cycle vehicles (tipper/loader).
# full_clean_cycle is the baseline majority case; the others (aborted_cycle,
# anomalous_dump_*, lunch_break_stop, real_breakdown) land in stage 7 per the build plan.
import math
import random

from simulator.layout import SiteLayout, offset_latlon
from simulator.motion import move_toward
from simulator.scenarios.base import BehaviorScenario, StepResult, VehiclePhysicalState

KMPH_TO_KNOTS = 1 / 1.852

# Dwell durations chosen to comfortably clear trip_engine.py's real thresholds regardless
# of which value is live: LOADING_DWELL is currently 1 min (temporarily shortened from a
# 3 min reference, per its own code comment) — 4 min clears both. DUMPING/other
# transitions only need the lighter 2-consecutive-reads agreement (satisfied by any dwell
# spanning >=2 ticks at the 30s cadence), so 90s is ample margin there.
LOADING_DWELL_S = 240.0
DUMPING_DWELL_S = 90.0

APPROACH, LOADING, HAUL_TO_DUMP, DUMPING, RETURNING = (
    "approach_excavator", "loading_dwell", "haul_to_dump", "dumping_dwell", "returning",
)


class FullCleanCycle(BehaviorScenario):
    name = "full_clean_cycle"
    applicable_vehicle_types = {"tipper", "loader"}

    def __init__(self, rng: random.Random, layout: SiteLayout, vehicle_asset_id: str):
        super().__init__(rng, layout, vehicle_asset_id)
        excavator_asset_id, (ex_lat, ex_lon) = rng.choice(list(layout.excavator_anchors.items()))
        self.excavator_asset_id = excavator_asset_id
        self.excavator_lat, self.excavator_lon = ex_lat, ex_lon
        self.dump_lat, self.dump_lon = layout.zone_by_type("dumping").center_latlon()

        # Approach from a random bearing/offset so consecutive cycles don't retrace an
        # identical line — more realistic, and avoids exact-repeat geometry across cycles.
        bearing = rng.uniform(0, 360)
        offset_m = rng.uniform(60, 120)
        north = offset_m * math.cos(math.radians(bearing))
        east = offset_m * math.sin(math.radians(bearing))
        self.staging_lat, self.staging_lon = offset_latlon(ex_lat, ex_lon, north, east)

        self.phase = APPROACH
        self.phase_elapsed_s = 0.0

    def step(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        if self.phase == APPROACH:
            return self._drive(state, dt_s, self.excavator_lat, self.excavator_lon, kmph=20.0, next_phase=LOADING,
                                expected={"detector": "trip_engine", "outcome": "approaching_loading",
                                          "threshold_ref": "EXCAVATOR_ENTER_RADIUS_M"})

        if self.phase == LOADING:
            state.speed_knots = 0.0
            self.phase_elapsed_s += dt_s
            if self.phase_elapsed_s >= LOADING_DWELL_S:
                self.phase = HAUL_TO_DUMP
                self.phase_elapsed_s = 0.0
            return StepResult(
                expected={"detector": "trip_engine", "outcome": "loading_confirmed_after_dwell",
                          "threshold_ref": "trip_engine.LOADING_DWELL"},
            )

        if self.phase == HAUL_TO_DUMP:
            return self._drive(state, dt_s, self.dump_lat, self.dump_lon, kmph=18.0, next_phase=DUMPING,
                                expected={"detector": "trip_engine", "outcome": "hauling"})

        if self.phase == DUMPING:
            state.speed_knots = 0.0
            self.phase_elapsed_s += dt_s
            if self.phase_elapsed_s >= DUMPING_DWELL_S:
                self.phase = RETURNING
                self.phase_elapsed_s = 0.0
            return StepResult(
                expected={"detector": "trip_engine", "outcome": "dumping_confirmed", "threshold_ref": "2-read agreement"},
            )

        if self.phase == RETURNING:
            result = self._drive(state, dt_s, self.staging_lat, self.staging_lon, kmph=25.0, next_phase=None,
                                  expected={"detector": "trip_engine", "outcome": "returning"})
            if result.finished:
                return StepResult(
                    finished=True,
                    expected={"detector": "trip_engine", "outcome": "cycle_complete",
                              "threshold_ref": "trip.status=completed"},
                )
            return result

        raise AssertionError(f"unreachable phase {self.phase}")

    def _drive(self, state, dt_s, target_lat, target_lon, kmph, next_phase, expected) -> StepResult:
        max_m = kmph * (dt_s / 3600.0) * 1000.0  # kmph * dt_hours -> km -> m
        new_lat, new_lon, arrived, bearing = move_toward(state.lat, state.lon, target_lat, target_lon, max_m)
        state.lat, state.lon = new_lat, new_lon
        state.course = bearing
        state.speed_knots = 0.0 if arrived else kmph * KMPH_TO_KNOTS
        if arrived and next_phase is not None:
            self.phase = next_phase
            self.phase_elapsed_s = 0.0
        return StepResult(finished=arrived and next_phase is None, expected=expected)


def _drive_toward(state: VehiclePhysicalState, dt_s: float, target_lat: float, target_lon: float, kmph: float) -> bool:
    """Shared motion primitive for the simpler single-purpose scenarios below —
    mutates state in place, returns True once arrived."""
    max_m = kmph * (dt_s / 3600.0) * 1000.0
    new_lat, new_lon, arrived, bearing = move_toward(state.lat, state.lon, target_lat, target_lon, max_m)
    state.lat, state.lon = new_lat, new_lon
    state.course = bearing
    state.speed_knots = 0.0 if arrived else kmph * KMPH_TO_KNOTS
    return arrived


class AbortedCycle(BehaviorScenario):
    """Loads normally, but a dispatcher reassignment (or a driver simply changing
    their mind) turns the truck back toward the excavator partway through the haul —
    never reaching DUMPING. Re-confirming LOADING back at the excavator is what
    triggers trip_engine._open_loading_trip's own abort-the-stale-trip path — this
    scenario exists to prove that path fires on a genuine case, not just react to it."""

    name = "aborted_cycle"
    applicable_vehicle_types = {"tipper", "loader"}

    APPROACH, LOADING, HAUL_PARTIAL, RETURN_DIRECT = (
        "approach_excavator", "loading_dwell", "haul_partial_turnback", "return_direct",
    )

    def __init__(self, rng: random.Random, layout: SiteLayout, vehicle_asset_id: str):
        super().__init__(rng, layout, vehicle_asset_id)
        _, (ex_lat, ex_lon) = rng.choice(list(layout.excavator_anchors.items()))
        self.excavator_lat, self.excavator_lon = ex_lat, ex_lon
        dump_lat, dump_lon = layout.zone_by_type("dumping").center_latlon()
        # Turn-back point: partway (30-50%) toward the dump — far enough to clear the
        # excavator's sustain radius and confirm HAULING, nowhere near the dump zone.
        frac = rng.uniform(0.3, 0.5)
        self.turnback_lat = ex_lat + (dump_lat - ex_lat) * frac
        self.turnback_lon = ex_lon + (dump_lon - ex_lon) * frac
        self.phase = self.APPROACH
        self.phase_elapsed_s = 0.0

    def step(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        if self.phase == self.APPROACH:
            if _drive_toward(state, dt_s, self.excavator_lat, self.excavator_lon, kmph=20.0):
                self.phase = self.LOADING
            return StepResult(expected={"detector": "trip_engine", "outcome": "approaching_loading"})

        if self.phase == self.LOADING:
            state.speed_knots = 0.0
            self.phase_elapsed_s += dt_s
            if self.phase_elapsed_s >= LOADING_DWELL_S:
                self.phase = self.HAUL_PARTIAL
                self.phase_elapsed_s = 0.0
            return StepResult(expected={"detector": "trip_engine", "outcome": "loading_confirmed_after_dwell"})

        if self.phase == self.HAUL_PARTIAL:
            if _drive_toward(state, dt_s, self.turnback_lat, self.turnback_lon, kmph=18.0):
                self.phase = self.RETURN_DIRECT
            return StepResult(expected={"detector": "trip_engine", "outcome": "hauling_then_turnback"})

        if self.phase == self.RETURN_DIRECT:
            arrived = _drive_toward(state, dt_s, self.excavator_lat, self.excavator_lon, kmph=22.0)
            return StepResult(
                finished=arrived,
                expected={"detector": "trip_engine", "outcome": "aborted_stale_trip",
                          "threshold_ref": "_open_loading_trip abort path"},
            )

        raise AssertionError(f"unreachable phase {self.phase}")


class AnomalousDumpGenuine(BehaviorScenario):
    """Material moved into the dump zone without ever passing through an excavator —
    e.g. a bowser/water-cart run, or a truck bringing material from off-site. Exercises
    trip_engine._apply_zone_transition's anomalous branch (had_anomalous_entry=True)
    on a case that's genuinely anomalous, not an artifact of a dropped GPS tick."""

    name = "anomalous_dump_genuine"
    applicable_vehicle_types = {"tipper", "loader"}

    APPROACH, DUMPING, DEPARTING = "approach_dump", "dumping_dwell", "departing"

    def __init__(self, rng: random.Random, layout: SiteLayout, vehicle_asset_id: str):
        super().__init__(rng, layout, vehicle_asset_id)
        self.dump_lat, self.dump_lon = layout.zone_by_type("dumping").center_latlon()
        _, (ex_lat, ex_lon) = rng.choice(list(layout.excavator_anchors.items()))
        self.depart_lat, self.depart_lon = offset_latlon(ex_lat, ex_lon, north_m=rng.uniform(-80, 80), east_m=rng.uniform(-80, 80))
        self.phase = self.APPROACH
        self.phase_elapsed_s = 0.0

    def step(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        if self.phase == self.APPROACH:
            if _drive_toward(state, dt_s, self.dump_lat, self.dump_lon, kmph=20.0):
                self.phase = self.DUMPING
            return StepResult(expected={"detector": "trip_engine", "outcome": "approaching_dump_no_load"})

        if self.phase == self.DUMPING:
            state.speed_knots = 0.0
            self.phase_elapsed_s += dt_s
            if self.phase_elapsed_s >= DUMPING_DWELL_S:
                self.phase = self.DEPARTING
            return StepResult(
                expected={"detector": "trip_engine", "outcome": "anomalous_dump_genuine",
                          "threshold_ref": "had_anomalous_entry=true"},
            )

        if self.phase == self.DEPARTING:
            # Repeats the dumping-window outcome rather than a generic "departing"
            # label — episode rollup keeps the LATEST tick's `expected` (ground_truth.py),
            # so a distinct final-phase label would silently overwrite the real
            # assertion by the time eval.py scores the closed episode.
            arrived = _drive_toward(state, dt_s, self.depart_lat, self.depart_lon, kmph=22.0)
            return StepResult(
                finished=arrived,
                expected={"detector": "trip_engine", "outcome": "anomalous_dump_genuine",
                          "threshold_ref": "had_anomalous_entry=true"},
            )

        raise AssertionError(f"unreachable phase {self.phase}")


class _OffZoneStop(BehaviorScenario):
    """Shared shape for lunch_break_stop and real_breakdown below: drive to a random
    point clear of every zone and the excavator, sit there past BREAKDOWN_AFTER (15min),
    then resume. Both hit the identical trip_engine signature (stationary >15min outside
    any zone) — see simulator/README.md's "known indistinguishable pairs" section. Only
    the ground-truth label and duration distribution differ; trip_engine cannot and
    should not be expected to tell them apart with today's signals."""

    applicable_vehicle_types = {"tipper", "loader"}
    APPROACH, STOPPED, DEPARTING = "approach_offzone", "stopped", "departing"
    OUTCOME_LABEL = "off_zone_stop"
    # Mirrors trip_engine.BREAKDOWN_AFTER (15 min). A sampled duration below this isn't
    # a scenario bug — the lognormal distribution legitimately produces some stops
    # shorter than the real threshold — but it means no breakdown Event SHOULD fire,
    # so scoring it against BREAKDOWN_OUTCOMES (which expects one) would be wrong.
    BREAKDOWN_AFTER_S = 900.0

    def __init__(self, rng: random.Random, layout: SiteLayout, vehicle_asset_id: str):
        super().__init__(rng, layout, vehicle_asset_id)
        _, (ex_lat, ex_lon) = rng.choice(list(layout.excavator_anchors.items()))
        # A haul-road point: far enough from the excavator (>SUSTAIN radius) and outside
        # every static zone by construction (site zones sit at distinct offsets from
        # center; this lands along the open corridor between excavator and dump).
        self.stop_lat, self.stop_lon = offset_latlon(ex_lat, ex_lon, north_m=rng.uniform(-150, -80), east_m=rng.uniform(150, 250))
        self.duration_s = self._sample_duration_s(rng)
        self.phase = self.APPROACH
        self.phase_elapsed_s = 0.0

    def _sample_duration_s(self, rng: random.Random) -> float:
        raise NotImplementedError

    def step(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        if self.phase == self.APPROACH:
            if _drive_toward(state, dt_s, self.stop_lat, self.stop_lon, kmph=20.0):
                self.phase = self.STOPPED
            return StepResult(expected={"detector": "trip_engine", "outcome": f"approaching_{self.OUTCOME_LABEL}"})

        if self.phase == self.STOPPED:
            state.speed_knots = 0.0
            self.phase_elapsed_s += dt_s
            if self.phase_elapsed_s >= self.duration_s:
                self.phase = self.DEPARTING
            outcome = self.OUTCOME_LABEL if self.duration_s > self.BREAKDOWN_AFTER_S else "stop_under_breakdown_threshold"
            return StepResult(
                expected={"detector": "trip_engine", "outcome": outcome,
                          "threshold_ref": f"BREAKDOWN_AFTER (stopped {self.duration_s:.0f}s)"},
            )

        if self.phase == self.DEPARTING:
            # Repeats the STOPPED phase's outcome rather than a generic "resuming"
            # label — episode rollup keeps the LATEST tick's `expected`
            # (ground_truth.py), so a distinct final-phase label would silently
            # overwrite the real assertion by the time eval.py scores the closed episode.
            arrived = _drive_toward(state, dt_s, self.excavator_lat_fallback(), self.excavator_lon_fallback(), kmph=20.0)
            outcome = self.OUTCOME_LABEL if self.duration_s > self.BREAKDOWN_AFTER_S else "stop_under_breakdown_threshold"
            return StepResult(
                finished=arrived,
                expected={"detector": "trip_engine", "outcome": outcome,
                          "threshold_ref": f"BREAKDOWN_AFTER (stopped {self.duration_s:.0f}s)"},
            )

        raise AssertionError(f"unreachable phase {self.phase}")

    def excavator_lat_fallback(self) -> float:
        return next(iter(self.layout.excavator_anchors.values()))[0]

    def excavator_lon_fallback(self) -> float:
        return next(iter(self.layout.excavator_anchors.values()))[1]


class LunchBreakStop(_OffZoneStop):
    """~30-45min, intended to cluster around midday — true time-of-day-weighted
    sampling isn't implemented (would need ScenarioLibrary to see sim_now at selection
    time, not just at step time); duration distribution alone is modeled here."""

    name = "lunch_break_stop"
    OUTCOME_LABEL = "driver_break_not_breakdown"

    def _sample_duration_s(self, rng: random.Random) -> float:
        return rng.uniform(1800, 2700)


class RealBreakdown(_OffZoneStop):
    """Real mechanical failure: unplanned, any time of day, longer-tailed duration than
    a lunch break — see LunchBreakStop for the paired "indistinguishable today" case."""

    name = "real_breakdown"
    OUTCOME_LABEL = "real_breakdown"

    def _sample_duration_s(self, rng: random.Random) -> float:
        return min(rng.lognormvariate(mu=7.3, sigma=0.8), 5400.0)  # median ~25min, tail to 90min
