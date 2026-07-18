# eval.py — pulls real Positions/Trips/Events back from the backend's own read API
# (never the DB directly) and scores them against episodes.jsonl. This is the actual
# "reduce false positives" deliverable: a per-condition confusion-matrix report, not
# just a demo that the simulator can run.
#
# Scoring is honest about its own limits: only conditions with an unambiguous REST-
# observable signature get a PASS/FAIL verdict. Everything else (backend_scorable=False,
# or a condition whose only tell is a backend log line — see README.md) is counted as
# OBSERVED rather than silently scored right or wrong.
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

PAD = timedelta(minutes=2)

# Outcomes where the assertion is "no haul-cycle trip should have opened/loaded during
# this episode" — the truck approached a loading point but must not be credited.
NO_LOAD_OUTCOMES = {"stationary_no_transition", "no_load", "no_load_yet", "not_loading"}
# driver_break_not_breakdown/real_breakdown: an intentionally indistinguishable pair
# (see README.md) — both SHOULD produce a breakdown Event under today's algorithm, so
# "did one fire" is the correct PASS/FAIL question for both, scored identically.
BREAKDOWN_OUTCOMES = {"driver_break_not_breakdown", "real_breakdown"}


@dataclass
class Verdict:
    episode_key: str
    vehicle_asset_id: str
    condition_name: str
    outcome: str
    verdict: str  # PASS | FAIL | OBSERVED
    detail: str = ""


@dataclass
class Report:
    verdicts: list = field(default_factory=list)

    def add(self, v: Verdict) -> None:
        self.verdicts.append(v)


def _load_episodes(run_dir: str) -> list[dict]:
    path = os.path.join(run_dir, "episodes.jsonl")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_fixtures(run_dir: str) -> dict:
    with open(os.path.join(run_dir, "fixtures.json")) as f:
        return json.load(f)


def _fetch_trips(client: httpx.Client, vehicle_id: str, start: datetime, end: datetime) -> list[dict]:
    resp = client.get(
        f"/vehicles/{vehicle_id}/trips",
        params={"start_date": start.date().isoformat(), "end_date": end.date().isoformat()},
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_events_for_day(client: httpx.Client, vehicle_id: str, day: datetime) -> list[dict]:
    # GET /events only accepts a single `date` param (no start/end range, confirmed in
    # backend/app/routers/events.py) — loop per IST calendar day covered by the run.
    resp = client.get("/events", params={"date": day.date().isoformat(), "vehicle_id": vehicle_id, "limit": 200})
    resp.raise_for_status()
    return resp.json()


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start <= b_end and b_start <= a_end


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _score_episode(ep: dict, trips: list[dict], events: list[dict]) -> Verdict:
    expected = ep.get("expected") or {}
    outcome = expected.get("outcome", "unknown")
    start = _parse(ep["start_event_time"]) - PAD
    end = _parse(ep["end_event_time"]) + PAD
    key = f"{ep['vehicle_asset_id']}/{ep['axis']}:{ep['condition_name']}/{ep['instance_id'][:8]}"
    v = lambda verdict, detail="": Verdict(key, ep["vehicle_asset_id"], ep["condition_name"], outcome, verdict, detail)

    if not ep.get("backend_scorable", True):
        return v("OBSERVED", ep.get("scorability_note") or "marked non-scorable by the scenario itself")

    if ep.get("observation_mode") == "live_only":
        return v("OBSERVED", "wall-clock-only signal — needs pace=live/demo, not fast-mode event-time")

    if outcome == "cycle_complete":
        hit = any(
            t["status"] == "completed" and not t["had_anomalous_entry"]
            and _overlaps(start, end, _parse(t["started_at"]), _parse(t["completed_at"] or t["started_at"]))
            for t in trips
        )
        return v("PASS" if hit else "FAIL", "expected a completed, non-anomalous Trip in this window")

    if outcome == "aborted_stale_trip":
        hit = any(t["status"] == "aborted" and _overlaps(start, end, _parse(t["started_at"]), _parse(t["started_at"]))
                  for t in trips)
        return v("PASS" if hit else "FAIL", "expected an aborted Trip opened in this window")

    if outcome == "anomalous_dump_genuine":
        hit = any(t["had_anomalous_entry"] and _overlaps(start, end, _parse(t["started_at"]), _parse(t["started_at"]))
                  for t in trips)
        return v("PASS" if hit else "FAIL", "expected a had_anomalous_entry Trip in this window")

    if outcome in NO_LOAD_OUTCOMES:
        # "No transition should have been credited from this episode" — so the check is
        # whether any Trip row was OPENED (started_at = the LOADING/DUMPING confirm
        # moment) inside the episode itself. Two deliberate differences from the padded
        # interval-overlap the other outcomes use, both traced to real mis-verdicts:
        # (a) no backward pad and only one tick of forward pad — these episodes can be
        #     as short as 2 ticks, so a +/-2min pad was 9x the episode and swept the
        #     NEIGHBORING full_clean_cycle's legitimate load in at the boundary second
        #     (measured: a 61-65% "fail rate" that was pure pad bleed, zero engine
        #     misbehavior); a falsely-credited transition's started_at necessarily
        #     falls within the stationary/flapping window itself, so the tight window
        #     loses nothing.
        # (b) started_at instead of loaded_at — an anomalous DUMPING entry opened at a
        #     flapping zone edge has loaded_at=None, so the old check silently MISSED
        #     the one genuine defect found here (tick suppression mid-flap defeating
        #     the 2-consecutive-reads anti-flap, verified in ground_truth.jsonl).
        assert_start = _parse(ep["start_event_time"])
        assert_end = _parse(ep["end_event_time"]) + timedelta(seconds=30)
        spurious = [t for t in trips if assert_start <= _parse(t["started_at"]) <= assert_end]
        return v("PASS" if not spurious else "FAIL",
                  "no trip credited during the episode" if not spurious
                  else f"{len(spurious)} trip(s) opened during the no-transition window: "
                  + "; ".join(f"{t['status']} started {t['started_at']}" for t in spurious))

    if outcome in BREAKDOWN_OUTCOMES:
        hit = any(
            e["event_type"] == "breakdown" and _overlaps(start, end, _parse(e["event_time"]), _parse(e.get("ended_at") or e["event_time"]))
            for e in events
        )
        return v("PASS" if hit else "FAIL", "expected a breakdown Event overlapping this window "
                  "(lunch_break_stop and real_breakdown are an intentionally indistinguishable pair — "
                  "see README.md)")

    if outcome == "delayed_not_missing":
        hit = any(e.get("delayed") and _overlaps(start, end, _parse(e["event_time"]), _parse(e["event_time"]))
                  for e in events)
        return v("PASS" if hit else "OBSERVED",
                  "" if hit else "no Event happened to fire during the buffered gap to carry the delayed flag")

    return v("OBSERVED", "no scoring rule defined for this outcome yet")


def score_run(run_id: str, runs_dir: str, backend_api_url: str) -> Report:
    """Pure scoring, no side effects — reused by both the `eval` CLI command (which
    writes/prints a single-run report) and aggregate.py's sweep (which combines many
    runs' Reports into one confusion matrix before writing anything)."""
    run_dir = os.path.join(runs_dir, run_id)
    episodes = _load_episodes(run_dir)
    fixtures = _load_fixtures(run_dir)
    vehicle_ids = fixtures["vehicle_ids"]

    report = Report()
    with httpx.Client(base_url=backend_api_url, timeout=15.0) as client:
        trips_cache: dict[str, list[dict]] = {}
        events_cache: dict[tuple[str, str], list[dict]] = {}

        for ep in episodes:
            asset_id = ep["vehicle_asset_id"]
            vehicle_id = vehicle_ids.get(asset_id)
            if vehicle_id is None:
                continue
            start = _parse(ep["start_event_time"])
            end = _parse(ep["end_event_time"])

            if asset_id not in trips_cache:
                trips_cache[asset_id] = _fetch_trips(client, vehicle_id, start - timedelta(days=1), end + timedelta(days=1))
            trips = trips_cache[asset_id]

            events: list[dict] = []
            day = start.date()
            while day <= end.date():
                cache_key = (asset_id, day.isoformat())
                if cache_key not in events_cache:
                    events_cache[cache_key] = _fetch_events_for_day(client, vehicle_id, datetime.combine(day, datetime.min.time()))
                events.extend(events_cache[cache_key])
                day = day + timedelta(days=1)

            report.add(_score_episode(ep, trips, events))

    return report


def run_eval(run_id: str, runs_dir: str, backend_api_url: str) -> None:
    run_dir = os.path.join(runs_dir, run_id)
    report = score_run(run_id, runs_dir, backend_api_url)
    write_report(run_dir, report)


def write_report(run_dir: str, report: Report) -> None:
    by_scenario: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for v in report.verdicts:
        by_scenario[v.condition_name][v.verdict] += 1

    lines = ["# Simulator eval report", ""]
    lines.append("| Condition | PASS | FAIL | OBSERVED |")
    lines.append("|---|---|---|---|")
    total_pass = total_fail = total_observed = 0
    for scenario in sorted(by_scenario):
        counts = by_scenario[scenario]
        p, f, o = counts.get("PASS", 0), counts.get("FAIL", 0), counts.get("OBSERVED", 0)
        total_pass += p
        total_fail += f
        total_observed += o
        lines.append(f"| {scenario} | {p} | {f} | {o} |")
    lines.append(f"| **TOTAL** | **{total_pass}** | **{total_fail}** | **{total_observed}** |")
    lines.append("")

    failures = [v for v in report.verdicts if v.verdict == "FAIL"]
    if failures:
        lines.append("## Failures")
        for v in failures:
            lines.append(f"- `{v.episode_key}` — outcome=`{v.outcome}`: {v.detail}")
        lines.append("")

    with open(os.path.join(run_dir, "report.md"), "w") as f:
        f.write("\n".join(lines))
    with open(os.path.join(run_dir, "report.json"), "w") as f:
        json.dump([vars(v) for v in report.verdicts], f, indent=2)

    print("\n".join(lines))
    print(f"\nFull report: {run_dir}/report.md ({run_dir}/report.json)")
