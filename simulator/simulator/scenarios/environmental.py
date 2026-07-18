# scenarios/environmental.py — operational-context BehaviorScenarios.
#
# Note: "legitimate scheduled night shift" is deliberately NOT a BehaviorScenario class
# here — it's not a distinct motion pattern, it's a scheduling concern. Running the CLI
# with --shift-start-ist inside 20:00-06:00 (e.g. "22:00") puts any normal
# full_clean_cycle traffic into the quiet-hours window and reliably trips
# event_engine's night_movement detector — a guaranteed false positive by design, since
# quiet_hours_start/_end (config.py) is one global window with no per-org schedule
# override. See simulator/README.md's "known indistinguishable pairs" section.
import random

from simulator.layout import SiteLayout
from simulator.scenarios.base import BehaviorScenario, StepResult, VehiclePhysicalState
from simulator.scenarios.trip_cycle import _drive_toward


class MaintenanceYardMovement(BehaviorScenario):
    """A mechanic repositions the vehicle in/near the parking yard — short move, no
    RFID tap (no driver-session concept exists in the backend yet, see CLAUDE.md), never
    enters a LOADING/DUMPING zone. Applies to every vehicle type, not just haul-cycle
    ones — this is a fleet-wide operational reality, not a trip-cycle condition."""

    name = "maintenance_yard_movement"
    applicable_vehicle_types = {"tipper", "excavator", "loader", "bowser", "drill", "surface_miner"}
    MOVE, SETTLE = "moving", "settled"

    def __init__(self, rng: random.Random, layout: SiteLayout, vehicle_asset_id: str):
        super().__init__(rng, layout, vehicle_asset_id)
        park_lat, park_lon = layout.zone_by_type("parking").center_latlon()
        self.target_lat = park_lat + rng.uniform(-0.0002, 0.0002)
        self.target_lon = park_lon + rng.uniform(-0.0002, 0.0002)
        self.phase = self.MOVE
        self.settle_elapsed_s = 0.0
        self.settle_duration_s = rng.uniform(120, 300)

    def step(self, state: VehiclePhysicalState, dt_s: float, sim_now) -> StepResult:
        if self.phase == self.MOVE:
            if _drive_toward(state, dt_s, self.target_lat, self.target_lon, kmph=8.0):  # yard speed, not haul speed
                self.phase = self.SETTLE
            return StepResult(expected={"detector": "event_engine", "outcome": "maintenance_move",
                                         "threshold_ref": "may false-fire night_movement if off-hours"})

        state.speed_knots = 0.0
        self.settle_elapsed_s += dt_s
        return StepResult(
            finished=self.settle_elapsed_s >= self.settle_duration_s,
            expected={"detector": "event_engine", "outcome": "maintenance_settled"},
        )
