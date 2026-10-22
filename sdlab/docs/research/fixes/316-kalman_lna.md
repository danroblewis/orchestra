# 316 (k8s-shared-database), kalman_lna, round 1 (2026-10-22, agent kalman_lna-316-r1)

**Status: kalman_lna passes every achievable variant of 316.** none-short, none-long and counts-long all PASS 16/16
with complexity 32, the same as the truth (pool job 351 at 4719544). counts-short still fails. `analyse` calls it
data-limited, so it is not a target.

| variant | achievable? (`analyse`) | before (59d2ccf) | job 344 (0c2e796) | after: job 351 (4719544) | discovery |
|---|---|---|---|---|---|
| none-short | yes (p 1.00) | FAIL 12/16 | PASS | **PASS 16/16**, complexity 32 = truth | 26 s (mac) |
| none-long | yes (p 1.00) | FAIL | PASS | **PASS 16/16**, complexity 32 | 152 s (mac) |
| counts-short | **no: data-limited** (p 0.41: the two query links' bound SE 18% and 12% against 10%) | FAIL | FAIL | FAIL 12/16 | 354 s (mac) |
| counts-long | yes (p 0.84) | FAIL | FAIL | **PASS 16/16**, complexity 32 | 1119 s (mac; limit 1800) |

Commands (2026-10-22): `uv run sdlab-ladder analyse 316-k8s-shared-database --variant V`; `uv run sdlab-ladder diff
316-k8s-shared-database --strategy kalman_lna --variant V`; `uv run sdlab-ladder submit --strategies kalman_lna --cases
316-k8s-shared-database --variants none-short,none-long,counts-short,counts-long --priority 400 --by kalman_lna-316-r1`
(jobs 344 and 351), then `uv run sdlab-ladder job 351 --wait` ("4 done in 1124.1 s: 3 pass, 1 fail").

## Diagnosis (rule 4b)

- **The db block was missing on every variant. This was a method fault.** The truth's move `db_waiting -> db_active =
  min(0.8 db_waiting, 80 - 0.2 db_active)` crosses units: queries become connections. kalman_lna wrote moves only
  between stocks of one unit (rows.py `_capped`, `_pair`, and oefit's own rule). The declared boundary leaves no other
  way to write it. db_waiting has only inflows, and db_active has only an outflow. So db_waiting's loss had nowhere to
  go, and the fit read it as negative links, e.g. `-63 + 0.18 pricing_queue` or `-1.6e6 - 1.3e6 cart_inflight`.
  The none rows show the structure exactly. db_active's row was already read as `-A + 80 - max(0, 80 - 0.8 W - 0.2 A)`,
  which is the capped move written as a floored outflow. capmin's offer, `MIN(db_waiting, 0.98 db_active)`, had the
  wrong shape: it has no constant, and its regime holds on 3% of the steps.
- **counts-long: the same block, plus noise.** Counting noise on db_waiting and db_active (about 60-80 a level)
  leaves a residual SD of about 10 a step on both rows. That hides the floored term the exact seed reads, so no cap was
  offered. Separately, the base answer had a move `frontend_inflight -> catalog_queue = 0.08` beside its link (a scale
  pattern). oefit then added a compensating `pricing_queue -> frontend_inflight = 0.107` and bent the pricing link to
  0.46. The one-step rows read these stocks right, but they beat the answer by only 43 and 28 BIC, under the rebuild
  margin of 6 log T = 46. When rows.py did rebuild them, counting noise read the two ends of `catalog_queue ->
  catalog_inflight` apart (0.623 in the receiver against a 0.607 drain). The pairing then made the move a link on a
  side the boundary does not have, so both stocks dropped out of the rebuild. All of these were method faults.
- **counts-short: data-limited.** The two query links have a bound SE of 18% and 12%, against an allowed 10%.
  The rows there have a residual SD of about 10 a step over 299 steps, and neither seed finds the cap.

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|---|---|---|---|
| **boundary-forced move across units** (new; extends the 311 capped move and the declared-boundary type 0) | `rows.movable(X, T)`: a move may cross units only where X is alone in its unit with no outside outflow, or T is alone in its unit with no outside inflow, under a declared boundary. Nothing else can carry the loss or the gain, so the move is the conservation claim. Used by `_capped` (cross-unit pairs, including a receiver whose row is already read) and by `_pair` (derived cap columns). | 0c2e796 | Wherever a strategy enforces "a move needs one unit" (kalman_lna's `oefit._same_unit`, every `boundary.py` `_same_unit`, combined2/milp/structures move candidates), allow it when this predicate holds. It needs `run["boundary"]` and the stocks' units only. **This reads the user's rule "a move needs both stocks in the same unit" as "unless the declared boundary leaves no other way".** Without that reading, 316's truth cannot be written at all. Flagged for the coordinator. |
| **cap from a floored row** (capped-move seed) | `_capped.seeds`: a row's floored term that reads X with a negative number, `-max(0, room - a X)`, gives the cap `min(a X, max(0, room))` directly (room = the term's other readers). No lower-bound fit is needed. On none-short it is exact: `min(0.8 W, max(0, 80 - 0.2 A))`. | 0c2e796 | Any strategy with a floored-row fit (combined2 `hinge.py`, structures `floor.py`, milp `hinge.py`): when a hinge reads the source of a possible move with a negative sign, offer the MIN built from it as a candidate column or flow. |
| **pool room seed** (for counts) | `_capped._pool_seed`, for cross-unit pairs only: the room is `c - b T`, a constant less a share of the receiver's own level (K slots, each held one takes b). It is fitted on both rows at once, with each row's current readers profiled out by least squares and each row weighted by its misfit: a grid over a and b, golden section on c, then an LM polish. Both regimes must act on at least 5 steps. counts-long gives `min(0.83 W, max(0, 81.5 - 0.194 A))`, drain 0.826, links 0.0597 and 0.1055. | 4719544 | Copy `_pool_seed` and `_golden_min`. It needs only the two stocks' one-step changes and a set of readers for each row. |
| **seed-only cross-unit search** (budget) | Cross-unit pairs try only the two seeds, not the 1-2-reader room grid. The grid over the new pairs had taken counts-short from 436 to 1015 s on node2 (job 344). | 4719544 | Constant. |
| **simpler-row margin** (rebuild judge) | A plain row (no schedule, delay or integrator) that reads fewer numbers than the answer spends on the stock needs to win by only `SIMPLER` = 2 log T, not 6 log T. On counts-long this removed oefit's move-plus-compensating-inflow and its bent pricing link. | 4719544 | One rule in any "rebuild where the rows beat the answer by BIC" judge (kalman_lna's rows.py copies; combined2 `sparseblock.py` and engine_forms `reread.py` have similar gates). |
| **closed-receiver move** (pairing) | In `_pair`, when the receiver has no outside inflow side, what it gains from reading a same-unit stock is a move even when that is more than the source's drain. `_build` then refits the source's row with its drain fixed at its moves' total. This is the existing "no outflow: drain fixed at its moves'" repair, run the other way. | 4719544 | Every copy of kalman_lna's `rows._pair`/`_build`. Strategies that pair moves from separate row fits (combined2 `hinge.py` repair, milp) can tie the move's two ends to one number where the boundary closes the receiver. |

Checks: `uv run pytest tests/test_kalman_lna_capped.py tests/test_kalman_lna_rows.py tests/test_kalman_lna_derived.py
tests/test_isolation.py tests/test_kalman_lna_boundary.py tests/test_kalman_lna_crossunit.py tests/test_kalman_lna_tracker.py
tests/test_kalman_lna_delayed.py`: 20 pass. The new `tests/test_kalman_lna_crossunit.py` is a synthetic tickets/desks
case with its own numbers. It checks two things: the move crosses units under a declared boundary, and it does not
cross without one.

## Risks and not done

- **No regression run on earlier rungs** (the plan: once, later). Three of the changes reach other cases:
  - The simpler-row margin can rebuild more stocks wherever the answer spends more numbers than its rows. It is still
    judged by the total BIC + 6 log T.
  - The closed-receiver pairing can change moves into stocks with no declared inflow.
  - The hinge seed applies to same-unit pairs too (311/312's capped moves).
- **counts-long time:** 1119 s on the Mac against the case's 1800 s. The previous node2 runs took 1232 s (59d2ccf) and
  1503 s (0c2e796), so a node2 run of this commit may come close to the limit. Most of the time is oefit: 815 s of the
  Mac's local trace, before this change.
- counts-short is not attempted (data-limited).
