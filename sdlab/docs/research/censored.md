# Censored: floors and caps fitted in the form the engine steps them

**Status:** done (commit 3a0f24c; ladder, benchmark v2.1 and 100 generated models)  
**Verdict:** adopt as a final step after the main line's choice. It passes 024 and 025 in every variant,
and on the examples it adds +9.4 / +16.7 points at skill@20 / @100 (p = 0.004 / 0.04; 16 of 62 runs
meet the goal, against 12). It is neutral on generated models (+1.3 / -1.3). The floor rewrite is
needed for 024, but costs about 2-3 points on the benches by imitating effects and seasons.

Strategy: `censored` (`sdlab/discovery/strategies/censored/`), tests `tests/test_ladder_censored.py`.
Continues [floors-and-caps](floors-and-caps.md) and the idea in [censored-floors](censored-floors.md).

## Why every strategy failed 024 and 025

Every one of the 37 strategies failed both rungs in every variant. The scorer is not the cause. Both
true models are expressible in SD Lab's model format: `outside -> B = linear {c: 30, terms: [A: -0.25]}`
is floored at 0 by `desired_rate` and by `simulate.Model`, and a constant outflow is capped by the
level in `simulate.Model` as in the engine. `tests/test_ladder.py` checks that the true model passes
its own scoring on every case, and the found models below pass. The failures come from discovery.

**024-floor-binds** (`B` gets `30 - 0.25 A`, which binds at 0 while A > 120, a third to a half of
the steps). Two things go wrong:

1. **Reading flows from the matrix (`flows.read_flows`).** A negative off-diagonal number is always
   read as an outflow ("B drains faster when A is high"). A link `c + k A` with `k < 0` into B
   cannot come out of the matrix at all. matrix finds `B -> outside = 0.13 A`, a spurious part, and
   the link part is missing (recall 80%).
2. **A straight line through a kink.** The one-step row is linear, so the floored steps bend the
   numbers. The row's outside-inflow pieces copy the kink (13 pieces in none-short, 48 in
   counts-long, mean 15-26 instead of 30). The judge then prefers that model, because it replays
   each model's own pieces. `floors` has hinges off by default. With `hinges: true` it still finds
   no floor, because the hinges are chosen against rows that keep their inflow pieces, and the
   pieces have already absorbed the kink.

**025-runs-empty** (inflow 2 / 10, unannounced, and a constant demand of 7). While A holds stock,
only `u - D` moves it (+3, then -5). Inflow and demand cannot be told apart by any linear row.
They can only be separated on the emptied steps, where everything leaves and A ends holding exactly
what arrived (A sits at 2 = the inflow). matrix's row finds 5 net pieces (0, +8, +3, -5, 0), but
their mean is about 0. The "clearly one way" pieces gate drops them (also with
`pieces_gate = "noise"`), the constant loses to none by BIC, and the row is empty. No flows: recall
0%, skill@20 -285%. `floors`' cap EM needs a found outflow that wants more than the stock holds, and
there is none. `caps.shortfall` also skips stocks empty on more than half the steps.
`starved_coflows` looks for co-flows between two stocks, and 025 has one stock.

## What it does

`censored` takes the main line's chosen model (`identify`). Row by row, it offers rewrites of the
row's flows to and from outside, and keeps moves between measured stocks as they are:

- **Floor** (`floor.py`). The row's change, less the kept flows, is fitted as
  `a max(0, s (x_j - theta)) + b x_own + sum c_m x_m (+ const)`. Every reader j and side s is tried,
  with theta searched over x_j's 3-97% quantiles and then refined. The floor must bind on 3-97% of
  steps. The hinge must also beat the same row with x_j as a straight line by (1 + margin) log T,
  and as a cubic in x_j (a smooth bend, such as an effect or a delay, is not a floor). The result is
  read back as a floored `linear` rate into the stock (a > 0) or out of it (a < 0).
- **Cap** (`cap.py`). For a demand D and own drain d on a grid, the outside inflow is what the row
  says arrived: `u_t = change_t - moves in_t + min(level_t, D + d level_t + other outflows wanted_t)`.
  It is cut into pieces by PELT and scored by BIC (one value and one cut per piece). The grid is
  coarse, then finer around the best point, then refined by Nelder-Mead with the cuts held. A cap is
  kept only if it beats the best D = 0 fit by margin x log T and binds on at least max(5, 2% of)
  steps.
- **Re-cut** (option `recut`, on). The best D = 0 fit from the same profile: the outside inflow's
  pieces priced at 2 log n x the noise variance, instead of the main line's 1 (which cuts pure
  counting noise into 23-43 pieces in 002 counts-long), with the own drain profiled, then refined
  continuously. The drain may only stay or fall relative to the main line's. On a stock whose level
  barely moves, a larger drain and a larger inflow trade off almost freely, and the pair grows into
  a runaway (generated models 14, 63).
- **Link** (option `links`, on). A row that the main line reads as "drains faster when x_j is high",
  beside a constant outside inflow, is offered as one inflow `c + k x_j` with k < 0. That inflow is
  floored at 0, never capped by the row's level. This is a goal gap's true form (047-random-goal-gap:
  E -> P). It may replace the row's inflow pieces only when they are effectively constant
  (spread < 5% of the mean). Otherwise the link is a level standing in for pieces (generated model 45).
- No rewrite may add self-growth (a positive own-level term) that the main line's row did not have.
  Refitted alone, an own term cancels the drains that conservation set, and the model runs away
  (generated model 22).

A rewrite is accepted when the **whole model's one-step BIC** improves by more than 2 log T. The BIC
is computed in the engine's form: `simulate.Model.change` applies every floor and cap, and the
residual has a floor of about 1e-4 per step, since levels are recorded to 4 decimals. Per row, the 1%
of steps where the main line's residual is largest are left out of every comparison (`trim`).
Without this, a Gaussian BIC lets a few one-step inflow spikes decide (generated model 14: 100% ->
-100%). Own-level hinges (`own_floors`) are off: they imitate delays, cycles and effects (015, 021,
sd-orders, sd-cloud-credits), and turning them off gained 2.4 points on the examples. Rows are
visited twice. The judge guard (`judge_slack`) is off by default. The main line's judge replays
each model's own pieces, so it rates the main line's many pieces better than true rewrites: 013
counts-short goes fail -> pass with judge error 2.15x, 002 counts-long 1.49x, 024 counts-long 1.33x.

Options: `margin` 2, `floors`, `caps`, `recut`, `links` (all on), `own_floors` off, `trim` 0.01,
`pelt_mult` 2, `passes` 2, `bend` 0 (the hinge's required margin over the cubic, in log T),
`floor_margin` (the floor's own margin; default `margin`), `judge_slack` None.

## Ladder results (P pass, E equivalent, F fail; none-short, none-long, counts-short, counts-long)

Commit 3a0f24c, `uv run sdlab-ladder status --strategies censored,matrix` (2026-10-19). matrix's
results date from earlier in the day, and the board marks them stale after a ladder hashing change.
The shared discovery code is unchanged in git, so they still describe matrix.

| case | matrix | censored |
|---|---|---|
| 001-inflow-only | PPPP | PPPP |
| 002-inflow-outflow | PPPF | PPPP |
| 003-chain-2 | PPPP | PPPP |
| 004-chain-3 | PPFP | PPFP |
| 005-chain-4 | PPFP | PPFP |
| 006-chain-exit-middle | PPFF | PPEP |
| 007-link | EEFF | EEFE |
| 008-link-loop | EEFF | EEEE |
| 009-births-and-deaths | EEEF | EEEE |
| 010-loop-branch | EEFF | EEFF |
| 011-goal-gap | EEFE | EEFF |
| 012-rework | PPFP | PPPP |
| 013-merge | PPFF | PPPF |
| 014-split | PPFF | PPPP |
| 015-hidden-stock | FFFF | FFFF |
| 016-coflow | EEFF | EEEE |
| 017-linear-effect | FFFF | FFFF |
| 018-table-effect | FFFF | FFFF |
| 019-announced-era | FPFP | FPFP |
| 020-unannounced-step | PPFP | PPFP |
| 021-daily-inflow | FFFF | FFFF |
| 022-pulse | FFFF | FFFF |
| 023-injection | PPPP | PPPP |
| **024-floor-binds** | FFFF | **PPPP** |
| **025-runs-empty** | FFFF | **PPPP** |
| 026-hidden-stock-driven | FFFF | FFFF |

On 024 and 025 every found model has the truth's complexity (`show`: "1.00x the truth"). The one
exception is 025 counts-short, with 3 extra inflow pieces (1.5x). Its parts: 024 counts-long link
30.13 - 0.259 A (true 30 - 0.25 A); 025 counts-long demand 7.10 (true 7).

On the whole ladder at that time (180 cases, 720 cells), censored has 442 pass, 134 equivalent and
144 fail; matrix has 345 / 116 / 259. 131 cells are better and 2 are worse:

- 011-goal-gap counts-long, E -> F. The link's slope is -0.237 against the true -0.2. matrix's
  equivalent form had 0.2246.
- 048-random-stepping-inflow-drain#2 counts-long, P -> F. The re-cut drain is 0.0489 against 0.0442,
  which is 10.6%, just outside the 10% tolerance.

Ablations (my harness, earlier commits): floors and caps alone give exactly matrix's ladder except 024
(PPPF) and 025 (PPPP). The re-cut adds 002, 006, 012, 013, 014 and 016 (counts) and 024
counts-long. Links add the 047 goal gaps.

## Bench results

Single-threaded, `--jobs 3`. Each was compared with a matrix run on the same day and the same shared
code (`matrix reference for censored 78def87`; the examples run equals the saved v2.1 baseline
exactly).

| bench | matrix skill@20 / @100, goal | censored (3a0f24c) | paired |
|---|---|---|---|
| examples (31 x 2) | 29.6% / 29.3%, 12 of 62 | **39.0% / 46.0%**, 16 of 62 (fresh 37.1% / 46.4%, 16) | @20 27 better / 9 worse, p = 0.004; @100 27 / 13, p = 0.04 |
| generated (100 x 2) | -52.4% / -48.1%, 7 of 200, parts 71.9% | -51.1% / -49.4%, 6 of 200, parts 71.3% | @20 49 / 26, +1.3, p = 0.01; @100 37 / 30, -1.3, p = 0.46 |

Examples, gains: sd-bakery (+145 / +54), sd-services (+90 / +62), sd-emergency default (+59),
sd-fishery (+37 / +55), sd-ev-fleet long (+42), sd-print-shop default (+42). Losses: sd-cloud-credits
long (-74), sd-kanban long (-23), sd-orders default (-6), sd-population long (-4), sd-manufacturing
long (-2.5). Generated, by motif (skill@20): cap -39.5% (matrix -47.4%), floor -46.5% (-53.7%),
goal_gap -40.2% (-39.8%), inflow_spikes -42.2% (-44.2%), inflow_steps -47.7% (-47.0%).

Ablations of skill@20 on both benches (my harness, which reproduces the official numbers exactly):

| variant | examples | generated @20 / @100 |
|---|---|---|
| matrix | 29.6% | -52.4% / -48.1% |
| caps only | 32.7% | -51.6% / -47.9% |
| re-cut only (before trim) | 39.4% | -56.6% / -49.1% |
| caps + re-cut (before trim) | 40.3% | -56.0% / -49.7% |
| everything, before trim / drain cap / own floors off | 34.8% | -58.3% / -55.9% |
| final without floors (trim, drain cap) | 39.4% | -49.1% / -47.3% |
| final (3a0f24c) | 39.0% | -51.1% / -49.4% |

Run time: ladder discovery 623 s summed over 720 cells (matrix 296 s). On examples, up to 108 s
for sd-services long (36,000 steps). The cost is PELT inside the demand profile and the whole-model
one-step BIC per candidate.

## Measured inputs (2026-10-19, commit 89adae4)

**Bug:** the one-step BIC, the cap's came/wanted and the judge stepped models with `Model(flows, ids)`,
without `opts["inputs"]`, so the matrix's flow k x input moved nothing there. The rewrites then
re-explained the input's effect (pieces, a demand, a drain) while the input flow stayed in the
model: the input counted twice (062 none-long: a 43-per-step demand against 43 in pieces next to
2 x pump; phys-newton-cooling none-long skill@20 -113% on the run it saw).
**Fix:** every simulation is stepped with the inputs (`onestep.model_inputs`); a floor or link
rewrite that replaces a flow on an input refits the input as a column beside the hinge (written back
marked `input`); the cap keeps a row's input flows and counts them in what arrived or was wanted;
the judge (`judge_slack`) is a local copy of identify.judge with inputs.

Before -> after on the cases with measured inputs (variants in the order shown; skill@20 on the run
it saw, none-long):

| case | variants | before | after | skill@20 none-long |
|---|---|---|---|---|
| 062-tank-fed-by-measured-pump | counts-long / counts-short / none-long / none-short | F P F F | P P P P | -16.60 -> 1.00 |
| 105-canonical-inventory-supply-line | counts-long / counts-short / none-long / none-short | F F F F | F F F F | 1.00 -> 1.00 |
| 106-canonical-workforce | counts-long / counts-short / none-long / none-short | F F F F | F F F F | 1.00 -> 1.00 |
| 110-canonical-world3-pollution | counts-long / counts-short / none-long / none-short | F F F F | F F F F | 0.97 -> 0.97 |
| phys-coupled-tanks | meas-long / meas-short / none-long / none-short | F F F F | F F P F | -23.03 -> 0.99 |
| phys-draining-tank | meas-long / meas-short / none-long / none-short | P P F F | P P F P | -25.86 -> 1.00 |
| phys-mass-spring-damper | meas-long / meas-short / none-long / none-short | F F F F | F F P P | -4.69 -> 1.00 |
| phys-newton-cooling | meas-long / meas-short / none-long / none-short | F F F F | P P P P | -1.13 -> 1.00 |
| phys-thermostat | meas-long / meas-short / none-long / none-short | F F F F | F F F F | -24.89 -> 1.00 |

105, 106 and 110 (canonical models whose input drives hidden delay stocks) fail before and after, as
for matrix, lna and combined. phys-thermostat fails its structure for every strategy (the closed loop
all but hides the outside's coupling; its own reference fails), though its skill rose. phys-draining-tank none-long still fails structure (matrix passes it): the cap reads the sqrt drain as a constant demand capped by the level, beside inflow pieces; it predicts better (0.9999 vs 0.98) but has no H <- H coupling. That is the cap's method, not the inputs.

**Cells without inputs:** every (case, variant) without a measured input was run before (parent of
`89adae4`) and after, each from an exported copy of the package that differs only in this strategy's
files, single-threaded: 1074 of 1074 cells gave byte-identical flows and the same status, the 62 realistic sd-* cells among them; none timed out
(script and outputs: the agent's scratchpad `inp/cells.py`, `cmp.py`, `old.jsonl`, `new.jsonl`).

## Open ideas

- **Floors with inflow pieces.** The floor rewrite either drops the row's pieces or keeps them
  fixed. A joint fit (hinge + pieces re-cut) would cover a floored link into a stock that also has a
  changing outside inflow.
- **Caps for stocks with several outflows to measured stocks.** The cap profile counts moves out as
  wanted, but keeps their numbers fixed. An EM over the receivers' rows (as in `caps.py`, but with D
  free) would fit them too.
- **The cubic test is weak on short noisy runs.** In 024 counts-short a cubic in A comes within
  3 log-likelihood points of the hinge, because A sits on two plateaus. A required margin of 0 lets
  the true floor through. On the effect cases (017, 018), hinges still win over the cubic on some
  rows, imitating table effects. They do no harm on the ladder, since those cases fail anyway, but a
  floor that binds exactly at 0 (zero variance on the bound steps, under counts) would be a sharper
  test.
- **The re-cut's price (2 log n) should be on the main line.** It is what moves 002, 006, 012, 013,
  014 and 016 (counts) to pass or equivalent, and most of the examples' gain. It is a pieces-pricing
  fix, independent of floors and caps.
- **A sharper floor test.** False floors clear even a 6 log T margin over the line
  (`floor_margin` 5 changed nothing on the benches). A floor that binds exactly at 0 leaves the
  bound steps with the rest of the row only (under counting noise, with less variance), and a test
  on that would separate it from an effect curve.
- **Without floors the strategy is better on both benches** (39.4% examples, -49.1% / -47.3%
  generated). Floors are kept on only because 024 needs them. A combined strategy could offer them
  as a candidate that a likelihood judge weighs (`combined`).

## A floored gap to a target (2026-10-19, commits deb1ffc and 6ca61d5)

**Why every strategy failed 125-floored-gap-to-measured-target** (hiring `(desired - R) / 6`, floored
at 0 when the measured target drops below R, beside a drain `0.025 R`; distilled from
106-canonical-workforce). While the gap is open the row is a straight line, `k desired - (k + d) R`,
and the gap's own-level term and the drain add up to one number. Only the steps where the floor
binds (the target fell below R, 3-6% of steps) separate them. The main line reads `0.12 desired`
and a drain `0.14 R` (counts), or a drain and 41-112 inflow pieces (noise-free). The floor rewrite
(`floor.py`) reads one level at a time, and own-level hinges are off.

**What was added** (`gap.py`, option `gaps`, on). For each row, a gap to a target
`max(0, a x_j - b x_own - sum b_m x_m (+ c))` beside a drain `e x_own`, fitted by nonlinear least
squares from the straight line's numbers, the own term split between the gap and the drain at six
ratios, with and without a constant (BIC), then refitted once with the steps weighted by their noise
when it grows with what the flows move (counting noise). Targets are the other levels and the
measured inputs whose number in the straight row is clearly positive (t > 2; the three clearest).
`x_m` are the other stocks the main line's row read (106's hiring reads Rookies and Experts). It is
offered when the floor binds on 3-97% of steps, the gap closes (a > 0, b > 0), the drain is not
negative and the kink beats the straight line by (1 + margin) log T; the whole-model one-step BIC
decides as for every rewrite.

**Results** (`uv run sdlab-ladder run --strategies censored --jobs 2 --timeout 300`, single-threaded,
the whole ladder at 6ca61d5, strategy hash a016216a, 1280 cells; before: the stored results of
the previous code, `uv run sdlab-ladder status --strategies censored`, read before the change):

| case | before (ns nl cs cl) | after |
|---|---|---|
| 125-floored-gap-to-measured-target | F F F F | P P E P |
| 106-canonical-workforce (the hard case) | F F F F | P P F P |

- 125 counts-short is the data's limit: 300 steps leave 6 binding steps; the kink gains 10.7 nats
  over the line (the bar is 17.1) and, forced, the drain comes out 0.036 (true 0.025).
- 106 counts-short: the same (short run, few binding steps).
- No cell that passed before fails now (`cmp.py`: every cell's result at a016216a against the
  previous stored result). The only errors are the timeouts on sd-k8s-small and sd-k8s-platform
  counts-long, which timed out before as well (1be97cd5, 08b55003).
- 124-gap-over-two-stocks (a gap with no floor) is unchanged (FFFF): without the floor binding the
  rewrite has nothing to read.

## Controllers: floors on a few steps, second inflows, exact integrals (2026-10-19, commits 2dee420 and a2d5e01)

**Why the leaders failed 218 and 216** (distilled from the control cases, docs/research/control-cases.md).
- **218** (a P controller `0.3 setpoint - 0.3 T`, floored on 10 of 2,000 steps; from 203, 209, 200).
  The floor binds on under 3% of steps, so `gap.py` never offered the gap, and the main line wrote a
  drain of 0.35 and `0.25 setpoint` plus a constant. **200** is the same controller beside a second
  inflow `0.05 outdoor`. The gap replaced every outside flow of the row, so the warming was lost.
  **203** has an outflow on an input as well (a hill's pull, `9.8 slope`). **209**'s main line had
  dropped the integral I from V's row, so the gap could not read it.
- **216** (a noise-free integral `dI = r - Y` among counted stocks; from 214, 202, 207). I's row
  is exact, but the main line wrote its inflow as a constant at r's mean, or as 112 pieces that
  replay the square wave. Under counting noise the controller's straight row also came out biased
  (214 counts: `0.23 setpoint`, a drain of 0.33 and `0.019 I`, against `0.2 / 0.25 / 0.01`).

**What was added** (options are on by default):
- `gap_few` (1): a gap is also offered when the floor binds on as few as this many steps. The BIC has
  to earn it, at `gap_margin` (1.0) x log T: the gap nests the straight row and adds one number.
  A long run is fitted on every m-th step plus the steps where the floor binds.
- `gap_side`: the other columns the row's outside flows read (inputs and levels) are fitted as
  unfloored flows beside the hinge. A positive number is an inflow and a negative one an outflow
  reading the column.
- In models of up to `gap_extra_upto` (3) stocks, the gap may also read one other stock that the
  main line's row did not read. On sd-moderation's 8 stocks these extra fits took 680 s.
- `gap_lines`: the straight row through the same columns (one inflow, plus the own term as a drain)
  is offered too, at the normal margin. This covers rows where the floor is not earned but the main
  line's row is worse than the straight one (214 counts).
- `exact` (`exact.py`): a row's change, less its moves, is regressed on every level, every input
  and a constant. If that fit is exact (residual at most 4x the rounding floor), the unneeded
  columns are dropped one at a time and the row is written as one flow per column, at margin 0
  (exact to rounding, the fewer numbers win). Exactness is read only from the data.

**Results** (`uv run sdlab-ladder run --strategies censored --jobs 2 --timeout 300`, single-threaded,
the whole ladder at a2d5e01, strategy hash df1e6882, 1380 cells in 1919 s; before: the stored
results of the previous code, read from `sdlab.ladder.store.latest(strategy="censored")` just before):

| case (ns nl cs cl) | before | after |
|---|---|---|
| 218-distilled-controller-floored-on-few-steps | not run (matrix F F E E) | P P E E |
| 216-distilled-exact-integral-fed-by-stepping-input | not run (matrix F E F F) | E E E E |
| 200-control-p-room-heater (218's hard case) | F F E F | P P E P |
| 203-control-cruise-on-hills (hard case) | F F F F | F P F P |
| 209-control-cruise-windup-downhill (hard case) | F F F F | F P F P |
| 214-control-closed-loop-id-steps (216's hard case) | E E F F | E E E E |
| 202-control-pid-two-tanks | E E F F | E E F E |
| 207-control-cascade-two-tanks | F F F F | F P F P |
| 201, 204 | - | 201 none-long, 204 none-short and none-long F -> P |

- **What the data allow** (`sdlab-ladder analyse`): 216 none is unidentifiable, because the
  controller's `-0.1 Y` and the drain add up without a floor, so equivalent is the best possible
  answer there. 216 counts-short is data-limited (p 0.14). 203 and 209 none-short are unidentifiable,
  because the setpoint does not move within 300 steps. On 218 counts the floored steps gain only
  3.5 nats over the straight row, so the split is not earned and equivalent is the honest answer.
  The fit there is right (0.278 / -0.273 / 0.052) but is not accepted.
- **Paired against the stored results** (1362 cells): 33 better, none worse from the code. 59 cells
  went from equivalent to fail with identical found flows: these are scorer changes made by others
  between the two runs (score hash 5fbaad97 -> ebf409cc), on 017, 018, 103, 109, 126, 127, 130, 131,
  136-139, 160, 171, the Gause twins and part-reacting-particles. Two cells changed their flows and
  went from equivalent to fail: 171 counts-long and part-reacting-particles counts-long. Under the
  current scorer the old flows fail as well, so they are not losses. The earlier run at 2dee420 timed
  out sd-moderation, sd-services and sd-bakery counts-long. At a2d5e01 only the timeout that was
  already there before remains.
- Beside the control cases, 16 further cells are better (010, 030, 043#6/#7, 045#3, 049#1, 054#1/#3,
  055#5-#7, 058, 082 bias-short, 087 meas-long). These come mostly from the exact rows and the
  straight rows.

**What remains:** the short control runs (the setpoint does not move: the data's limit), 201 and 211
short and counts, 204 counts-long and 106 counts-short.

## The declared boundary (2026-10-20)

Outside flows only where the case declares them (own copy of matrix/boundary.py, wired into this
strategy's search): see [declared-boundary-six.md](declared-boundary-six.md) for the hooks and the paired results.
