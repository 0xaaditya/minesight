# identity.py — asset-ID convention from CLAUDE.md (S- tipper, EX- excavator, L- loader,
# BB- bowser, K- drill, CSM- surface miner), mirrored from backend/app/models.py's
# ASSET_ID_PREFIXES / VehicleType. traccar_unique_id == asset_id, same convention the
# backend uses for its own DIY ESP32 nodes (models.py:129-131).
from pydantic import BaseModel

# Only tipper/loader run the haul-cycle state machine (backend HAUL_CYCLE_VEHICLE_TYPES);
# excavator is a zone anchor; bowser/drill/surface_miner never load/dump but still
# participate in event_engine (night_movement, boundary_exit, zone_overspeed, breakdown).
TIPPER = "tipper"
EXCAVATOR = "excavator"
LOADER = "loader"
BOWSER = "bowser"
DRILL = "drill"
SURFACE_MINER = "surface_miner"

PREFIX_BY_TYPE = {
    TIPPER: "S-",
    EXCAVATOR: "EX-",
    LOADER: "L-",
    BOWSER: "BB-",
    DRILL: "K-",
    SURFACE_MINER: "CSM-",
}


class VehicleSpec(BaseModel):
    asset_id: str
    vehicle_type: str
    traccar_unique_id: str


def generate_roster(vehicle_count: int, id_base: int = 3000) -> list[VehicleSpec]:
    """Composition, not pure count: a haul-cycle fleet needs at least one excavator to
    pair against (dynamic loading circle) or every tipper/loader scenario is a no-op.
    Ratios are deliberately fixed, not sampled — roster composition isn't a probabilistic
    condition, it's a site-layout decision the operator makes once.

    id_base is configurable (not just a hardcoded constant) for two reasons: (a) a
    collision with a deactivated leftover vehicle from an earlier dev/test session is
    silent and dangerous — event_engine.py skips deactivated vehicles entirely, and
    there's no reactivate endpoint (VehicleUpdate has no deactivated_at field) to undo
    it; (b) aggregate.py's multi-seed sweep needs each seed's run to get a genuinely
    fresh, never-before-used roster — reusing the same vehicles across sequential runs
    reintroduces the "teleport" artifact (a new VehicleAgent starts fresh at parking
    while the backend's persisted trip_state carries over from the previous run),
    which would inject spurious aborts unrelated to whatever condition is being
    measured. A real deployment only ever calls this once against an empty registry, so
    the default matters only for development sessions."""
    if vehicle_count < 2:
        raise ValueError("need at least 2 vehicles (>=1 excavator, >=1 haul-cycle vehicle)")

    excavator_count = max(1, vehicle_count // 5)
    loader_count = 1 if vehicle_count >= 8 else 0
    bowser_count = 1 if vehicle_count >= 4 else 0
    remaining = vehicle_count - excavator_count - loader_count - bowser_count
    tipper_count = max(1, remaining)

    roster: list[VehicleSpec] = []
    counters = {TIPPER: id_base, EXCAVATOR: id_base, LOADER: id_base, BOWSER: id_base}

    def _add(vehicle_type: str, n: int) -> None:
        for _ in range(n):
            counters[vehicle_type] += 1
            asset_id = f"{PREFIX_BY_TYPE[vehicle_type]}{counters[vehicle_type]}"
            roster.append(VehicleSpec(asset_id=asset_id, vehicle_type=vehicle_type, traccar_unique_id=asset_id))

    _add(EXCAVATOR, excavator_count)
    _add(TIPPER, tipper_count)
    _add(LOADER, loader_count)
    _add(BOWSER, bowser_count)
    return roster
