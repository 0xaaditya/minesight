# cli.py — `python -m simulator.cli run ...` wires bootstrap -> fleet loop together;
# `eval` (stage 9 of the build plan) scores a completed run's ground truth against the
# real backend.
import argparse
import asyncio
import json
import logging
import os
import random
import secrets
import sys
from datetime import datetime, timezone

from simulator.bootstrap import bootstrap
from simulator.config import SimConfig
from simulator.fleet import Fleet
from simulator.ground_truth import GroundTruthLogger
from simulator.identity import EXCAVATOR, generate_roster
from simulator.layout import build_layout
from simulator.osmand_client import OsmAndClient
from simulator.scenario_registry import build_library
from simulator.time_utils import ist_wallclock_to_utc
from simulator.vehicle_agent import VehicleAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("simulator.cli")


def _parse_forced_scenarios(pairs: list[str]) -> dict[str, str]:
    forced = {}
    for pair in pairs or []:
        if ":" not in pair:
            raise ValueError(f"--force-scenario expects ASSET_ID:scenario_name, got {pair!r}")
        asset_id, name = pair.split(":", 1)
        forced[asset_id] = name
    return forced


def _make_run_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"


async def run_simulation(config: SimConfig) -> str:
    run_id = _make_run_id()
    run_dir = os.path.join(config.runs_dir, run_id)
    os.makedirs(run_dir, exist_ok=True)

    roster = generate_roster(config.vehicle_count, id_base=config.id_base)
    layout = build_layout(roster, site_index=config.site_index)
    fixtures = bootstrap(config.backend_api_url, roster, layout)

    with open(os.path.join(run_dir, "manifest.json"), "w") as f:
        json.dump(config.model_dump(), f, indent=2)
    with open(os.path.join(run_dir, "fixtures.json"), "w") as f:
        json.dump({"vehicle_ids": fixtures.vehicle_ids, "zone_ids": fixtures.zone_ids}, f, indent=2)

    library = build_library(config.mix_config_path)
    rng = random.Random(config.seed)
    gt_logger = GroundTruthLogger(run_dir)
    osmand_client = OsmAndClient(config.traccar_osmand_url)

    parking_lat, parking_lon = layout.zone_by_type("parking").center_latlon()

    agents = []
    for i, spec in enumerate(roster):
        agent_rng = random.Random(rng.random())
        if spec.vehicle_type == EXCAVATOR:
            start_lat, start_lon = layout.excavator_anchors[spec.asset_id]
        else:
            start_lat, start_lon = parking_lat, parking_lon
        agent = VehicleAgent(
            spec=spec,
            layout=layout,
            rng=agent_rng,
            start_lat=start_lat,
            start_lon=start_lon,
            driver_id=f"DRV-{i + 1:03d}",
        )
        agents.append(agent)

    sim_start = ist_wallclock_to_utc(config.shift_date, config.shift_start_ist)
    fleet = Fleet(
        run_id=run_id,
        agents=agents,
        library=library,
        config=config,
        gt_logger=gt_logger,
        osmand_client=osmand_client,
        sim_start=sim_start,
    )
    logger.info("run %s starting: %d vehicles, %.1fh simulated shift, pace=%s", run_id, len(agents), config.shift_hours, config.pace)
    await fleet.run(shift_seconds=config.shift_hours * 3600.0)
    logger.info("run %s done -> %s", run_id, run_dir)
    return run_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simulator.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run a simulated shift against the real backend/Traccar stack")
    run_p.add_argument("--vehicles", type=int, default=SimConfig().vehicle_count)
    run_p.add_argument("--hours", type=float, default=SimConfig().shift_hours)
    run_p.add_argument("--seed", type=int, default=SimConfig().seed)
    run_p.add_argument("--date", dest="shift_date", default=SimConfig().shift_date)
    run_p.add_argument("--shift-start-ist", default=SimConfig().shift_start_ist)
    run_p.add_argument("--mix", dest="mix_config_path", default=SimConfig().mix_config_path)
    run_p.add_argument("--pace", choices=["fast", "live", "demo"], default=SimConfig().pace)
    run_p.add_argument("--backend-url", dest="backend_api_url", default=SimConfig().backend_api_url)
    run_p.add_argument("--osmand-url", dest="traccar_osmand_url", default=SimConfig().traccar_osmand_url)
    run_p.add_argument("--runs-dir", default=SimConfig().runs_dir)
    run_p.add_argument("--id-base", type=int, default=SimConfig().id_base)
    run_p.add_argument("--site-index", type=int, default=SimConfig().site_index)
    run_p.add_argument("--force-scenario", action="append", default=[], help="ASSET_ID:scenario_name, repeatable")

    eval_p = sub.add_parser("eval", help="score a completed run against the real backend")
    eval_p.add_argument("--run-id", required=True)
    eval_p.add_argument("--runs-dir", default=SimConfig().runs_dir)
    eval_p.add_argument("--backend-url", dest="backend_api_url", default=SimConfig().backend_api_url)

    sweep_p = sub.add_parser("sweep", help="run N seeded runs + eval, aggregate into one confusion matrix")
    sweep_p.add_argument("--seeds", type=int, default=10, help="number of independent seeded runs")
    sweep_p.add_argument("--seed-start", type=int, default=0)
    sweep_p.add_argument("--vehicles", type=int, default=SimConfig().vehicle_count)
    sweep_p.add_argument("--hours", type=float, default=SimConfig().shift_hours)
    sweep_p.add_argument("--date", dest="shift_date", default=SimConfig().shift_date)
    sweep_p.add_argument("--shift-start-ist", default=SimConfig().shift_start_ist)
    sweep_p.add_argument("--mix", dest="mix_config_path", default=SimConfig().mix_config_path)
    sweep_p.add_argument("--pace", choices=["fast", "live", "demo"], default=SimConfig().pace)
    sweep_p.add_argument("--backend-url", dest="backend_api_url", default=SimConfig().backend_api_url)
    sweep_p.add_argument("--osmand-url", dest="traccar_osmand_url", default=SimConfig().traccar_osmand_url)
    sweep_p.add_argument("--runs-dir", default=SimConfig().runs_dir)
    sweep_p.add_argument("--id-base-start", type=int, default=4000,
                          help="first seed's asset-ID base; each subsequent seed gets id_base_start + i*id_base_stride")
    sweep_p.add_argument("--id-base-stride", type=int, default=50)
    sweep_p.add_argument("--site-index-start", type=int, default=1,
                          help="first seed's site_index (physically isolates each seed's geometry, see layout.build_layout)")

    cleanup_p = sub.add_parser("cleanup", help="close Sim-prefixed zones, deactivate simulator vehicles, delete their Traccar devices")
    cleanup_p.add_argument("--backend-url", dest="backend_api_url", default=SimConfig().backend_api_url)
    cleanup_p.add_argument("--traccar-api-url", default="http://localhost:8082/api")
    cleanup_p.add_argument("--traccar-api-user", default="admin")
    cleanup_p.add_argument("--traccar-api-password", default="admin")
    cleanup_p.add_argument("--min-asset-number", type=int, default=1000,
                            help="asset-ID numeric suffix at/above which a vehicle is treated as simulator-created")

    args = parser.parse_args(argv)

    if args.command == "run":
        config = SimConfig(
            backend_api_url=args.backend_api_url,
            traccar_osmand_url=args.traccar_osmand_url,
            shift_date=args.shift_date,
            shift_start_ist=args.shift_start_ist,
            shift_hours=args.hours,
            vehicle_count=args.vehicles,
            seed=args.seed,
            id_base=args.id_base,
            site_index=args.site_index,
            pace=args.pace,
            mix_config_path=args.mix_config_path,
            runs_dir=args.runs_dir,
            forced_scenarios=_parse_forced_scenarios(args.force_scenario),
        )
        run_id = asyncio.run(run_simulation(config))
        print(run_id)
        return 0

    if args.command == "eval":
        from simulator.eval import run_eval

        run_eval(run_id=args.run_id, runs_dir=args.runs_dir, backend_api_url=args.backend_api_url)
        return 0

    if args.command == "sweep":
        from simulator.aggregate import run_sweep

        base_config = SimConfig(
            backend_api_url=args.backend_api_url,
            traccar_osmand_url=args.traccar_osmand_url,
            shift_date=args.shift_date,
            shift_start_ist=args.shift_start_ist,
            shift_hours=args.hours,
            vehicle_count=args.vehicles,
            pace=args.pace,
            mix_config_path=args.mix_config_path,
            runs_dir=args.runs_dir,
        )
        seeds = list(range(args.seed_start, args.seed_start + args.seeds))
        run_sweep(
            base_config=base_config,
            seeds=seeds,
            id_base_start=args.id_base_start,
            id_base_stride=args.id_base_stride,
            site_index_start=args.site_index_start,
        )
        return 0

    if args.command == "cleanup":
        from simulator.teardown import cleanup

        cleanup(
            backend_api_url=args.backend_api_url,
            traccar_api_url=args.traccar_api_url,
            traccar_api_user=args.traccar_api_user,
            traccar_api_password=args.traccar_api_password,
            min_asset_number=args.min_asset_number,
        )
        return 0

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
