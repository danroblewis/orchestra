# Where the time goes: top 5 on 311 (2026-10-22)

The user asked why a 311 run takes 5 minutes and more. Measured on the Mac (nice 10, three runs at once, single
threaded; absolute times rough, shares reliable): `cProfile` around `runner.discover` on 311-k8s-node-pool
none-short, and milp's `program.solve` timed directly (cProfile does not see HiGHS). Pool times of job 293 for
scale: 46 s (engine_forms none-short) to 1,788 s (milp counts-long); long variants take 3-8x the short ones.
Scoring is 3-14 s an item: not the cost.

| strategy | none-short | where |
|---|---|---|
| milp | 219 s | 76% in HiGHS (`program.solve`, C++): 4 solves of 765-895 columns, two stopped by the 60 s `TIME_LIMIT`; the rest mostly `refit.prune` (scipy `least_squares`, 1,270 calls, SVD-bound) |
| structures | 128 s | 56% in scipy `nnls` (Fortran), 40,645 calls at about 1.8 ms (`structures/fit.py` `_solve` / `fit`) |
| kalman_lna | 108 s | `numpy.linalg.lstsq` called 2.8 million times (`kalman_lna/rows.py` `_lstsq`, from `revise` / `row` / `_floored` / `_sparse`); about half of it numpy's per-call Python overhead |

The hot spots are already compiled; a rewrite in another language would buy at most the Python share (20-40%).

## The speed round (decided by the user, 2026-10-22: option 1)

After the climb reaches 317, each top-5 strategy's agent does fewer or smaller solves, nothing else:
- milp: stop a solve when its incumbent stops improving (gap or stall), rather than at the 60 s limit; smaller
  candidate sets where the earlier pass already rules terms out.
- structures: cache repeated `nnls` fits (same columns, same rows), warm-start from the last active set.
- kalman_lna: batch the many small `lstsq` calls (same shapes stacked) or solve the normal equations once per row.
- combined2, engine_forms: profile the same way first.

A speed change is kept only when the strategy's ladder results are unchanged (same status per cell on the
kubernetes set and its earlier passing cells), compared through the pool; benches stay single threaded (rule 6).
