# ground_truth.py — one GroundTruthTick per emitted (or suppressed) tick, appended to
# ground_truth.jsonl. Two INDEPENDENT episode streams roll up from it into
# episodes.jsonl (axis="behavior" or axis="modifier") — a BehaviorScenario instance and
# a TickModifier instance have different lifetimes (a single full_clean_cycle episode
# can live through several gps_dropout/clean_fix modifier episodes), so merging them
# into one rollup would silently overwrite the shorter-lived modifier's own
# expected/scorability metadata with whatever behavior tick happened to close last —
# eval.py needs both, independently, to score each axis correctly.
import json
import os
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class GroundTruthTick(BaseModel):
    run_id: str
    seq: int
    vehicle_asset_id: str
    vehicle_type: str
    traccar_unique_id: str
    tick_event_time: datetime
    tick_sent_wallclock_time: datetime

    lat: float
    lon: float
    speed_knots: float
    course: float
    hdop: float
    satellites: int

    behavior_scenario: str
    behavior_instance_id: str
    behavior_expected: Optional[dict] = None
    behavior_backend_scorable: bool = True
    behavior_observation_mode: str = "fast_ok"
    behavior_scorability_note: Optional[str] = None

    tick_modifier: Optional[str] = None
    tick_modifier_instance_id: Optional[str] = None
    modifier_expected: Optional[dict] = None
    modifier_backend_scorable: bool = True
    modifier_observation_mode: str = "fast_ok"
    modifier_scorability_note: Optional[str] = None

    suppressed: bool = False

    # Sent on the wire, never scored (see simulator/README.md's non-scorable field list).
    fuel_level_pct: float
    driver_id: str
    ignition: bool
    batt_voltage: float


class Episode(BaseModel):
    run_id: str
    axis: str  # "behavior" | "modifier"
    vehicle_asset_id: str
    vehicle_type: str
    condition_name: str  # behavior_scenario or tick_modifier name
    instance_id: str
    start_event_time: datetime
    end_event_time: datetime
    tick_count: int
    expected: Optional[dict] = None
    backend_scorable: bool = True
    observation_mode: str = "fast_ok"
    scorability_note: Optional[str] = None


class GroundTruthLogger:
    def __init__(self, run_dir: str):
        os.makedirs(run_dir, exist_ok=True)
        self.run_dir = run_dir
        self._ticks_path = os.path.join(run_dir, "ground_truth.jsonl")
        self._episodes_path = os.path.join(run_dir, "episodes.jsonl")
        self._ticks_fh = open(self._ticks_path, "a")
        self._open_episodes: dict[tuple[str, str, str], Episode] = {}  # (axis, vehicle, instance_id)

    def log_tick(self, tick: GroundTruthTick) -> None:
        self._ticks_fh.write(tick.model_dump_json() + "\n")
        self._ticks_fh.flush()
        self._roll_episode(
            axis="behavior", vehicle_asset_id=tick.vehicle_asset_id, vehicle_type=tick.vehicle_type,
            condition_name=tick.behavior_scenario, instance_id=tick.behavior_instance_id,
            event_time=tick.tick_event_time, expected=tick.behavior_expected,
            backend_scorable=tick.behavior_backend_scorable, observation_mode=tick.behavior_observation_mode,
            scorability_note=tick.behavior_scorability_note, run_id=tick.run_id,
        )
        if tick.tick_modifier is not None and tick.tick_modifier_instance_id is not None:
            self._roll_episode(
                axis="modifier", vehicle_asset_id=tick.vehicle_asset_id, vehicle_type=tick.vehicle_type,
                condition_name=tick.tick_modifier, instance_id=tick.tick_modifier_instance_id,
                event_time=tick.tick_event_time, expected=tick.modifier_expected,
                backend_scorable=tick.modifier_backend_scorable, observation_mode=tick.modifier_observation_mode,
                scorability_note=tick.modifier_scorability_note, run_id=tick.run_id,
            )

    def _roll_episode(
        self, axis, vehicle_asset_id, vehicle_type, condition_name, instance_id,
        event_time, expected, backend_scorable, observation_mode, scorability_note, run_id,
    ) -> None:
        key = (axis, vehicle_asset_id, instance_id)
        existing = self._open_episodes.get(key)
        if existing is None:
            self._open_episodes[key] = Episode(
                run_id=run_id, axis=axis, vehicle_asset_id=vehicle_asset_id, vehicle_type=vehicle_type,
                condition_name=condition_name, instance_id=instance_id,
                start_event_time=event_time, end_event_time=event_time, tick_count=1,
                expected=expected, backend_scorable=backend_scorable,
                observation_mode=observation_mode, scorability_note=scorability_note,
            )
        else:
            existing.end_event_time = event_time
            existing.tick_count += 1
            if expected is not None:
                existing.expected = expected  # latest tick's expectation wins within this axis

    def close_episode(self, vehicle_asset_id: str, behavior_instance_id: str) -> None:
        """Called by fleet.py when a BehaviorScenario finishes. The modifier axis closes
        itself naturally (a TickModifier reports its own finished=True and fleet.py
        starts a new instance_id) — no explicit close needed there."""
        key = ("behavior", vehicle_asset_id, behavior_instance_id)
        episode = self._open_episodes.pop(key, None)
        if episode is not None:
            self._write_episode(episode)

    def close_modifier_episode(self, vehicle_asset_id: str, modifier_instance_id: str) -> None:
        key = ("modifier", vehicle_asset_id, modifier_instance_id)
        episode = self._open_episodes.pop(key, None)
        if episode is not None:
            self._write_episode(episode)

    def _write_episode(self, episode: Episode) -> None:
        with open(self._episodes_path, "a") as fh:
            fh.write(episode.model_dump_json() + "\n")

    def close(self) -> None:
        for episode in self._open_episodes.values():
            self._write_episode(episode)
        self._open_episodes.clear()
        self._ticks_fh.close()
