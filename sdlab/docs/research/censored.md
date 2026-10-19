# Censored: floors and caps fitted in the form the engine steps them

**Status:** done (ladder rungs 024 and 025; benchmark v2.1 and 100 generated models)  
**Verdict:** BENCH_VERDICT

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
  counting noise into 23-43 pieces in 002 counts-long), with the own drain profiled.

A rewrite is accepted when the **whole model's one-step BIC** improves by more than 2 log T. The BIC
is computed in the engine's form: `simulate.Model.change` applies every floor and cap, and the
residual has a floor of about 1e-4 per step, since levels are recorded to 4 decimals. Rows are
visited twice. The judge guard (`judge_slack`) is off by default. The main line's judge replays
each model's own pieces, so it rates the main line's many pieces better than true rewrites: 013
counts-short goes fail -> pass with judge error 2.15x, 002 counts-long 1.49x, 024 counts-long 1.33x.

Options: `margin` 2, `floors`, `caps`, `recut` (all on), `pelt_mult` 2, `passes` 2, `bend` 0 (the
hinge's required margin over the cubic, in log T), `judge_slack` None.

## Ladder results (P pass, E equivalent, F fail; none-short, none-long, counts-short, counts-long)

LADDER_TABLE

## Bench results

BENCH_RESULTS

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
  014 and 016 (counts) to pass or equivalent. It is a pieces-pricing fix, independent of floors and
  caps.
