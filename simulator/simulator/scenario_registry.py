# scenario_registry.py — maps scenario/modifier names to their implementing classes and
# builds a ScenarioLibrary from config/default_scenario_mix.json's weights. New
# BehaviorScenario/TickModifier subclasses register here as they're built (stages 6-8 of
# the build plan) — nothing elsewhere needs to change to pick them up.
import json

from simulator.scenarios.base import ScenarioLibrary, WeightedBehavior, WeightedModifier
from simulator.scenarios.comms import DeviceRebootMidShift, DuplicatePacketRetry, WifiGapStoreForward
from simulator.scenarios.environmental import MaintenanceYardMovement
from simulator.scenarios.gps import CleanFix, DegradedFixPitWall, GpsDropout, SubThresholdSpeedJitterParked
from simulator.scenarios.stationary import StationaryIdle
from simulator.scenarios.trip_cycle import (
    AbortedCycle,
    AnomalousDumpGenuine,
    FullCleanCycle,
    LunchBreakStop,
    RealBreakdown,
)
from simulator.scenarios.zone_conditions import (
    BoundaryEdgeFlapping,
    DriveThroughNoStop,
    ShortQueuedStopBelowDwell,
    TruckQueuedOutsideEnterRadius,
)

BEHAVIOR_FACTORIES = {
    FullCleanCycle.name: FullCleanCycle,
    StationaryIdle.name: StationaryIdle,
    AbortedCycle.name: AbortedCycle,
    AnomalousDumpGenuine.name: AnomalousDumpGenuine,
    LunchBreakStop.name: LunchBreakStop,
    RealBreakdown.name: RealBreakdown,
    BoundaryEdgeFlapping.name: BoundaryEdgeFlapping,
    DriveThroughNoStop.name: DriveThroughNoStop,
    ShortQueuedStopBelowDwell.name: ShortQueuedStopBelowDwell,
    TruckQueuedOutsideEnterRadius.name: TruckQueuedOutsideEnterRadius,
    MaintenanceYardMovement.name: MaintenanceYardMovement,
}

MODIFIER_FACTORIES: dict[str, type] = {
    CleanFix.name: CleanFix,
    DegradedFixPitWall.name: DegradedFixPitWall,
    SubThresholdSpeedJitterParked.name: SubThresholdSpeedJitterParked,
    GpsDropout.name: GpsDropout,
    WifiGapStoreForward.name: WifiGapStoreForward,
    DeviceRebootMidShift.name: DeviceRebootMidShift,
    DuplicatePacketRetry.name: DuplicatePacketRetry,
}


def build_library(mix_config_path: str) -> ScenarioLibrary:
    with open(mix_config_path) as f:
        mix = json.load(f)

    behaviors = []
    for name, weight in mix.get("behaviors", {}).items():
        cls = BEHAVIOR_FACTORIES.get(name)
        if cls is None:
            raise KeyError(f"unregistered behavior scenario {name!r} in {mix_config_path}")
        behaviors.append(WeightedBehavior(factory=cls, weight=weight, vehicle_types=cls.applicable_vehicle_types))

    modifiers = []
    for name, weight in mix.get("modifiers", {}).items():
        cls = MODIFIER_FACTORIES.get(name)
        if cls is None:
            raise KeyError(f"unregistered tick modifier {name!r} in {mix_config_path}")
        modifiers.append(
            WeightedModifier(factory=cls, weight=weight, vehicle_types=cls.applicable_vehicle_types or None)
        )

    return ScenarioLibrary(behaviors=behaviors, modifiers=modifiers)
