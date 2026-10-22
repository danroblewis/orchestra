# 311 (k8s-node-pool): kalman_lna, round 1 (2026-10-22, agent kalman_lna-311-r1)

**Status: kalman_lna now passes every achievable variant of 311. none-short and none-long both PASS 26/26 at 082119d
(pool job 300).** counts-short and counts-long still fail. They are data-limited in the OOM part, the same way as on 310
(below), so they are not targets. The rung passes for kalman_lna.

Where the numbers come from: `uv run sdlab-ladder submit --strategies kalman_lna --cases 311-k8s-node-pool --variants
none-short,none-long,counts-short,counts-long --priority 400 --by kalman_lna-311-r1` (job 300 at 082119d, on the Mac),
then `uv run sdlab-ladder show 311-k8s-node-pool --strategy kalman_lna --variant V` and `sdlab-ladder diff`.

| variant | achievable? | before (cae16d8) | after (job 300, 082119d) | complexity (truth 66) | discovery |
|---|---|---|---|---|---|
| none-short | yes | FAIL 14/26 | **PASS 26/26** | 58 | 107 s |
| none-long | yes | FAIL 10/23 | **PASS 26/26** | 58 | 404 s |
| counts-short | no: data-limited | FAIL 7/23 | FAIL 5/23 | 43 | 316 s |
| counts-long | no: data-limited | FAIL 12/23 | FAIL 17/23 | 52 | 765 s (limit 1800) |

## Diagnosis (rule 4b)

`analyse 311 --variant none-*` reports "hidden stock without noise: exact if identifiable". For counts-* it reports
"not analysed".

- **pending -> ready = min(0.5 pending, max(0, 4 nodes - ready)) was missing on both none variants. This was a method
  fault.** rows.py could fit a row as linear plus one floored term. ready's row needs the capped move as well as the
  floored deletion `max(0, ready - desired)`. pending's row needs it as well as the floored creation gap. The room
  binds on 172 of 299 steps (none-short) and on 1094 of 1999 (none-long), with room = 0 on 144 and 861 of them.
  Because the move was missing, the 309 gap and surplus were lost too, and the pod rows were read as `-0.00095 x desired`
  and `1.30 x ready - 0.06 x traffic`.
- **mem's block failed on none-short** (`leak -> outside` 15.9% off, `mem -> outside` not plain). **This was a method
  fault.** The integrator borrows the kill switch's threshold, found from the counter's rows (479.994). A hidden
  integrator accumulates that error step after step. At 480.000 the row fits to the truth's misfit (3.4e-6), and at
  479.994 it leaves 2.9e-4. mem's row then read the kill column to make up the difference.
- **On none-long, the floored deletion in ready's row was not found even with the true cap.** The hinge readers are
  first fitted on every step where the always-on part leaves a positive residual. On 283 of 439 such steps that
  residual came from a slightly-off kill threshold, and that pulled `ready, desired` to rank 108 of 231. Separately,
  the kill threshold refit drifted from 480.00002 to 480.27, because rows whose other flows were not read yet pulled it.
  Both were method faults.
- **counts-short and counts-long: data-limited, not targets.** They have the same OOM sub-model as 310: 9 kills on 4
  steps (counts-short) and 88 kills on 46 steps (counts-long, mem up to 599, past the 512 and 560 corners). Fitting
  the kill rate gives a relative SE of 1/sqrt(N): 33% and 10.7%, against a 10% tolerance. On 310 the truth's own table
  refitted at its true knots missed the OOM move by 28.7% and 16.4% (310-combined2-r2.md, 310-milp-r2.md). At 082119d
  the only counts-long misses (`sdlab-ladder diff 311-k8s-node-pool --strategy kalman_lna --variant counts-long`) are
  in that sub-model: the OOM move and its table are 20% off, and mem's drain is 0.0118 plus a constant. That drain is
  downstream of the kill table, as combined2 found on 310. The capped move, the gaps and every other part pass there.

## Fixes kept (all in commit 082119d)

| type | mechanism | how another strategy adopts it |
|---|---|---|
| **capped move** (new; the MIN family of capmin, generalised to a floored room) | `derived.py` 4 and `rows._capped`. Candidates are a move X -> T between same-unit stocks with rate `min(a X, max(0, B . z))`, where the room reads 1-2 levels with or without a constant. (1) The amount is read as `max(0, dy_T, -dy_X)`. This is a lower bound of the move, and it is exact on steps where T has no other outflow or X no other inflow. `capfit` alternates the two regimes (a on the rate-limited steps, B on the room-limited ones; an empty X counts as rate-limited), then refits with the steps that sit well below the fit left out. (2) Candidates are scored on what they add beyond the two rows' spans. The source must lose the move and the receiver must gain it. (3) The CAP_TRY=4 best are judged by refitting both rows with the column, because the cap is what lets a row's floored term be read. (4) The winner joins the derived columns, so rows.py pairs it as a move. Its numbers are refitted on the rows that read it, each row weighted by its fit, starting from the current numbers and from a capfit restart. A refit the rows lose by is undone. (5) The room's constant is dropped where the rows lose less than one number's price (on none-short, `3.6 nodes + 1.2` and `4 nodes` were indistinguishable). (6) It is written as one MIN, `min(k a X, max(0, k B . z))`. This round runs once beyond ROUNDS. | Copy `derived.py` sections 4 (`cap_expr`, `cap_column`, `capfit`, `refine_cap`) and, in rows.py, `_capped`, the "capped" block of the derived loop, the cap branch of the refine loop with its constant drop, and the cap branch of `_flow`. Needs kalman_lna's rows.py/derived.py at c058aae or later. A strategy without rows.py can still use `capfit` on `max(0, dy_T, -dy_X)` to offer the column to its own fit, the way capmin offers `MIN(X, theta Y)`. **Limit:** the lower-bound start needs steps where one of the two rows carries nothing else (on 311 the HPA moves only now and then; in the test, waiting's batches). With dense other flows on both rows, the start is off (found in the synthetic test before it was given batch arrivals). |
| **hinge reread** (oe-row-revise family) | In `_floored`, the 3 best always-on parts are searched again. Each floored-reader subset is refitted on its own active steps (`X_B b > 0`, up to 3 rereads). The first read takes every step with a positive residual, and steps the always-on part misses by a little bias it. Other supports are unchanged. | `_hinge_readers(..., reread=True)` and the `tried` loop in `_floored`. This applies to any copy of kalman_lna's rows.py, and to combined2 `hinge.py` / structures `floor.py` wherever the hinge is fitted on a residual-sign set. |
| **integrator threshold** (hidden-stock write-out, 310) | When a row's hidden integrator is switched by a derived switch, that switch's threshold and the drain rate are refitted together on the integrator's own row, with its readers held (coordinate golden section, 4 rounds). The hidden stock's effect table then carries its own threshold (480.0000 against the kill column's 479.994). | `_integrator_threshold` and its call in `_hidden` (rows.py). This applies to every strategy with a 310 hidden integrator (combined2 `hiddenrow.py`, structures `hidden.py`, milp's): refit the switch on the integrator's row, not only on the switched flow's rows. |
| **weighted threshold refit** | `derived.refine` weights each row reading a switch by 1 / its SSE, so a clean counter row sets the threshold (none-long: 480.00002 is kept, where it had drifted to 480.27). | One argument in `refine`. |
| **duplicate-switch guard** | A switch on the same (X, Y, direction) as one already taken needs its threshold at least 5% of Y's range away. On none-short a second `ready x max(0, mem - 479.95)` had used up a derived round. | `hinges=` in `derived.search`. |
| **budget** | rows' TIME goes from 90 to 200 s, and the capped round runs beyond ROUNDS. On the pool, none-long took 404 s and counts-long 765 s, against the case's 1800 s. | Constants in rows.py. |

Checks: `uv run pytest tests/test_kalman_lna_capped.py tests/test_kalman_lna_rows.py tests/test_kalman_lna_derived.py
tests/test_isolation.py tests/test_kalman_lna_tracker.py tests/test_kalman_lna_boundary.py tests/test_ladder_kalman_lna.py`:
23 pass. The new `test_kalman_lna_capped.py` covers two things. One is a capfit unit check. The other is a synthetic
jobs/racks case with its own numbers: `min(0.35 waiting, max(0, 3 racks - running))`, rack failures by injection, and a
floored quota drain. It checks that the found MIN is within 2% of the move at its largest.

## Risks and not done

- **No regression run on earlier rungs** (the plan: once, later). Three changes reach every case that rows.py sees:
  - the capped search (a spurious cap is possible where a MIN-like kink exists, e.g. queue -> inflight, which capmin
    already writes);
  - the hinge reread (it only adds candidates to the 3 best supports);
  - the weighted threshold refit.

  All three are kept only where the rows' BIC wins. counts-short fell from 7/23 to 5/23 (not a target).
- Discovery time went up: none-long 436 -> 404 s, but counts-long 629 -> 765 s.
- counts-long is left as research. The OOM table's second and third segments (mem past 512) and mem's drain belong
  with 310's open counts items (Poisson-weighted table fit, output-error drain).
