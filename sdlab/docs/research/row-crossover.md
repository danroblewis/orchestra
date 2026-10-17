# Assembling the model row by row from the candidates

**Status:** done (wave 4, benchmark v2.1)  
**Verdict:** needs a combination: +6.1 points at skill@20 and +13.4 at @100, in-sample and on fresh
runs alike. Every loss is a flexible row the in-data judge prefers, so it should run behind the
piece-proof judge or the behaviour-consistency gate.

## What was done
Branch `exp/row-crossover`, commit `525ac17` (worktree `.claude/worktrees/agent-a8971c3f1afe3d867`).
- `matrix.py`: the tail of `identify_one` (conservation, re-measuring, reading flows) is now
  `finish(rows, ctx, opts)`, with unchanged behaviour (zero deltas on saas, eras and pipeline default).
  Option `keep_rows` returns the rows as fitted, before conservation (only the chosen columns kept), and
  the context. Conservation reads a per-row `trust_receivers` when a row carries one.
- `crossover.py`: `Pool` holds every candidate's rows. A stock's gene is (candidate row, trust receivers
  or not); the trust setting only counts for rows with a changing inflow, and identical rows are merged.
  `assemble(mix)` runs `finish` on the mixture. A row with one set of numbers joins a model with eras by
  repeating its numbers. `crossover()` is the greedy search: start from the judge's pick, visit stocks
  worst first by partial-model error, take the best other gene for the stock, and keep it if the
  whole-model error falls by more than `margin`. Two sweeps; judge calls are cached.
- `partial.py`: partial-model error per stock (that stock simulated, the others reset to the data each
  step).
- Strategy `row_crossover`, with options `crossover_margin` (0.05), `crossover_sweeps` (2) and
  `crossover_judge` (any `(flows, stocks, run) -> error`, so a stricter judge can be dropped in).
  `chosen` lists each swap and its error ratio.

## Mechanism test
`tests/test_strategy_row_crossover.py`, 600 steps:
- Model: an inbox whose intake changes every 30 steps (40 to 100, drain 0.1), next to a bakery line
  (orders baked onto a shelf at 0.5, each loaf using 0.5 kg of flour restocked by a gap with a time of 80).
- `matrix`: the changing-inflow candidates run away on the bakery line (flour links traded against
  pieces). It picks "backward, constant inflows" whole, so the inbox loses its drain (< 0.02) and skill@20
  is about -370%.
- `row_crossover`: one swap, the inbox's row from a changing-inflow candidate. Drain about 0.12,
  skill@20 above 85% (seeds 1 and 3), above every whole candidate (best about 82%). Over seeds 1 to 6 it
  beat every whole candidate on 5.
- Control: the inbox alone (one candidate right everywhere) gives no swap and the same model.
- Invariant: assembling a candidate's own rows gives that candidate's flows exactly.

The brief's second subsystem, "a slow drain absorbed by pieces", does not work. With equilibrium or
slowly filling stores, `matrix` grades -6 to -900% (the changing row's drain is 0.15 to 0.2 against a
true 0.03) while the constant-inflow row is right. But the in-data judge rates the piece-absorbed row
as well as the right one, because its pieces track the data. No swap is made. That is the piece-proof
judge's problem, not the crossover's.

## Results (baseline v2.1: in-sample 29.6% / 29.3% / 12 of 62; fresh 28.9% / 29.7% / 12)
| margin | skill@20 | skill@100 | goal | fresh @20 / @100 / goal | time (summed) |
|---|---|---|---|---|---|
| 2% | 35.2% | 42.9% | 14 | 34.2% / 43.6% / 14 | 615 s |
| 10% | 35.6% | 40.3% | 12 | 34.7% / 40.9% / 12 | 905 s |
| **5% (default)** | **35.7%** | **42.7%** | **14** | **34.9% / 43.4% / 14** | 972 s (machine shared and loaded; per run about 1.5-2x `matrix`) |

At 5%, skill@20 (in-sample):

| example | v2.1 | row_crossover | rows swapped |
|---|---|---|---|
| sd-bakery default | -1170% | 48% | orders, stale |
| sd-fishery default | 3% | 94% (meets the goal) | 4 rows |
| sd-services default | 7% | 81% | 1 row |
| sd-brewery long | 66% | 87% | 1 row |
| sd-fishery long | -19% | 47% | 2 rows |
| sd-bakery long | 19% | 41% | 1 row |
| sd-services long | 35% | 55% | 1 row |
| sd-cloud-credits long | -17% | 3% | 1 row |
| sd-population default | 68% | 80% | 1 row |
| sd-orders default | 76% | 80% | 1 row |
| sd-manufacturing default | 65% | 68% | 2 rows |
| sd-restaurant default | 64% | 67% (@100 -14% -> 37%) | 2 rows |

- sd-farm-soil long @100 78% -> 84% (meets the goal). Gains at @100 only (still clipped at @20):
  clinic-doses (both lengths), print-shop default, sawmill long.
- Losses: **sd-webshop-stock default 61% -> -11%** (fresh 55% -> -26%), moderation default -67% ->
  -100%, moderation long @100 -10, learning-curve long -3, restaurant long @100 -8.
- Fresh runs follow in-sample everywhere, so the gains are not fitted to the run's own draws.
- Brief targets: bakery default, pipeline default (+6 at 2% only), clinic-doses long (@100 only) and
  learning-curve default (no swap). Emergency default: no swap.

## Where the judge is fooled
These are the swaps a stricter judge must stop.
- **sd-webshop-stock default** (x0.58). The packing row without pieces wins in-data at every horizon
  (errors 0.62/0.35/0.41 -> 0.41/0.18/0.20 at 5/20/100). The truth's pick rate is 0.6 x shelf/300 (an
  effect); the swapped row reads 0.21 x backlog.
- **sd-moderation default** (moderators x0.48, credits x0.70). In-data 3.3 -> 1.2 at 20 steps, graded
  -67% -> -100%.
- **sd-eras default**, at a 2% margin only. A 2.3% in-data "gain" swapped the era-split raw row for a
  plain one, and the grade fell from 96.5% to 36%. That is judge noise: the margin must exceed it, and a
  5% margin blocks this swap.

More choices per stock give flexible rows more chances against the in-data judge. This mechanism adds
exactly that flexibility, so it should be combined with the piece-proof judge or the
behaviour-consistency gate (`crossover_judge`) before it is adopted.

## Open ideas
- Combine with the piece-proof judge. It is the only way to reach the brief's "slow drain absorbed by
  pieces" case (equilibrium stores grade -6 to -900% on `matrix` today, with the right row in the pool).
- A judge-ties rule for swaps (see [judge-ties](judge-ties.md)): require the gain to exceed a bootstrap
  standard error, not a fixed margin.
- Genes beyond the 16 candidates: a per-stock "no pieces" row is already in the pool. A per-stock era
  split (instead of all or nothing) is not.
- Coverage (I1): the swaps show where the candidate pool already holds a better row. Fishery, services
  and bakery are pool-choice failures, not representation failures.
- `matrix` form-choice bug seen in sd-bakery default. In the changing-inflow candidates, orders ends
  with no inflow at all: after 14 pieces in the passes, the final form choice picks `none`, leaving
  -0.005 x orders, a near random walk. The cause is not yet traced. Worth a look in the main line.

## Why
identify() picks one whole candidate out of 16. Each candidate makes its choices globally: forward or
backward search, changing or constant inflows, trusting receivers or rows, eras or not. Different
stocks need different choices:
- sd-bakery default: the constant-inflows candidate grades 26.6% at skill@20 and the chosen
  changing-inflows candidate -1170%. The orders row should have no pieces; flour's should.
- sd-clinic-doses long: changing-inflow candidates grade -77% to -109%, the chosen one -347%.
- sd-pipeline default: the receiver's row holds the right move (0.32) while the source row, under
  constant inflows, has 0.11.

"Choose the inflow form per stock by behaviour" is an open idea of [change-price](change-price.md).
A greedy row swap reaches combinations no single candidate has, from candidates we already compute.
Wrapper feature selection and algorithm portfolios work the same way. Structure search (running) edits
flows; this recombines whole rows of the existing pool and needs no new generator.

## How it could be tried
- Strategy `row_crossover`: keep every variant's rows (coefficients per configuration, inflow pieces).
- Assemble a model from a choice of row per stock, re-run `conserve` and `read_flows` on the mixture,
  and judge it.
- Start from the judge's pick. Visit stocks in order of their partial-model error (each row simulated
  alone with the others measured; [partial-model-simulation](partial-model-simulation.md)), and try
  every other variant's row for that stock.
- Keep a swap only if the whole-model judge improves by more than a margin (2% relative). Two sweeps.
- Mechanism test: two independent subsystems in one model. One is an inbox whose intake changes every
  30 steps (needs changing inflows). The other is a slowly draining stock with a constant inflow, where
  pieces absorb the drain (needs constant). Baseline: the best whole candidate is right on one
  subsystem only. Strategy: rows from both, and skill@20 above either candidate's. Control: when one
  candidate is right everywhere, no swap.
- Run it behind the piece-proof judge (wave 3): more choices give flexible rows more chances to fool
  the in-data judge.
- Targets: sd-bakery default, sd-clinic-doses long, sd-pipeline default, sd-emergency default,
  sd-learning-curve default.

## Sources
Kohavi and John (1997) Artif. Intell. 97(1-2):273-324 (wrapper selection); Rice (1976) Advances in
Computers 15:65-118; Gomes and Selman (2001) Artif. Intell. 126(1-2):43-62 (portfolios);
[held-out-judge](held-out-judge.md) (oracle 78.3% vs 70.8% on v1); failure analysis in
[IDEAS-WAVE4](IDEAS-WAVE4.md).
