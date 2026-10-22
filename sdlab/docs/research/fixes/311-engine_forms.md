# 311 (k8s-node-pool): engine_forms on the noise-free and counts variants

**Status (round 1, 2026-10-22, agent ef311-r1, engine_forms lock held and released): engine_forms passes every
achievable variant of 311.** none-short and none-long pass 26/26 at commit 4326b3a, pool job 295 on node2
(`uv run sdlab-ladder job 295`). counts-short and counts-long fail and are data-limited by the same OOM-kill bound
as on 310 (measured below), so they are not targets.

| variant | before (cae16d8, store) | after (4326b3a, job 295) | note |
|---|---|---|---|
| none-short | FAIL (pods block: `pending -> ready` 0.018 pending, kills a constant) | **PASS 26/26** (136 s) | `pending -> ready = min(0.49999 pending, max(0, 3.99997 nodes - 0.99999 ready))` |
| none-long | FAIL (pods block missing: created, deleted, kills) | **PASS 26/26** (393 s) | the same block |
| counts-short | FAIL | FAIL 5/23 (292 s) | data-limited (kill flow) |
| counts-long | FAIL | FAIL 3/23 (666 s) | data-limited (kill flow) |

## Diagnosis (rule 4b)

`analyse 311-k8s-node-pool` gives "not analysed" for all four variants, so the checks below were made by hand
(scratchpad `ef311/`). `diff --strategy engine_forms` on none-short and none-long showed every block right except
the pods block (ready, pending). On none-short the mem block and the counter were wrong too. Three method faults
were found, all in `reread.py`:

1. **A start limited by room is no linear-plus-one-hinge row.** On 311, `started = min(0.5 pending, max(0, 4 nodes -
   ready))`. ready's row is `started - deleted - kills` and pending's is `created + kills - started`. Each row carries
   a MIN and a hinge, so neither is linear plus one hinge, and the 309 reader left both rows. On the run the room
   binds (strictly) on about 27 of 299 steps (short), the pending side on about 65, and the floor (started 0) on
   the rest. The floor `max(0, 4 nodes - ready)` itself binds on 30 steps, after each announced node failure.
2. **The counter's row looked linear (collinear columns).** responses_total and errors_total are exactly
   proportional (0.06). A fit of oom_kills_total on `inflight, responses_total, errors_total, desired` had numbers
   -10.7 and 179, and the rounding tolerance `3q(1 + sum|k|)` grew to 0.057 against kills of at most 0.32. So the
   counter was "exact" and never read as `ready x T(mem)`. Without it, the hidden mem stock had no drain to read.
   That is why mem failed on none-short only.
3. **The counter screen did not see the table's onset.** mem passes 480 on 26 of 299 steps (short). The
   16-quantile screen had no knot between 480 and 483, so the screen dropped the right pair (ready, mem).

## Fixes kept (commit 4326b3a)

| type | mechanism | where | how another strategy adopts it |
|---|---|---|---|
| **MIN move from a row pair** (new type: floored-MIN move, the capacity counterpart of ledger type "hinge row") | **Applies to:** exact data (some moving row is exactly reproduced), and two rows of one unit that neither the exact nor the hinge form reproduces. **Step 1, the pair's sum:** the move cancels in the sum. The sum is exactly linear, or linear plus a mixed-sign hinge pair: `lin + max(0, h_in) - max(0, h_out)` (`_Rows.hinges`: the linear part exact on at least half the steps, the rest split by sign, each sign one floored linear function). Each hinge goes to a declared side of one of the two stocks (in for +, out for -), one hinge per stock. **Step 2, one row less its hinge:** this is `lin + s x max(0, min(u, v))`. Its linear pieces are peeled (`pieces`: up to 3, the largest first). Each piece comes from `regime`, which solves every column set (up to 3 columns) exactly on 300 seeded random step samples and keeps the set exact on the most steps. A column's rounding counts only on steps where it is not 0. Least-squares trimming failed here, because over a mixture of pieces it fits none of them. One piece is lin (the floor), the others are lin + u and lin + v. All the numbers are then fitted at once, each step on its branch, until the branches stop changing. Columns are pruned while the fit stays exact. **Step 3:** the other row must equal the sum's linear part less lin, less the same move. **Written:** the hinges as floored linear outside flows, the linear parts joined as before (the counted kills move), and the move as an expression flow with an `id`. It is `min(u, max(0, v))` when u never goes below 0 on the run (here `0.5 pending`), so it is algebraically the truth's form | `reread.py`: `_Rows.regime`, `pieces`, `two_regimes`, `_branches`, `hinges`, `_pair`, the `moves` in `_block`, `exact_any` in `apply` | Copy these functions together with `_Rows`. They need numpy only. Call `_pair(a, b, rows_of_a_unit, Z, may=boundary side check)` on two rows your row reader leaves. To check the written flows, the strategy's simulator must evaluate expression rates (engine_forms uses hidden.py's `_change`) |
| **collinear column sets read nothing** (precision guard; extends the 310 note that the tolerance must not scale with huge numbers) | A column set whose scaled condition number exceeds 1e6 (`COND`) is skipped by `exact` and `regime`. Its huge numbers would inflate the rounding tolerance `3q(1 + sum abs(k))` until any row looked exact | `reread.py` `_posed` | Any exact-row reader whose tolerance grows with the numbers should add this check |
| **counted-flow screen sees the onset** (fix to the 310 counted-flow type) | The quick 16-quantile screen of `X x T(Y)` also gets knots at the onset: the smallest Y where the counter moves, and the largest Y below it where it does not. A table that rises only over the top 5% of Y passes the screen | `reread.py` `_counter_rate` | a two-line change wherever the counted-flow screen is copied |
| **expression rates in the checks** (correctness) | The "is this row explained" check and the check of the written flows now evaluate expression rates (a written-back capmin MIN, the new move), as the engine does. Before, `simulate.Model` read them as 0. A row counts as explained within 2x its tolerance, the same bound the written flows must meet. A row the answer explains is no longer a blocker when all its flows are outside flows (they are kept). A tiny move at the fit's precision is not written | `reread.py` `apply`, `_block` | strategies with their own exact re-read: evaluate expression flows before judging a row unexplained |

Tests (`tests/test_engine_forms_reread.py`): `test_a_start_limited_by_room_is_a_min_move` uses a synthetic pod chain
with `started = min(0.3 pending, max(0, nodes - ready))` and nodes added one by one. The re-read writes the MIN move
expression, which matches the truth at four test states, and the created hinge.
`test_collinear_columns_read_nothing` checks the COND guard. The other engine_forms tests (reread, hidden,
controller, tidy), `test_isolation.py` and `test_frozen.py` pass (15 passed).

## Data limits of the counts variants (rule 4b, measured)

The kills are Poisson in `ready x T(mem)`. The Fisher information was computed for the truth's own table form,
with its knots 480/512/560 given and its heights free, on each counts run's measured ready and mem (scratchpad
`ef311/bound.py`):

| variant | expected kills (steps) | rel. SE of the total killed | expected rel. rms error of the kill flow's amounts | tolerance |
|---|---|---|---|---|
| counts-short | 10.8 (6) | 0.31 | 0.31 | 0.10 |
| counts-long | 94.1 (84) | 0.10 | 0.20 | 0.10 |

This is the 310 bound almost unchanged (310: 0.35 / 0.20). No method can be expected to get the kill flow (and the
effect of mem on ready -> pending) within the tolerance, so both counts variants are data-limited and not targets.
engine_forms's other counts faults are method faults left for the counts round: queue/retries numbers off, cpu,
`outside -> pending` with absurd numbers (-2.2e6 x pending on short, `ready -> outside = -1.15e8 x traffic`), and
`desired -> errors_total` invented on long.

## Notes for the regression run

- The pair reader runs only on exact data (a moving row reproduced, or a counted flow), only on rows that are
  left over, and its result must pass the same "written flows reproduce the rows" check. On 309 and 310 the pods
  rows were already linear plus one hinge, so the pair reader should not fire there. Check 309 and 310 none-short
  and none-long once.
- Changes that affect every exact re-read: the COND guard, the 2x bound on explained rows, the expression-aware
  checks, and the tiny-move snap. The expression-aware check means a block with a written-back capmin MIN now
  counts as explained, where before it was always "unexplained" and its re-read always failed. This should make
  nothing change on 306-310, but it is the change most likely to move a cell.
- Time: on counts-short the gate (`exact_any`) keeps the reread at about 3 s (136 s without it). none-long took
  393 s on node2, under the case's timeout of 1800 s. The job spec showed `timeout: 300.0` while that item ran
  393 s, so the pool appears to use the case's own timeout.
