# Inflow attribution: which stocks receive an outside inflow, and drains that do not absorb it

**Status:** done (benchmark v2.1), branch `exp/inflow-attribution`. Builds on Playbook M8
([partial-model simulation](partial-model-simulation.md)) and the diagnosis in
[behaviour-consistency](behaviour-consistency.md) and [bench instrumentation](bench-instrumentation.md).
**Verdict:** needs a combination / promising. +3.8 points skill@20 and +7.0 points skill@100, with no
example worse except sd-moderation default. That is not significant on the paired test (Wilcoxon
p = 0.19 at @20, p = 0.06 at @100) and not enough to adopt alone: no run crosses the goal. The
counting-noise test is the most useful new diagnostic so far: it flags the rows that send the main
line's runaways off. Separately, a **matrix form-choice flaw** (the pieces gate) is confirmed. It is
offered as an option, and it is neutral on the bench.

## Hypothesis
Most failing runs (44 of 50 "not representable" on v2.1) run away only when the grader feeds the
truth's outside inflows. The outside inflow was attributed to the wrong stocks, or a drain absorbed
it. The main lever is to decide which stocks receive an outside inflow, and to estimate drains so
that they do not absorb it.

## What the data said first
On the main line's chosen models (31 default runs), the rows the grader makes run away all share one
signature. Fed true inflows that their drains cannot balance, they run away. A row with **no or a
small inflow and a collapsed drain** where the truth has a matched in/out pair:

- sd-bakery orders: 0 found against 40.7 true in, drain 0.6 against 40.7 per step;
- sd-cloud-credits credits: 0 against 8.3;
- sd-support-tiers customers: 4.5 against 26, and new_tickets: 0 against 59;
- sd-print-shop mono_queue: 41 against 219, and colour_queue: 3.7 against 54;
- sd-sawmill lumber: 0 against 11.5;
- sd-clinic-doses waiting: 17 against 46;
- sd-fishery juveniles; sd-moderation creators.

The opposite also shows up: rows with a spurious pair (inflow pieces and a drain both too big), for
example sd-ev-fleet queue (21 against 1.2), sd-sawmill sharpness (35 against 5.8), and
sd-support-tiers engineering.

**Counting noise identifies both.** Every ground-truth example moves whole things (Poisson flows,
variance = mean). So the robust variance of a row's one-step residual is the stock's *gross*
throughput: everything in plus everything out. Compare it with what the row's terms imply,
|inflow| + sum |k| x level, as `z` = the robust variance of residual / sqrt(gross):

- Rows that are right give z ≈ 1 (sawmill rows, hospital, cloud-credits queued 1.7).
- z > 4 ("missing") flagged orders 284, credits 54, creators 70, children 28, energy 26,
  finished 15, doses 12, juveniles 6.6, minutes 5.9, mono_queue 4.9, waiting 4.6, customers 4.3.
  Almost every one is a true misattribution.
- z < 0.25 ("spurious") flagged ev-fleet queue 0.05, sharpness 0.12, engineering 0.13,
  yeast 0.19, and others.

**Why the drain collapses (sd-bakery orders):** a pooled one-step fit is ruled by the few stretches
where the level moves most. These are the pile-ups when flour runs out: orders climb 300 -> 700 at
+20 an hour while the row says they should fall. Changing arrivals (40/55/30) add between-piece
variation with slope 0. Pooled: k = 0.009. On flour > 60: 0.19. Fits on 20- to 60-step stretches
with their own intercept: 0.34-0.67. Median over 25-step stretches: 0.48 (truth 0.5).

## What was built
- `sdlab/discovery/counting.py`: `gross`, `robust_var` (MAD²), `ratio` (z), `verdict`.
- `sdlab/discovery/stretches.py`: `stretch_fit(y, X, length=25, own=...)`.
  - Each column's number is the weighted median of OLS fits within fixed stretches (own intercept
    each; stretch length >= 6 x (columns + 1)).
  - Stretches whose residual variance is far above the throughput the row implies there (counting
    noise, relative to the run's median; bisquare at 4x) are left out.
  - The stock's own number gets the short-sample (Hurwicz/Kendall) correction: phi is found low by
    (1 + 3 phi)/n. Without it the drain came out 0.60-0.62 instead of 0.5.
- `sdlab/discovery/partial.py`: `partial_error`. The row is simulated alone for 20 steps from ~80
  starts, with the other levels fed in as measured and floored at 0. The error is the median over
  starts relative to holding the level (robust to the few capped stretches).
- `sdlab/discovery/attribution.py`:
  1. `diagnose` gives z and the partial error per row.
  2. `refit` takes the row's levels plus its own as a drain (unless `final`). It measures them by
     `stretch_fit`, clips a positive own number to 0, then recovers the inflow **with the numbers
     held**: none, constant or PELT pieces by BIC. Pieces need a mean clear of its standard error.
  3. `repair` refits a flagged row and replaces it if the refit is closer to z = 1. With
     `accept="strict"` (the default) the refit must also no longer be flagged (0.25 <= z <= 4), and
     its partial error may be at most 0.1 above the old row's.
  4. `to_flows` reads the flows back as `identify_one` does, including eras.
- Strategy `inflow_attribution`:
  - Every variant of `identify()` is fitted. Its rows are repaired. The repaired candidate replaces
    the original whenever a row changed (originals stay when nothing is flagged). The judge chooses.
  - Ablations: `inflow_attribution_both` (originals kept beside the repaired) and
    `inflow_attribution_refine` (only the main line's chosen model, repaired; the judge keeps it or
    not).
- **Matrix option `pieces_gate`** (default unchanged), strategy `pieces_gate`; see below.

## Mechanism test (`tests/test_strategy_inflow_attribution.py`, 6 tests, pass)
The model is a bakery: orders arrive from outside at 40/55/30 an hour (scheduled, repeating every 250
steps). They are baked at 0.5 x orders, using 0.5 kg of flour each. Flour is restocked toward 600 and
is slow now and then, so it runs out. 1000 steps, seed 2.

- **Main line:** orders row drain 0.004, no inflow, skill@20 -1128%.
- **Counting noise:** z > 20 on the main line's row. Control: the true row on flour-on-hand steps has
  0.5 < z < 2.
- **`stretch_fit`:** 0.5 ± 0.08 (0.49). Without the bias correction: faster by > 0.05. A pooled fit:
  > -0.1.
- **`refit`:** drain 0.49, mean inflow 68. The pieces also carry the pile-ups; the mean > 30.
- **Strategy:** orders drain 0.49, skill@20 +54% (> main line + 100 points).
- **Control:** a plain in/out stock (20 in, 0.4 out) is not flagged, and the strategy returns the
  main line's choice and numbers.
- Across seeds 1-3 and with a stale-bread stock added, the strategy's skill@20 is 0.42-0.72 in every
  case. The main line's is -12.4 to 0.61: it fails on half the draws.

## Bench (v2.1 baseline: 29.6% / 29.3% / 12 of 62; `--jobs 3 --seeds 2`)

| strategy | skill@20 | skill@100 | goal | fresh @20 / @100 | seeds' mean @20 | better / worse @20 | Wilcoxon @20 / @100 |
|---|---|---|---|---|---|---|---|
| `inflow_attribution` (strict accept) | **33.4% (+3.8)** | **36.3% (+7.0)** | 12 | 32.5% / 36.5% | 29.3% ± 4.9 | 4 / 1 | p = 0.19 / 0.0625 (sign 0.375 / 0.0625) |
| `inflow_attribution` (first cut: any z improvement) | 33.2% (+3.6) | 36.9% (+7.6) | 12 | 32.5% / 37.3% | 29.0% ± 4.7 | 7 / 4 | p = 0.41 / 0.13 |
| `inflow_attribution_refine` | 32.7% (+3.0) | 32.8% (+3.5) | 12 | 31.8% / 33.1% | 28.1% ± 5.2 | 2 / 1 | p = 0.5 / 0.25 |
| `pieces_gate` (matrix option) | 30.0% (+0.4) | 30.0% (+0.7) | 12 | 29.3% / 30.4% | 25.2% ± 6.0 | 2 / 3 | p = 0.81 / 0.84 |

Failure classes are unchanged (44 not representable, 1 not chosen, 5 not supported) in every row.
The main line's seed mean, measured through `pieces_gate` (identical except 5 runs), is 25.2%. So the
strategy's +4 points also holds on fresh discovery draws.

`inflow_attribution` (strict), runs moving > 2 points at skill@20 (@100 in brackets):

| run | skill@20 v2.1 -> now | skill@100 v2.1 -> now | what changed |
|---|---|---|---|
| sd-bakery default | -1170 -> **54.8** | -10328 -> 73.4 | orders z 284 -> 1.1; drain 0.58 |
| sd-bakery long | 18.8 -> **52.6** | -1650 -> 73.5 | |
| sd-cloud-credits default | -859 -> -152 | -1648 -> -171 | queued z 17.5 -> 1.1 |
| sd-print-shop default | -529 -> -358 | -2305 -> -1216 | mono_queue z 4.9 -> 3.6 |
| sd-support-tiers default | -548 -> -419 | -1574 -> -1183 | |
| sd-fishery default | 2.8 -> 16.7 | -102 -> -57 | |
| sd-fishery long | -18.5 -> **40.1** | -142 -> -90 | juveniles z 4.3 -> 1.3 |
| sd-moderation default | -67 -> -93 (worse) | -172 -> -70 | creators z 70 -> 0.36; appeals 4.4 -> 1.2: the creators' quitting also depends on flagged posts, which the row does not read |

The first cut (any improvement in z) lost sd-ci long (-39), sd-clinic-doses long (-720) and
sd-ev-fleet default (-35). In those runs a spurious-flagged row (a small, rarely moving stock with
many columns) was refitted to all zeros: z moved from 0.03 to 4.4 and the partial error from 0.2 to
1.0. The strict acceptance removed all three losses and kept every gain except part of sd-fishery
long (75 -> 40).

Zero-delta check: `matrix` on `--examples sd-saas,sd-eras,sd-pipeline --lengths default --baseline
v2.1` shows 3 of 3 the same.

Run time: about the main line's, plus one row refit per flagged row (the full bench with 2 seeds
took ~10 min at 3 workers).

## The pieces gate (matrix form choice): a real flaw, neutral on the bench
**Lead:** from row crossover. **Traced:** `matrix.fit_row`'s last step (none / constant / pieces) for
sd-bakery orders.

- After 5 passes the row has 17 pieces and drain 0.043. BIC: none 5831, constant 5836, **pieces
  4833**.
- The pieces are still refused, because "pick is none and |mean of piece values| <= 0.5 x their
  spread". The mean is 5.75 and the spread is 15.9, inflated by four short pile-up pieces (+30 to +56)
  and four recovery pieces (-46 to -51).
- So a row that BIC prefers by 1000 falls back to "none". The drain is then refitted *without an
  intercept* (0.0046), which is the random walk the row-crossover experiment saw.

**Option:** `opts["pieces_gate"] = "noise"` tests the mean against its own standard error from the
steps' noise (2 x sqrt(rss/T)/sqrt(T)) instead of against the pieces' spread. Default unchanged.

**Results:**
- sd-bakery default: orders gets its 17 pieces and drain 0.062. Skill@20 -1170% -> -243%, @100
  -10328% -> -212%.
- sd-cloud-credits default: +192 @20.
- sd-support-tiers long: +22.6 @20, +41 @100. Default: -4.1.
- The headline does not move (+0.4 / +0.7, p = 0.8), because clipped runs stay below -100% and the
  drain is still biased (pieces of 5+ steps; the Hurwicz bias again).

**Verdict:** the gate is a genuine flaw (it vetoes on the spread that a changing inflow is supposed
to have), but fixing it alone does not fix behaviour. Fold it into a combination with drains measured
as here. Test: `test_pieces_gate_keeps_the_changing_inflow`.

## Lessons
- The variance of a row's residual is information the main line throws away. Under counting noise it
  measures gross throughput, which tells a matched in/out pair from nothing, and a goal-seeking
  inflow (one flow: variance c - kx) from a constant in plus a proportional out (two flows:
  c + kx). It flags the misattributed rows almost without false alarms. The exceptions are pulsed
  inputs (clinic doses), unit-converting flows and co-flows (per² scaling), and stocks that rarely
  move.
- Drains need **local** estimation. Pooled fits are ruled by capped stretches and by between-piece
  variation. PELT pieces of 5+ steps bias every drain the same way short stretches do (Hurwicz), so
  the main line's drains are fast wherever its pieces are fine. The control model (20 in, 0.4 out)
  gets 0.547 from the main line. That is the row-crossover "equilibrium stock" finding: pieces absorb
  the drain.
- The partial-model test is a useful acceptance check (it stopped the zero-row refits) but a poor
  flag. A row with a collapsed drain still tracks its stock alone (its own inflow pieces replay the
  data), and a correct linear row is wrong exactly in the capped stretches. Medians make it usable.
- The in-sample judge cannot see attribution errors: original candidates replay their own inflows
  well. Repaired candidates must *replace* the originals. `refine` (where the judge may keep the
  original) only helps where the main line's chosen variant was repaired. `_both` was built but not
  benched.

## Open ideas
- **Receivers:** after a drain is repaired, conservation should move the gain to the receiving row
  (bakery shelf still has +0.06 x orders and a spurious inflow of 25). Re-run `conserve` on the
  repaired rows.
- **Bias-corrected drains on the main line:** apply the Kendall correction (or stretch medians) to
  every row with fine pieces, not only flagged ones (the control's 0.547 -> 0.4).
- **Spurious rows:** offer the stepwise column selection again under stretches, rather than the old
  row's columns, so that a refit is not degenerate.
- **Combine with `pieces_gate`** and with [recession drains](recession-drains.md) and
  [starved co-flows](starved-coflows.md). The bakery orders pile-ups are a co-flow cap that a linear
  row cannot follow; z flags exactly those stretches.
- **A counting-noise likelihood** (weights 1/gross per step) in the main regression, and z as a judge
  term.
