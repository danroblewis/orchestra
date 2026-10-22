# 317 (k8s-mesh-of-three): milp, round 1

Status (2026-10-22, code a72bb0d; pool job 370): **milp does not pass 317 on any variant.** The round turned
three timeouts into measured fails and fixed 11 of the truth's flows on none-short. Two fix commits: bb82235 and
a72bb0d. counts-long still times out at 1800 s.

| variant      | achievable? (`analyse`)           | before (64b5f36, job 361)              | bb82235 (job 366)                        | a72bb0d (job 370)                        |
|--------------|-----------------------------------|----------------------------------------|------------------------------------------|------------------------------------------|
| none-short   | yes (equivalences only)           | TIMEOUT (1800 s)                       | FAIL 357 s: 6 removed, 6 added, 17 wrong, 70 unchanged | **FAIL 590 s: 2 removed, 0 added, 16 wrong, 75 unchanged** |
| none-long    | yes (equivalences only)           | TIMEOUT (1800 s)                       | FAIL 1679 s: 5 removed, 4 added, 20 wrong, 69 unchanged | FAIL 1477 s: 4 removed, 4 added, 23 wrong, 70 unchanged |
| counts-short | not analysed ("a truth this analysis does not cover") | FAIL 672 s: 12 removed, 8 added, 22 wrong | FAIL 344 s: 14 removed, 8 added, 21 wrong, 56 unchanged | FAIL 338 s: 13 removed, 9 added, 22 wrong, 56 unchanged |
| counts-long  | not analysed                      | TIMEOUT                                | TIMEOUT                                  | TIMEOUT                                  |

Commands: `uv run sdlab-ladder job 361|366|370`, `uv run sdlab-ladder diff 317-k8s-mesh-of-three --strategy milp --variant V`,
`uv run sdlab-ladder analyse 317-k8s-mesh-of-three --variant V`. `analyse` does not cover the counts variants, so they are
not known to be achievable. They are not counted as data-limited either.

## Diagnosis (rule 4b)

On the none variants `analyse` reports only equivalences (moves against link-plus-drain, and collinear counters), so every
remaining miss is a method fault.

1. **The time went into one dense least squares (method).** I timed it with a scratch trace of `_identify_program` on
   none-short. The first refit of the program's structure took 29 s (about 80 numbers on 36 x 299 rows, 200
   evaluations, 25 s of it the SVD in `trf`). The local search then ran hundreds of such refits: the program took
   1386 s, against 126 s for both HiGHS solves. The structure separates into independent blocks, because a reader is
   data and couples no rows (36 stocks gave 13 blocks). The joint fit also did not converge in 200 evaluations. On the
   same structure, the block fit's BIC is -144,373 against -127,358 for the joint fit.
2. **cart's HPA had too few events for the controller rule (method).** On none-short `cart_desired` moves 3 times up
   and 5 down. `quantized.py` needed 5 events per side, so the rule was rejected and the program fitted the steps
   linearly (`cart_desired -> cart_ready` 0.34 and similar).
3. **Links and gaps that equal conserving moves (method).** Two cases:
   - `outside -> catalog_queue` read `0.6 catalog_retries`, with `catalog_retries -> outside` at 1.0, in place of the
     move retries -> queue 0.6 and gave up at 0.4.
   - `outside -> *_cpu` read `-0.25 cpu`, with a 0.25 window, in place of the 0.5 window.

   Both drawings give the same levels. `analyse` names the move as the parsimonious one, and the user's rule prefers the
   conserving move.

Remaining faults at a72bb0d (none-short diff). None of them is fixed here:

4. **The gap flows of pods are never offered.** These are `outside -> *_pending = max(0, desired - pending - ready)`
   and `*_ready -> outside = max(0, ready - desired)`. A local probe of `hinge.refine` on job 366's answer gives
   "a flow on the touched stocks cannot be evaluated", for two reasons:
   - The flows that read the hidden stocks (`frontend_mem`'s inflow, `nodes_delay -> nodes`) cannot be evaluated, and
     they block the whole gap search.
   - With those set aside, each pods side has 9 same-unit readers (three services' desired, pending and ready) against
     `MAX_READS` 4, so the side is skipped.

   I tried two things: skipping only the blocked stocks, and screening the readers by forward selection. The fit then
   ran, but the screened readers were the wrong ones (`cart_pending`, `cart_desired` for frontend_ready's deletions)
   and the gap BIC came out infinite, so the change was reverted (not committed). The side's target is bent by the
   started flows, which are written as plain proportional moves.
5. **The shared node room is not a form room.py has.** The truth is `min(0.5 P_i, max(0, 4 nodes - sum ready) x P_i /
   max(1, sum pending))`: one ceiling shared by three moves in proportion to their sources. room.py's rooms read one
   receiver, and `room.refine` found nothing on 317 (17-20 s, no candidate). The diff scores the started flows as
   unchanged, but their plain stand-ins bend the pods rows (fault 4).
6. **Hidden stocks.** These are the three leaks and the autoscaler's provisioning stage. Only `frontend_mem` gets its
   hidden integrator. catalog_mem and cart_mem drain at 0.26 and 0.22 against 0.5, and every hidden stage is scored
   "delay 1.649 against 2".
7. **The counters of cart are collinear.** `cart_inflight -> cart_responses_total` and `-> cart_errors_total` are both
   0.265. `analyse` lists these counters as exactly collinear on none-short, so this may be an identifiability limit
   and not a method fault. It needs `analyse`'s per-flow verdict.
8. **counts-long times out.** No local trace was made. Job 366 also timed out, so the program or the after-passes are
   still too slow on 2000 counts steps.

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|---|---|---|---|
| **block refit** (new, speed) | `Structure.blocks()`: union-find over the parts' measured ends. A reader couples nothing, so every residual row, a source's counts share, a level row and a drain penalty lie in one block. `refit` solves each block's least squares alone (`_refit` on that block's rows), and the result is the same optimum. | bb82235 | any strategy whose refit is one `least_squares` over all stocks (the earned family's refits, combined2/structures judges, kalman_lna rows): split the parameters by connected stocks and fit each block. On 317 none-short the program fell from 1386 s to 214 s, and each refit from 29 s to 1.5 s. |
| **few-event controller** (extends quantized controller, type 2) | a controller side with 3-4 events (`FEW`), down from 5, is kept only where the whole rule then misses no step. | bb82235 | every copy of the quantized controller (structures `controller.py`, kalman_lna `tracker.py`, combined2 `switch.py`, engine_forms `controller.py`): lower the per-side event minimum to 3 when the rule reproduces every step exactly. |
| **conserving rewrite** (new; the user's conserving-move rule) | last pass, `conserve.py`. (a) A link `k x S` on `outside -> D`, with S a measured stock of D's unit that has one proportional outside drain `g >= k`, is rewritten as the move `S -> D` at k, with the drain at `g - k`. (b) An own-level gap `-k x D` on D's inflow, beside D's proportional drain g, is rewritten as the drain at `g + k`. Each rewrite is made only where it is exact: the inflow is never below 0 before or after, and the drain stays positive. | a72bb0d | copy `milp/conserve.py` (it needs `hinge._env`, `_plain` and `_rate`, or their equivalents) and run it on the final answer. It fixed 9 flows on none-short (the retry moves and gave-ups of catalog and cart, the cpu windows of all three) and the same retry flows on none-long. |

None of them names a stock, unit or case.

## Not fixed: for the next round

- **shared room** (fault 5): a group of moves `S_k -> D_k` of one unit that share a ceiling `b Y - sum_k D_k`, split
  as `S_i / max(1, sum_k S_k)`. This would be a new room.py form, judged on all the group's rows together.
- **gap search with hidden flows and wide units** (fault 4): set aside only the stocks whose rows are blocked, and
  choose the gap readers on rows the shared room has already fixed.
- **hidden integrators per stock** (fault 6): `hidden.refine` and `delay.refine` stopped at "a flow could not be
  evaluated" (local trace). The same blocking rule as in fault 4 applies.
- counts-long speed (fault 8), and `analyse` coverage of the counts variants.

## For the regression run

- The block refit changes every result whose answer has more than one block. Results move where the joint fit had
  not converged (it now reaches a lower BIC), so check 307-316 on all four variants.
- `FEW` adds controller rules on sparse whole-number stocks that need a zero-miss rule. Check 308-312 counts (pods
  stocks) for rules that should not be there.
- `conserve.py` rewrites only exact equivalents, but on counts-short it also rewrote spurious mem links as cross-service
  mem moves (`catalog_mem -> frontend_mem` 0.007). The levels are the same and the flows were already wrong, but check
  that no passing cell gains a move.
