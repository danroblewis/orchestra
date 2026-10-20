# Inflow effects: an outside inflow that is a base times a table of a stock's level

**Status:** done for this round (distilled 160 and 217, whole ladder; commits 62c6c1d-0c7a76b, guards 5498259)  
**Verdict:** keep as a specialist for inflows that carry an effect: 160 and 217 pass noise-free (every strategy failed both), 14 cells better and 3 worse than effect_hats on 1,404 paired; the hard cases improve in behaviour but not in status

Strategy: `inflow_effects` (`sdlab/discovery/strategies/inflow_effects/`): a copy of `effect_hats`
(at commit 89adae4, CLAUDE.md invariant 11) plus `gate.py`.

## Why the leaders fail 160 and 217

- **160-effect-on-outside-inflow** (from sd-farm-soil: `grow = base x table(nitrogen)`). The field A
  grows by a schedule nobody announces (10 a step, 20 for 90 steps of every 300) times a table of
  nitrogen N, and every unit grown uses 0.4 N; N is restocked by its gap `(150 - N) / 12`. effect_hats
  (none-long) writes a move `N -> A = 0.095 N`, 22 inflow pieces into A and 22 into N; structures is
  "equivalent" only because the grader reads its pieces-and-links model as the same levels (skill@20
  -531%). Neither has a way to say "a schedule times a curve": effect_hats' screen offers a stock or
  1 as the base of an effect, never a schedule, and the schedule's steps are bigger than the curve's
  bend, so the matrix's pieces take all of it.
- **217-distilled-input-gated-by-own-level** (from 212-control-admission-queue). Arrivals, a measured
  input, are let into the queue Q in full below 30, none above 40: `arrivals x table(Q)`, Q drained at
  `0.3 Q`. Every leader writes `k x arrivals` with k 0.3-0.9, a constant and a faster drain: the
  shared library's screens never multiply an input by a curve.

`sdlab-ladder analyse`: 217 is achievable in every variant (counts-short p 0.75, the gate's table
within 8% of its amount at the bound); 160 noise-free is achievable up to the gap's two equal
writings, and with counts it is data-limited (counts-long p 0.00: the gap's slope cannot be read
within tolerance; counts-short p 0.40).

## What it does

effect_hats' model; then, per stock R, its inflow is tried as `B(t) x f(C)` (`gate.py`):

- `B` is a measured input, or a schedule of a few values (`pieces`) that changes where the data say;
  `f` a table (tents over C, `basis.py`), C any stock, R included.
- Optionally the flow uses up another stock U as it arrives (a co-flow, `per` fitted), or runs from U
  (a move). U's schedule-like inflows (constants, pieces) and its gap become one `c + d x U`, only
  where the base had an outside inflow into U (otherwise the mirror reading, "U's inflow is the
  schedule and it uses R", fits as well under counting noise and invents an inflow).
- Every other flow of the base on R and U keeps its form and gets a scale; moves between R and U (the
  base's stand-ins for the co-flow) go.
- Fitting: the schedule's cuts come from R's row with a drain added back (`dy + k R` for k on a grid,
  the k whose pieces cost least on R's own row: a stock that settles fast shows a change in its level,
  not its change); free values between the cuts, then pooled into 1-4 values (BIC); alternating least
  squares (with B fixed everything else is linear; with f fixed the values are), then all numbers at
  once by Levenberg-Marquardt with an analytic Jacobian (alternation crawls along the ridge where the
  schedule and the curve trade). The cuts are read again from the fitted schedule (the curve divided
  out) and the fit repeated if that prices better; inner knots are moved where the curve bends.
- A screen (one knot count, no polishing) ranks every (R, C, base); the best two per row are fitted
  in full with every U. A reading is kept if it prices better than the base by 10 log T (one-step BIC,
  a table a number per point, a schedule one per value and per change, no row's error below its levels'
  rounding), beats the same flow written as a straight line in C by as much, leaves no stock without
  flows, and has no flow running backwards. Up to three rounds go on by price; the round returned is
  the one that behaves best on the multi-step judge, if no worse than the base.

## Results

All single-threaded, `--jobs 2`, `--timeout 300`. The whole ladder ran at 0c7a76b (1,404 cells);
the cells whose found model differed from effect_hats' (57 cases, 268 cells) ran again at 5498259,
and 160, 217 and 100-canonical-sir once more at 5498259. Paired with effect_hats' stored results,
re-run at its current code on every cell that differed (`sdlab.ladder.store.latest`).

| case | effect_hats | inflow_effects (5498259) |
|---|---|---|
| 160-effect-on-outside-inflow | F F F F | **P P** F F |
| 217-distilled-input-gated-by-own-level | F F F F | **P P** F **P** |

(none-short, none-long, counts-short, counts-long.) 160's counts variants are data-limited by
`sdlab-ladder analyse` (counts-long p 0.00, counts-short p 0.40: the gap's slope). 217 counts-short
is achievable (p 0.75) and still fails: the gate is not earned on 300 counted steps.

**Whole ladder, paired on 1,404 cells:** 557 pass / 215 equivalent against 551 / 210; 14 better,
3 worse.
- Better: 160 ns, nl; 217 ns, nl, cl; 139-noisy-crowding cl; 196-concave-move-between-tanks ns;
  phys-coupled-tanks meas-short; 216 ns, cs (equivalent); four real-adoption twins (fail ->
  equivalent; different scorer hashes, so partly the scorer).
- Worse: 047-random-goal-gap#2, #3, #7 counts-long, equivalent -> fail. The gate writes P -> I as
  a constant times a table of P (or I's inflow using P), where the truth is a goal gap of P on I that
  neither strategy offers. Fresh skill@20 rises from -178% / -279% / -22% (effect_hats) to 99.7% /
  99.3% / 92.1%: a better-behaved model with the wrong parts.
- Two guards (5498259) removed two earlier losses: 100-canonical-sir none-long (the gate wrote
  I -> R as pieces x f(I), soaking up the misfit of S -> I's table through I's row; a reading must
  now earn its gain on the row whose inflow it rewrites) and 047#6 none-short (P -> I re-labelled as
  an inflow of I using 4e-5 P per unit; a co-flow must now use at least 5% of what its stock loses).
- Errors and timeouts: part-stirred-chambers counts errors (a harness KeyError, `stirred-chambers`
  missing from `systems.SYSTEMS`); sd-eras, sd-hospital, sd-moderation, sd-ev-fleet and
  sd-print-shop counts-long time out at 300 s.

**Hard cases** (fresh skill@20 / @100):
- sd-farm-soil: fail in both variants, but counts-short 95.1% / 62.1% -> 98.2% / 94.4%, counts-long
  95.6% / 64.4% -> 98.2% / 93.2%. The grow inflow is still not written as base x table(N).
- 212-control-admission-queue: fail in every variant; none-short now has every flow right (recall
  and precision 100%, 2 of 6 parts in tolerance). `analyse` calls none-long data-limited (p 0.00).

## What remains

- 217 counts-short and 160's counts variants (the latter data-limited).
- sd-farm-soil: the effect on the inflow carried back into behaviour, not into the parts.
- 212: two gated inflows (Q and Rejected) from one input, and a saturating move; the base model is
  too far off for one gate per round.
- 047 counts-long: a goal gap on another stock is not among the gate's readings, so a curve stands in.
