# scenarios/gps.py — TickModifiers for GPS/positioning signal quality, layered on top of
# whatever BehaviorScenario is currently driving the vehicle's route. Independent of trip
# phase: a truck can be mid-haul with a degraded fix, or parked with clean one.
import random

from simulator.scenarios.base import StepResult, TickModifier, VehiclePhysicalState

STATIONARY_KNOTS_THRESHOLD = 0.5  # mirrors trip_engine.py's own constant


class CleanFix(TickModifier):
    """Baseline majority condition (~75% of ticks on a real site): HDOP 0.8-2.0,
    sats 7-12. A no-op on lat/lon — just sets realistic quality fields.

    Finite duration (unlike a true no-op) so the library actually keeps re-sampling the
    weighted mix over time — every modifier here needs an eventual finished=True, or
    whichever one gets drawn first simply locks in for the rest of the run and the
    configured weights never materialize as an actual mix."""

    name = "clean_fix"
    DURATION_S = 120.0

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.elapsed_s = 0.0

    def apply(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        state.hdop = round(self.rng.uniform(0.8, 2.0), 2)
        state.satellites = self.rng.randint(7, 12)
        self.elapsed_s += dt_s
        return StepResult(
            finished=self.elapsed_s >= self.DURATION_S,
            expected={"detector": "none", "outcome": "clean_fix"},
            backend_scorable=False,
            observation_mode="not_applicable",
            scorability_note="baseline signal quality, not an assertable condition",
        )


class DegradedFixPitWall(TickModifier):
    """Pit-wall/high-wall sky obstruction: HDOP 2.5-4.5, sats 4-6, with lat/lon jitter
    proportional to HDOP. No HDOP gating exists in the backend today (only firmware's
    own pre-buffer quality gate) — this tests that zone/trip attribution still resolves
    correctly under realistic noise, not a specific threshold."""

    name = "degraded_fix_pit_wall"
    DURATION_S = 90.0  # a bench-adjacent stretch of haul road, not the whole shift

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.elapsed_s = 0.0

    def apply(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        state.hdop = round(self.rng.uniform(2.5, 4.5), 2)
        state.satellites = self.rng.randint(4, 6)
        jitter_deg = 0.00003 * (state.hdop / 2.5)  # ~3-6m CEP scaling with HDOP
        state.lat += self.rng.uniform(-jitter_deg, jitter_deg)
        state.lon += self.rng.uniform(-jitter_deg, jitter_deg)
        self.elapsed_s += dt_s
        return StepResult(
            finished=self.elapsed_s >= self.DURATION_S,
            expected={"detector": "trip_engine/event_engine", "outcome": "degraded_fix_not_theft",
                      "threshold_ref": "no HDOP gate in backend today"},
            backend_scorable=True,
        )


class SubThresholdSpeedJitterParked(TickModifier):
    """One-shot: while genuinely parked (speed==0), inject a single-tick GPS-noise
    speed spike just above STATIONARY_KNOTS_THRESHOLD (0.5kt) to prove the 2-consecutive-
    reads debounce in trip_engine._update_stationary_state absorbs an isolated glitch
    instead of registering the vehicle as "moving"."""

    name = "sub_threshold_speed_jitter_parked"

    def apply(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        if state.speed_knots > STATIONARY_KNOTS_THRESHOLD:
            # Not actually parked right now — this modifier only makes sense at rest;
            # skip quietly and let the library resample next tick.
            return StepResult(finished=True, expected={"detector": "none", "outcome": "skipped_not_parked"})
        state.speed_knots = round(self.rng.uniform(0.55, 0.9), 2)
        return StepResult(
            finished=True,
            expected={"detector": "trip_engine", "outcome": "isolated_glitch_not_moving",
                      "threshold_ref": "STATIONARY_DEBOUNCE_READINGS"},
        )


class GpsDropout(TickModifier):
    """Satellite signal loss (pit shadow, dense tree cover, tunnel-like terrain) — no fix
    is acquired at all, so unlike a comms gap (see comms.wifi_gap_store_forward) there is
    nothing to buffer: firmware's own quality gate would have discarded these before they
    ever reached the ring buffer. Ticks are suppressed outright for the dropout's
    duration. Duration deliberately spans both NO_COMM_AFTER (10min) and BREAKDOWN_AFTER
    (15min) — the taxonomy's highest-value GPS scenario."""

    name = "gps_dropout"

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        # lognormal: median ~4min, tail out past 15min into the NO_COMM/BREAKDOWN bands.
        self.duration_s = min(self.rng.lognormvariate(mu=5.4, sigma=0.9), 2400.0)
        self.elapsed_s = 0.0

    def apply(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        self.elapsed_s += dt_s
        finished = self.elapsed_s >= self.duration_s
        threshold_note = (
            "spans NO_COMM_AFTER/BREAKDOWN_AFTER" if self.duration_s > 600 else "under NO_COMM_AFTER"
        )
        return StepResult(
            finished=finished,
            suppress=True,
            expected={
                "detector": "vehicle_status/trip_engine",
                "outcome": "gap_not_breakdown",
                "threshold_ref": f"NO_COMM_AFTER/BREAKDOWN_AFTER ({threshold_note}, duration={self.duration_s:.0f}s)",
            },
            backend_scorable=True,
            observation_mode="live_only",
            scorability_note="NO_COMM branch of compute_vehicle_status compares real wall-clock "
            "received_at, not event_time — only observable in pace=live/demo runs",
        )
