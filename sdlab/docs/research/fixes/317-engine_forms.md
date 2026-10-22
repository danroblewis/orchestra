# 317 (k8s-mesh-of-three): engine_forms, round 1

**Status (2026-10-22, agent ef317-r1; engine_forms lock held, then released): engine_forms does not pass 317 on any
plan variant. At the start of this round every variant timed out at the case's 1800 s cap (pool job 360 at 64b5f36).
This round made one general fix, a speed fix to reread's exact subset searches (2bca23f). The fix makes the exact
row search about 40x faster, but reread still spends about 10-15 minutes on none-short, in the k-311 pair reader's
`hinges`. Pool job 368 (2bca23f) is the test. It is **queued, not run** at the time of writing (`uv run sdlab-ladder job 368`), so no result after the fix is claimed.** The rung's remaining faults are diagnosed below, so the
next round can start from them.

| variant | achievable? (`analyse`) | before (64b5f36, job 360) | after (2bca23f, job 368) |
|---|---|---|---|
| none-short | not analysed (a truth analyse does not cover) | TIMEOUT 1800 s (Mac) | queued, not run |
| none-long | not analysed | TIMEOUT 1800 s (Mac) | queued, not run |
| counts-short | not analysed | "ERROR" at 1800 s: a timeout (below) | queued, not run |
| counts-long | not analysed | "ERROR" at 1803 s: a timeout (below) | queued, not run |

`uv run sdlab-ladder analyse 317-k8s-mesh-of-three --variant V` says "not analysed" on all four variants, so none is
known to be data-limited, and all four remain targets. Commands: `uv run sdlab-ladder job 360 --json`, `uv run
sdlab-ladder job 368`, `uv run sdlab-ladder diff 317-k8s-mesh-of-three --strategy engine_forms --variant none-short`
(the stored result #386822 at bab9156, the last finished one).

## Diagnosis (rule 4b): method faults, not data limits

1. **The counts variants' "error" is a timeout.** Job 360's counts-long and counts-short items fail with `SystemError:
   CPUDispatcher(<function _sens ...>) returned a result with an exception set`. Their wall times are 1803 s and
   1800 s, against a cap of 1800 s. The runner's SIGALRM `Timeout` was raised while oefit's numba `_sens` was running,
   and numba reports it as a SystemError. Earlier rungs' "errors" of this shape (316 counts-long at bab9156, 901 s
   against the then 900 s cap) are the same thing. **Harness note (not this agent's module):** `runner.run_item` could
   report a `SystemError` whose wall time reaches the cap as a timeout.
2. **reread's brute-force subset searches (none variants).** 317 has 38 columns (36 levels, the traffic input and a
   constant). `_Rows.exact` tried every set of up to 4 columns, which is C(38,4) = 73,815 sets, each with a condition
   number and a least-squares fit. That took 4.0 s for each row with no exact linear form (local profile: 3.6M
   `_posed` calls, 8.6M `tol` calls). `floored` did the same inside each of `hinge`'s ~8,400 linear parts. Its 5,461
   calls on none-short were mostly identical, because the pod, desired and counter rows are still on most steps, so
   a linear part of zeros leaves the same remainder. reread alone ran for more than 25 minutes on none-short (local
   trace, killed).
3. **After the speed fix, the k-311 pair reader is the cost.** `_block` tries `_pair` on every two unexplained rows of
   one unit: the pods unit has 9 (ready, pending and desired of three services), which makes 36 pairs. Each pair calls
   `hinges` on the summed row: robust trimming over ~8,400 linear parts of up to 3 columns, about 17 s each (local
   profile at 2bca23f: 36 `_pair` calls took 727 s, of which `hinges` took 607 s). Skipping ill-posed column sets
   does not help, because 8,328 of the 8,436 are well posed.
4. **counts: oefit on 36 stocks.** On counts-short the base took 145 s (local), and oefit then ran for more than
   8 minutes. Its `BUDGET` (4e8) counts simulated steps, not stocks x steps. One step of a 36-stock, 62-flow model
   costs about 6x a 316 step, so the budget that took about a minute on 316 takes many minutes here. `WALL` (180 s)
   applies to each search, and there are up to `CYCLES` (3) of them.
5. **What the answer gets wrong when it finishes** (bab9156, none-short, #386822: 18/76 parts, 31 removed, 10 added).
   The base (kalman_lna's copy) leaves most rows unexplained. reread's exact rows at 2bca23f read every queue,
   inflight, retries, cpu, counter and database row exactly (local: `catalog_queue = 0.3 frontend_inflight - 0.68
   catalog_queue + 0.6 catalog_retries + 0.2 cart_inflight`, and so on). Still unread:
   - the pods rows (ready, pending, desired; the shared room expression);
   - the three mem rows (each reads its hidden leak);
   - nodes (a hidden DELAY1 stage);
   - the three frontend/catalog/cart queue rows where their capacity MIN binds.

   On none-short the MIN binds only for frontend: catalog and cart read as linear `0.6 x queue`. With the MIN never
   binding on the run, those two flows would at best be "fits".

## Fixes kept

### 1. Screened exact subset search (new, call it **subset-screen**): 2bca23f

- `_Rows.ranked(y, n, on, pool)` solves the least-squares fit of y for every n-column set at once. It uses the
  columns' Gram matrix (columns scaled to unit norm, batched `np.linalg.solve`; batched `eigvalsh` for the COND test)
  and returns the SCREEN = 64 sets with the smallest misfit. A set that reproduces y has a misfit near 0, so it is
  among them. `exact` then runs its unchanged test (`lstsq`, `tol`, best rms) on those 64 only.
- `floored` screens the same way, on the steps where its target is not 0. A floored rate `max(0, Z w) = r` equals
  `Z w` exactly wherever r > 0, so the right set is among the smallest misfits there. The censored iteration and its
  acceptance test are unchanged.
- `_Rows.posed(sub)` remembers a column set's conditioning, which does not depend on the row.
- `floored` is memoized on its target's bytes.
- Measured locally on 317 none-short (base cached): a row's exact search takes 0.1 s instead of 4.0 s and returns the
  same columns. `floored` reads fall from 5,461 to 3,008, and its 48,777 calls are answered from the memo.
- **Semantics:** where more than 64 sets of one size pass the exact test, the pick could differ (best rms among the
  64 screened). Normal equations lose precision on near-collinear sets (cond up to 1e6), which is why they only rank
  and never accept.
- **Port:** any exact best-subset row reader. That means combined2's sparseblock, kalman_lna's `rows.py` (best sparse
  linear), milp's exact best subset, and the exact solvers (z3exact, sindy's library search) as a pre-screen. Copy
  `_Rows.ranked` with `posed`. On rungs with tens of stocks, every such reader meets the C(n,4) wall.
- Test: `tests/test_engine_forms_screen.py` (the screen keeps the exact set among 31 columns; a floored rate is found
  through it; the posed cache agrees with `_posed`).

## Not fixed (next round, in order)

1. **`hinges`/`hinge` trimming cost.** Replace the per-set trimming loop with `regime`'s batched random-sample solve,
   which reads exact-on-most-steps linear parts the same way. Or screen pairs before `_pair`: a pair's summed row must
   be linear plus at most two floored sides, which `exact` on the quiet steps can test cheaply.
2. **oefit's budget in stock-steps** (`d.steps += d.n * d.S`, with BUDGET rescaled to keep 316's time), so a large
   model does not run CYCLES x WALL. This changes oefit's stopping on every rung, so earlier rungs need the regression
   run.
3. **Hidden leaks x3 and the provisioning stage.** hidden.py and delay.py read one hidden integrator per row. 317 has
   three mem rows, each with its own leak drained by its own OOM table, and nodes with a DELAY1. Check that each pass
   handles every row, not only the first.
4. **The pods block:** ready, pending and desired of three services, with `started` sharing the room
   `4 nodes - sum(ready)` by `pending / max(1, sum(pending))`. That is a ratio of sums, which neither reread's
   two-regime reader nor the k-311 pair reader writes.

## Checks

- `uv run pytest tests/test_engine_forms_*.py tests/test_isolation.py tests/test_frozen.py`: 28 passed (before the new
  test), and `tests/test_engine_forms_screen.py`: 3 passed (at 2bca23f).
- Earlier rungs were not re-run (the plan: the current rung first, regression later). **Regression risk:** the screen
  changes `exact`/`floored` only where more than 64 sets of one size pass, or where the normal-equation ranking puts
  the exact set below 64. Check 309-312 none-* (the floored and pair readers' home rungs) in the regression run.
