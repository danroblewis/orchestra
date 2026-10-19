# realistic_hats: effect_hats that answers in time, with hidden transit stocks

**Status:** done (first version, commit 52cd6d1; realistic cases and 462 hand-written test cells run
19 Oct 2026).
**Verdict:** keep as the realistic leader's successor. It loses no test cell against effect_hats and
gains 11 (015, 026, 085: hidden stocks). It answers on 10 of effect_hats' 12 realistic timeouts.
On the 54 runs both graded, behaviour is unchanged (mean -0.1 points: sd-webshop-stock +9/+11,
sd-brewery long -30). It is not the large realistic gain the user wants: most realistic failures
are mechanisms neither strategy has yet (docs/research/realistic-triage.md).

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
| realistic_hats | 64 | 2 | 47.0% | 42.6% | 45.6% | 45.9% | 15 | 0 | 0.569 |

Strict passes: 0 for both (strict needs a pass first).

- **Paired on the 54 runs both graded:** mean -0.1 points. Better: sd-webshop-stock long 85.8% ->
  94.5% (it now meets the goal) and short 74.4% -> 85.9%, both from a hidden in-transit stock.
  Worse: sd-brewery long 29.8% -> 0.2%. There a transit water -> H -> fermenting was accepted, but
  water is a used stock, not a stage; skill@100 went 40% -> 60%.
- **The 10 runs that now have a model:** sd-ci long 85.7%, sd-clinic-doses long -86.6%, sd-eras
  long 49.6%, sd-ev-fleet long 18.3%, sd-hospital long 83.0%, sd-k8s-small long 87.2%, short
  58.2%, sd-moderation long -100%, sd-restaurant long 64.7%, sd-services long 64.8%. They are the
  hard runs, so the mean over the graded runs falls (49.9% -> 47.0%) while the mean over all runs
  rises. sd-k8s-platform still times out in both variants.

**Test cells (462 hand-written cells, the same rescoring):** effect_hats 125 pass / 53 equivalent,
realistic_hats 140 / 53. 0 cells worse, 15 better:
- 015-hidden-stock (4 of 4), 026-hidden-stock-driven (3) and 085-noisy-hidden-stock (4) come from
  the transit step;
- 062-tank-fed-by-measured-pump (4) comes from effect_hats' own measured-input fix (89adae4),
  which postdates its stored results.

On the new distilled cases: 156 and 161 still fail. 161 accepts a transit A -> H -> B, but its
numbers are off: the co-flow on H's exit is not modelled. 156 is never tried, because hidden_transit
skips a pair with a move B -> A.

## Next

- **Transit on closed loops.** hidden_transit's rule against a pair with a move B -> A ("a loop's
  echo") blocks 156, sd-ev-fleet and sd-recycling. A probe without the rule (not committed, in
  progress at the time of writing) accepted the transit on 156's counts variants: recall 1.0, fresh
  skill@20 0.92 / 0.88 against 0.42 / 0.08. It found no transit on 008, 009, 010, 011, 012, 016,
  105, 106 or 135.
- **Don't take a used stock for a stage** (sd-brewery). Skip a pair where A's loss follows another
  stock's flow, so the stage is not just a co-flow's mirror.
- **Mechanisms B, C, D, E** of the triage (an inflow standing in for a flow; co-flows; destination
  gaps; flows driven by a third stock) are where most realistic skill is lost. Each now has a
  distilled case (152-155, 161).
