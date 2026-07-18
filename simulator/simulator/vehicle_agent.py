# vehicle_agent.py — identity + physical state + whichever BehaviorScenario/TickModifier
# is currently active. Deliberately thin: resampling on completion, tick-cadence, sending,
# and logging all live in fleet.py (this class only knows how to advance its own state by
# dt_s when asked).
import random
from datetime import datetime
from typing import Optional

from simulator.identity import VehicleSpec
from simulator.layout import SiteLayout
from simulator.scenarios.base import BehaviorScenario, StepResult, TickModifier, VehiclePhysicalState


class VehicleAgent:
    def __init__(
        self,
        spec: VehicleSpec,
        layout: SiteLayout,
        rng: random.Random,
        start_lat: float,
        start_lon: float,
        driver_id: str,
    ):
        self.spec = spec
        self.layout = layout
        self.rng = rng
        self.state = VehiclePhysicalState(lat=start_lat, lon=start_lon, driver_id=driver_id)
        self.behavior: Optional[BehaviorScenario] = None
        self.modifier: Optional[TickModifier] = None
        self.seq = 0

    def step(self, dt_s: float, sim_now: datetime) -> tuple[StepResult, Optional[StepResult]]:
        if self.behavior is None:
            raise RuntimeError(f"{self.spec.asset_id}: no active BehaviorScenario assigned")
        behavior_result = self.behavior.step(self.state, dt_s, sim_now)
        modifier_result = self.modifier.apply(self.state, dt_s, sim_now) if self.modifier is not None else None
        self.seq += 1
        return behavior_result, modifier_result
