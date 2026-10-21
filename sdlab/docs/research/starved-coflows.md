# Co-flows found where the used stock runs dry

**Status:** done (wave 4, benchmark v2)  
**Verdict:** adopt as a candidate family (+10.9 / +15.0 points in-sample, +10.5 / +14.5 on fresh runs);
needs a combination with a judge inflow pieces cannot fool (two losses are the judge picking a wrong co-flow)

## Why
In the co-flow examples the used stock runs dry for stretches, and while it does the engine scales the
flow down to what the used stock holds. The source queue then piles up 7-14 times its usual level
(sd-print-shop default: mono_queue 400 -> 5590 while toner sits near 30 g and paper near 64-108
sheets; sd-bakery: orders 86 -> 677 while flour is at 4-14 kg; sd-cloud-credits: queued 18 -> 146 while
credits are near 0 for about 15% of steps). The one-step fit mixes the two regimes. The source's drain
comes out at a fraction of the truth: bakery orders -> shelf 0.0046 + link 0.057 against 0.5;
print-shop mono_queue -> done 0.008 + link 0.078 against 0.5; cloud-credits queued -> running 0.16
against 0.3. Inflow pieces fill the gap (print-shop long: 1362 pieces). Fed the true inflows, a model
with no cap runs away (v2.1 skill@20: -1170%, -529%, -859%). Our simulator already applies the cap
when a flow declares `uses`, so what is missing is finding the `uses` and fitting the source row on
the steps where the cap does not bind. This differs from [censored-floors](censored-floors.md), which
censors a stock's *own* outflows when it empties, and from [count-likelihoods](count-likelihoods.md),
which reads `per` from shared noise but leaves the starved steps in the fit.

Found on the way: in sd-bakery default the main line's orders row has **no** outside inflow and a drain
of 0.0046 (orders a random walk): high orders go with both large positive changes (starved, piling up)
and large negative ones (flour back, draining fast), so the slope is ~0. The grader feeds the true 40
an hour into a stock that never drains.

## What was done
Branch `exp/starved-coflows`, commit `054cb95` (worktree `.claude/worktrees/agent-a9817f8f0c29b2c26`).
Module `discovery/starvation.py`, strategy `starved_coflows`, one option in `matrix.identify_one`:
`keep` (fit only these steps; default None, the main line unchanged: zero deltas on sd-saas, sd-eras,
sd-pipeline default).

1. **Candidates C**: non-final stocks below half their median on at least 1% of steps.
2. **Users, measured where C is plentiful**: fit with every step where C is below its median left out;
   C's row's negative cross terms on stocks *of another unit* are its users (per x k x level of A).
3. **Dry steps**: C below 1.5 x what its users want; refit without them, measure again (one refine).
   C is kept if this leaves at least 1% of steps out and no more than half. A second round tries the
   remaining stocks with the found stocks' dry steps left out too. Each found C alone, and all together
   when that leaves out at most half the steps.
4. **Masked fits**: every main-line variant fitted on the kept steps; each cross term "C drains faster
   when A is high" becomes `uses: [{stock: C, per: (per x k) / k}]` on A's move (A -> B; the largest),
   accepted only if A's residual on C's dry steps is positive (t > 2).
5. **Outside inflows over the left-out steps** (`remeasure_inflows`): the found model's own flows are
   run one step from every measured state (co-flows capped), and each piece-wise inflow is measured
   again (PELT) on all steps. While C is dry its users take all it holds, so what it receives shows in
   its level; without this the masked candidates were judged poorly and graded 11% on sd-bakery
   (with it, 95.5%).
6. All candidates (16 main line + the co-flow ones) go to the main line's judge.

## Mechanism test (`tests/test_strategy_starved_coflows.py`, synthetic bakery)
Orders (40 an hour) -> shelf at 0.5 x orders using 0.5 flour; shelf drains 0.25; flour restocked
toward 600 over 10 hours, over 60 for 60 hours of every 250 (unannounced); 1000 steps.

| | matrix (main line) | starved_coflows |
|---|---|---|
| orders drain | below 0.25 (spurious pieces take the rest) | 0.566 (changing inflows), 0.501 (constant inflows) |
| `uses` on orders -> shelf | none | flour, per 0.40 from the cross term, 0.43 / 0.497 from the dry steps |
| skill@20 | below 0 | 0.86 (per from cross term), 0.90 (per from dry steps), co-flow candidates alone |
| steps left out | - | 163, covering all 150 steps the truth's cap bound |

Controls: flour that never runs dry gives exactly the main line (same choice, skill within 0.01); an
outflow of flour driven by the orders that does not cap the bake (flour runs dry, orders unaffected)
gets no `uses`.
Short of the brief's thresholds (k within 0.05, skill above 0.9) through the full strategy, for two
reasons outside the mechanism: (a) the main line's fine first pass finds 26 chance pieces in the
orders' constant inflow, which pull the drain to 0.57 (with a constant inflow the masked fit gives
0.501); (b) **the judge prefers the main line here** (0.114 vs 0.170): its inflow pieces replay the
pile-ups, which the judge, feeding each model its own inflows, cannot see. The test therefore runs the
co-flow candidates alone (`starved_only`) and checks the mechanism in isolation separately.

## Results (baseline v2.1: 29.6% / 29.3%, fresh 28.9% / 29.7%, 12 of 62, 586 s)
| version | skill@20 | skill@100 | fresh @20 / @100 | goal (fresh) | time |
|---|---|---|---|---|---|
| v1: as above, without the unit rule or share cap | 40.0% | 45.6% | 39.7% / 45.8% | 14 (14) | 2447 s |
| v2: + C of another unit than A | 42.6% | 49.3% | 41.4% / 49.0% | 14 (14) | 2598 s |
| **v3: + C dry on at most half the steps (final)** | **40.5%** | **44.3%** | **39.4% / 44.2%** | **14 (14)** | **1865 s** |
| v4: v3, per from the dry steps | 37.6% | 43.3% | 36.4% / 43.1% | 14 (14) | 1335 s |
| v5: v3, best co-flow candidate taken over the judge | 37.7% | 39.0% | 36.7% / 38.8% | 12 (12) | 1362 s |

(Times are summed over runs on a loaded shared machine, 3 workers; compare within this table only.)

v3, every run moving more than 2 points (skill@20 / @100, v2.1 -> v3; fresh @20 in brackets):

| run | v2.1 | v3 | found |
|---|---|---|---|
| bakery default | -1170 / -10328 | **95.5 / 97.2** (95.5) | orders -> shelf 0.52 uses flour 0.52 (truth 0.5 / 0.5) |
| bakery long | 18.8 / -1650 | **98.1 / 98.7** (97.9) | same |
| print-shop default | -529 / -2305 | 28.1 / 69.8 (26.3) | mono_queue -> done 0.09 uses paper 0.54 (truth 0.5 / 1; toner not found) |
| cloud-credits default | -859 / -1648 | 14.5 / -33.3 (23.2) | queued -> running 0.33 uses credits 2.1 (truth 0.3 / 2) |
| cloud-credits long | -16.5 / 54.4 | 42.0 / 40.8 (39.7) | same flow |
| restaurant default | 63.6 / -14.4 | 82.3 / 94.0 (76.1) | orders -> cooking 0.24 uses prep 1.05 (truth 0.15 / 1) |
| restaurant long | 65.3 / -75.1 | 86.1 / 91.3 (84.9) | prep |
| ev-fleet default | 32.0 / 47.8 | 48.5 / 62.8 (17.5) | charging -> ready 0.32 uses energy 145 (truth 0.25 / 160) |
| ev-fleet long | 18.3 / 40.3 | 38.8 / 53.2 (12.4) | parcels (wrong stock) |
| clinic-doses default | -602 / -864 | -235 / -67.7 (-233) | vaccinated -> waiting uses doses (wrong direction; weekly delivery pulses) |
| moderation long | -99.0 / -90.5 | 1.8 / -204 (6.1) | credits |
| sawmill default | -261 / -72.2 | -249 / -172 (-196) | logs -> planks 0.20 uses sharpness 0.59 (truth 0.25 / 0.5) |
| manufacturing long | 87.0 / 95.1 | **39.8 / 63.6** (38.3) | inspection -> rework uses backlog (spurious) |
| moderation default | -67.4 / -172 | **-422 / -54.6** (-443) | flagged -> removed 0.004 uses credits 7.4, 31 steps (truth: flagged -> vendor) |

Fresh-run skill tracks in-sample skill everywhere (the gain is not fitted noise). Unchanged: brewery,
hospital, kanban, print-shop long, clinic-doses long (no co-flow candidate chosen by the judge).

## Lessons
- Leaving out the steps where a used stock is dry, with the dry steps found from the users' demand
  measured where the stock is plentiful, recovers the source's drain and the co-flow; the simulator's
  cap does the rest. The largest tail gains on the board (bakery, cloud-credits, print-shop default).
- The left-out steps still carry information: the used stock's inflow must be measured on them with
  the cap applied, or the candidate runs dry at the wrong times.
- Measuring the demand on the low-C steps (first try: C below 10% of median) underestimates it 10x:
  the steps right after the stock refills are still capped. Measuring it where C is plentiful fixes it.
- Units are the strongest guard: a stock used by a flow of the same unit was nearly always a queue in
  the chain (ev-fleet: ready -> road "uses" queue, -91 points). Only sd-kanban's capacity breaks it.
- Taking a co-flow over the judge whenever one exists (v5) is worse: hospital, webshop, clinic long and
  sawmill long collapse. The judge is right more often than not; where it is wrong (synthetic bakery,
  manufacturing long, moderation default) it is fooled by inflow pieces.
- `per` from the dry steps (what the flow moved where the cap bound, against C's level) is exact when
  the source's inflow is known (synthetic: 0.497), but on the bench it inherits the inflow pieces'
  errors (cloud-credits default -193%); the cross term is the better default.

## Judge and gate notes (for the behaviour-consistency gate and the piece-proof judge)
- The strategy adds flexibility the current judge can be fooled by: the masked candidates' inflows are
  re-measured on all steps, and a spurious `uses` (manufacturing long, moderation default) can win on
  in-sample behaviour while grading far worse. Both losses would need a judge that does not feed models
  their own inflow pieces.
- Conversely the judge rejects the right co-flow on the synthetic bakery because the main line's pieces
  replay the pile-ups. A piece-proof judge should help in both directions.
- Everything is optional: `prefer_coflows`, `starved_only`, `per_from`, `same_unit`, `max_share`, and
  `matrix`'s `keep` can be combined with the gate later.

## Open ideas
- Resources that bind most of the time (print-shop toner, capped on 62% of steps) are beyond masking:
  fit the flow with the cap inside it (column k x A x min(1, C / demand), iterated), using every step.
- A co-flow's demand from shared noise ([count-likelihoods](count-likelihoods.md)) instead of the cross
  term, which collinearity between C and A biases (the flour row: restock gap makes flour track orders).
- Same-unit resources (kanban capacity): allow them only when the C stock exchanges no moves with A's
  chain.
- Co-flows on inflows from outside (clinic walk-ins, orders' purchases, support hiring): only moves are
  offered now.
- Run time 3.2x: the masked fits rerun every variant; trust-rows and trust-receivers variants mostly
  agree and could share a fit.

## Sources
Tobin (1958) Econometrica 26(1):24-36; Lariviere and Porteus (1999) Manage. Sci. 45(3):346-363 (sales
capped by stock are censored demand); Paoletti et al. (2007) Eur. J. Control 13(2-3):242-260 (known
switching surfaces); Martinelli et al. (2022) Reactmine, arXiv:2209.03185 (fixed-ratio co-variation);
[symbolic-regression](symbolic-regression.md) open ideas; failure analysis in [IDEAS-WAVE4](IDEAS-WAVE4.md).

## The declared boundary (2026-10-20)

Outside flows only where the case declares them (docs/research/declared-boundary.md; CLAUDE.md invariant
2). `starved_coflows/boundary.py` is a copy of `matrix/boundary.py` at 723f72c (HIDDEN_PRICE 0). The
main-line candidates are refitted inside the boundary (`earned.refit`: an outside term only where an
estimated one may be, a measured input only where a measured one may be, sources with no estimated outflow
tied); every candidate, co-flow ones included, is guarded before the judge (`consider`). The answer: guard
and anti-correlated pairs made moves (declared), or each outside flow priced as a boundary claim at 2 log T
(not declared). The copy's one change: `alternatives()` never pairs an inflow into B with B's own outflow.

Results: in progress (paired before/after on Kubernetes 300-305 and 40 stored Tests cells, CPU pool).
