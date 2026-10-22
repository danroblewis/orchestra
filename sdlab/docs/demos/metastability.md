# Demo 6: Metastability scan

Tab "6. Metastability scan" on `/demos` (`?demo=metastability`). Ideas 16 and 20 in `OPERATIONALIZATION.md`.
Code: `sdlab/demos/metastability.py`, `sdlab/static/demos-metastability.js`, tests `tests/test_demos_metastability.py`.

## What it shows

A *metastable failure* (Bronson et al., HotOS 2021; Brooker, 2021) starts with a trigger, such as a load spike. A
reinforcing loop (timeouts → retries → more load → more timeouts) then keeps the system broken after the trigger
has gone. The demo pushes 36 load spikes (+50 to +1600 requests a step, lasting 15 min to 8 h) through a kubernetes
case's true model and through the stored passing found models of five strategies (milp, combined2, kalman_lna,
engine_forms, structures). It sorts each run into one of four bands: back to normal within 1 h, within 6 h, within
a day, or not back within a day. "Not back" is split into still growing (stuck) and still draining. The grid of
bands is the safe-load envelope. The true model's grid sits beside each found model's grid. A dashed red cell is
one where a found model calls a stuck spike safe; a black frame is any other band disagreement. Two runs (queue,
retries, ready pods) are drawn: the smallest spike that leaves the true system stuck (or its slowest recovery), and
the largest one it recovers from within an hour. Clicking a cell draws that run.

There are two cases:
- **310** (one service, autoscaled to 16 pods): in the measured data the dispatch cap `min(0.6 × queue, 40 × ready)`
  **never bound**. Dispatch reached at most 98.8% of the cap.
- **311** (the same service on a 3-node pool, 12 pods): the cap bound on 631 of 2000 measured steps.

There are four retry behaviours. Each one is applied the same way to an in-memory copy of the true model and of each
found model:
- *as built*: the case unchanged.
- *a second retry layer*: one extra flow, outside → queue at k × retries. A timed-out request then comes back
  0.6 + k times. The demo offers k = 0.3, 0.45 and 0.6, so a timed-out request comes back 0.9, 1.05 or 1.2 times.

## How it works

- The spike is a `pulse` term added to the traffic input of an in-memory copy of the true model. The same series
  (`spike_series`, which a test checks against the engine's pulse) is fed to each found model.
- Found models run free from the truth's initial levels with the case's announced injections (311's node
  failures). The traffic is carried as a stock the model reads. All 37 runs (36 spikes and the no-spike run) go in
  one batched simulation (`found_runs`). On 310 the free run reproduces the true queue exactly (error < 1e-3,
  tested), because the cap never binds there. On 311 it is within about 1-2% at the peaks.
- Recovery is measured from the end of the spike until the queue is within 5% (or 10 requests) of the same model's
  no-spike run and stays there for 2 hours. One day after the longest spike is watched. A run whose no-spike
  baseline itself runs away is reported as "broken with no spike at all".
- Answers are cached as JSON in `~/.cache/sdlab/demos/metastability/`. The cache key holds the case hash, the
  result id and a version. A scan takes about 10 s uncached and well under 1 s cached. Regenerate the cache with
  `OMP_NUM_THREADS=1 nice -n 19 uv run python -m sdlab.demos.metastability` (about 4 CPU-minutes for all 24 scans).
  No new discovery run was needed: the stored passing results are enough.

API: `/api/demos/metastability/options`,
`/api/demos/metastability/scan?case=&mechanism=&start=` (start: trough 888, ramp 960, peak 1032),
`/api/demos/metastability/example?case=&strategy=&mechanism=&start=&height=&width=`.

## What it found (2026-10-22; results 386907/386908/386891/386893/386918 on 310, 386951/386967/386962/386942/386957 on 311, none-long)

**The true system as built has no metastable region.** All 36 spikes recover on both cases at every start time.
The reason: a timed-out request comes back only 0.6 times. Below the cap the queue loses 63.2% a step. At the cap it
still loses 0.08 × 0.4 = 3.2% a step to clients giving up, so every backlog drains. The nearest real effect is a
**long recovery**: up to 81 steps (6 h 45) on 310 when the spike starts as traffic rises (91 at the trough), and up
to 141 steps on 311.

**310, where the cap never bound: no found model has the cap.** All five write dispatch as `0.6 × queue`. That fits
every measured step exactly. But it means each model says every spike is over within 20 minutes (at most 4 steps).
As built, they put only 17/36 cells in the truth's band (ramp start) and underestimate recovery by up to 77 steps
(6 h 25). With a second retry layer above 1 (k = 0.45), the true system tips: 3 spikes leave it growing a day later at
every start time (8-14 with k = 0.6), and at the ramp start 5 are not back. Every found model calls all of them safe
(missed stuck: 5 at the ramp start; 14 with k = 0.6). This is the lesson of the demo: **a model is only valid
where the data has been**. These models were fitted where the cap never bound, so they cannot show the tipping
point.

**311, where the cap bound: every found model has it and finds the envelope.** As built, they agree on 32-36 of 36
cells. With amplification 1.05 the true system has a metastable region (15 of 36 spikes still growing a day later
at the ramp start, 10-15 across starts). All five models put 35-36/36 cells in the truth's band and miss none. At
1.2 the 311 system breaks with no spike at all (its own daily peak tips it over), and the demo says so. With
amplification 0.9 there is no growing region, only 1-2 large spikes that are still draining after a day.

Commands: `uv run python -c "from sdlab.demos import metastability as M; r = M.scan('310-k8s-memory-oom', 'as-built', 'ramp'); ..."`,
or the endpoints above. The tests (`tests/test_demos_metastability.py`) pin these findings.

## Limits

- The metastable region exists only under the added "second retry layer" mechanism, which is a what-if on the
  truth, not the case as built. The page says this plainly.
- "Back to normal" looks only at the queue. A spike can also shift the OOM-kill cycle by a few steps, which makes
  some small spikes on 311 read as hours of recovery. That is a real difference from the no-spike run, but not a
  broken service.
- Noise-free runs, the none-long variant only, three start times, one day watched. "Stuck" means "not back within
  the day watched". A queue that is still draining is marked apart from one that is growing.
- The found models are stepped with the ladder's simulator for found models, without the scorer's alignment. Their
  hidden leak starts at the truth's initial level (0).
