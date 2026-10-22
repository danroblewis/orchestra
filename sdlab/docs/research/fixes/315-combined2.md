# 315 (k8s-fan-out), combined2, round 1 (2026-10-22, agent combined2-315-r1)

**Status: combined2 passes all four plan variants of 315 at 54987a4 (pool job 341, 4/4 pass, complexity 25 = truth on
every variant).** Before: none-short failed (7/12 parts) and the other three passed (store, code 20ed81c).

| variant | achievable? (`analyse`) | before (20ed81c) | after (54987a4, job 341) |
|---|---|---|---|
| none-short | yes (p 1.00) | FAIL 7/12, complexity 38 vs 25 | **PASS** 12/12, 25 = truth, 162.3 s |
| none-long | yes (p 1.00) | PASS 12/12 | **PASS** 12/12, 168.8 s |
| counts-short | yes (p 1.00) | PASS 12/12 | **PASS** 12/12, 112.9 s |
| counts-long | yes (p 1.00) | PASS 12/12 | **PASS** 12/12, 232.4 s |

Commands: `uv run sdlab-ladder analyse 315-k8s-fan-out --variant V`, `uv run sdlab-ladder diff 315-k8s-fan-out
--strategy combined2 --variant none-short`, `uv run sdlab-ladder job 341`, `uv run sdlab-ladder show 315-k8s-fan-out
--strategy combined2` (2026-10-22 16:25Z).

## Diagnosis (none-short): a method fault, not a data limit

`analyse` gives p 1.000 on every number. The diff at 20ed81c:

```
- outside -> catalog_queue       0.3·frontend_inflight
- outside -> cart_queue          0.15·frontend_inflight
- cart_queue -> cart_inflight    0.5·cart_queue
+ cart_queue -> cart_inflight    0.135·catalog_queue + 0.0225·catalog_inflight
+ cart_queue -> catalog_inflight 0.232·cart_queue
+ catalog_queue -> cart_inflight 0.23·cart_queue
  (and hidden stages cart_queue_stage, catalog_queue_stage on the two callees' inflows)
```

A local trace of the pipeline showed the cause. The judge picked lna (tied with five other specialists at BIC -23697,
k 38). Its block had crossed moves between the two callees (`cart_queue -> catalog_inflight`, `catalog_queue ->
cart_inflight`). Catalog and cart share one caller's daily shape, so their queues and inflights are nearly collinear
on the short record (analyse: relative size 1.2e-6). The crossed model came close, but it was not exact: the block's
SSE was 0.656, against an exact level of 6e-4 for rounding to 1e-4. No later pass searches for a sparser structure.
They refit only the flows a model already has. At the end, lagrow found the callee rows above rounding and wrote
their inflows as hidden first-order stages: `H' = 0.18 frontend_queue - H/2`, which rebuilds 0.3 x
frontend_inflight. That behaviour fits, but the structure is wrong.

## Fix kept

**Type 11 (new): sparse block re-read (`sparseblock.py`, 54987a4).**
- **What:** this is a general mechanism. For each unit's block of measured stocks, it runs only when four things hold:
  - the levels are reported to a resolution q > 0 (noise-free decimals; idle on whole-number counts);
  - every flow the pick has on the block is a plain linear or proportional rate between measured stocks (a
    switch, table, MIN or hidden stock is left to the pass that wrote it);
  - no move leaves the block;
  - the pick leaves the block's rows above EXACT (100) x n x q^2/6.

  When it runs, it re-reads the block from the levels alone:
  1. Each row's exact best subset: the fewest columns (at most 4, from the measured non-final levels and inputs,
     with column sets above condition 1e6 excluded) whose least squares reproduce the row to the rounding. A
     declared `input` side is held at 1 x the series.
  2. The terms are joined into atoms. Each atom is either a proportional move A -> B, where A's own row reads -A
     and B's row reads +A, or an outside term k x X on a side the boundary allows.
  3. All atoms are fitted together by NNLS on the stacked rows.
  4. Atoms are dropped one at a time while the block stays exact. Outside terms are tried first, so the conserving
     move is preferred.
  5. Each side's terms are written as one linear flow.

  The re-read replaces the pick's block only when it is exact and the pick's SSE is over 1000 x the re-read's.
- **Where:** `combined2/__init__.py` `identify`, right after `one_unit_moves`, before switch/hinge/oefit. The later
  passes then see an exact block and leave it alone. lagrow's SKIP_REL skips the rows.
- **Cells fixed:** 1 (315 none-short). The trace shows sse 0.656 -> 4.9e-6 and 11 atoms, which are the truth's 12
  flows with the input held. It costs 17 ms.
- **Port:** copy `sparseblock.py`. It needs hinge.py's `columns`/`row_error`/`allowed_sides`/`_linear`, counted.py's
  `_row_sse` and rowrepair's `resolution`. A strategy without those can replace them with about 30 lines: a row is the
  level's one-step change, and a flow's amount is its linear rate on the step-start levels. Call
  `apply(result, stocks, run, opts)` on the chosen model before any pass that refits rows. It is closest to
  engine_forms' `reread.py` (fix type 3, exact rows), without the hinge, counter and MIN arms. A strategy that
  already carries reread gets the same effect by triggering it on an inexact *plain* block, not only on rows left
  unexplained.
- **Others likely to benefit:** any strategy whose search can settle on crossed moves between stocks that share a
  driver: the vendored-combined family (structures, archetypes), the lna family, and the earned family. milp's and
  kalman_lna's row rebuilders already read rows sparsely.
- **Test:** `tests/test_sparseblock_combined2.py`: a crossed block is re-read to the truth, an exact pick is kept, it is
  idle on whole-number levels, and it leaves a block holding a switch alone.

## Regression risk (to check in the later regression run)

The pass runs on every case. It is idle unless the pick's block is plain, its rows are inexact, the data are
decimal, and every row has an exact linear subset of at most 4 columns. When it fires, the result is exact to the
rounding by construction, so a regression would show up as a different exact model: for example, an outside term
where the truth has a move that the NNLS drop order did not prefer. Earlier rungs (307-314) were not re-run, per the
plan.
