# scenarios/comms.py — TickModifiers for transport/device-health conditions. Distinct
# from gps.py's GpsDropout: here a fix IS available, but transmission fails or the
# device misbehaves — the store-and-forward / ordering-guard side of the taxonomy.
import random
from datetime import timedelta

from simulator.scenarios.base import StepResult, TickModifier, VehiclePhysicalState


class WifiGapStoreForward(TickModifier):
    """A real WiFi dead zone: the fix exists but the smart-trigger send fails, so
    firmware's ring buffer holds it for later replay (CLAUDE.md: "store-and-forward is
    non-negotiable"). Simplified replay model: rather than buffering every suppressed
    tick and bursting them all out (would need a multi-emit-per-round fleet.py change),
    this replays just the FIRST buffered position with its true (past) fixTime the
    moment the gap ends — enough to exercise event_engine.DELAYED_THRESHOLD's flagging,
    which is the actual behavior under test, without the extra plumbing."""

    name = "wifi_gap_store_forward"

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        # lognormal: median ~2min, occasional tail past DELAYED_THRESHOLD (5min).
        self.duration_s = min(self.rng.lognormvariate(mu=4.7, sigma=1.0), 2700.0)
        self.elapsed_s = 0.0
        self.buffered_event_time = None
        self.buffered_lat = None
        self.buffered_lon = None

    def apply(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        self.elapsed_s += dt_s
        if self.buffered_event_time is None:
            self.buffered_event_time = sim_now
            self.buffered_lat, self.buffered_lon = state.lat, state.lon

        if self.elapsed_s < self.duration_s:
            return StepResult(
                finished=False,
                suppress=True,
                expected={"detector": "none", "outcome": "buffered_mid_gap"},
                backend_scorable=False,
                observation_mode="not_applicable",
            )

        # Gap over: flush the oldest buffered fix with its true, now-stale fixTime.
        delayed_by_s = self.elapsed_s
        return StepResult(
            finished=True,
            suppress=False,
            event_time_override=self.buffered_event_time,
            expected={
                "detector": "event_engine",
                "outcome": "delayed_not_missing",
                "threshold_ref": f"DELAYED_THRESHOLD (buffered {delayed_by_s:.0f}s)",
            },
            backend_scorable=True,
        )


class DeviceRebootMidShift(TickModifier):
    """Transient bad/duplicate timestamp right after a power cycle, before GPS reacquires
    lock — tests the out-of-order/duplicate `<=` guard in both trip_engine.py and
    event_engine.py (each engine independently skips a position whose event_time doesn't
    exceed the last one it processed for that vehicle)."""

    name = "device_reboot_mid_shift"

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self._sent_glitch = False

    def apply(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        if not self._sent_glitch:
            self._sent_glitch = True
            # A stale clock reading from before GPS relock — strictly behind whatever
            # this vehicle's last real tick was, so the guard must skip it.
            return StepResult(
                finished=False,
                event_time_override=sim_now - timedelta(seconds=45),
                expected={"detector": "trip_engine/event_engine", "outcome": "stale_clock_skipped",
                          "threshold_ref": "out-of-order <= guard"},
            )
        return StepResult(
            finished=True,
            expected={"detector": "none", "outcome": "relocked"},
            backend_scorable=False,
            observation_mode="not_applicable",
        )


class DuplicatePacketRetry(TickModifier):
    """A retried delivery (ambiguous timeout on the device side) resends the exact same
    fixTime — must be deduped by the same out-of-order-or-equal guard, not double-counted
    into a phantom extra cycle/event."""

    name = "duplicate_packet_retry"

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self._last_event_time = None

    def apply(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        if self._last_event_time is None:
            self._last_event_time = sim_now
            return StepResult(finished=False, expected={"detector": "none", "outcome": "original_send"})
        return StepResult(
            finished=True,
            event_time_override=self._last_event_time,
            expected={"detector": "trip_engine/event_engine", "outcome": "duplicate_deduped",
                      "threshold_ref": "out-of-order <= guard"},
        )
