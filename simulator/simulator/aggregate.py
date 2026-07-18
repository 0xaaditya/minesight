# aggregate.py — runs N independently-seeded simulations and combines their eval
# Reports into one confusion matrix. A single run's PASS/FAIL numbers are one random
# draw from the scenario mix (a low-weight condition like device_reboot_mid_shift might
# get sampled once or not at all); this is what turns that into a statistically
# meaningful per-condition fail rate, and it's the reusable regression suite CLAUDE.md's
# "prove every engine feature against the simulator" line calls for.
#
# Each seed gets its own asset-ID range (id_base_start + i*id_base_stride), never a
# shared/reused roster — see identity.generate_roster's docstring for why reusing
# vehicles across sequential runs would inject a spurious "teleport" artifact into the
# fail-rate measurement.
import asyncio
import json
import os
from collections import defaultdict

from simulator.config import SimConfig
from simulator.eval import Report, score_run, write_report


def run_sweep(
    base_config: SimConfig, seeds: list[int], id_base_start: int, id_base_stride: int, site_index_start: int = 1
) -> None:
    """Every seed gets both a fresh vehicle-ID range AND a physically distinct site
    (site_index) — id_base alone isn't enough. All seeds in a sweep share the same
    simulated date/shift-start (that's the point, for a controlled comparison), which
    means their excavators' anchor points would otherwise land at IDENTICAL physical
    coordinates with overlapping simulated timestamps — confirmed live: trip_engine's
    nearest-excavator attribution doesn't know "which sweep seed" a position came from,
    so a truck from one seed can get paired with an excavator from a different one
    entirely. See layout.build_layout's site_index docstring."""
    from simulator.cli import run_simulation  # deferred: avoids a cli<->aggregate import cycle at module load

    run_reports: list[tuple[str, Report]] = []
    for i, seed in enumerate(seeds):
        config = base_config.model_copy(
            update={"seed": seed, "id_base": id_base_start + i * id_base_stride, "site_index": site_index_start + i}
        )
        run_id = asyncio.run(run_simulation(config))
        report = score_run(run_id, config.runs_dir, config.backend_api_url)
        write_report(os.path.join(config.runs_dir, run_id), report)  # keep the individual report too
        run_reports.append((run_id, report))

    _write_aggregate(base_config.runs_dir, run_reports)


def _write_aggregate(runs_dir: str, run_reports: list[tuple[str, Report]]) -> None:
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_run_fail_rate: dict[str, list[float]] = defaultdict(list)

    for _run_id, report in run_reports:
        run_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for v in report.verdicts:
            totals[v.condition_name][v.verdict] += 1
            run_counts[v.condition_name][v.verdict] += 1
        for condition, counts in run_counts.items():
            scored = counts.get("PASS", 0) + counts.get("FAIL", 0)
            if scored > 0:
                per_run_fail_rate[condition].append(counts.get("FAIL", 0) / scored)

    run_ids = [rid for rid, _ in run_reports]
    lines = ["# Simulator sweep — aggregate report", "", f"Runs: {len(run_reports)}", ""]
    lines.append("| Condition | PASS | FAIL | OBSERVED | fail rate | runs w/ ≥1 FAIL |")
    lines.append("|---|---|---|---|---|---|")
    grand_pass = grand_fail = grand_observed = 0
    for condition in sorted(totals):
        counts = totals[condition]
        p, f, o = counts.get("PASS", 0), counts.get("FAIL", 0), counts.get("OBSERVED", 0)
        grand_pass += p
        grand_fail += f
        grand_observed += o
        scored = p + f
        rate = f"{f / scored:.1%}" if scored else "n/a"
        rates = per_run_fail_rate.get(condition, [])
        runs_with_fail = sum(1 for r in rates if r > 0)
        lines.append(f"| {condition} | {p} | {f} | {o} | {rate} | {runs_with_fail}/{len(rates)} |")
    lines.append(f"| **TOTAL** | **{grand_pass}** | **{grand_fail}** | **{grand_observed}** | | |")
    lines.append("")

    out_md = os.path.join(runs_dir, "sweep_aggregate.md")
    with open(out_md, "w") as f:
        f.write("\n".join(lines))
    with open(os.path.join(runs_dir, "sweep_aggregate.json"), "w") as f:
        json.dump(
            {
                "run_ids": run_ids,
                "totals": {k: dict(v) for k, v in totals.items()},
                "per_run_fail_rate": per_run_fail_rate,
            },
            f,
            indent=2,
        )

    print("\n".join(lines))
    print(f"\nRun IDs: {', '.join(run_ids)}")
    print(f"Full aggregate: {out_md}")
