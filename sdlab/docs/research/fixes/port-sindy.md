# port-sindy: the kubernetes climb's fixes ported to sindy (rungs 308-311)

**Status:** done 2026-10-22 (agent port-sindy). sindy now passes **308-311 none-short and none-long** and 308
counts-long; every remaining fail on 308-311 is a cell the fix ledger calls data-limited. No regression on 300-307.

## Before and after (pool jobs; cells: status parts-right/of)

Baseline: job 377 at 7c3fb13 (sindy as it stood). After: job 396 at 6732e88 (sindy code identical at 458a9e1).

| case | variant | before (job 377) | after (job 396) | target? |
|---|---|---|---|---|
| 308 | none-short | fail 10/12 | **pass 12/12** | yes |
| 308 | none-long | fail 10/12 | **pass 12/12** | yes |
| 308 | counts-short | fail 8/12 | fail 10/12 | no: data-limited (`analyse` p 0.094) |
| 308 | counts-long | fail 10/12 | **pass 12/12** | yes |
| 309 | none-short | error (LinAlgError: SVD did not converge) | **pass 18/18** | yes |
| 309 | none-long | fail 10/18 | **pass 18/18** | yes |
| 309 | counts-short | fail 7/18 | fail 7/18 | no: data-limited (p 0.010) |
| 309 | counts-long | fail 3/18 | fail 5/18 | no: data-limited (p 0.25) |
| 310 | none-short | fail 7/23 | **pass 26/26** | yes |
| 310 | none-long | fail 10/23 | **pass 26/26** | yes |
| 310 | counts-short | fail 9/23 | fail 9/23 | no: measured data-limited in the climb |
| 310 | counts-long | fail 8/23 | fail 8/23 | no: measured data-limited in the climb |
| 311 | none-short | fail 10/23 | **pass 26/26** | yes |
| 311 | none-long | fail 10/23 | **pass 26/26** | yes |
| 311 | counts-short | fail 7/23 | fail 6/23 | no: measured data-limited in the climb |
| 311 | counts-long | fail 7/23 | fail 10/23 | no: measured data-limited in the climb |

Cells fixed: 9 (all achievable 308-311 cells). Run times after: 310 none-long 856 s, 311 none-long 365 s,
311 counts-long 527 s (limit 1800 s).

**Regressions (job 397 at 458a9e1):** 300-307, all four variants: 32/32 pass, as in the baseline (job 377).
Co-flow cases checked as well, because of the new co-flow pass: 128-coflow-on-outside-inflow E E F F, the same
statuses as stored before the port. 016-coflow is E E F E against a stored E E F F, so counts-long went F -> E.
The stored rows are stale (older sindy code), so that change is not credited to the port.

## What was ported (fix-ledger type numbers)

sindy is a sparse regression on exact one-step changes, so engine_forms' exact row readers fit it best (the
ledger: "the exact solvers can take engine_forms' reread.py"). Copied from engine_forms at 2bca23f (rule 11;
each file says so in its first line) and run after sindy's own fit in engine_forms' order: oefit, tidy,
capmin.restore, then reread, pool, controller, hidden, delay, earn, each guarded.

| type | what | file |
|---|---|---|
| 1 | zero-term prune before the MIN is written back | `tidy.py` |
| 2 | quantized controller (the HPA's desired / ready) | `controller.py` |
| 3 | floored rows, exact re-read of a unit's rows | `reread.py` |
| 5 | capmin source-row and unit guards; fixed-pool offer | `capmin.py` (engine_forms' copy replaces sindy's) |
| 6 | counted flow: the OOM counter as ready x table(mem), placed as the move ready -> pending | `reread.py` (5.) |
| 10 | oefit-guard, refit-guard (`_guarded`), the subset screen | `oefit.py`, `__init__._guarded`, `reread.py` |
| 11 | hidden integrator written as the model's own stock (the leak) | `hidden.py` |
| 12 | room-limited move `min(0.5 pending, max(0, 4 nodes - ready))` from a row pair | `reread.py` (6.) |
| 13, 14, 17 | forced cross-unit move, DELAY1 stage, flows earn their place | `pool.py`, `delay.py`, `earn.py` (not needed on 308-311; carried for 312-317) |
| 15 | expression-aware row checks | `hidden._change`, used by reread |

Two sindy-specific changes were needed on top:

1. **Co-flows on unexplained rows are dropped** (`coflows.py`, 1a640aa). sindy reads product terms in a third
   stock's row as co-flows (`uses`). On 309-311 it wrote them into exactly the rows its library cannot reproduce
   (on 310 none-short, `retries -> queue` took 0.19 ready per unit and `queue -> inflight` took 4.08 mem per unit).
   The copied readers rebuild a row only from flows whose ends are on it, so a co-flow left on that row stays in
   its change. Every re-read was refused: 310 none-short stayed at 10/23 after round 1. Now, on exact data only,
   a co-flow on a stock whose row the answer does not reproduce is removed, and its flow is kept. Co-flows on
   reproduced rows stay. With the change, 310 none-short went 10/23 -> 26/26.
2. **reread's subset screen keeps 256 sets, not 64** (6732e88). engine_forms' 317 screen (2bca23f) checks only
   the 64 smallest-misfit column sets. On 311 none-short the near-collinear counters (responses_total,
   errors_total) fill those 64, so the pods rows' true set falls out. The hinge then reads `ready` wrongly and the
   block is refused at "a hinge and a linear outside flow on one side". engine_forms' reread at 6034c4e (no screen)
   reads this block, and so does this copy at a screen of 128 or more. With 256, 311 none-short and none-long went
   10/23 and 18/26 -> 26/26.

**Finding for engine_forms (not changed, not my package):** its own reread at 2bca23f should hit the same
refusal on 311 none-short. Its stored 311 pass is from 4326b3a, before the screen. The other inputs to the block
read do not depend on the answer, so its next 311 run may fail. Worth checking with its owner.

## Not ported, and why

- Types 4 (actuator's smeared moves), 7 (table effects via milp/kalman_lna), 9 (joint active-set refit), 16
  (best-subset block re-read), 18 (conserving drawing) and 19 (count-noise weighting) were not ported as separate
  mechanisms. On exact data engine_forms' reread already rebuilds the whole unit from its rows (which covers 4, 9
  and 16 there), and types 7, 9 and 19 matter only on the counts variants, which are data-limited on 308-311.
- Nothing was done for the counts variants: every remaining fail is a cell the ledger calls data-limited. The
  copied readers do nothing on noisy rows, so the counts cells still use sindy's own fit.

## Commits and jobs

- 29f3a1b: engine_forms' post passes copied and wired; tests copied (`tests/test_sindy_{controller,reread,hidden,tidy}.py`).
  Job 380: 308 and 309 none-* pass; 310 and 311 none-* still fail; 300-307 32/32.
- 1a640aa: `coflows.py` plus `tests/test_sindy_coflows.py`. Job 389: 310 none-short passes; 300-307 32/32.
- 6732e88: the reread screen at 256. Job 396 (308-311 x 4) is the "after" table above. Job 397 (at 458a9e1) is
  the 300-307 and co-flow regression check.
- Baseline: job 377 at 7c3fb13.

Commands: `uv run sdlab-ladder submit --strategies sindy --cases 308,309,310,311 --variants
none-short,none-long,counts-short,counts-long --priority 400 --by port-sindy`, then `uv run sdlab-ladder job <id>
--wait`. Diagnosis: replays of the post passes on a cached pre-pass answer, kept in a local scratch directory.

## Suggested fix-ledger line

| port | sindy, port-sindy 29f3a1b, 1a640aa, 6732e88 | engine_forms' exact post passes (types 1-3, 5, 6, 10-17) copied at 2bca23f; plus **coflow-strip** (a co-flow on a row the answer does not reproduce is dropped before the exact re-read; exact data only) and **screen-width** (reread's subset screen 64 -> 256: on 311 collinear counters push the true set out of the top 64, so engine_forms' own reread at 2bca23f is at risk on 311) | 9 (308-311 none-*, 308 counts-long; jobs 377 -> 396) |
