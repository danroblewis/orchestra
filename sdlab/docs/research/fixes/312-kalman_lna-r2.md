# 312 (k8s-cluster-autoscaler): kalman_lna, round 2 (2026-10-22, agent kalman_lna-312-r2)

**Status: no change in what passes.** none-short still passes 28/28. none-long is still 27/28, and its one miss is the
scorer's. counts-short and counts-long fail and are data-limited, so they are not targets. This round made the rows
pass faster without changing its answers. The found models are byte-identical, and discovery is 30-50% faster on every
variant. That leaves margin on node2, which runs this strategy up to 3 x slower than the Mac. The rung's achievable
target for kalman_lna is now blocked only by the harness fix that round 1 named (item 2 below). This agent did not make
that fix: the harness is not a strategy agent's to edit.

## Where the numbers come from

- Before: pool job 315 (bf287fb, kalman_lna code as in ac5443e), `uv run sdlab-ladder submit --strategies kalman_lna
  --cases 312-k8s-cluster-autoscaler --variants none-short,none-long,counts-short,counts-long --priority 400 --by
  kalman_lna-312-r2`, then `uv run sdlab-ladder job 315 --wait` / `--json`.
- After: pool job 321 (6fd4778), the same command.
- Local checks used pre-rows answers cached from the strategy, with `rows.revise` stopped at entry. Then rows + tracker
  were timed and scored with `score.equations`. The scripts are in the agent's scratchpad (`k312/cache.py`, `time.py`,
  `prof.py`, `counter.py`) and were not committed.

| variant | achievable? | job 315 (before) | job 321 (6fd4778) | discovery s, before -> after (Mac pool) |
|---|---|---|---|---|
| none-short | yes | **PASS 28/28** | **PASS 28/28** | 129.5 -> 62.3 |
| none-long | yes, but blocked by the scorer (2) | FAIL 27/28: `outside -> oom_kills_total [as a whole]` 2.018% vs 2% | FAIL 27/28, the same part and error | 526.9 -> 368.6 |
| counts-short | no: data-limited (3) | FAIL 7/25 | FAIL 7/25 | 187.4 -> 107.1 |
| counts-long | no: data-limited (3) | FAIL 8/25 | FAIL 8/25 | 1056.9 -> 774.5 |

All 8 items ran on the Mac. None has run on node2 at 6fd4778.

## Diagnosis (rule 4b)

`analyse 312 --variant V` reports "not analysed" for all four variants, with no verdict. `diff --strategy kalman_lna`:
none-long has no hunk except the hidden stock's name (31 unchanged). counts-short has 7 removed, 3 added and 3 values
wrong, across the pod, retry, nodes and OOM parts.

1. **none-short: passes.** There was nothing to fix.
2. **none-long: the one miss is the scorer's, measured again this round (harness; reported, not fixed).** I wrote the
   truth's own counter as `ready x table(mem)`, using the truth's own table, and compared it with the engine's recorded
   counter (`data["counters"]["oom_killed"]`). The relative rms error is 0.02018 on the levels before the step's
   injections, which is what `score._levels_at` gives the scorer. It is 8.9e-6 with the injections added, which is what
   the engine's rates read. The cause is the node loss at t 706 (ready -3), which none-short does not have (scratchpad
   `k312/counter.py`). The same proof is in 312-milp.md, 312-combined2.md and 312-structures.md. **Needed (harness):**
   `score._levels_at` should add the announced injections to the levels a step's rates read, as `rows._data` and milp's
   `Steps` do. That is a scoring change, so it goes to the user with before and after statuses (rule 5). Until it is
   made, no strategy can pass 312 none-long.
3. **counts-short and counts-long: data-limited, so not targets.** 312-milp.md measured the bound on the 312 data: the
   truth's knots given, the kills Poisson about `ready x table(mem)`, and the Monte Carlo probability that the scorer's
   whole-flow error is within 10%. It is 0.36 for counts-short (19 kills on 7 steps) and 0.39 for counts-long (128 kills
   on 50 steps, heights at 512 and 560 free). Both are below 0.5, as on 310 and 311. kalman_lna's counts runs also fail
   well beyond the OOM part. Those are method faults under counting noise, and they belong to the deferred noise round.
4. **The time risk from round 1.** Round 1 named a risk: a pass that depends on the machine. On node2 (job 312), 312
   none-long ran out of its 400 s rows budget, its derived rounds were undone, and the result dropped to 18/28. A
   profile of rows + tracker on cached none-long answers showed where the time went. Under the profiler it took 355 s:
   2.6 million `numpy.linalg.lstsq` calls, 151 s, from `_sparse`'s best-subset search (115 s, every row, derived column
   and hidden-integrator decay), `_hinge_readers`'s active-set rereads, and `_joint`'s active-set iterations (49,305
   calls). These are method costs (fixed below), not a data limit.

## Fixes kept (commit 6fd4778)

| type | mechanism | cells | how another strategy adopts it |
|---|---|---|---|
| **batched best-subset fits** (speed; the prune-budget family, type 10, after round 1's Gram-matrix subset fits) | `subsets.py`, new. `fits` fits every subset of one size at once: a stack of k x k solves on the scaled Gram matrix, with least squares only for a singular one. `sse` computes each subset's sum of squares on its own residuals, which is exact for the coefficients found and has no Gram cancellation below the rounding. It is chunked to 4 million numbers. `best` refits the batch's best 3 by `lstsq` and keeps the least, with ties going to the first in combination order. So the subset chosen and its numbers are what the one-at-a-time search gave; the batch only ranks the rest. `rows._sparse` uses it for the exhaustive sizes and for each forward step. `rows._hinge_readers` uses `fits` for the first read on the acting steps and `reread` for the (311) active-set rereads: each subset is refitted on its own acting steps, all of a size at once, and kept only where it improves, as before. `rows._joint` finds the active set with the scaled normal equations (`subsets.normal`) and fits the set it settles on by least squares. If that exact fit moves the set, it continues exactly. | every variant's time: rows + tracker on none-long 272 -> 176 s single-threaded; discovery (pool, Mac) none-short 130 -> 62, none-long 527 -> 369, counts-short 187 -> 107, counts-long 1057 -> 775 s | Copy `subsets.py` (no imports beyond numpy). Any best-subset search that ranks subsets of one size by least squares on one fixed set of steps can call `subsets.best(X, y, combos)`. A floored-term search can call `fits(..., rows=on)`, then `sse(..., fn=np.maximum(0, .))`, then `reread`. The key idea: **rank in a batch, refit the few best exactly**, so the choice stays least squares' own. Candidates: structures `floor.py` and `moves.py`, combined2 `hinge.py` and `lagrow.py`, and milp's `pairs.py` subset searches. |

**Equivalence check.** I cached pre-rows answers for 312 none-short, none-long and counts-short and ran rows + tracker
at 6fd4778. The found flows are byte-identical (JSON, sorted keys) to job 315's found models (23/23, 23/23 and 22/22
flows), and the scores are the same. `tests/test_kalman_lna_subsets.py` compares `_sparse` with the
one-at-a-time version from ac5443e (a copy in the test) on 6 synthetic data sets with a nearly collinear column and
rounded levels: the same support, coefficients within 1e-9. It also compares `reread` with the per-subset least-squares
reread. Pool job 321 reproduces job 315's statuses and parts on all four variants.

Checks: `uv run pytest tests/test_kalman_lna_subsets.py tests/test_kalman_lna_delayed.py tests/test_kalman_lna_capped.py
tests/test_kalman_lna_rows.py tests/test_kalman_lna_derived.py tests/test_isolation.py tests/test_kalman_lna_tracker.py
tests/test_kalman_lna_boundary.py tests/test_ladder_kalman_lna.py tests/test_frozen.py` gives 30 passed.
`ruff check` is clean on the changed files.

## Considered and not done

- **The pre-rows phase**, about 190 s of the 369 s on none-long, single-threaded. Profiled: the vendored combined
  candidates, 175 s, made up of common_cause `places.prune` (81 s, the shared `regression.row_sums`) and the shared
  `pulses.detect` (57 s). `pulses.py` is the pinned shared library. The vendored common_cause could be batched the same
  way, but it was left alone this round: the rows were the part with the budget that runs out on node2.
- **Writing the counter as `flow(id)`.** A found model cannot do this: `flow(id)` reads the engine's recorded counters,
  which are keyed by the truth's flow ids, and reading those is reading the truth (invariant 1).

## Risks

- **No regression run on earlier rungs** (the plan: once, later). The batched search reaches every case rows.py sees.
  The answers are identical except where subsets tie within the batch's rounding and a 4th-ranked subset would have won
  the exact refit. No case here showed that.
- **node2 has not run 6fd4778.** At the Mac's 176 s for the rows, node2's up to 3 x is about 530 s, under the 600 s
  budget, but the margin is small. A budget counted in work rather than seconds is still the robust fix, and it was not
  made.
- The harness fix in item 2 is the only thing between kalman_lna and a pass on every achievable 312 variant.
