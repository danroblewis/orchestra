# Demo 10: before/after attribution

Ideas 36 (validate outcomes) and 37 (causal attribution) of `OPERATIONALIZATION.md`. Tab "10. Before/after
attribution" on `/demos`. Code: `sdlab/demos/attribution.py`, `sdlab/static/demos-attribution.js`; tests:
`tests/test_demos_attribution.py`.

## What it shows

A simulated SRE project ships at step 1000 of the 310 scenario (the API service with a memory leak and OOM kills;
2000 steps). Three projects, each a schedule change on an in-memory copy of the true model:

- `slower-retries`: the client retries half as fast (`retried` 0.6 → 0.3 × retries);
- `fewer-errors`: a bug fix halves the error rate (`errors` 0.03 → 0.015 × inflight);
- `fewer-timeouts`: a longer timeout halves timeouts (`timeouts` 0.08 → 0.04 × queue).

The page answers two questions, each beside the truth:

1. **How big was the effect?** The found model's structure is kept and its numbers are refitted on the steps before
   the project: the "before" model. Run free from the state at step 999 on the traffic that came after, it is the
   counterfactual. Measured minus counterfactual is the effect on failed requests, successful responses, the queue,
   the retry queue and OOM kills. The true effect is the true model run with and without the project (noise-free).
   The "predicted from the moved number" column is idea 36: the before model with only the moved number(s) set to
   their after values.
2. **Which number moved?** The numbers are refitted again on the steps after the project; each number's before and
   after values with intervals, and which ones moved.

The found model is milp's stored passing result on `310-k8s-memory-oom` none-long (#386907, code 491632e57), named on
the page.

## How it works

- **Refit** (`attribution.refit`): every proportional coefficient and linear term of the found flows that touch a
  measured stock (not the measured input, not expressions, effect tables or constants), fitted by one-step weighted
  least squares (each stock's equations weighted by its residual spread) with Gauss-Newton on the scorer's simulator
  for found models (`ladder/sim.found_model`). The hidden leak stock is carried as the model carries it one step
  ahead. Intervals: 2.5–97.5% of a block bootstrap of the equations (200 draws, 50-step blocks). A number whose flow
  moves nothing on 20 steps of a window is "not identified" there and left out.
  `sdlab/discovery/refine.py` (multi-step refit) is not used: its simulator (`discovery.simulate.Model`, built
  without inputs) does not read measured inputs or expression rates, which this model has.
- **Band.** Noise-free: the spread of 30 counterfactuals from bootstrap draws of the before refit. Counted noise (the
  ladder's counts: flows move whole requests, Poisson): the bootstrap alone is far too narrow, so the band is the
  spread of the same measurement on 12 **placebo** runs (the service with no project, seeds 101–112, never the test
  seeds); the estimate is also shown "less the placebo" (minus the placebo's median: what the method reports when
  nothing changed).
- **Moved**: |z| > 3 (about 5% family-wise over ~18 numbers) after dividing each number's z by its root-mean-square z
  on the placebo runs (at least 1), and a change of more than 1%.

Endpoints (under `/api/demos`): `/attribution/projects`, `/attribution/run?project=&counts=&seed=` (about 6 s the
first time, then cached in memory), `/attribution/seeds?project=` (the counts table over seeds 1–8, from a file).
Cache: `~/.cache/sdlab/demos/attribution/` (placebo and seed tables, keyed by the stored result id). Regenerate:
`OMP_NUM_THREADS=1 nice -n 19 uv run python -m sdlab.demos.attribution` (about 2 CPU-minutes).

## What it found (2026-10-22, store result #386907; `/attribution/run`, `/attribution/seeds`)

**Noise-free**, `slower-retries`: the refit finds `retries → queue` 0.6000 → 0.2998 [0.2988, 0.3000] and nothing
else moved. Measured effect = true effect to the digits shown: failed requests −397 (true −397), responses −6,621
(−6,621), mean queue −11.7 (−11.7), mean retry queue +17.5 (+17.5). OOM kills: +0.2 [−0.5, +0.8] against a true
−0.55, outside the band; the placebo run gives +0.75 there (the model's misfit on memory, at a level of one kill).
Before calibrating by the placebo, `mem → outside` looked "moved" (z 27 on a change of 0.0001); the placebo
calibration and the 1% rule remove it.

**Counted noise**, 8 seeds per project (truth inside the band / 8):

| project | changed number found moved | its true new value inside the after interval | errors | queue | retries | OOM kills |
|---|---|---|---|---|---|---|
| slower-retries | 7 | 8 | 8 | 7 | 8 | **3** |
| fewer-errors | 8 | 8 | 7 | 6 | 7 | 7 |
| fewer-timeouts | 8 | 7 | 7 | **4** | 8 | **4** |

- The structural answer holds up best: the changed number is found in 23 of 24 runs, with a few extra flags
  (a pending or OOM-counter number in 4 runs).
- The outcome effects that are large against the noise are measured well: fewer-errors' −9,098 failed requests is
  −9,095 ± 208 (mean ± sd over seeds, less the placebo).
- **Biased refits.** With counted noise the before refit of the retry share is low (0.46–0.63 over seeds, true 0.6),
  and the retry-queue effect is under-estimated in every seed (15.9 ± 1.0 vs 17.5 for slower-retries). The OOM
  counterfactual is poor: the placebo runs report +1.7 to +36.8 kills with no project at all (median +8.7), so the
  OOM effect is not measurable this way. This is the counts variants' data limit (docs/research/kubernetes-ladder.md,
  "310 after round 1": counted noise on `mem` biases the memory drain) seen from operations.
- Bands from 12 placebo runs are rough (their 2.5–97.5% is close to their min and max).

## Limits

- One-step least squares on noisy levels; no state filter. A Kalman-style filter (as kalman_lna does) should reduce
  the bias.
- Only proportional and linear numbers are refitted; a project that changes an expression's number (the autoscaler
  divisor) or an effect table would not be seen as a moved number.
- The placebo correction assumes the method's misfit is the same with and without the project.
- No control services (idea 37's "other services that did not change"); the placebo runs play that part.
