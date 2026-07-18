# MineSight Simulator

The "Simulator (build early, keep forever)" tool CLAUDE.md's roadmap has always called
for: emulates N vehicles speaking real OsmAnd HTTP protocol against the real local
Traccar stack, exercising the actual `trip_engine.py`/`event_engine.py` pipeline
production hardware will use — not a mock, not a bypass of the webhook.

It exists to answer one question with evidence instead of guesswork: **which of the
detectors' anti-flap/hysteresis/timing assumptions actually hold up under realistic and
adversarial conditions, and which produce false positives or false negatives?**

## Architecture

Two independent, composable axes per vehicle, avoiding a combinatorial
one-condition-per-everything explosion:

- **BehaviorScenario** (`simulator/scenarios/trip_cycle.py`, `zone_conditions.py`,
  `environmental.py`, `stationary.py`) — governs the vehicle's route/state-machine path.
  One active instance per vehicle at a time.
- **TickModifier** (`simulator/scenarios/gps.py`, `comms.py`) — governs signal
  quality/comms layered on top of whichever behavior is active. Independently sampled
  and stackable (a truck can be mid-clean-cycle with a degraded fix on one leg).

Both axes are weighted-sampled from `config/default_scenario_mix.json` via
`scenario_registry.build_library()`. New scenario/modifier classes register there —
nothing else needs to change to pick them up.

`bootstrap.py` provisions vehicles/zones through the **real backend REST API**
(`POST /vehicles` — which also side-registers the Traccar device — and `POST /zones`),
never touching Postgres or Traccar directly. `fleet.py` owns the simulated clock and the
per-vehicle tick loop, sending real OsmAnd HTTP GETs to Traccar's port 5055.
`ground_truth.py` logs one record per tick to `ground_truth.jsonl` and rolls contiguous
same-instance ticks into `episodes.jsonl` — **two independent episode streams** (axis
`"behavior"` and axis `"modifier"`), since a single long-lived BehaviorScenario episode
can live through several shorter TickModifier episodes; merging them would silently
overwrite the modifier's own scorability metadata with whatever behavior tick closed
last. `eval.py` pulls real Positions/Trips/Events back from the backend's read API and
scores each episode against its `expected` outcome.

## Running

```
docker compose up -d        # from repo root: postgres, traccar, backend
cd simulator
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python3 -m simulator.cli run --vehicles 10 --hours 8 --seed 42 \
  --date 2026-07-17 --shift-start-ist 06:00 --pace fast \
  --force-scenario "S-701:boundary_edge_flapping"   # optional, repeatable

.venv/bin/python3 -m simulator.cli eval --run-id <printed_run_id>
cat runs/<run_id>/report.md

# Multi-seed sweep: N independent runs + eval, combined into one confusion matrix.
# A single run is one random draw from the scenario mix — low-weight conditions may get
# sampled once or not at all. Each seed gets its own fresh, never-reused vehicle roster
# (--id-base-start/--id-base-stride) to avoid the vehicle-reuse "teleport" artifact —
# see identity.generate_roster's docstring.
.venv/bin/python3 -m simulator.cli sweep --seeds 10 --vehicles 6 --hours 4 \
  --date 2026-07-17 --shift-start-ist 06:00 --pace fast \
  --id-base-start 6000 --id-base-stride 50
cat runs/sweep_aggregate.md

# Cleanup: every run/sweep leaves vehicles, zones, and Traccar devices behind (nothing
# ever deletes them automatically). Run this after a batch of runs — confirmed to
# accumulate into 124 stray zones and 551 stray Traccar devices across one session
# otherwise. Only touches asset IDs >= --min-asset-number (default 1000; the real dev
# fleet's own IDs are all under 1000, see identity.generate_roster's docstring).
.venv/bin/python3 -m simulator.cli cleanup
```

`--pace`: `fast` (default) advances simulated time with no wall-clock sleeping beyond a
small pacing floor (see below) — an 8-hour shift runs in a couple of real minutes.
`live`/`demo` pace real sends for the one wall-clock-only signal (NO_COMM) and for
literal sales-demo playback.

## Known findings from building this

Two real, pre-existing backend bugs were found and fixed while proving this pipeline
end-to-end (not simulator-specific — these would have hit real hardware too):

1. **`VehicleTripState`/`VehicleEventState` creation race** (`trip_engine.py`,
   `event_engine.py`): `SELECT ... FOR UPDATE` can't lock a row that doesn't exist yet,
   so two near-concurrent webhook deliveries for a brand-new vehicle could both attempt
   the initial `INSERT`, losing one tick to a silently-rolled-back `UniqueViolation`.
   Fixed: catch the conflict and re-fetch the winner's row instead of dropping the tick.
2. **Traccar's forward-to-backend hop is not FIFO under burst load.** Sending positions
   with zero real-world spacing (true "fast" pace) reordered deliveries by whole
   minutes, tripping the out-of-order guard and silently dropping ticks. Real hardware
   never floods it like this (30s cadence assumes 30 real seconds elapse). Fixed:
   `Fleet.FAST_PACE_FLOOR_S` (0.15s) — still a ~200x speedup, not zero.

And one genuine backend **limitation** the simulator surfaced by composing conditions
that were each built and tested independently — not a bug to fix, but exactly the kind
of interaction effect this tool exists to find:

3. **A GPS dropout that coincides with a trip-closing transition can silently corrupt
   cycle completion.** `gps_dropout` suppresses transmission for several minutes; if
   that window happens to cover the truck leaving the dump zone (the ticks
   `_apply_zone_transition` needs to confirm DUMPING→RETURNING), the backend never sees
   the exit, the trip never reaches `completed`, and it sits open until the *next*
   LOADING confirmation silently aborts it (`_open_loading_trip`'s stale-trip path).
   Confirmed directly in `ground_truth.jsonl`: 7 consecutive `suppressed: true,
   tick_modifier: gps_dropout` ticks spanning exactly the truck's departure from the
   dump zone and re-arrival at the excavator for its next load. Two independently-correct
   pieces of logic (dropout suppression, 2-read zone-exit confirmation) combine into a
   real gap. **A fix was attempted and reverted** — see `simulator/aggregate.py`'s sweep
   tool and the postmortem below before trying again.

### Postmortem: attempting to fix finding #3, and what it taught about measuring this

Built `aggregate.py` (the `sweep` CLI command) specifically to A/B this: run N seeded
simulations, score each, combine into one confusion matrix, so a fix's effect could be
measured rather than eyeballed from one run. Baseline (10 seeds, same config every time):
`full_clean_cycle` failed 32.0% of scored episodes.

Three fix attempts in `trip_engine.py`'s `_apply_zone_transition`, each trusting a
single post-gap reading as a confirmed zone-exit under progressively narrower
conditions (both directions → leaving-only → leaving-only-and-moving), were each
measured against the **identical 10 seeds** used for the baseline. All three landed at
~41.5-42.0% — a consistent, reproducible *regression*, not an improvement. Traced one
failing episode by hand each time rather than trusting the aggregate number blindly;
the specific failure mode shifted (stuck-in-DUMPING vs. anomalous-entry-on-resume) but
the total failure count did not improve. **All three attempts were reverted** —
`trip_engine.py` today carries only the verified concurrency fix (#1 above), not any of
these zone-transition changes.

While chasing the regression, a second, more important problem surfaced: re-running the
supposedly-identical baseline seeds (same code, same seeds, same config) after dozens of
accumulated test runs produced meaningfully different fail rates (21.5% → ~48% for the
same seed subset) with **no fix code active at all**. Root cause is twofold: (a) per-run
async HTTP delivery timing (which vehicle's concurrent request lands first, sub-floor
jitter in Traccar's forward queue) is not reproducible even for an identical
`--seed`, and (b) `Fleet.FAST_PACE_FLOOR_S` was tuned early against a near-empty
database — the same floor let 63 out-of-order warnings through per sweep after the
local Postgres/Traccar stack had accumulated a session's worth of test data (raised
`0.15s` → `0.4s`, though that alone didn't close the gap). **Net effect: the "clean A/B"
comparisons above have more inherent noise than a same-seed comparison appears to
promise**, so the specific 32%→42% regression figure should be read as "reliably
worse across three attempts," not as a precise, noise-free measurement. Resolving this
properly needs a much larger sweep (30-50+ seeds) run back-to-back on a freshly-reset
stack, ideally as its own follow-up rather than folded into whatever else is being
tested at the time.

Two scoring/attribution bugs were also found and fixed in the simulator itself while
verifying it against a real 10-vehicle/8-hour mixed run: (a) `fleet.py` was reassigning
`agent.behavior`/`agent.modifier` to the next instance *before* logging the tick that
actually finished the current one, mislabeling that tick as belonging to the new
episode; (b) several scenarios' final "departing" phase used a generic outcome label
that silently overwrote the real assertion when the episode rollup keeps only the
latest tick's `expected` value. Both are fixed; `real_breakdown`'s lognormal duration
sampling below `BREAKDOWN_AFTER` (15min) is now labeled distinctly
(`stop_under_breakdown_threshold`) rather than scored as a wrongly-expected breakdown.

### Postmortem addendum: site isolation, and where the numbers actually landed

The measurement-noise mystery above was later resolved: the dominant confound was
**cross-run physical contamination**, not timing. Every run's excavator anchors were
computed from a fixed site center by roster index, so every separate invocation's
first excavator landed at the identical coordinates — and since sweeps reuse the same
`--date`/`--shift-start-ist` across seeds, `trip_engine`'s nearest-excavator attribution
happily paired one run's trucks with a *different* run's excavators occupying the same
place at the same simulated time (confirmed live: two excavators from unrelated runs ~3m
apart, both with real cross-credited load counts). `build_layout(site_index=...)` now
shifts each run's whole site 5km apart, `sweep` assigns one site per seed, and the
backend's `_fresh_excavator_positions` gained a `deactivated_at` filter so retired
excavators can't project loading circles (that half IS a real production fix, not just
sim hygiene).

With isolation in place, a clean 20-seed sweep re-measured everything: `full_clean_cycle`
fell from the contaminated 32% to **7.7%** — most of what looked like the finding-#3
dropout interaction was actually contamination. The honest residual (~8-10%) is the real
dropout-swallows-transition class. The same sweep initially showed 61-65% fail rates on
the no-load scenarios, which a hand trace exposed as an **eval bug** (a ±2min pad, 9x
wider than the 30s episodes, swept the neighboring cycle's legitimate load in at the
boundary second) — while the same over-broad check was silently *missing* a genuine
defect. Both fixed (started_at-in-window scoring, staging pre-phases for the queued
scenarios); the validation sweep then showed exactly the right shape: queued scenarios
**0%** (artifact gone), `boundary_edge_flapping` still ~42% in 9/10 runs — the one
surviving, verified-real defect:

4. **Tick loss defeats the 2-consecutive-reads anti-flap at zone edges.** A stationary
   truck whose GPS jitter straddles a zone boundary alternates inside/outside every
   tick, which the anti-flap correctly absorbs — until a dropout or WiFi gap deletes
   one or more ticks from the delivered stream, leaving two consecutive same-side
   reads, which confirms a phantom transition (verified in `ground_truth.jsonl`:
   `wifi_gap_store_forward` suppressed two mid-flap ticks; an anomalous-dump Trip
   opened moments later). Real-world shape: a truck parked on a dump-zone edge with
   patchy connectivity racks up phantom trips. Open backend finding — any fix must
   survive the sweep, given finding #3's fix attempts all measurably regressed.
   **Update after Round 2 (see below): this was actually two conflated mechanisms.**
   The tick-loss sub-case above is fixed by the adjacency gate. A second, distinct
   sub-case — plain GPS jitter producing two genuinely adjacent same-side reads with
   nothing missing at all — is NOT addressed by a temporal gate by construction, and
   accounts for most of the still-open ~39% flapping fail rate. Still open.

5. **A dropout swallowing the LOADING→HAULING exit confirmation (not the DUMPING→
   RETURNING one finding #3 covers) can leave a trip's `trip_status` stuck at LOADING
   through the whole haul, so the eventual DUMPING entry sees `state.trip_status !=
   HAULING` and falls into the anomalous-entry branch instead of completing normally.**
   Verified via trace (`S-50002/47fad820`, see Round 2 results below): a genuine 4.5min
   loading dwell, one tick lost to `wifi_gap_store_forward` and replayed out of order,
   and the resulting trip dumps with `had_anomalous_entry=True` despite a real load
   having occurred. Distinct from finding #3 (that one swallows the *closing* exit
   confirmation on an already-dumped trip; this one swallows an *opening* exit
   confirmation earlier in the same cycle). Open — Fix 1 does not touch this path.
   **Correction (Round 3 below): the "stuck at LOADING" mechanism described here was a
   working theory, not a confirmed one, and turned out to be wrong once traced against a
   controlled repro. The actual, verified cause is Fix 3's excavator-freshness bug —
   the opposite failure direction (a premature, one-read-early confirmation, not a
   blocked one).**

### Round 2: sweep-designed fixes for findings #3 and #4

Unlike the three blind attempts above, these were designed directly from the traced
mechanism, not guessed and then measured:

- **Fix for #3 — complete, don't abort.** `_open_loading_trip` now checks whether the
  stale in-progress trip it's about to override already has `dumped_at` set. If so, the
  cycle genuinely finished and only the RETURNING-confirmation ticks were lost — it's
  marked `COMPLETED` (with `completed_at`/`trip_distance_m` stamped from the LOADING
  re-entry that proves the vehicle made it back), not `ABORTED`. A trip that never
  reached `dumped_at` still aborts, unchanged.
- **Fix for #4 — adjacency gate.** New `ADJACENT_READS_MAX_GAP` (90s = 3x nominal
  cadence) in `trip_engine.py`, reused in `event_engine.py` via `_reads_adjacent()`: a
  2-consecutive-reads agreement only confirms a transition when the two stored reads
  are actually temporally adjacent. A pair spanning a larger gap (a tick got lost) is
  treated as unconfirmed rather than trusted — strictly *stricter* than before, which is
  why this doesn't carry the same regression risk as the #3 attempts (those made
  confirmation *looser*). Applied everywhere a 2-read pattern gates a transition:
  trip_engine's HAULING/DUMPING/RETURNING confirms, and event_engine's
  night_movement/boundary_exit/zone_overspeed openers and closers.

### Validation sweep results — kept, but partially open, not "fixed"

10-seed validation sweep (`--seeds 10 --vehicles 6 --hours 4 --site-index-start 41
--id-base-start 50000`), same code that's live now:

| Condition | PASS | FAIL | fail rate | prior baseline |
|---|---|---|---|---|
| full_clean_cycle | 548 | 55 | 9.1% | ~9.5% |
| boundary_edge_flapping | 22 | 14 | 38.9% | ~42% (9-10/10 runs) |
| aborted_cycle (new) | 17 | 7 | 29.2% | n/a — first sweep scoring it |
| queued scenarios | 61 | 0 | 0.0% | 0.0% |

**Neither fix regressed anything — both are kept.** But hand-tracing individual FAIL
episodes (not just trusting the aggregate) shows each fix closed a narrower slice of its
target finding than the sweep-design section above implied:

- **Fix 1 verified working on its actual mechanism.** Traced `S-50002/1bbed0cd`
  (run `20260718T060445Z-46547f`): a `full_clean_cycle` trip dumped normally at
  `03:16:30Z`, then a `gps_dropout` swallowed 10 consecutive ticks spanning its
  RETURNING-exit confirmation. The next LOADING re-confirmation (`03:25:30Z`, once
  transmission resumed) correctly hit Fix 1's `dumped_at is not None` branch and marked
  it `COMPLETED`, not `ABORTED`. Confirms the fix does what it was designed to do.
- **A second, distinct dropout sub-case still produces FAILs and neither fix touches
  it.** Traced `S-50002/47fad820`: a genuine ~4.5min LOADING dwell at the excavator
  (`03:08:30`-`03:13:00`, one tick lost to `wifi_gap_store_forward` and replayed via
  store-and-forward) should have opened a normal in-progress trip. Instead the eventual
  DUMPING entry at `03:16:30` landed in `_apply_zone_transition`'s **anomalous** branch
  (`had_anomalous_entry=True`, no `load_excavator_vehicle_id`) — `eval.py` correctly
  scores this a FAIL since `full_clean_cycle` expects a non-anomalous trip. Working
  theory: the replayed out-of-order tick disrupts the LOADING→HAULING exit confirmation
  (line ~447), leaving `state.trip_status` stuck at LOADING through the whole haul, so
  the later DUMPING entry sees `state.trip_status != HAULING` and falls into the
  anomalous-creation path (line ~470) instead of the normal one. This is why
  `full_clean_cycle`'s fail rate barely moved (9.5%→9.1%) — Fix 1 only covers the
  swallowed-RETURNING-exit flavor of dropout interaction; a swallowed-LOADING-exit
  flavor is a distinct, still-open failure mode. **Not yet fixed — logged as finding #5
  below, not folded into Fix 1's claim.**
- **Fix 2 only closes the tick-loss half of finding #4.** Traced `S-50054/bfa309dc`
  (run `20260718T060807Z-07941c`): the truck is genuinely stationary and jittering
  across a zone edge, **every single tick delivered, zero suppression, all reads 30s
  apart** (well inside the 90s adjacency gate) — and a phantom trip still opened at
  `03:36:00Z`. The adjacency gate can only reject a confirming pair when the gap between
  the two reads exceeds 90s; it does nothing when jitter simply produces two genuinely
  adjacent same-side reads by chance, which is apparently common enough to still drive
  38.9% of flapping episodes. **Finding #4 is therefore two separate mechanisms that had
  been conflated under one label**: (a) tick-loss defeating anti-flap — now fixed by the
  adjacency gate — and (b) plain jitter occasionally agreeing twice in a row with nothing
  missing — still open, and a 90s temporal gate can't address it by construction. A real
  fix for (b) likely needs a 3-consecutive-reads requirement or a dwell-based hysteresis
  at zone edges (mirroring how LOADING entry already avoids this by using
  `_confirm_loading_dwell` instead of a 2-read check) — not attempted this round.
- **`aborted_cycle`'s 29.2% fail rate is a scenario/eval gap, not a trip_engine
  defect.** Traced `S-50002/1bbed0cd` (yes, the same episode that proved Fix 1 works —
  it's scored under two condition names because it spans a stale-trip close and its own
  attempt). When suppression is heavy enough (11 consecutive dropped ticks here), the
  *scenario's* internal phase clock keeps advancing through simulated time the backend
  never saw, so by the time transmission resumes the vehicle has already driven past its
  own LOADING dwell window in real position terms — the backend's independent
  `_confirm_loading_dwell` never gets enough observed stationary time to fire at all, so
  `_open_loading_trip` (and therefore the abort path under test) never runs. The
  scenario's assertion goes unexercised, not violated. This needs an eval/scenario fix
  (e.g. don't advance a scenario's internal dwell clock across suppressed ticks), not a
  backend fix — logged as a known gap below, not attempted this round.

**Net call:** both fixes stay merged (net-neutral-to-positive, nothing got worse), but
"fixed" only accurately describes each fix's own narrow, traced mechanism. The headline
fail rates (`full_clean_cycle` 9.1%, `boundary_edge_flapping` 38.9%) are still real,
open numbers — see finding #5 and the revised finding #4 above for what's actually left.

### Round 3: the real root causes for #4(b) and #5, found by direct repro instead of static-log guessing

Round 2's "working theory" for finding #5 (a disrupted exit confirmation leaving the trip
stuck at LOADING) turned out to be wrong once tested against a controlled repro instead
of re-reading `ground_truth.jsonl` harder. Both fixes below were found and verified by
hitting `POST /webhook/traccar` directly with hand-crafted, precisely-timed payloads —
bypassing only Traccar's relay, not trip_engine.py itself — which made it possible to
control exact timing/ordering and isolate each mechanism deterministically.

- **Fix 3 — `prev_membership` re-derived with the wrong excavator-freshness window.**
  `process_position` reconstructs what membership *was* at `prev_position` by re-running
  `_determine_membership` against `excavators`, a list fetched via
  `_fresh_excavator_positions(db, org_id, position.event_time)` — i.e. freshness as of
  the *current* tick, not as of `prev_position`'s own time. Repro: send one excavator
  position, then have a truck dwell at it past `EXCAVATOR_LIVENESS` (2 min) before
  exiting. The excavator's position is now "stale" relative to the exit tick, so
  `prev_membership` retroactively evaluates to `None` even though the truck genuinely
  was inside the circle when that position was recorded — letting a single "outside"
  reading masquerade as 2-consecutive-reads agreement and confirm the exit a full read
  early, bypassing the anti-flap entirely. This — not a stuck LOADING state — is the
  actual mechanism behind anomalous DUMPING entries on genuinely-loaded trips. Fixed:
  `prev_membership` now fetches excavators via
  `_fresh_excavator_positions(db, org_id, prev_position.event_time)` — freshness as of
  the read being reconstructed. Verified: identical repro now correctly waits for the
  second genuine "outside" reading, and the resulting trip completes non-anomalously
  with `loaded_at` set (previously `had_anomalous_entry=True`).
- **Fix 4 — a 3rd stationary read required for jitter-only phantom transitions.**
  Finding #4(b)'s "two genuinely adjacent same-side reads, nothing dropped" case: a
  vehicle that never moved cannot have genuinely crossed a boundary, so when BOTH
  confirming reads show ~0 speed, a 3rd adjacent, agreeing, stationary read is now
  required before trusting the transition (`_third_read_agrees`, re-deriving excavator
  freshness the same corrected way as Fix 3 to avoid reintroducing that bug). A
  genuinely moving vehicle (either read above `STATIONARY_KNOTS_THRESHOLD`) skips this
  entirely — real transitions during actual driving confirm exactly as before. Verified
  via repro: a stationary 2-read DUMPING arrival now correctly waits for a 3rd matching
  read (adds ~30s latency only for genuinely-parked arrivals/departures, never for
  moving ones) — mirrors the reasoning `_confirm_loading_dwell` already used for LOADING
  entry, now applied to every other stationary transition too.

Both fixes are net-additive safety (stricter confirmation, same direction as Fix 2 —
never looser), verified deterministically via direct repro. A fresh multi-seed sweep to
re-measure the aggregate fail rates was attempted but blocked by an unrelated, newly
discovered problem — see below.

### A third, unrelated problem found while trying to re-validate: the sweep tooling itself is unreliable right now

1. **Real bug, found and fixed: `fleet.py` fired every vehicle's HTTP request for a
   tick via `asyncio.gather`, all at the same instant.** Confirmed empirically: 10
   requests fired with zero relative delay forwarded almost none of them past Traccar
   (each got a 200 from the OsmAnd endpoint, but the forward to the backend silently
   dropped for all but ~1). Real hardware never does this — one device sends one
   request at a time. Fixed: the tick loop now sends each vehicle sequentially with an
   explicit `INTER_VEHICLE_SPACING_S` (0.15s) between them — plain sequential `await`s
   alone aren't enough, since a round-trip over localhost completes in single-digit
   milliseconds and doesn't actually space anything out on its own.
2. **Unresolved, NOT fixed: Traccar's forward-to-backend relay is intermittently
   unreliable in this Docker Compose setup, independent of the above.** After fixing
   (1), sweeps still intermittently lost all forwarding for an entire run — verified
   down to zero Positions stored on Traccar's *own* side (`GET /api/positions`), meaning
   Traccar's own OsmAnd listener silently failed to hand off to its forwarder, not just
   a downstream drop past Traccar. Deliberately isolated with matched repros (same
   spacing, same vehicle/request count, sync httpx client, async httpx client,
   keep-alive on vs. off): sometimes 100% forwarded, sometimes 0% forwarded, with no
   reliable trigger identified this round — not cleanly tied to request rate,
   concurrency, sync-vs-async, or connection reuse in the tests actually run. Restarting
   the Traccar container sometimes, but not reliably, clears it. **This makes the
   `sweep` command's aggregate numbers untrustworthy until this is root-caused — always
   spot-check that a sweep's vehicles have nonzero stored Positions
   (`GET /vehicles/{id}/positions`) before trusting its FAIL/PASS counts.** Filed as an
   open simulator/Traccar-infrastructure issue, orthogonal to trip_engine.py; Fix 3 and
   Fix 4 above are verified by direct-webhook repro instead, which never depends on
   Traccar's relay at all.

## Known non-scorable fields

Fuel, ignition, battery, and driver values are generated and sent on the wire (matching
CLAUDE.md's literal OsmAnd spec, forward-compatible with real hardware). As of migration
`0007`, the backend now **captures** them (`Position.ignition`/`battery_level`/
`fuel_raw`/`driver_uid`, parsed in `webhook.py` from Traccar's forwarded `attributes` —
confirmed exact keys via a stored payload: `ignition`, `batteryLevel`, `fuel`, `driver`),
but nothing **scores** them yet: no detector reads these columns, so every ground-truth
tick carrying them is still marked `backend_scorable=false`. A fuel-theft classifier and
driver-session logic are the follow-on that would actually consume them.

## Known indistinguishable pairs (not bugs — report honestly, don't force a verdict)

- **`lunch_break_stop` vs. `real_breakdown`**: both are a vehicle stationary >15min
  outside any zone — the identical signature `trip_engine.BREAKDOWN_AFTER` checks for.
  Only the ground-truth label and duration distribution differ; nothing in the current
  algorithm can or should be expected to tell them apart. `eval.py` scores both the same
  way (breakdown Event expected) rather than flagging either as a false positive.
- **GPS dropout spanning `NO_COMM_AFTER`**: the `NO_COMM` branch of
  `compute_vehicle_status` compares real wall-clock `now()` against `received_at`, not
  event_time — genuinely unobservable in a `pace=fast` run. Marked `observation_mode:
  "live_only"` and reported as `OBSERVED`, not scored PASS/FAIL, in `fast` runs.
- **Legitimate scheduled night shift**: not a BehaviorScenario class — a scheduling
  concern. Run with `--shift-start-ist` inside 20:00-06:00 to put ordinary
  `full_clean_cycle` traffic into quiet hours; `event_engine`'s `night_movement`
  detector will reliably false-positive, by design, since `quiet_hours_start/_end`
  (`config.py`) is one global window with no per-org schedule override today.
- **`device_reboot_mid_shift` / `duplicate_packet_retry`**: the assertion is an
  *absence* (no spurious Trip/Event from the bad tick), which `eval.py`'s REST-only
  design can't directly confirm — supplement with
  `docker compose logs backend | grep "Skipping out-of-order"` to confirm the guard
  actually fired.

## Deferred (documented, not built)

- `excavator_relocating_mid_load` and `two_excavators_close_near_equidistant` need
  either cross-vehicle behavior coordination or a special close-pair site layout,
  neither of which the v1 architecture supports cleanly — noted as follow-on work
  rather than half-built.
- `cold_start_acquisition` (HDOP>5 climbing on power-up) — firmware's own pre-buffer
  quality gate discards these before they'd ever reach the backend, so there's nothing
  for the backend side of this simulator to usefully assert; omitted from the default
  mix (weight 0), not registered.
