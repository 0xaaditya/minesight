# config.py — mirrors backend/app/config.py's "one place to look" principle. All
# defaults point at the local docker-compose stack; every field is overridable from
# the CLI (see cli.py) rather than via env vars, since a simulator run is a one-shot
# invocation, not a long-lived service.
from pydantic import BaseModel


class SimConfig(BaseModel):
    backend_api_url: str = "http://localhost:8000"
    traccar_osmand_url: str = "http://localhost:5055"

    # Smart-trigger cadence, matching CLAUDE.md's firmware rule (30s or >15 deg heading
    # change) — the simulator emulates the same device-side behavior real firmware uses.
    tick_interval_s: float = 30.0
    heading_change_trigger_deg: float = 15.0

    # Simulated shift window. IST wall-clock start, UTC internally like everything else
    # in this codebase (CLAUDE.md: "all times stored UTC, displayed IST").
    shift_date: str = "2026-07-17"  # YYYY-MM-DD
    shift_start_ist: str = "06:00"  # HH:MM
    shift_hours: float = 8.0

    vehicle_count: int = 6
    seed: int = 42
    id_base: int = 3000  # see identity.generate_roster's docstring
    site_index: int = 0  # see layout.build_layout's docstring — isolates site geometry across runs
    pace: str = "fast"  # fast | live | demo
    demo_speed_multiplier: float = 60.0  # only used in pace="demo"

    mix_config_path: str = "config/default_scenario_mix.json"
    runs_dir: str = "runs"

    # "asset_id:scenario_name" overrides — lets a verification run force a specific
    # vehicle into a specific BehaviorScenario instead of relying on sampling.
    forced_scenarios: dict[str, str] = {}
