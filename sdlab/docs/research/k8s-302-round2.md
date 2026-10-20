# Kubernetes rung 3 (case 302), round 2, cause A2: the earned refit in recession, starved_coflows, matrix_v2

**Status:** done (2026-10-20). Code at 284390d. Round 1 (k8s-302.md, 8c507a8) is not redone here.

## Cause (confirmed)

Each of recession, starved_coflows and matrix_v2 failed only 302-k8s-responses-counter counts-short, for
round 1's cause A: chance PELT pieces on inflight (a stock with no outside inflow) win the in-sample judge
once the final counter `responses_total` fixes inflight's drain at 0.4973.

- recession and starved_coflows (stored answer, code c33de93): the three true flows plus `inflight ->
  outside 32.2` in 4 pieces and `outside -> inflight 0.0635 x queue`; judge 0.0461 for "changing inflows"
  against 0.0520 for "backward, constant inflows".
- matrix_v2 (code e25727e): `inflight -> outside 18.2` in 1 piece (its `pool` option merges the 4 chance
  pieces) and `outside -> inflight 0.0395 x queue`; judge 0.0419 against 0.0520.

8c507a8 never reached them: recession (`__init__.py`) and starved_coflows call the pinned
`matrix.identify_one` directly (8c507a8 replaced only `identify.identify` calls), and matrix_v2 has its own
copy of matrix.py from aad5c7b with no `keep_fit`. Not the data's limit: `sdlab-ladder analyse` rates
counts-short achievable (p 1.00); 301 passed for all three.

Confirmation: with each main-line candidate refitted (below), all three pass all 4 variants of 302
(in-process, `runner.run_item`, single-threaded).

## Change (284390d)

A change inside one fit (each candidate's rows), not a choice between finished models.

- **recession, starved_coflows:** own copies of matrix/earned.py (`refit` only), earned_rows.py and
  earned_joint.py at 8c507a8. Each main-line candidate is fitted by the pinned `identify_one` with
  `keep_fit`, `keep_rows`, `input_columns` and refitted before recession drains are tried / before the
  judge. starved_coflows became a package; its co-flow candidates (steps left out) are as before.
- **matrix_v2:** new option `earned`, on by default. Its matrix.py returns the fit with `keep_fit`; its own
  copy of the refit (earned.py, earned_rows.py, earned_joint.py from matrix/ at 8c507a8) reads its input
  columns (not its product columns) and assembles with its own `finish()`. Two additions in this copy,
  each found from losses on the first paired sample:
  - under `exact`, the reselection's rss floor includes the float-precision floor (without it noise-free
    rows took collinear cross-links: 032, 034, 043#2, 043#6, 057 none-short went pass -> fail);
  - a pooled row is priced as its pools plus one place per change (without it free pieces replaced the
    pools: 086 counts-long drain 0.1171, fail; 048#2 counts-long fail).
  The other option the task named, turning on `white` or `pelt_mult 2`, was measured on the same 94 cells
  (below) and not taken.
- Tests: matrix_v2's `test_every_option_off_is_the_matrix` compares with the pinned `identify.identify`
  (the matrix strategy refits since 8c507a8, so this test already failed at HEAD before this change);
  starved_coflows' never-dry control now asserts a main-line candidate (no co-flow) no worse than the
  pinned main line (skill -1.54 against -21.7) instead of the pinned main line's exact choice.

## Ladder (committed code)

`uv run sdlab-ladder run --strategies recession,starved_coflows,matrix_v2 --cases 300,301,302 --jobs 4
--timeout 600` (2026-10-20, single-threaded): 42 done, 42 pass; `store.latest` 14/14 pass for each, all
rows on 284390d. 302 counts-short fail -> pass for all three; no 300/301 cell changed (all passed before).

## Flips (paired, in-process)

Before = `git archive` of HEAD cc7fbd6 (the three strategies as at c33de93 / e25727e), after = the tree
that became 284390d; same cells, `runner.run_item` statuses, single-threaded, scratch scripts
(`cell.py`, `cmp.py`, `cmpv2.py`). Sample 1 per strategy: 300-302 (14 cells), 50 random cells it ran on the
store (< 8 s), 30 random cells it passed there.

| strategy | cells | pass before -> after | fail -> pass | other gains | losses |
|---|---|---|---|---|---|
| recession | 94 | 57 -> 63 | 6 (302 counts-short, 042#4 cs, 043#1 cl, 049#6 cs, 050#2 cs, 053#3 cs) | fail -> equivalent 4 (046#7 cs, 054#2 cl, 081 gaps-short, 083 cs) | equivalent -> fail 1 (083-noisy-goal-gap counts-long) |
| starved_coflows | 94 | 57 -> 61 | 6 (302 counts-short, 042#2 cl, 042#4 cs, 042#8 cl, 043#3 cs, 049#5 cl) | fail -> equivalent 3 (054#1 cl, 083 lag-short, 128 cl) | pass -> fail 2 (042-random-two-chains-of-two#5 counts-short, 043-random-three-chains-of-two#6 none-short) |
| matrix_v2 | 94 | 60 -> 64 | 3 (302 counts-short, 103 cl, 142 meas-long) | equivalent -> pass 1 (042#8 cs) | 0 |

starved_coflows' two losses are the ones matrix inherited from earned_pieces' refit in round 1 (k8s-302.md,
sample 2: noise-free collinear cross-links in reselect's backward elimination; 042#5 counts-short).

matrix_v2 sample 2 (fresh, drawn after the two additions above: 40 random + 30 passed cells, none in
sample 1): pass 47 -> 49; fail -> pass 157-two-chained-eras none-short, 139-noisy-crowding counts-long;
equivalent -> pass 053#5 counts-short; fail -> equivalent 055#7 counts-long; **pass -> equivalent
043-random-three-chains-of-two#4 counts-short**.

matrix_v2's alternatives on sample 1 (its defaults with `earned` off and one option on, `SDLAB_MATRIX_V2`;
the defaults alone reproduce all 94 before-statuses): `white` 59 pass, +1 (302) -2 (086 counts-long,
053#3 counts-short); `pelt_mult 2` 60 pass, +2 (302, 103) -2 (053#7 counts-long, 044#4 counts-short);
`earned` 64 pass, +4 -0.

Runtime (summed seconds over sample 1): recession 15 -> 26, starved_coflows 15 -> 34, matrix_v2 15 -> 21.

Not yet on the ladder: the non-k8s flips come from the paired in-process runs; the watcher re-runs these
strategies' other cells (their hashes changed), so the board mixes versions until it catches up.

## Open

- The inherited earned_pieces losses (noise-free collinear cross-links, 042#5 counts-short) now also in
  starved_coflows; matrix_v2's copy avoids them with its `exact` floor, which the other copies do not have.
- recession 083 counts-long equivalent -> fail and matrix_v2 043#4 counts-short pass -> equivalent are
  not diagnosed.
- The 087 outliers-long eiv.py regression is untouched.
