# Symbolic effects accepted by an addition judge inflow pieces cannot fool

**Status:** done (wave 4, benchmark v2.1)  
**Verdict:** reject as stated (the anchor rule refuses every true effect); the best variant is a
do-no-harm filter (+5.9 points skill@20, no run worse than v2.1) that keeps only a third of plain
symbolic's gain; plain `symbolic` stays the better strategy on the mean

## Question
[Symbolic regression](symbolic-regression.md) finds effects but its judge (each candidate run with its
own inflow pieces) also takes spurious curves. [Inflow-conditioned judge](inflow-conditioned-judge.md)
proposed judging an addition by comparing the model with and without it, both fed the inflow of the
model WITHOUT it. Hypothesis: with that rule (and a margin from the judge's noise) symbolic keeps its
gains (sawmill, webshop, learning-curve, co-flow examples) and loses its losses (eras default,
farm-soil long, ...).

## What was done
Branch `exp/symbolic-addition-judge` (from `aeb9b9e`), worktree `.claude/worktrees/agent-a2e5f20b6ea958817`.
The symbolic code (`curves.py`, `effects.py`, `onestep.py`, strategy `symbolic`, `matrix.py` option
`only_rows`, default off; from `b917b0f`) and `judges.py` (from `5207b48`) brought onto the main line;
`symbolic` now lists its candidates for the bench's grading.
`sdlab/discovery/addition.py`: `addition_test(base, cand, stocks, run, inflow=...)`: both models run
from ~80 starts over 5/20/100 steps with an outside inflow chosen by `inflow`; the gain is the base's
error minus the candidate's, relative to the base's, per start; its noise is the spread of a block
bootstrap over starts (blocks of 8 neighbouring starts); accept when gain > max(0.02, 2 x noise).
Inflows: `anchor` (the base's pieces for both), `remeasure` (the base's piece times, values
re-measured under each model's dynamics), `refit` (a coarse inflow, pieces of at least n/50 steps,
re-measured under each model's dynamics into the stocks the base feeds: judges.refit_inflow), `own`.
Strategy `symbolic_anchor`: base = main line; the screen's effects fitted in every variant (or the
base's only); every candidate tested, the largest passing gain accepted; options for one effect at a
time, the main judge's pick, a pieces-variance condition, and `also` (inflows under which the gain
must also be positive).

## Mechanism (`tests/test_strategy_symbolic_anchor.py`)
| case | plain symbolic | anchor | refit | refit and own > 0 (default) |
|---|---|---|---|---|
| true effect, backlog -> done at k x backlog x table(skill) | effect, skill@20 -42% | refused (gain -1.6 to -3.6: counted twice) | accepted (+0.157 ± 0.044), 50% vs matrix -95% | accepted |
| true effect, steep table (sawmill-like) | keeps matrix | refused | refused (-0.07) | refused |
| spurious: chain whose stage rates change at announced eras, no effect | effect taken, 88% -> 42% (seed 1), 99% -> 34% (seed 3); 5 of 5 designs | - | refused (-0.06 ± 0.03, -0.004 ± 0.007) | refused |
Own inflow with the noise margin and the base's variant only accepts the spurious curve on seed 1 (+0.10).
On bench data the anchor gain of every true effect is hugely negative (sawmill -30 to -1600, webshop
-3.3): the base's pieces already carry the effect's imitation, and the effect adds it again.

## Results (benchmark v2.1: 29.6% / 29.3%, fresh 28.9% / 29.7%, 12 of 62 meet the goal; `--seeds 2`)
| strategy | skill@20 | skill@100 | fresh @20 / @100 | goal | failures NR / NC / NS | seeds @20 | paired vs v2.1 @20 (better/worse, sign p, Wilcoxon p) | @100 | CPU |
|---|---|---|---|---|---|---|---|---|---|
| main line (v2.1) | 29.6% | 29.3% | 28.9% / 29.7% | 12 | 44 / 1 / 5 | | | | 586 s |
| symbolic (b917b0f) | **47.2%** | **42.6%** | 46.5% / 42.9% | 13 | 37 / 3 / 9 | 41.2% ± 5.4 | 17 / 3, p=0.0026, 0.0020 | 17 / 4, 0.0072, 0.0038 | 2969 s |
| symbolic_anchor refit, all variants | 23.1% | 20.1% | 22.4% / 20.1% | 9 | 40 / 7 / 6 | 18.3% ± 6.4 | 7 / 6, p=1, 0.59 | 4 / 8, 0.39, 0.27 | 2250 s |
| own inflow + margin, base's variant | 37.4% | 35.3% | 36.6% / 35.7% | 14 | 39 / 2 / 7 | 31.2% ± 6.7 | 9 / 1, p=0.022, 0.020 | 10 / 1, 0.012, 0.0020 | 477 s |
| **refit and own > 0, all variants (default)** | 35.6% | 31.2% | 35.1% / 31.6% | 13 | 40 / 3 / 6 | 30.9% ± 6.5 | **6 / 0**, p=0.031, 0.031 | 4 / 1, 0.38, 0.13 | 1815 s |
Against plain symbolic: refit -24.1 points (4 better / 19 worse, p=0.003), refit and own -11.6 (4 / 13,
p=0.049), own + margin -9.8 (3 / 8, p=0.23). CPU: discovery's summed time on a loaded machine (3 workers).

Runs moving more than 2 points (skill@20 / @100, clipped at -100):
| run | v2.1 | symbolic | refit | own + margin | refit and own (default) |
|---|---|---|---|---|---|
| sd-bakery default | -100 / -100 | 66 / 33 | -100 / -100 | 66 / 33 | -100 / -100 |
| sd-bakery long | 19 / -100 | 44 / 39 | 19 / -100 | 19 / -100 | 19 / -100 |
| sd-brewery long | 66 / 88 | 86 / 85 | 66 / 88 | 66 / 88 | 66 / 88 |
| sd-clinic-doses long | -100 / -100 | 23 / 8 | -100 / -100 | -100 / -100 | -100 / -100 |
| sd-cloud-credits long | -16 / 54 | 80 / 64 | 72 / 76 | 80 / 64 | 72 / 76 |
| sd-emergency long | -47 / 61 | -47 / 61 | -11 / -46 | -47 / 61 | -47 / 61 |
| sd-eras default | 96 / 98 | **60 / 83** | 96 / 98 | 96 / 98 | 96 / 98 |
| sd-ev-fleet long | 18 / 40 | 55 / 70 | 18 / 40 | 61 / 77 | 18 / 40 |
| sd-farm-soil long | 97 / 78 | **75 / -78** | -100 / -100 | 97 / 78 | 97 / 78 |
| sd-fishery default | 3 / -100 | 3 / -100 | 80 / 85 | 3 / -100 | 3 / -100 |
| sd-fishery long | -18 / -100 | -62 / -100 | -100 / -100 | -62 / -100 | -18 / -100 |
| sd-hidden-chain long | 98 / 97 | 98 / 97 | -100 / -100 | 98 / 97 | 98 / 97 |
| sd-kanban default | 61 / 63 | 73 / 65 | 61 / 63 | 61 / 63 | 61 / 63 |
| sd-learning-curve long | 45 / 49 | 99 / 100 | 45 / 49 | 99 / 100 | 45 / 49 |
| sd-print-shop default | -100 / -100 | 68 / 80 | -100 / -100 | -100 / -100 | -100 / -100 |
| sd-reservoirs long | 91 / 90 | 91 / 90 | -100 / -100 | 91 / 90 | 91 / 90 |
| sd-sawmill default | -100 / -72 | 52 / 65 | 60 / 71 | -100 / -72 | -100 / -72 |
| sd-sawmill long | -100 / -5 | 73 / 77 | -100 / -100 | -100 / -5 | 80 / 43 |
| sd-services default | 7 / 72 | 68 / 90 | 7 / 72 | 68 / 90 | 7 / 72 |
| sd-services long | 35 / 78 | 97 / 99 | -100 / -100 | 97 / 99 | 97 / 99 |
| sd-webshop-stock default | 61 / 55 | 88 / 86 | 86 / 84 | 88 / 86 | 86 / 84 |
(Also, in every effect strategy: orders default 76 -> 81, moderation default -67 -> -58; small @100
moves on ci long, cloud-credits default, housing long.) On v2.1 plain symbolic no longer loses
manufacturing default, support-tiers long or restaurant long (the v2 losses); its losses are eras
default, farm-soil long, fishery long, cloud-credits default @20.

`matrix` unchanged: sd-saas, sd-eras, sd-pipeline default, zero deltas against v2.1.

## Lessons
- **The anchor rule cannot accept a true effect.** The base model's pieces are fitted beside the
  missing effect and already imitate it (that is the whole problem); the model with the effect, fed
  them, counts the effect twice. "The addition must remove pieces" needs the pieces to be re-measured,
  not kept.
- **A re-measured coarse inflow ("refit") separates true and spurious effects on equal footing, but
  only when the candidates differ by the addition alone.** Across variants it rewards a constant-inflow
  candidate or a runaway set of curves once everyone's inflow is coarse (hidden-chain, reservoirs,
  services, sawmill, farm-soil, fishery long to -100%), as in the piece-proof experiment. Requiring
  the gain under the candidate's own pieces too removes all of those: no run worse than v2.1.
- **What the filters cost is most of symbolic's gain.** The gains on bakery, print-shop, clinic-doses,
  brewery long, kanban and services default come from effects (often curves standing in for co-flows
  or a stock running dry) that do not beat the base by the margin under refit, or not under own
  pieces; plain symbolic's choice there is right by the grader though the data's evidence is weak.
  On this bench the in-data judge's mistakes cost less (4 runs) than a strict test's refusals (8-11).
- Discovery noise: one run's skill@20 spreads 20-31 points across seeds for every strategy; the
  paired tests above are on the main seed only.

## Open ideas
- Per-candidate both-sided rule: accept when (refit gain > margin and own gain > 0) OR (own gain >
  margin and refit gain > -margin): keeps services/bakery-type gains if refit is merely neutral there.
- Effects as replacements for co-flows (bakery, print-shop, clinic-doses): a co-flow search
  ([starved-coflows](starved-coflows.md)) may give the same gains with structure the tests can accept.
- Refit with the base's own segmentation coarsened (merge pieces until each has >= 20 steps) instead of
  PELT per model: same budget, fewer degrees of freedom to tailor.
- Steep tables (sawmill-like synthetic) are refused by every rule: the base's links already capture
  most of a steep curve; a curve refined by output error might clear the margin.
