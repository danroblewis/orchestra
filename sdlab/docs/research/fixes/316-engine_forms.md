# 316 (k8s-shared-database): engine_forms, round 1

**Status (2026-10-22, agent ef316-r1; engine_forms lock held, then released): engine_forms passes all four plan variants of 316 at b20e3cc (pool job 354: 4 pass, 0 errors).** That covers the three achievable variants, plus counts-short, which `analyse` calls data-limited. The work took three commits: 7cdd811 (reread), 6034c4e (capmin fixed pool, pool.py, earn.py), and b20e3cc (earn wired in). Complexity equals the truth's (32) on none-short, none-long and counts-long, and is 33 on counts-short.**

| variant | achievable? (`analyse`) | before (59d2ccf, store) | attempt 1 (7cdd811, job 348) | attempt 2 (6034c4e, job 350) | attempt 3 (b20e3cc, job 354) |
|---|---|---|---|---|---|
| none-short | yes, p 1.000 | FAIL 12/16 | **PASS** 16/16, 28 s | **PASS** 16/16, 29 s | **PASS** 16/16, 32 = truth, 29 s |
| none-long | yes, p 1.000 | FAIL (3 missing, 1 added) | **PASS** 16/16, 152 s | **PASS** 16/16, 143 s | **PASS** 16/16, 32 = truth, 142 s |
| counts-short | **data-limited**, p 0.407 (the two query links' bound SE 0.0109 and 0.0116, allowed 0.006 and 0.01) | FAIL | FAIL 12/16, 362 s | PASS 16/16, 354 s | PASS 16/16, 33 vs 32, 343 s (not a target) |
| counts-long | yes, p 0.844 | FAIL 9/16, 1137 s | FAIL 9/16, 1117 s | FAIL 13/16, 1065 s | **PASS** 16/16, 32 = truth, 1036 s (of 1800) |

Commands: `uv run sdlab-ladder analyse 316-k8s-shared-database --variant V`, `uv run sdlab-ladder diff
316-k8s-shared-database --strategy engine_forms --variant V`, `uv run sdlab-ladder job 348`, `uv run sdlab-ladder job 350`, `uv run sdlab-ladder job 354`.
All results above ran on the Mac's pool worker.

## Diagnosis (rule 4b): method faults, not data limits

The truth's database half:

```
outside -> db_waiting    0.06 pricing_inflight        (queries)
outside -> db_waiting    0.1 cart_inflight
db_waiting -> db_active  min(0.8 db_waiting, 80 - 0.2 db_active)   (queries -> connections)
db_active -> outside     0.8 db_active
```

The boundary declares `db_waiting: {in: [estimate, estimate]}` and `db_active: {out: estimate}`, nothing else.

**Before (59d2ccf), none-short:** `outside -> db_waiting = -0.068 frontend_inflight - 1.44 catalog_queue - 3.06
cart_inflight`, `db_active -> outside = 0.000057 db_active`, and no `db_waiting -> db_active` at all. The requests half
was right. counts-long had the same broken database half plus two moves that cancel each other in the requests half:
`pricing_inflight -> frontend_inflight 0.079` (on the Mac in my trace: `pricing_queue -> frontend_inflight 0.107` with
`frontend_inflight -> catalog_queue 0.038`), and with them the calls into catalog and pricing were 10-15% off.

There were four causes, each of them a method fault:

1. **Units.** reread.py (the exact re-read, k8s-309/311) re-reads one unit at a time, and a move joins stocks of one
   unit. db_waiting (queries) and db_active (connections) are each alone in their unit, so neither row could be read.
   The declared boundary leaves no other drawing: db_waiting has no outside outflow and db_active has no outside
   inflow.
2. **A cap read off the receiver, seen on one step.** On every capped step but the first of each capped spell,
   db_active sits at exactly 80 (`a + (80 - 0.2a) - 0.8a = 80`). The cap's slope in db_active therefore shows only
   where a spell starts: 1 step of 300 on none-short and 5 of 2000 on none-long, each with a = 79.91, so the cap is off
   by 0.018. reread's two-regime reader checked only the rms residual, and the rms tolerance is scaled by the numbers'
   sizes, including the constant 64. So it dropped db_active from the cap and read `min(0.8 w, 64)`. It also put every
   column both pieces read into the linear part, so `80 - 0.2 a` could never keep `a`.
3. **capmin had no fixed pool.** Its offer is `MIN(X, theta Y)`. It offered `MIN(db_waiting, 0.98 db_active)`
   (none-short, binding 5% of steps) and `MIN(db_waiting, 0.21 cart_inflight)` (counts-long), both spurious. Its
   receiver had to be of X's unit (the 309 unit guard).
4. **counts: moves that cancel.** These have nothing to do with the pool. With the database half removed, the base's
   requests half still carries the cancelling pair above. Each one alone makes some row worse, but together they fit
   the near-collinear levels (inflights and queues are lagged copies of the traffic).

**counts-long is achievable**, and analyse says so (p 0.844). The cap's slope is also readable there: under counts
noise the releases are whole-number draws, so db_active is not pinned at 80 while the pool is capped. pool.py reads
`81.5 - 0.194 db_active` (3% off).

## Fixes kept

### 1. Boundary-forced cross-unit move (type 12, as combined2's; engine_forms' own code): 7cdd811, 6034c4e

- `capmin.forced_pairs(stocks, run)` returns (x, z) where four things hold:
  - the boundary is declared;
  - x and z are each the only non-final stock of their (different) units;
  - x has no declared outside outflow;
  - z has no declared outside inflow.

  A move may cross units only for such a pair. Everywhere else the user's one-unit rule stands. The rule is
  combined2's (6b1c269), written here (rule 11). On 316 the only pair is (db_waiting, db_active).
- reread.py (7cdd811): once the per-unit pass is done, each forced pair whose two rows are still unexplained is read
  as one block (`_bridges`). The block uses the k-311 pair reader: a MIN move between two rows, `_pair`.
- capmin.py (6034c4e) has a **fixed-pool arm** for a forced pair: `MIN(X, theta (beta - Z))`, where Z is the
  receiver and beta is 1.05-10 times Z's largest level. The receiver Z is allowed across units. It is written back
  as `min(k X, k theta beta - k theta Z)`. On none-short it offers beta 400, theta 0.25, which is the truth exactly.
  oefit declines this cap. Note: engine_forms' base never pairs the offered series into a move across units, so on
  316 the offer only helps through the passes below.

### 2. Every step within its rounding (new, call it **per-step exactness**): 7cdd811

- `_Rows._each`: where the data are finely rounded, a two-regime fit must hold on every step within
  `EACH x ROUND x rounding x (1 + sum |numbers of rounded columns|)` (EACH = 2). The constant is not rounded, so its
  number is not counted. The rms check alone let a column that matters on a few steps be dropped.
- `_two_regimes` adds roles in which a column both pieces read is lin's and also stays in one branch. This is the cap
  `80 - 0.2 a` on the receiver a, whose row's linear part is `-0.8 a`.
- **Port:** for any exact row reader that judges a fit by its rms (combined2's sparseblock, kalman_lna's rows.py,
  milp's exact best subset), add a max-residual check against the rounding where the data are exact.

### 3. No floor written that never binds (new, **unbound-floor**): 7cdd811

`_pair` writes `min(u, v)` when neither argument goes below 0 on the run (the engine floors the rate). Before, it
wrote `min(u, max(0, v))`. Under the proven-equivalence rule, a floor that never bound would make the answer "fits".
**Port:** wherever a strategy writes `max(0, .)` into an expression, check that the floor binds on the run.

### 4. One outside flow per declared side (boundary rule, **per-side split**): 7cdd811

`reread._per_side` splits an outside flow of plain linear terms with no constant in two cases: when its stock's
side is declared n > 1 times and the flow has exactly n terms. Each term becomes one flow (db_waiting's two
services' queries). **Port:** after any pass that writes outside flows, on a declared boundary.

### 5. Pool read from both rows on any data (new, **pool-rows**): 6034c4e

pool.py, for each forced pair with no move between them yet:
- The summed row `dx + dz` has no move. Its best column subset by Gaussian BIC (up to 4 columns of non-final levels,
  inputs and a constant) gives the outside sides: positive terms are x's declared inflows, negative terms are z's
  declared outflow.
- The move is started from a grid over the pool, `min(g x, c - d z)` (beta 1.05-10 times z's largest level, or a
  fixed cap). It is then refitted with the sides by bounded least squares on both rows at once.
- The pass replaces the pair's flows when the two rows' BIC falls by more than 6 log T and nothing leaves the
  boundary.

On counts-long it gives `0.0597 pricing_inflight`, `0.105 cart_inflight`, `0.826 db_active` and
`min(0.828 w, 81.5 - 0.194 a)` (BIC 21301 -> 17881 in my trace). combined2's minrefit found the same numbers. On
noise-free data reread has already written the move, so pool.py does nothing there.

**Port:** pool.py is self-contained. It needs only `forced_pairs`, a one-step change simulator for the BIC check
(engine_forms' `hidden._change`), and an `_rate` writer. It suits any strategy whose base pairs moves within a unit
only: kalman_lna, structures, the lna family and the earned family.

### 6. Moves earn their place on every row at once (the ledger's proposed **flow-earn**, made): 6034c4e

earn.py does the following:
- Every linear flow (constant, proportional or linear; not a declared input's flow, an expression, or a flow with
  pieces or effects) is refitted on all rows at once by weighted least squares. Each row is weighted by its own
  residual variance under the answer, and the flows the refit cannot run are held at their amounts.
- Each move between two measured stocks is then dropped in turn, greedily, while the refit's BIC does not worsen.
- Outside flows are never dropped.
- The answer changes only if a move was dropped, and only if the rows' BIC as the engine runs the new flows (floored)
  is lower than the answer's.

On counts-long (the Mac trace) it dropped `frontend_inflight -> catalog_queue` and
`pricing_queue -> frontend_inflight`. The refit then gave `outside -> catalog_queue = 0.2999`,
`outside -> pricing_queue = 0.3998` and `pricing_queue -> pricing_inflight = 0.699`.

**Port:** earn.py is self-contained apart from the change simulator. It fits any strategy whose search can keep
cancelling moves on noisy rows, including the 315 misses (invented `frontend_inflight -> catalog_queue` and
`catalog_inflight -> pricing_queue` in 26-29 strategies). Run it last, after the passes that add flows.

**Attempt 2 (job 350) and a mistake of mine.** 6034c4e added earn.py and its test, but I wired it only into my
local trace script and not into `identify`. So job 350's counts-long kept another cancelling pair, which this run's
base produced: `pricing_inflight -> frontend_inflight 0.079`, `frontend_inflight -> catalog_queue 0.031`,
`pricing_queue -> pricing_inflight 0.79` (13/16). The base is not deterministic between processes on counts-long, and
my local base had `pricing_queue -> frontend_inflight` in place of the first move. Run on job 350's stored flows,
earn.apply drops both moves (BIC 156199 -> 156046), and the re-score passes 16/16 (local, scratchpad `earnprobe.py`).
b20e3cc wires earn in as the last pass.

## Order in identify (engine_forms/__init__.py)

The order is capmin.offer, then the base, oefit, tidy, capmin.restore, reread (with bridges), **pool**, controller,
hidden, delay and **earn** (last, b20e3cc). earn holds the flows it cannot refit (expressions, pieces, effects) at
their amounts, and it does nothing where the answer has a hidden stock.

## Checks

- `uv run pytest tests/test_engine_forms_*.py tests/test_isolation.py`: 27 passed (at b20e3cc). This includes the new
  `test_a_pool_the_boundary_joins_across_units_is_a_min_move` (exact),
  `test_a_forced_pool_is_read_from_both_rows_on_counts` and `test_a_move_that_earns_nothing_is_dropped_and_a_real_one_kept`.
- 315 none-short local trace at the new code: pass. This is only a smoke test. Earlier rungs wait for the regression
  run, as the plan says.

## Regression risk (for the later regression run)

- `_each` makes the exact two-regime reader stricter. 311/312's room-limited starts used it, so check 311 and 312
  none-short and none-long.
- earn.py runs on every case and drops moves on BIC. On exact data a needed move cannot be dropped, because the rows
  would no longer be exact. On short noisy runs, though, a weak real move could go. Check 305 (retries, a loop that
  turns over every step) and 309/310 counts.
- `forced_pairs` is empty unless two single-stock units face each other with no outside side. 317 has the shared
  database again (db_waiting, db_active) inside a larger model; check that the pair is still alone in its units there.
- counts-long uses 1036 s of the case's 1800 s, almost all of it in the base (unchanged from before: 1137 s).
