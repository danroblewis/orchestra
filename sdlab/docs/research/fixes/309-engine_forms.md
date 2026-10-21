# 309 (k8s-pod-startup): engine_forms, the noise-free and counts variants

**Status:** 2 of 4 pass. These two are the only achievable targets. 2026-10-21, agent engine_forms-309 (held the engine_forms lock for the work and released it after).
Fix commit 740ed95. Pool job 255 ran at 740ed95: `uv run sdlab-ladder job 255`. Results: **none-short pass (18/18 parts), none-long pass
(18/18), counts-short fail, counts-long fail**. Both counts variants are data-limited, so neither is a target (see below).

## Before (store, code 4f04ce1; `uv run sdlab-ladder show 309-k8s-pod-startup --strategy engine_forms --variant V`)

| variant | status | what was wrong |
|---|---|---|
| none-short | FAIL 9/18 | capmin offered a false MIN(desired, ready). The requests block came out garbled (`queue -> inflight = 7.62 retries - 0.00086 errors_total`, `retries -> outside = -4704 pending`). The pods were read as pieces (`outside -> pending`, `ready -> outside`) |
| none-long | FAIL | the same |
| counts-short | FAIL | data-limited |
| counts-long | FAIL | data-limited |

## Diagnosis (rule 4b)

`uv run sdlab-ladder analyse 309-k8s-pod-startup --variant V`:
- **none-short and none-long are method faults.** The only reason analyse gives for "unidentifiable" is the move-vs-link equivalence on retries, and the scorer accepts that. Every bound SE is below 1e-4.
  - **capmin.** capmin offered MIN(desired, 1.0 x ready) with ready as the receiver. desired's own row gains nothing from it (gain 0.0). The kink it found sits in ready's and pending's rows: it is the floor of `deleted = max(0, ready - desired)` and `created = max(0, desired - pending - ready)`, not a capacity. On 308 counts-long and 309 none-long, capmin also offered a "move" from a requests stock into a pods stock.
  - **The base.** The base is the vendored combined/matrix copy. On these data every one of its candidates is wrong on the requests rows, even though those rows are exactly linear. On the requests stocks alone the base gets them right. So the pods rows, which no candidate can express, derail the whole-model choice.
  - **The pods rows.** The pods rows are a linear part plus one floored linear flow. The engine floors every rate at 0, so `desired - pending - ready` written as a linear rate already is the truth's flow.
- **counts-short is data-limited** (p 0.01). The bound SE is 0.275 on `outside -> pending [desired/ready]` against an allowed 0.1, and 0.113 on retries -> outside against an allowed 0.04.
- **counts-long is data-limited** (p 0.25). The bound SE is 0.102 against an allowed 0.1 on the pending and ready links, and 0.044 against 0.04 on retries.

## Fixes kept

| type | mechanism | where | commit | how another strategy adopts it |
|---|---|---|---|---|
| source-row-guard | capmin accepts a candidate MIN(X, theta Y) only when X's own row gains more than PRICE x log T from it. Before, any gain above 0 was enough, so a kink seen only in other rows (a floor on a different flow) could pass | `engine_forms/capmin.py` `offer` (`gx <= price`) | 740ed95 | a one-line change in its capmin copy (`if cx >= 0 or gx <= price`) |
| unit-guard (moves) | the receiver of an offered MIN, and so the move it becomes, must have the source's unit. A stock with no unit announced may pair with anything | `capmin.py` `_same_unit`, used in the receiver loop | 740ed95 | copy `_same_unit` and filter the receiver loop with it |
| exact-reread (floored linear) | runs on noise-free data, when the answer leaves a stock's one-step changes unexplained beyond the data's rounding. Every stock of that stock's unit is then read again, from the levels alone. A row is (1) the smallest best-subset linear fit (levels, inputs, constant; up to 4 columns) that is exact. Failing that, it is (2) a linear part (up to 3 columns, found by backward trimming, exact on at least half of the steps) plus one floored linear flow of fixed sign. That flow is fitted by censored least squares: steps where the remainder is 0 and Z w < 0 are dropped until stable, and max(0, Z w) must reproduce the remainder on every step. The rows' terms are joined into flows column by column. The column's own stock, or its single negative reader, is the source, and same-unit positive readers get moves from it up to what it gives. Remainders become outside flows, and remainders below 1e-4 of the column's largest number are dropped. Each pair keeps one flow, and an "input" side is snapped to exactly 1 x the input. A hinge is written as a plain linear rate, which the engine floors. A row neither form reproduces (desired's ceil controller) keeps its own outside flows and loses its moves. The block is replaced only when no row that was explained is lost, some row that was not explained is now explained, nothing leaves the declared boundary, and the written flows reproduce the rows through the simulator. Noisy data never meet the exactness test, so nothing changes there | `engine_forms/reread.py`, called in `__init__.identify` after `capmin.restore` and before `controller.apply` (desired then has no move, so the controller still reads it) | 740ed95 | copy `reread.py`. It imports only numpy and the package's `_kalman/boundary.py` (`Data`, `Boundary`, `violations`); a strategy without that file copies those three. Call `reread.apply(result, stocks, run, opts)` on the final flows, after any pass that rewrites rates and before a controller pass |

After (none-short, job 255): `pending -> ready = 0.49997 pending`, `outside -> pending = desired - 1.00001 pending - ready`,
`ready -> outside = ready - desired`, the requests block exact (0.6 queue, 0.08 queue, 0.6 / 0.4 retries, 1 x traffic), and the
desired controller as on 308.

## Notes

- Test: `tests/test_engine_forms_reread.py`. A synthetic gap/start/delete pod chain is read as its floored flows, and the same rows with noise are left alone.
- `tests/test_engine_forms_boundary.py::test_a_form_that_leaves_the_boundary_is_undone` still fails. It failed before this change too (noted on 307 and 308).
- Possible regression, not run (by the plan): with the two capmin guards, capmin no longer offers anything on 308 counts-long. That cell passed at 6b0d2c5 with the offer `queue/ready -> ready`, a cross-unit move. Locally, the offers on 306 and 307 (all four variants) are unchanged (scratchpad `offer_all.py`). The later full regression run should check 308 counts-long.
- Not run: earlier rungs and the noise variants other than counts.
