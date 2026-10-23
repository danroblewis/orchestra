# Port of the climb's fixes to z3robust (kubernetes 308-311)

**Status:** done 2026-10-22, three rounds (commits 8edfe20, 9032b6b, 27df2d1 on `sdlab`). All 8 achievable cells of
308-311 now pass (none 0 of 8 before). No regression on 300-307: every cell that passed before still passes, and
307 counts-short went from fail to pass. The task came from the user (2026-10-22): "pick another 5 models and apply the
same fixes to them, then run tests 308 through 311 on those 5 models". Fix types are numbered as in
`docs/research/fix-ledger.md`.

## Before and after

Variants are listed in the order none-short, none-long, counts-short, counts-long. P means pass, F means fail, and
each cell gives its parts right. **Before** is z3robust at 79d7da5. The none-short and counts rows come from the store
(`sdlab.ladder.store.latest`, scored at bab9156). The none-long row comes from pool job 379 at 7c3fb13, which carried
the same z3robust code (none-long had never been run on 308-311). **After** is pool job 404 at 27df2d1, read with
`uv run sdlab-ladder job 404 --json`.

| rung | before | after | targets (ledger: data-limited excluded) |
|---|---|---|---|
| 308 | F 10/12, F 8/12, F 8/12, F 10/12 | **P 12/12, P 12/12**, F 10/12, **P 12/12** | none-short, none-long, counts-long (counts-short p 0.094) |
| 309 | F 5/18, F 11/18, F 8/18, F 10/18 | **P 18/18, P 18/18**, F 10/18, F 18/18 | none-short, none-long (counts p 0.010 / 0.25) |
| 310 | F 5/23, F 10/23, F 7/23, F 11/23 | **P 26/26, P 26/26**, F 16/23, F 18/23 | none-short, none-long (counts measured data-limited) |
| 311 | F 4/23, F 10/23, F 6/23, F 9/23 | **P 26/26, P 26/26**, F 13/23, F 18/23 | none-short, none-long (counts measured data-limited) |

**Achievable cells: 0 of 8 before, 8 of 8 after.** 310 and 311 none are scored out of 26 once the hidden leak stock is
credited (`hidden_match.py`). Discovery times in job 404 (seconds): 308 51-59, 309 14-64, 310 31/223/78/69, and 311
170/429/271/231. All are under the cases' 1800 s limit.

**Not targets, and still failing:** 308 counts-short, 309 counts-short, and the counts variants of 310 and 311. The
fix ledger calls all of these data-limited. 309 counts-long gets all 18 parts right but fails on one spurious term:
retries' gap outflow reads `-1.73 + 0.004 cpu - 0.011 inflight` beside its `0.39 retries`. The counts noise lets the
warm start keep those terms, and the floored gap pass then keeps the readers it was given. The other strategies
pass this cell, but the ledger puts it at p 0.25 and it was left alone here.

## Regressions, 300-307 (job 404, every cell of the four variants)

| | before (store, 79d7da5) | after (job 404) |
|---|---|---|
| 300-304 | 20 / 20 pass | 20 / 20 pass |
| 305 | P P P F (counts-long 7/7 with three spurious moves) | P P P F (counts-long 5/7) |
| 306 | 4 / 4 pass | 4 / 4 pass |
| 307 | P P F P (counts-short 8/10) | **P P P P** |

**No regressions.** 305 counts-long failed before and still fails. It now gets 5 of 7 parts with no spurious flow
(before: 7 of 7 with three). The rounds caught one regression and one lost cell:
- Round 1 (job 385) turned **305 counts-short from pass into "equivalent"**. In the "sides" class, a move
  `retries -> responses_total` beat the "kinds" class's outside drain by 0.17, and tidy then dropped the move. Round 2
  fixed this with the tie rule across classes (below), and it passes again in jobs 392 and 404.
- Round 2 (job 392) **lost 310 none-short and none-long** (23/26 and 14/23). Round 3 fixed both (below).

## What was ported

z3robust's own search is unchanged: the Z3 band search over the linear class, followed by the least-squares refit.
The fixes were added around it:

1. **The passes after the search are milp's, copied** (`z3robust/post/`). These are milp's post-program modules at
   a72bb0d, copied from `sdlab` 7c3fb13: `steps`, `hinge`, `room`, `effects`, `polish`, `pairs`, `hidden`, `delay`,
   `tidy`, `conserve` and `quantized`. They are chained as milp's `_after_program` chains them, without milp's
   output-error refit (oefit). They act on an answer's flows alone, so they apply to z3robust's answer unchanged.
   Each copied file is headed with its source, and nothing imports milp (`tests/test_isolation.py` passes). The
   ledger types they carry:
   - **type 2**, whole-unit controllers (`quantized.py`).
   - **types 3 and 9**, floored gaps, the active-set refit, and adding missing moves (`hinge.py`).
   - **types 6 and 7**, counted moves and table effects (`effects.py`).
   - **type 11**, the hidden integrator written as a stock (`hidden.py`, with the drain polish).
   - **type 12**, room-limited moves (`room.py`, `pairs.py`, `polish.py`).
   - **type 14**, the delay stage (`delay.py`).
   - **type 15**, injection-aware rows (`steps.py`).
   - **types 16-18**, re-reads, needless moves, and conserving moves (`tidy.py`, `conserve.py`).
   - **type 10**'s refit-guard (`_guarded`) on every pass.
2. **Type 2, row removal (milp's)** (`core.prepare(skip=...)`). Before the search, `quantized.find` picks out the
   controlled stocks, such as 308's `ready` and 309-311's `desired`. Their rows and every term on them are left out
   of the Z3 problem, but their levels stay columns that other rows may read. A threshold rule's steps were what made
   "nothing fits the band" on 309.
3. **Type 5, capmin guards** (`capmin.py`, from engine_forms 740ed95). Two guards were ported. The source-row guard
   requires X's own row to gain more than PRICE x log T. The unit guard requires a limit's receiver to share the
   source's unit. In addition (z3robust's own), a controlled stock is never a limit's source or receiver. On 309,
   capmin had offered a false `MIN(desired, ready)` and a cross-unit `MIN(retries, desired)`.
4. **Counters are never readers** (`core.py`; the type 11 rule from structures 824f241). A final stock's level reads
   no term. On noise-free data the counters' trend columns had huge t values, which crowded the true moves out of
   the 30 screened candidates. On 310, `queue -> retries [queue]` was screened out.
5. **A counter the declared boundary feeds from outside takes no move** (z3robust's own, round 3). The rule holds in
   the Z3 class and in the effect pass's candidates (`effects.py`, the one marked change to a copied file). On 310
   none-short, a stand-in `ready -> oom_kills_total` had beaten the counted move `ready -> pending`. This is the type
   6 counted-move pairing made robust to the answer the pass is handed.
6. **Floored gaps first** (z3robust's own, round 3; type 3 ordering). The hinge pass also runs before milp's
   sequence. z3robust's search leaves out gross steps, and on a row with floored or switched flows those are its
   informative steps, so the row can come back bare. Its gaps have to be read before the counted-flow pass can see
   the rows it repairs. On 310 none-long this took the cell from 14/23 to 26/26 (local, then job 404).
7. **Idle one-sided flows are dropped after the refit** (z3robust's own, round 2; types 10 and 17). An outside flow on
   a declared side whose amount is above 0 on fewer than 5 steps moves nothing, because the engine floors it. As
   the answer's own reading of the side, it had blocked the gap search on 311 none-long: the warm start read ready's
   outflow as `-176 x mem` (21 -> 26/26). The same penalty inside the warm start was tried and is off
   (`IDLE_IN_WARM`), because it changed 310's warm start.
8. **The tie rule across classes** (z3robust's own, round 2; type 18 in spirit). The "kinds" and "sides" class
   answers within `robust.TIE` (0.5) of each other on L1 + price are ranked by fewer moves, as robust's band search
   already ranks structures within one class.
9. **Negligible moves are dropped last** (`post/negligible.py`, z3robust's own; types 1 and 17). A move between
   measured stocks whose amount never reaches 1e-3 of its stocks' largest one-step change is removed. On 310
   none-short, a room limit had been polished down to `9.4e-5 x pending` beside the plain `0.5 x pending` move.
   Outside flows are exempt.

**Not ported:**
- Output-error refit (oefit, types 0 and 10 oefit-guard). z3robust's numbers are least squares on every step, and the
  none and counts variants carry no measurement error.
- combined2's switch drop (type 4) and structures' every-row rebuild and shared room (types 12 and 16 on 317). They
  are not needed on 308-311, and milp's equivalents came with the copy.
- The 312-317 extensions (forced cross-unit moves, fixed pool, delay per service). They came along inside the copied
  files but were not tested here, because the task covered 308-311.
- Poisson weighting for counts (type 19's share gates are inside the copied files; the counts cells are data-limited).

## Notes and risks

- **Z3 makes the core answer nondeterministic.** The cardinality search runs on wall-clock limits: 25 s a class, and
  Z3 is killed at its timeout. The structure Z3 or the warm start returns, especially on the switched pod rows,
  differed between runs of the same commit (seen while bisecting 310). Most of round 3 made the post passes robust
  to the bare or stand-in rows this produces. A slower machine can still change a cell.
- Run time went up on the larger rungs: 311 none-long took 429 s on node2, where the core takes about 50 s and the
  passes the rest. 300-305 stay within their 120 s limit (305 at most 52 s).
- 309 counts-long's spurious gap readers come from noise-fit terms in the core on counts. A stronger term price on
  counts, or the gap search refusing readers the answer's row did not need, are the candidates for a later round.

## Commands and jobs

- Baseline: `uv run sdlab-ladder status --strategies z3robust`, the store rows read with `sdlab.ladder.store.latest`,
  and job 379 (none-long at 7c3fb13).
- Diagnosis: `uv run sdlab-ladder diff <case> --strategy z3robust --variant <v>` on 308-311, plus local runs of the
  strategy with the note and flows printed. The local runs were scratch scripts and were not committed.
- Round 1 (8edfe20): job 384 (308-311 x 4) and job 385 (300-307 x 4).
- Round 2 (9032b6b): job 392 (300-311 x 4).
- Round 3 (27df2d1): job 404 (300-311 x 4), the numbers above.
- Each job was submitted with `uv run sdlab-ladder submit --strategies z3robust --cases ... --variants
  none-short,none-long,counts-short,counts-long --priority 400 --by port-z3robust`.
- Tests: `uv run pytest tests/test_z3robust.py tests/test_isolation.py` (6 pass). Two of them are new: counters are
  not readers and skipped rows are left out, and a negligible move is dropped.

## Suggested fix-ledger line

| port | z3robust, 8edfe20 / 9032b6b / 27df2d1 (port-z3robust) | milp's post-program passes copied whole (`post/`, types 2, 3, 6, 7, 9, 11, 12, 14-18) after the Z3 band search; controlled rows out of the Z3 problem (type 2), capmin source-row and unit guards (type 5), counters never readers, no move into a counter the boundary feeds from outside (type 6 pairing), floored gaps also first (a robust search's gross steps are a switched row's informative ones), idle one-sided flows and negligible moves dropped (types 1, 10, 17), class tie by fewer moves | 308-311: 8 of 8 achievable cells (0 before; job 404); 300-307: no regression, 307 counts-short fail -> pass |
