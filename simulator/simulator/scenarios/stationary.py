# scenarios/stationary.py — default filler behavior for vehicle types that don't run
# the haul-cycle state machine (excavator/bowser/drill/surface_miner). An excavator digs
# and swings but barely translates (trip_engine.py's own comment: "an excavator's own
# GPS speed reads ~0 whether it's mid-cycle loading trucks or genuinely idle") — this
# models exactly that: near-fixed position, tiny jitter, speed pinned at 0.
import random

from simulator.layout import SiteLayout
from simulator.scenarios.base import BehaviorScenario, StepResult, VehiclePhysicalState

JITTER_DEG = 0.000015  # a few meters of GPS-noise-like wobble, not real translation


class StationaryIdle(BehaviorScenario):
    name = "stationary_idle"
    applicable_vehicle_types = {"excavator", "bowser", "drill", "surface_miner"}

    def __init__(self, rng: random.Random, layout: SiteLayout, vehicle_asset_id: str):
        super().__init__(rng, layout, vehicle_asset_id)
        anchor = layout.excavator_anchors.get(vehicle_asset_id)
        self.anchor_lat, self.anchor_lon = anchor if anchor is not None else (layout.zones[0].center_latlon())

    def step(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        state.lat = self.anchor_lat + self.rng.uniform(-JITTER_DEG, JITTER_DEG)
        state.lon = self.anchor_lon + self.rng.uniform(-JITTER_DEG, JITTER_DEG)
        state.speed_knots = 0.0
        # Never finishes on its own — a background vehicle just sits for the shift;
        # fleet.py only resamples when a scenario reports finished=True.
        return StepResult(finished=False, expected={"detector": "none", "outcome": "stationary_baseline"})
