# scenarios/base.py — the two composable axes (see simulator/README.md): BehaviorScenario
# governs a vehicle's route/state-machine path, TickModifier governs signal quality/comms
# layered on top of whatever behavior is active. Independently sampled and stackable.
from __future__ import annotations

import random
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from simulator.layout import SiteLayout


@dataclass
class VehiclePhysicalState:
    lat: float
    lon: float
    speed_knots: float = 0.0
    course: float = 0.0
    hdop: float = 1.0
    satellites: int = 9
    # Sent on the wire (CLAUDE.md's literal OsmAnd spec), never scored — no backend
    # column reads them (backend/app/routers/webhook.py:36-39).
    fuel_level_pct: float = 80.0
    driver_id: str = "DRV-UNSET"
    ignition: bool = True
    batt_voltage: float = 12.6


@dataclass
class StepResult:
    finished: bool = False
    suppress: bool = False  # don't emit this tick at all (buffered/dropped mid-transport)
    expected: Optional[dict] = None  # {"detector":..., "outcome":..., "threshold_ref":...}
    backend_scorable: bool = True
    observation_mode: str = "fast_ok"  # fast_ok | live_only | not_applicable
    scorability_note: Optional[str] = None
    # Set by a modifier that's replaying a buffered position (store-and-forward): the
    # emitted OsmAnd packet's declared fixTime is this instead of the fleet clock's
    # current sim_now, so received_at ends up meaningfully later than event_time —
    # exactly the store-and-forward shape event_engine.DELAYED_THRESHOLD checks for.
    event_time_override: Optional[datetime] = None


class BehaviorScenario(ABC):
    name: str = "behavior_base"
    applicable_vehicle_types: set[str] = set()

    def __init__(self, rng: random.Random, layout: SiteLayout, vehicle_asset_id: str):
        self.rng = rng
        self.layout = layout
        self.vehicle_asset_id = vehicle_asset_id
        self.instance_id = str(uuid.uuid4())

    @abstractmethod
    def step(self, state: VehiclePhysicalState, dt_s: float, sim_now: datetime) -> StepResult: ...


class TickModifier(ABC):
    name: str = "modifier_base"
    applicable_vehicle_types: set[str] = set()  # empty = applies to all types

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.instance_id = str(uuid.uuid4())

    @abstractmethod
    def apply(self, state: VehiclePhysicalState, dt_s: float, sim_now: datetime) -> StepResult: ...


BehaviorFactory = Callable[[random.Random, SiteLayout, str], BehaviorScenario]
ModifierFactory = Callable[[random.Random], TickModifier]


@dataclass
class WeightedBehavior:
    factory: BehaviorFactory
    weight: float
    vehicle_types: Optional[set[str]] = None  # None = applies to all


@dataclass
class WeightedModifier:
    factory: ModifierFactory
    weight: float
    vehicle_types: Optional[set[str]] = None


class ScenarioLibrary:
    """Weighted, vehicle-type-filtered pools for both axes. Mixing weights come from
    config/default_scenario_mix.json (see simulator/config.py mix_config_path) — the
    taxonomy's probability numbers live there, not hardcoded here."""

    def __init__(self, behaviors: list[WeightedBehavior], modifiers: list[WeightedModifier]):
        self.behaviors = behaviors
        self.modifiers = modifiers

    def _applicable(self, entries, vehicle_type: str):
        return [e for e in entries if e.vehicle_types is None or vehicle_type in e.vehicle_types]

    def sample_behavior(self, rng: random.Random, layout: SiteLayout, vehicle_asset_id: str, vehicle_type: str) -> BehaviorScenario:
        pool = self._applicable(self.behaviors, vehicle_type)
        if not pool:
            raise ValueError(f"no behavior scenarios applicable to vehicle_type={vehicle_type!r}")
        chosen = rng.choices(pool, weights=[e.weight for e in pool], k=1)[0]
        return chosen.factory(rng, layout, vehicle_asset_id)

    def sample_modifier(self, rng: random.Random, vehicle_type: str) -> Optional[TickModifier]:
        pool = self._applicable(self.modifiers, vehicle_type)
        if not pool:
            return None
        chosen = rng.choices(pool, weights=[e.weight for e in pool], k=1)[0]
        return chosen.factory(rng)

    def force_behavior(self, name: str, rng: random.Random, layout: SiteLayout, vehicle_asset_id: str) -> BehaviorScenario:
        for e in self.behaviors:
            candidate = e.factory(rng, layout, vehicle_asset_id)
            if candidate.name == name:
                return candidate
        raise KeyError(f"no registered behavior scenario named {name!r}")
