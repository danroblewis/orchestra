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
