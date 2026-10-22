# Port of the kubernetes climb's fixes to matrix_v2 (2026-10-22, agent port-matrix_v2)

**Status: done.** matrix_v2 now passes every achievable plan variant of 308-311. It also passes two cells the climb
measured as data-limited: 308 counts-short (p 0.094) and 309 counts-long (p 0.25). Earlier rungs 300-307 show no
regression: 32 of 32 pass before and after. The work took 2 rounds: commit 307af7c (pool jobs 386 and 387), then
commit a1520e8 (jobs 393 and 394).

## Before and after (none-short, none-long, counts-short, counts-long)

"Before" is the stored result at the start: bab9156, except none-long at 793b5b5. "After" is job 393 at a1520e8.
Parts are right/of from `sdlab-ladder status` and the store (`sdlab.ladder.store.latest`). The number of parts
changed on 310 and 311 when the found hidden stock started being credited (198baf2, /23 -> /26).

| rung | before | parts before | after | parts after | targets (climb's analysis) |
|---|---|---|---|---|---|
| 308 | FFFF | 10/12, 10/12, 8/12, 10/12 | **PPPP** | 12/12 x 4 | none-*, counts-long (counts-short data-limited, p 0.094) |
| 309 | FFFF | 11/18, 11/18, 5/18, 5/18 | **PPFP** | 18, 18, 17, 18 /18 | none-* (counts data-limited: p 0.010, p 0.25) |
| 310 | FFFF | 10/23, 10/23, 7/23, 10/23 | **PPFF** | 26/26, 26/26, 9/23, 17/23 | none-* (counts data-limited by the measured bounds) |
| 311 | FFFX | 10/23, 4/23, 6/23, error | **PPFF** | 26/26, 26/26, 10/23, 11/23 | none-* (counts data-limited) |

Cells fixed: 12 (308 x4, 309 x3, 310 x2, 311 x2, and the 311 counts-long error is now a scored fail). Wall times in
job 393 run from 3 s to 357 s (311 counts-short), all under the 1800 s limit.

## What was ported (fix ledger type numbers)

matrix_v2 already had copies of capmin.py and oefit.py identical to kalman_lna's, so kalman_lna's post-passes fit in
after `capmin.restore` without changes. They were copied from kalman_lna at **9d3ca8e**: `rows.py`, `derived.py`,
`delayed.py`, `subsets.py` and `tracker.py`. Each file carries the source and the commit. They are wired in
`matrix_v2/__init__.py` as: oefit, capmin.restore, tracker, rows, tracker again, then dead.

- **Type 2, quantized controller** (`tracker.py`). It runs before the rows as well as after them (the ledger's
  ordering rule). Without the first pass, the rows drew 308's `ready` and 309's `desired` as a delayed inflow (type
  14's hidden stage). The controller then came in beside that inflow, so the one declared inflow had two flows
  (invented boundary).
- **Types 3, 6, 7, 11, 12, 14, 15, 16** (`rows.py`, `derived.py`, `delayed.py`, `subsets.py`). These cover the
  floored rows (309's `desired - pending - ready`), the counted OOM flow `ready x table(mem)` placed as the move
  `ready -> pending` (310), the derived columns `inflight / max(1, ready)` and `ready x max(0, mem - 480)`, the hidden
  integrator written as `mem_hidden` (credited at R^2 1.0), the capped move
  `min(0.5 pending, max(0, 4 nodes - ready))` (311), injection-aware rows, and batched best subsets.
- **Type 4, removing an actuator's smeared moves** (matrix_v2's change to its tracker copy, after combined2
  `switch.py` `_try(drop=True)` at 2a1db63). For a stock that holds exactly still on at least half the steps, the
  tracker also tries the search with the stock's moves to other measured stocks left out. That variant is taken only
  where the rule then fits the stock at most half as badly, and the rows repair the partners afterwards. On 311
  none-short, the matrix's `desired -> pending = 0.0057 desired` had stayed beside the controller (its stop rate
  became 0.936 instead of 1), and pending's rebuilt row was refused because its one declared inflow then held two
  flows.
- **Type 10, guards**: combined2's oefit-guard (7539346: `_weights` keeps its weights on a run that blows up or an
  SVD that does not converge) and a refit-guard around oefit, the rows and both tracker passes (structures 3bf52d6,
  widened as in engine_forms 104ee76). In job 386, 309 and 311 counts-long had errored in `oefit._weights`. In job 393,
  309 counts-long passes and 311 counts-long fails with a score.
- **Type 17 in its exact case** (`dead.py`, new). A move between two stocks whose rate has no positive number, and
  which reads only levels and inputs that are never negative on the run, is 0 on every nonnegative state. It is
  dropped, and declared outside sides are never touched. On 310 none-short the matrix had left
  `desired -> pending = -21.97 desired` and `ready -> desired = -1.2 ready - 0.04 retries`, both zero after the
  floor, and the scorer counted them as spurious.

Other changes in matrix_v2's tracker copy (marked "matrix_v2"):
- A hidden stage that feeds the stock (a found stock H whose flows are all outside <-> H or H <-> S) counts as part
  of S's outside side. H's `inferred_levels` are read like a stock's levels, and replacing the side removes the
  whole stage.
- A side that never rests (y > 0 on all but fewer than 3 steps) is not a rule. Before this, 004 none-long's constant
  inflow became `20 x (A < ceil(B / a))`.
- A constant written as `{"value": ...}` (the matrix's format) is now read. kalman_lna's tracker reads only `c`/`k`,
  so it reads such a constant as 0. That broke 032 none-long until this fix.
- A net above 6000 a step is refused before the breakpoint search. On 309 none-long, `np.arange` had raised
  "Maximum allowed size exceeded".

## Not ported, and why

- **Types 1 and 5** (zero-term prune, capmin guards): 307 already passed all four variants, and no 308-311 cell
  needed them.
- **Types 13, 18 and 19** (forced cross-unit move, conserving drawing, count-noise share tests): these belong to rungs
  312-317 and the counts round. kalman_lna's rows.py carries `movable` (type 13) with it.
- **capsteps.py** (type 12's rare regime, 312): not needed on 308-311, so matrix_v2 keeps its capmin.py.
- **Counts variants of 309-311**: no attempt was made, because they are data-limited (ledger: 309 `analyse`
  p 0.010; 310 and 311 by the climb's measured bounds). 311 counts-short and counts-long now fail with a score
  instead of erroring.

## Regressions checked

- 300-307, all four variants: 32/32 pass before (stored), 32/32 after (job 387 at 307af7c, job 394 at a1520e8).
- `tests/test_ladder_matrix_v2.py`: 5 of 6 pass. `test_exact_data_walk_to_the_plainest_exact_set` fails at HEAD
  7c3fb13 too, before this port, on 034-identical-twins (checked in a detached worktree of HEAD). During the port it
  briefly failed on 032 and on 004 (`test_products_offered...`) as well. Both came from the tracker issues above (the
  "value" constant, and the side that never rests) and were fixed before the first commit.
- `tests/test_matrix_v2_port.py` (new, 3 tests) and `tests/test_isolation.py` pass. matrix_v2 imports no other
  strategy.
- Not re-run: the rest of the ladder (Tests, noisy, canonical and the meas/gaps/... variants). The new passes run on
  every case. matrix_v2 has only re-run 300-311 on its four plan variants, so the backlog's re-run of its stale cells
  is the full regression check.

## Commands and jobs

- Baseline: `uv run sdlab-ladder status --strategies matrix_v2`, `uv run sdlab-ladder show 30N --strategy matrix_v2
  --variant V`, and `diff` (308's diff is empty because the controller flows are scored as whole flows; `show` gives
  the parts).
- Local small tests: `uv run sdlab-ladder run --strategies matrix_v2 --cases 308,309,310,311 --variants none-short`
  (4 pass, 28 s).
- Pool: `uv run sdlab-ladder submit --strategies matrix_v2 --cases 308,309,310,311 --variants
  none-short,none-long,counts-short,counts-long --priority 400 --by port-matrix_v2`. Job 386 at 307af7c: 10 pass,
  4 fail, 2 error. Job 393 at a1520e8: 11 pass, 5 fail.
- Regression: the same command with `--cases 300,...,307`. Job 387 at 307af7c: 32 pass. Job 394 at a1520e8: 32 pass.

## Suggested line for the fix ledger

| port | matrix_v2 | 308-311 FFFF/FFFF/FFFF/FFFX -> PPPP/PPFP/PPFF/PPFF (a1520e8, job 393); 300-307 32/32 kept (job 394) | kalman_lna's rows/derived/delayed/subsets/tracker copied at 9d3ca8e (types 2, 3, 6, 7, 11, 12, 14, 15, 16) after capmin.restore; tracker before and after the rows; type 4 in the tracker (a still stock's moves left out where the rule fits 2x better); type 10 oefit/refit guards; dead moves dropped (type 17, exact). Note for kalman_lna: its tracker reads a constant written `{"value": v}` as 0 and has no guard against an always-on side read as a step rule (not checked whether its own answers hit either) |
