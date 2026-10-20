# matrix_v2: the proposed matrix fixes, each a switch

**Status:** done (queue item 6). **Code:** `sdlab/discovery/strategies/matrix_v2/` (commits 87c485c ...
d8e1d85; defaults at d8e1d85). **Tests:** `tests/test_ladder_matrix_v2.py`. **Ablation script:**
`tests/study_matrix_v2.py` (results in `~/.sdlab/matrix_v2_ablation/<run>.jsonl`).
**Verdict:** adopt as the main line's successor: tests 585 pass + 207 equivalent of 1150 against
matrix's 390 + 146 (287 cells better, 8 worse), realistic skill@20 36.7% against 31.0% with 21 of 64
goals against 12, and the examples bench +6.8 points at skill@20 (Wilcoxon p = 0.007). It still
trails the composite leaders on the tests (structures 757 pass, kalman_lna 755) and on strict.

## What it is

The shared matrix method (`identify.py`, `matrix.py`, `flows.py`, `regression.py`, `changes.py`) is
pinned (CLAUDE.md invariant 11), so the package carries copies taken at aad5c7b (matrix.py last changed
in cb97c26), trimmed to the paths `identify` reaches, and changes only the copies. With every option
off it gives the matrix's flows exactly (checked on 48 cells, and by
`test_every_option_off_is_the_matrix`). It imports no other strategy; code taken from one is copied
and its source and commit noted.

| option | fix | from | default |
|---|---|---|---|
| `rss_floor` | every BIC's rss floored at the data's rounding (T q^2 / 6) | earned_pieces | on |
| `exact` | rss and PELT's noise variance floored at float precision (1e-8 T x mean square change); an exact fit walked along exact ties to the plainest set (fewest columns, fewest other stocks, own stock first) | common_cause (proper copy of its runtime patch) | on |
| `pelt_mult` 2 | inflow changes priced at 2 log n | censored | off |
| `white` | a constant inflow kept unless its residuals are not white (Ljung-Box) | earned_pieces | off |
| `pool` (+`pool_white`) | pieces pooled into 1-4 values, re-cut by Viterbi (a change 2 log T), drain fitted without the steps beside a change; kept if it prices better than the pieces and (pool_white) leaves white residuals | effect_hats | on |
| `tie_se` | conservation tie tested with both rows' standard errors, z^2 <= log T, for rows whose inflow does not change; receivers are rows that gain | earned_pieces | on |
| `falling_inflow` (+`fold_strict`) | a negative cross reading folded into the row's constant inflow, c - k a floored at 0; strict: only where it beats the drain reading by one BIC price on the engine's one-step fit | censored | on |
| `gap_inflow` | the row's links and inputs folded too (multi-stock gap as one floored linear inflow) | structures | off |
| `pair_moves` | a drain of s at a and a link into b at a (or the move read_flows gave a's own drain to b) read as one move s -> b at k a | effect_hats | on |
| `products` | columns a x c (c = a or the destination allowed); "after": offered only to the finished row at 3 log T; a candidate with products judged beside the same without (products_guard) | structures | after |
| `inputs_judge` | the variant judge steps candidates with the measured inputs | earned_pieces, censored | off |

## Ablation (every option alone, then combinations)

`OMP_NUM_THREADS=1 ... JOBS=2 uv run python tests/study_matrix_v2.py run <run> '<options>'`, then
`... table matrix <runs>` and `... diff matrix <run>` (2026-10-19). Each cell is scored exactly as
the ladder scores it (`runner.run_item`), nothing is stored. "matrix" is the shared strategy run by
the same script. Totals are over the cells matrix ran (the ladder grew during the day); "better /
worse" counts test cells whose status (pass > equivalent > fail) changed. Realistic: mean skill@20
over 64 runs (clipped at -100%), goals met; "not run" where the realistic set was not run for that
option. Code per row: rss_floor, pelt2, white, pool, falling, gap, products, inputs_judge 87c485c;
all 68848a4; exact, products_after, falling_strict, all2 80cf209; pair ced67dc; tie_se, d1b 298f027;
products_guarded, d1c cf9c4b6; pool_white, d1d d8e1d85. Superseded versions: tie_se v1 (the SE test
on every row: 3 better / 30 worse) and pair v1 (0 / 2).

| run | tests P+E (of) | noisy | canonical | distilled | physics P | realistic skill@20 / goals (err) | better / worse vs matrix |
|---|---|---|---|---|---|---|---|
| matrix | 390+146 (1150) | 36+3 (156) | 0+4 (48) | 12+11 (170) | 17 (44) | 31.0% / 12 of 64 (0) | 0 / 0 |
| rss_floor | 393+144 (1150) | 36+3 (156) | 0+4 (48) | 12+11 (170) | 17 (44) | not run | 3 / 2 |
| exact | 409+151 (1150) | 36+3 (156) | 0+4 (48) | 12+13 (170) | 17 (44) | not run | 24 / 0 |
| pelt2 | 499+204 (1150) | 42+11 (156) | 0+4 (48) | 13+13 (170) | 16 (44) | not run | 179 / 13 |
| white | 507+210 (1150) | 42+11 (156) | 0+4 (48) | 13+12 (170) | 17 (44) | not run | 192 / 12 |
| pool | 529+211 (1150) | 44+11 (156) | 0+4 (48) | 14+12 (170) | 17 (44) | 23.6% / 15 of 64 (0) | 211 / 9 |
| pool_white | 528+210 (1150) | 43+11 (156) | 0+4 (48) | 14+12 (170) | 17 (44) | 30.7% / 15 of 64 (0) | 208 / 8 |
| tie_se | 390+148 (1150) | 36+3 (156) | 0+4 (48) | 12+11 (170) | 17 (44) | not run | 2 / 0 |
| falling | 414+119 (1150) | 32+5 (156) | 0+4 (48) | 8+15 (170) | 17 (44) | not run | 28 / 7 |
| falling_strict | 416+117 (1150) | 36+1 (156) | 0+4 (48) | 12+11 (170) | 17 (44) | not run | 26 / 3 |
| gap | 414+119 (1150) | 32+5 (156) | 0+4 (48) | 8+15 (170) | 16 (44) | not run | 28 / 8 |
| pair | 390+146 (1150) | 36+3 (156) | 0+4 (48) | 12+11 (170) | 17 (44) | not run | 0 / 0 |
| products | 271+124 (1150) | 22+0 (156) | 7+6 (48) | 21+20 (170) | 18 (44) | not run | 38 / 178 |
| products_after | 392+158 (1150) | 35+3 (156) | 6+6 (48) | 19+21 (170) | 20 (44) | 11.9% / 12 of 64 (0) | 33 / 16 |
| products_guarded | 398+157 (1150) | 34+3 (156) | 6+6 (48) | 19+20 (170) | 18 (44) | 31.6% / 14 of 64 (0) | 28 / 8 |
| inputs_judge | 390+146 (1150) | 36+3 (156) | 0+4 (48) | 12+13 (170) | 16 (44) | not run | 4 / 5 |
| all | 356+152 (1150) | 20+9 (156) | 8+6 (48) | 18+26 (170) | 18 (44) | not run | 140 / 151 |
| all2 | 571+209 (1150) | 44+11 (156) | 7+6 (48) | 23+24 (170) | 20 (44) | not run | 287 / 17 |
| d1b | 590+207 (1150) | 45+11 (156) | 7+6 (48) | 24+24 (170) | 20 (44) | 10.0% / 14 of 64 (0) | 294 / 8 |
| d1c | 587+206 (1150) | 43+11 (156) | 6+6 (48) | 22+23 (170) | 18 (44) | 24.4% / 18 of 64 (0) | 288 / 8 |
| d1d | 585+207 (1150) | 42+11 (156) | 6+6 (48) | 22+23 (170) | 18 (44) | 36.7% / 21 of 64 (0) | 287 / 8 |

all = every option (products inline, falling not strict); all2 = every option with products "after",
fold_strict and exact; d1b = the defaults without the products guard and pool_white; d1c = with the
guard; d1d = the defaults (with pool_white).

## Which fixes help, which hurt, and where

- **pool** is most of the gain (211 cells; 002-006, 012-014, 039-053 counting variants): the chance
  pieces' drain bias (027) goes. Alone it cost realistic skill (31.0% -> 23.6%): a few values cannot
  follow an inflow that changes every 30 steps (sd-pipeline long 99% -> 44%). **pool_white** fixes that
  (30.7%, 15 goals, 208 better / 8 worse).
- **pelt_mult 2** and **white** each recover most of what pool does (179, 192) but miss real small
  steps (053 sweep-excitation, 059 small-inflow-step, 048#1); beside pool they add nothing the
  defaults need, so they are off.
- **exact**: 24 better, 0 worse (032, 034, 035, 038, 043, 049, 057, 058 noise-free; also 5 control cells
  under counts become equivalent).
- **falling_inflow**: the 047 goal gaps pass (26 cells). Without fold_strict it also rewrote 141/142's
  oscillator drains (pass -> equivalent: the two readings tie when no floor binds, and only the drain
  is the truth there). **gap_inflow** adds nothing beyond it and loses part-conveyor-bottleneck.
- **products**: inline it was a disaster (38 / 178: products stand in for levels and pieces on chains).
  Offered only to the finished row: 33 / 16, but realistic skill fell to 11.9% (runaway product loops:
  the judge's runs explode). With products_guard 28 / 8 and realistic 31.6%. Wins: 017, 101, 102, 103,
  126, 127, 136-139, 171, phys-lotka-volterra.
- **tie_se**: as proposed (every row) 30 cells lost: a row whose inflow is in pieces has its drain
  biased by the pieces beyond its standard error (040-random-chain-2#3: 0.435 +- 0.01 against the
  receiver's 0.353). Restricted to rows without changing inflow: 2 better, 0 worse.
- **pair_moves**: neutral alone (0 / 0) after the fix for 152 (the first version paired the link left
  over after read_flows gave S's drain to B, 3.875 for 4).
- **inputs_judge**: 4 / 5 (loses part-conveyor-bottleneck and three control cells); off.
- **rss_floor**: 3 / 2 alone; kept (it stops products and levels joining on rounding structure).

## The defaults on the ladder (stored)

`uv run sdlab-ladder run --strategies matrix_v2 --jobs 2 --timeout 300` at 948c0a2 (defaults of d8e1d85),
read by `leaderboard.view` (2026-10-19 ~18:00; the other strategies' rows are their latest stored
results and mix versions):

| strategy | tests P + E of 1192 | strict | realistic skill@20 / goals of 66 | physics pass of 28 |
|---|---|---|---|---|
| matrix_v2 | 585 + 207 | 375 | 36.7% / 21 (64 run, 2 heavy not run) | 14 |
| matrix | 390 + 143 | 212 | 29.0% / 12 | 13 |
| structures | 757 + 161 | 684 | 35.7% / 14 | 9 |
| kalman_lna | 755 + 134 | 666 | 38.6% / 15 | 12 |
| combined | 704 + 130 | 626 | 40.6% / 16 | 12 |
| effect_hats | 534 + 210 | 333 | 49.9% / 14 | 13 |
| earned_pieces | 517 + 227 | 371 | 35.0% / 15 | 15 |

Run time: 151 s of discovery over the tests (matrix 247 s).

## Examples bench

`uv run python tests/bench/evaluate.py --strategy matrix_v2 --baseline v2.1 --jobs 2` (d8e1d85; saved
`~/.cache/sdlab/bench/runs/2026-10-19T18-02-32-846Z.json`): mean skill@20 31.4% (+1.8 on the v2.1 headline),
skill@100 31.9% (+2.6), 21 of 66 meet the goal. Paired over 62 runs: skill@20 30 better, 13 worse
(+6.8 points, sign p = 0.014, Wilcoxon p = 0.007); skill@100 28 / 16 (+7.5, Wilcoxon p = 0.024). Worse by
more than 2 points: sd-eras long, sd-ev-fleet long, sd-farm-soil, sd-fishery, sd-hospital, sd-housing
long, sd-print-shop long, sd-recycling, sd-support-tiers long, sd-university long, sd-webshop-stock long.

## Cells lost against matrix (d1d, the defaults), with the reason

- 011-goal-gap counts-long, 083-noisy-goal-gap counts-long and lag-long (E -> F): the gap's number is
  read 0.237 against 0.2 with a constant inflow (plain OLS is 3.5 SE off there: errors in variables);
  the matrix's 2 chance pieces happened to land it at 0.225. Lost by every inflow fix (pool, pelt2,
  white, falling); earned_pieces and censored lose it too.
- 042-random-two-chains-of-two#5 counts-short (P -> F), #8 counts-short (P -> E): a slow drain (0.04)
  in 300 steps; pooled, it is read as part of the inflow (earned_pieces loses #5 too).
- 053-sweep-excitation#5 counts-short (P -> E): a weakly excited move; pooled inflow absorbs part.
- 087-noisy-injection meas-short (P -> F): measurement noise; with pooled pieces the judge prefers a
  variant with pieces into B and a spurious exit from A.
- 087-noisy-injection outliers-long (P -> F): a product B x B joins B's row on outliers.

Realistic runs much worse than matrix: sd-support-tiers long (42% -> -100%), sd-webshop-stock long
(64% -> 8%), sd-k8s-small short (58% -> -2%), sd-ev-fleet long (18% -> -28%).

## Open

- A pooled inflow still runs away on sd-support-tiers long; pool_white did not catch it.
- Products under outliers (087) want a robust row.
- tie_se as proposed needs the joint fit (earned_pieces' joint.py) to be right on changing rows.
