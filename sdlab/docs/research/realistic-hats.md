# realistic_hats: effect_hats that answers in time, with hidden transit stocks

**Status:** done. First version at commit 52cd6d1; current version at 06b0062, which allows transit
on closed loops and never takes a used stock as a stage. Both were run on the realistic cases and on
462 hand-written test cells, 19 Oct 2026.
**Kubernetes 303 (2026-10-20, 099e99d):** the base is now matrix's earned main line (a copy of its earned
refit), clearing 303 counts-short; 2 of 40 paired cells lost (083 counts-long, 084 outliers-short), see
[k8s-303-realistic-hats.md](k8s-303-realistic-hats.md).
**Verdict:** keep as the realistic leader's successor.
- It loses no test cell against effect_hats and gains 11 (015, 026, 085: hidden stocks).
- It answers on 11 of effect_hats' 12 realistic timeouts.
- On the 54 runs both graded, mean skill@20 is +0.4 points. Two runs are better (sd-webshop-stock
  +9/+11) and none worse.
- It is not the large realistic gain the user wants. Most realistic failures are mechanisms neither
  strategy has yet (docs/research/realistic-triage.md).

## Why

The triage (realistic-triage.md) found two things a copy of the realistic leader, effect_hats, could
fix without new theory:

1. **Timeouts.** effect_hats ran out of the 300 s on 12 of 66 realistic runs: 9 long runs and the
   k8s cases. A timed-out run gets no model and never meets the goal.
2. **Hidden stages.** A hidden stage was missed in 19 of 33 cases. hidden_transit's pair search
   (a Kalman likelihood of A's loss waiting in an unmeasured H before reaching B) passes 015.
   It had never been tried on the realistic cases or on top of effect_hats' models.

## What it does

`sdlab/discovery/strategies/realistic_hats/` is self-contained (CLAUDE.md invariant 11). It holds:
- effect_hats' modules, copied at 89adae4;
- combined's `deadline.py`, copied at beab53e;
- hidden_transit's committed `__init__`, `fit`, `kalman` and `pairs`, copied at 376fa34 under
  `transit/`, with `identify` turned into `add(model, ...)`.

The changes from effect_hats:

- **Anytime.** After the base model, the search runs under a cap of `share` (0.85) of what the
  caller's timer leaves. The best answer so far is kept: the base, the base with re-cut inflows,
  then each accepted effect. When the cap fires, that answer is returned with "(search stopped:
  out of time)" in `chosen`.
- **Hidden transit stocks** (`transit`, on by default), on the answer, in the time left. Pairs
  touched by an effect flow or a co-flow are skipped (the Kalman rows are linear). Acceptance is
  hidden_transit's: BIC margin 4 log n, and the model with H must behave better on the data than
  the model without it with B's arrivals held at their mean.

## Results

The store's rows carried different scorer hashes while another agent changed the scorer. Both
strategies' stored models were therefore scored again by the current scorer, in one process:
`JOBS=2 uv run python tests/study_rescore_pair.py effect_hats realistic_hats tag:realistic OUT`
(and the same with the list of hand-written cases), 19 Oct 2026. effect_hats' stored models are
from d95fb2d and later (its code changed after that only for measured inputs, 89adae4). realistic_hats'
are from 52cd6d1.

**Realistic (66 runs; skill@20 in-sample, each clipped at -100%):**

| | runs graded | timeouts | mean skill@20 (graded) | mean over all 66, timeout = -100% | timeout = 0 | fresh@20 | goals met | equation passes | recall |
|---|---|---|---|---|---|---|---|---|---|
| effect_hats | 54 | 12 | 49.9% | 22.6% | 40.8% | 48.7% | 14 | 0 | 0.555 |
| realistic_hats 52cd6d1 | 64 | 2 | 47.0% | 42.6% | 45.6% | 45.9% | 15 | 0 | 0.569 |
| realistic_hats 06b0062 | 65 | 1 | 44.5% | 42.3% | 43.8% | 43.8% | 15 | 0 | 0.566 |

Strict passes: 0 for all three (strict needs a pass first).

- **Paired on the 54 runs both graded (06b0062):** mean +0.4 points, 2 better, 0 worse.
  - Better: sd-webshop-stock long 85.8% -> 94.5% (it now meets the goal) and short 74.4% -> 85.9%,
    both from a hidden in-transit stock.
  - At 52cd6d1, sd-brewery long fell 29.8% -> 0.2%: a transit water -> H -> fermenting was accepted,
    but water is a used stock, not a stage. 06b0062 skips a source whose loss mostly follows other
    stocks, and sd-brewery is back to 29.8%.
- **The 11 runs that now have a model (06b0062):**

  | run | skill@20 |
  |---|---|
  | sd-ci long | 85.7% |
  | sd-clinic-doses long | -86.6% |
  | sd-eras long | 49.6% |
  | sd-ev-fleet long | -28.6% |
  | sd-hospital long | 83.0% |
  | sd-k8s-small long | 87.2% |
  | sd-k8s-small short | 58.2% |
  | sd-moderation long | -100% |
  | sd-restaurant long | 64.7% |
  | sd-services long | 64.8% |
  | sd-k8s-platform short | -100% |

  These are the hard runs, so the mean over the graded runs falls while the mean over all runs rises.
  sd-k8s-platform long still times out. sd-ev-fleet long varies between runs (18.3% at 52cd6d1, with
  no transit in either version), because where the time cap stops the search depends on the
  machine's load.

**Test cells (462 hand-written cells, the same rescoring; identical for 52cd6d1 and 06b0062):**
effect_hats 125 pass / 53 equivalent, realistic_hats 140 / 53. 0 cells worse, 15 better:
- 015-hidden-stock (4 of 4), 026-hidden-stock-driven (3) and 085-noisy-hidden-stock (4) come from
  the transit step;
- 062-tank-fed-by-measured-pump (4) comes from effect_hats' own measured-input fix (89adae4),
  which postdates its stored results.

On the new distilled cases, 156 and 161 still fail.
- 161 accepts a transit A -> H -> B, but its numbers are off: the co-flow on H's exit is not
  modelled.
- 156 counts (06b0062) now finds the hidden stage on the loop. Recall is 1.0, fresh skill@20 is
  92% / 88% (was 42% / 8%), but the numbers are outside tolerance. 52cd6d1 never tried it, because
  hidden_transit skips a pair with a move B -> A.

## Next

- **Transit numbers on loops and co-flowed exits** (156, 161): a hidden stage is now found there, but
  its numbers are off.
- **Mechanisms B, C, D and E** of the triage are where most realistic skill is lost: an inflow
  standing in for a flow, co-flows, destination gaps, and flows driven by a third stock. Each now
  has a distilled case (152-155, 161).
- **Time on long runs.** On the long realistic runs the cap, not convergence, ends the search, so
  results depend on the machine's load. A cheaper effect screen on long runs (a window, or the
  short run's candidates) would make them repeatable.
