# fleet.py — owns all VehicleAgents + one simulated clock. Because both engines process
# by declared event_time, not arrival time (CLAUDE.md), a full shift can run with zero
# wall-clock sleeping by default (pace="fast") — only pace="live"/"demo" actually sleeps,
# for the one genuinely wall-clock-driven signal (NO_COMM, see README.md) and for literal
# sales-demo playback.
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from simulator.bootstrap import Fixtures
from simulator.config import SimConfig
from simulator.ground_truth import GroundTruthLogger, GroundTruthTick
from simulator.osmand_client import OsmAndClient, OsmAndTick
from simulator.scenarios.base import ScenarioLibrary
from simulator.vehicle_agent import VehicleAgent

logger = logging.getLogger(__name__)


class Fleet:
    def __init__(
        self,
        run_id: str,
        agents: list[VehicleAgent],
        library: ScenarioLibrary,
        config: SimConfig,
        gt_logger: GroundTruthLogger,
        osmand_client: OsmAndClient,
        sim_start: datetime,
    ):
        self.run_id = run_id
        self.agents = agents
        self.library = library
        self.config = config
        self.gt_logger = gt_logger
        self.osmand_client = osmand_client
        self.sim_now = sim_start
        self._pending_forced = dict(config.forced_scenarios)  # asset_id -> scenario name, consumed once

    async def run(self, shift_seconds: float) -> None:
        dt_s = self.config.tick_interval_s
        elapsed = 0.0
        tick_count = 0
        sleep_s = self._sleep_seconds(dt_s)

        while elapsed < shift_seconds:
            # Sequential, not asyncio.gather: firing every vehicle's HTTP request at the
            # exact same instant silently overwhelms Traccar's forward-to-backend relay in
            # this environment — confirmed empirically (10 zero-delay concurrent OsmAnd
            # sends forwarded only 1; 60 purely sequential sends, even 0.15s apart,
            # forwarded all 60). Real hardware never does this (one device, one request at
            # a time); only this simulator's own concurrent tick-fan-out could trigger it.
            for i, agent in enumerate(self.agents):
                if i > 0:
                    await asyncio.sleep(self.INTER_VEHICLE_SPACING_S)
                await self._step_and_send(agent, dt_s)
            self.sim_now += timedelta(seconds=dt_s)
            elapsed += dt_s
            tick_count += 1
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)

        for agent in self.agents:
            if agent.behavior is not None:
                self.gt_logger.close_episode(agent.spec.asset_id, agent.behavior.instance_id)
            if agent.modifier is not None:
                self.gt_logger.close_modifier_episode(agent.spec.asset_id, agent.modifier.instance_id)
        self.gt_logger.close()
        await self.osmand_client.aclose()
        logger.info("run %s complete: %d ticks/vehicle over %d vehicles", self.run_id, tick_count, len(self.agents))

    # Traccar's own forward-to-backend hop is asynchronous and NOT guaranteed FIFO under
    # burst load (verified empirically: zero-delay sends reordered deliveries by whole
    # minutes, tripping the out-of-order guard in trip_engine.py/event_engine.py and
    # silently dropping ticks). Real hardware never floods it like this — a 30s
    # smart-trigger cadence assumes 30 real seconds actually elapse between packets,
    # giving Traccar time to drain each forward before the next arrives. FAST_PACE_FLOOR_S
    # is the minimum real-world spacing needed to keep that backlog from building up,
    # even in "fast" mode — still a meaningful speedup over real-time, not zero.
    #
    # 0.15s was measured against a near-empty database early in development; after
    # dozens of accumulated test runs the same floor let 63 out-of-order warnings
    # through in a single 3-seed sweep (per-request latency grows with table size —
    # trip_engine's own dwell-confirmation scan alone reads up to 60 rows per vehicle
    # per tick). A fixed constant tuned once against a pristine database isn't robust
    # for a tool meant to accumulate data indefinitely; bumped with headroom rather than
    # re-tuned to the exact minimum, since the cost of being wrong (silently confounding
    # every future sweep's numbers) is much higher than the cost of a slightly slower run.
    FAST_PACE_FLOOR_S = 0.4
    # Minimum spacing between individual vehicles' sends WITHIN one tick. Sequential
    # `await`s alone aren't enough — over localhost each round-trip completes in single-
    # digit milliseconds, so a plain for-loop still fires the whole fleet at Traccar in
    # a burst nearly as tight as asyncio.gather did. Confirmed empirically: 10 requests
    # with zero explicit spacing forwarded almost none; 0.15s apart forwarded all of
    # them, repeatedly, even across a sustained 60-request run. This is on top of
    # FAST_PACE_FLOOR_S (which only gates the delay *between* ticks, not between
    # vehicles inside one).
    INTER_VEHICLE_SPACING_S = 0.15

    def _sleep_seconds(self, dt_s: float) -> float:
        if self.config.pace == "fast":
            return self.FAST_PACE_FLOOR_S
        if self.config.pace == "live":
            return dt_s
        if self.config.pace == "demo":
            return dt_s / self.config.demo_speed_multiplier
        raise ValueError(f"unknown pace {self.config.pace!r}")

    async def _step_and_send(self, agent: VehicleAgent, dt_s: float) -> None:
        if agent.behavior is None:
            self._assign_behavior(agent)
        if agent.modifier is None:
            agent.modifier = self.library.sample_modifier(agent.rng, agent.spec.vehicle_type)

        # Attribute this tick to whichever behavior/modifier instance actually produced
        # it, BEFORE rotating either one — reassigning agent.behavior/agent.modifier
        # first (as an earlier version of this method did) mislabels the tick that
        # finished an episode as belonging to the *next* episode instead, corrupting
        # eval.py's window boundaries (caught via a real false failure: a truck's last
        # position from a finishing episode, sitting at a different excavator entirely,
        # got attributed to the next scenario's episode).
        producing_behavior = agent.behavior
        producing_modifier = agent.modifier

        behavior_result, modifier_result = agent.step(dt_s, self.sim_now)

        suppressed = bool(modifier_result.suppress) if modifier_result is not None else False

        tick_event_time = (
            modifier_result.event_time_override
            if (modifier_result is not None and modifier_result.event_time_override is not None)
            else self.sim_now
        )
        gt = GroundTruthTick(
            run_id=self.run_id,
            seq=agent.seq,
            vehicle_asset_id=agent.spec.asset_id,
            vehicle_type=agent.spec.vehicle_type,
            traccar_unique_id=agent.spec.traccar_unique_id,
            tick_event_time=tick_event_time,
            tick_sent_wallclock_time=datetime.now(timezone.utc),
            lat=agent.state.lat,
            lon=agent.state.lon,
            speed_knots=agent.state.speed_knots,
            course=agent.state.course,
            hdop=agent.state.hdop,
            satellites=agent.state.satellites,
            behavior_scenario=producing_behavior.name,
            behavior_instance_id=producing_behavior.instance_id,
            behavior_expected=behavior_result.expected,
            behavior_backend_scorable=behavior_result.backend_scorable,
            behavior_observation_mode=behavior_result.observation_mode,
            behavior_scorability_note=behavior_result.scorability_note,
            tick_modifier=producing_modifier.name if producing_modifier else None,
            tick_modifier_instance_id=producing_modifier.instance_id if producing_modifier else None,
            modifier_expected=modifier_result.expected if modifier_result else None,
            modifier_backend_scorable=modifier_result.backend_scorable if modifier_result else True,
            modifier_observation_mode=modifier_result.observation_mode if modifier_result else "fast_ok",
            modifier_scorability_note=modifier_result.scorability_note if modifier_result else None,
            suppressed=suppressed,
            fuel_level_pct=agent.state.fuel_level_pct,
            driver_id=agent.state.driver_id,
            ignition=agent.state.ignition,
            batt_voltage=agent.state.batt_voltage,
        )
        self.gt_logger.log_tick(gt)

        if not suppressed:
            tick = OsmAndTick(
                traccar_unique_id=agent.spec.traccar_unique_id,
                epoch_utc=int(tick_event_time.timestamp()),
                lat=agent.state.lat,
                lon=agent.state.lon,
                speed_knots=agent.state.speed_knots,
                course=agent.state.course,
                hdop=agent.state.hdop,
                sat=agent.state.satellites,
                fuel_level_pct=agent.state.fuel_level_pct,
                driver_id=agent.state.driver_id,
                ignition=agent.state.ignition,
                batt_voltage=agent.state.batt_voltage,
            )
            result = await self.osmand_client.send(tick)
            if not result.ok:
                logger.warning("send failed for %s: %s", agent.spec.asset_id, result.error or result.status_code)

        # Rotate AFTER this tick is fully attributed/sent — takes effect starting next tick.
        if behavior_result.finished:
            self.gt_logger.close_episode(agent.spec.asset_id, producing_behavior.instance_id)
            self._assign_behavior(agent)
        if modifier_result is not None and modifier_result.finished:
            self.gt_logger.close_modifier_episode(agent.spec.asset_id, producing_modifier.instance_id)
            agent.modifier = None

    def _assign_behavior(self, agent: VehicleAgent) -> None:
        forced_name = self._pending_forced.pop(agent.spec.asset_id, None)
        if forced_name is not None:
            agent.behavior = self.library.force_behavior(forced_name, agent.rng, agent.layout, agent.spec.asset_id)
        else:
            agent.behavior = self.library.sample_behavior(
                agent.rng, agent.layout, agent.spec.asset_id, agent.spec.vehicle_type
            )
