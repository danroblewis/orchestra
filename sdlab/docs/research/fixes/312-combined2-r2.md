# 312 (k8s-cluster-autoscaler), combined2, round 2 (2026-10-22, agent combined2-312-r2)

**Status: combined2 passes none-short (28/28) and gets none-long to 27/28 on node2 (job 322, 7f6fb41).** The one
none-long miss is the scorer's: `outside -> oom_kills_total [as a whole]`, 2.0% against 2%. The truth's own counter,
written as `ready x table(mem)`, misses it by the same 2.02% (312-combined2.md, 312-kalman_lna.md item 7). none-long
therefore passes as soon as the harness evaluates a step's rates on the levels with that step's announced injections
added (`score._levels_at`). counts-short and counts-long are still data-limited on the OOM move (round 1 measured the
free-knot Poisson ML optimum at 32.9% and 19.2% off, with a 10% tolerance), so they are not targets.

| variant | achievable? | before (febd195, round 1, job 311) | job 319 (2f4462c) | job 322 (7f6fb41) | job 323 (388d15d) |
|---|---|---|---|---|---|
| none-short | yes | PASS (#387013) | PASS, 585 s | PASS, 587 s | **PASS**, 329 s (Mac) |
| none-long | scorer-limited (1 part) | FAIL 22/28 (#387017) | FAIL 25/28: the retries block (#387033) | **FAIL 27/28: only the scorer's counter part** (#387042), 908 s | **FAIL 27/28, the same one part**, 716 s (Mac) |
| counts-short | no: data-limited (OOM move) | FAIL 7/25 | FAIL | FAIL 7/25 (#387040) | FAIL 5/25 (Mac) |
| counts-long | no: data-limited (OOM move) | FAIL 19/28 | FAIL | FAIL 19/28 (#387043) | FAIL 19/28 (Mac) |

Jobs 319 and 322 ran on node2, and job 323 on the Mac. counts-short fell from 7/25 to 5/25 in job 323. That cell is not
a target, and the machine changed along with the code (so the pick may differ). It is not diagnosed. Commands: `uv run sdlab-ladder job 319|322|323`, `uv run sdlab-ladder diff
312-k8s-cluster-autoscaler --strategy combined2 --variant V`, `show ...` (read 2026-10-22).

## Diagnosis (rule 4b)

Round 1's local trace from a local linear stage gave 27/28 on none-long, but node2 gave 22/28. Both faults found in
round 2 depend on which candidate the judge picks, and the pick depends on how far the time budget gets on the
machine (specialists run under a 90 s cap and a 240 s budget). Scratch traces ran the pipeline stage by stage, with
different specialist sets to reproduce each pick.

1. **A junk limit on the reverse pod move held the real limit off (method fault).** capmin offered
   `ready -> pending = min(0.0017 ready, max(0, 0.0117 pending))` on rows that still carried the OOM kills. After
   counted.py placed the real move (`ready x table(mem)`), the junk limit stayed beside it. Held fixed, it kept the
   pods' start at `min(0.508 pending, 4.02 nodes - 1.005 ready)`, with pod rows at 2400 x the truth's misfit. The
   scorer then failed `ready -> pending` and its mem effect by 2.7%. Without the junk limit, minrefit refits the start
   to `min(0.5 pending, 4 nodes - ready)` exactly. On the path where its room `max(0, -6e-7 mem - 0.118 pending)` is
   never open, idle_dropped had already removed it, which is why round 1's local trace passed.
2. **A pick with a wrong request block (method fault).** When common_cause runs, the runaway guard takes it. Its
   wrong pod rows run away least: multi-step error 21, against 376 for lna, censored and odefit. Every candidate
   whose request rows were exact to the rounding is set aside by that comparison of whole models. The pick has no
   `queue -> retries` move. Its retries row reads desired in and out, and the two terms cancel. The rows fit, so no
   later pass rebuilds them. Result: 19/28. Node2's pick differed in its numbers (`retries -> queue` 0.3145 in its
   carried `rates`, then `retries -> outside = 0.164 oom_kills_total` after the passes) but has the same kind of
   fault. With fix 2, node2 got 27/28.
3. **On that path the HPA never switched (method fault).** The pick smeared desired's steps over three moves, one of
   them `desired -> oom_kills_total` into a final counter. switch.py drops an actuator's smeared moves and repairs
   each partner's row, but it refused any partner that is a final counter. Allowing it gives 27/28 on the local
   trace of that path (25/28 without).

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|---|---|---|---|
| limit-earns (new; capmin guard family, ledger type 5) | `minrefit._earn`: after the limits are refitted, each limit is tried removed, with every other limit refitted (`_refit_all`). The removal is kept where the block's BIC does not rise by more than 2 log n. The BIC's SSE is floored at the levels' rounding (`rowrepair.resolution`, q²/6 per row-step). A limit offered before the block's other flows existed must earn its numbers once they are placed. Notes go in `limits_unearned`. | 2f4462c | Copy minrefit.py's `_earn`, `_limits` and `_refit_all` split. In a strategy without minrefit: after the passes that place the other flows, drop each `MIN` flow in turn, refit the rows, and keep the drop where the rows' BIC does not rise by 2 log n. |
| exact-block-compose (new) | `blocks.compose`, right after the judge's pick (`base()`). A move carries one thing, so a unit's measured stocks form a block whose one-step rows depend only on the flows that touch them, which makes the blocks separable. Where some candidate's flows explain a block's rows to within 100 x the rounding's variance and the pick's block SSE is over 1000 x that, the pick's flows on the block are replaced by that candidate's (the most exact one, then the one with fewest numbers). Blocks touched by a hidden stock are left alone. On noisy levels no block is exact, so the pass is idle. | 7f6fb41 | Copy blocks.py (it needs hinge.columns/delta, counted._row_sse/_nums, rowrepair.resolution). Call `compose(pick, other_results, stocks, run, opts)` on any judge's pick that is chosen among whole models. |
| switch-final-partner (switch type 4) | `switch._try(drop=True)`: a final counter is a partner like any other. Its declared inflow is refitted (`hinge.refit_row`), and the drop is kept only where its row ends no worse. | 388d15d | The two-line change in any copy of combined2's switch.py (structures' floor.py candidate drop: the same rule for counters). |

Tests: `tests/test_limits_combined2.py::test_a_limit_that_does_not_earn_its_numbers_goes` (a junk reverse limit
beside the true pool limit is dropped, and the true one refits exactly) and `tests/test_blocks_combined2.py` (2: an
exact block replaces a wrong one and leaves the other unit alone; a nearly exact pick is kept). With
test_isolation, test_frozen, test_rowrepair, test_switch and test_hinge, 16 passed before the commits.

## Left, and risks for the regression run

- **Harness fix needed (not mine):** `score._levels_at` must add a step's announced injections to the levels its
  rates read, as the rows and the data do. Until then no strategy passes 312 none-long (the truth's own counter
  formula fails by 2.02%).
- **The pick is machine-dependent.** Which specialists finish depends on the cap and budget in seconds, so node2 and
  the Mac can pick different candidates. Fixes 2 and 3 make the result less sensitive to the pick, but they do not
  remove that dependence.
- Regression risks (306-311 not run, by the plan): (a) `_earn` can drop a real limit whose rows are at rounding
  without it, for example one that never binds; that limit would be "fits" at best anyway. (b) `compose` changes
  the pick's block only when another candidate is exact and the pick is 1000 x off, so it applies on noise-free
  variants only. (c) switch now drops moves into counters.
- Run time on node2: none-long 908 s, counts-long 919 s, of 1800 s. `_earn` adds about 30 s on none-long (one
  `_refit_all` per limit).
