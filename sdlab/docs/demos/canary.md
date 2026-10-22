# Demo 11: canary guard

Idea 32 (rollout guard) of `OPERATIONALIZATION.md`. Tab "11. Canary guard" on `/demos`. Code:
`sdlab/demos/canary.py` (it uses the refit of `sdlab/demos/attribution.py`), `sdlab/static/demos-canary.js`; tests:
`tests/test_demos_canary.py`.

## What it shows

Two copies of the 310 scenario's service run side by side: the baseline (the true model as it is) and the canary (an
in-memory copy with one rate a little worse). Regressions: `errors` (error rate up), `timeouts` (timeout rate up),
`slower` (completion rate down), each by 0%, 5%, 15% or 30%. Each copy runs on its own seed (baseline 1000+s, canary
2000+s), with counted noise (the ladder's counts) by default or noise-free; 300 or 1000 steps.

The found model's structure is kept and its numbers are refitted on each copy (`attribution.refit`: one-step weighted
least squares, block-bootstrap standard errors). Each number's difference canary − baseline is shown with its z; a
number is **flagged** when |z| > 3 and it differs by more than 1%. Any flag means **stop**. The page says whether that
was right (the truth knows whether the canary is worse), whether the flagged number is the one that changed, and
shows a table of decisions over all sizes and 10 seeds: right stops, missed regressions, false stops.

The found model is milp's stored passing result on `310-k8s-memory-oom` none-long (#386907, code 491632e57).

## How it works

The bootstrap within one run is too narrow: it misses how a number's refit varies from run to run through the
model's misfit (mostly on memory). So each number's z is divided by its root-mean-square z over 12 **A/A pairs**
(two identical copies on calibration seeds 101–112, never the test seeds), at least 1 (`canary.calibration`). The
page also shows the uncalibrated z ("bootstrap only") and what the decision would have been without it.

Endpoints (under `/api/demos`): `/canary/options`, `/canary/run?regression=&size=&seed=&steps=&counts=` (under a
second per copy, cached), `/canary/table?regression=&steps=&counts=` (from a file). Cache:
`~/.cache/sdlab/demos/canary/` (calibration and decision tables, keyed by the stored result id). Regenerate:
`OMP_NUM_THREADS=1 nice -n 19 uv run python -m sdlab.demos.canary` (about 1.5 CPU-minutes).

## What it found (2026-10-22, store result #386907; `/canary/table`)

Counted noise, 10 seeds, stops out of 10 (bootstrap-only in brackets):

| regression | steps | 0% (false stops) | 5% | 15% | 30% |
|---|---|---|---|---|---|
| errors | 1000 | 0 (2) | 9 (10) | 10 | 10 |
| timeouts | 1000 | 0 (2) | 0 (2) | 4 (7) | 10 |
| slower | 1000 | 0 (2) | 10 | 10 | 10 |
| errors | 300 | 2 (5) | 3 (9) | 10 | 10 |
| timeouts | 300 | 2 (5) | 2 (7) | 3 (8) | 6 (7) |
| slower | 300 | 2 (5) | 10 | 10 | 10 |

- The 0% rows share the same runs (a canary with nothing changed is the same copy for every regression), so the false
  stops are 0 of 10 at 1000 steps and 2 of 10 at 300 steps, not three times that. Without the A/A calibration they are
  2 of 10 and 5 of 10, mostly on `mem → outside` (the memory drain, where the found model's memory expression misfits).
- When it stops on a worse canary, the flagged numbers include the changed one in every stop at 1000 steps. At 300
  steps the timeouts stops are partly for the wrong reason: 0 of 2 at 5% and 2 of 3 at 15% flag the timeout rate
  (6 of 6 at 30%); those right stops are luck, as good as the false stops at 0%. Other numbers are sometimes flagged
  beside the right one (e.g. `retries → outside` at errors +15%, seed 1).
- Sensitivity follows how much each rate moves the data: a slower completion (the largest flow) is caught at 5% even in
  300 steps; errors at 5% need 1000 steps (9 of 10); timeouts (a small flow into the retry queue) are missed at 5% and
  caught only 4 of 10 at 15% in 1000 steps.
- Noise-free: every regression is stopped at every size on the right number and the 0% canary goes (trivially: the two
  copies are the same deterministic run).

## Limits

- 10 test seeds and 12 calibration pairs: the false-stop rates are rough (0/10 does not prove 5%).
- The canary here has the baseline's traffic; a real canary gets a slice of it (smaller counts, more noise).
- Only proportional and linear numbers are compared; a regression inside an expression or an effect table (e.g. the
  OOM threshold) is not looked at.
- The refit is one-step least squares on the copies' noisy levels (see docs/demos/attribution.md for its bias).
