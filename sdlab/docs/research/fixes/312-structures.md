# 312 (k8s-cluster-autoscaler): structures, round 1

**Status (2026-10-22, agent structures-312-r1):** none-short **PASS 28/28** at b6f2b6e (pool job 309, node2). none-long
fails at **27/28**. Its only wrong part is `outside -> oom_kills_total [as a whole]`, 2.0% off against a 2.0% tolerance.
That part is a scoring artifact, shown below: the truth's own equations fail it the same way once the counter is
written as a rate. counts-short and counts-long fail, and both are data-limited, so they are not targets. I made
nine fixes, all inside `sdlab/discovery/strategies/structures/`, in commits f76b167 and b6f2b6e. I held the structures
lock for the work and released it after this doc's commit.

## Where the numbers come from

`uv run sdlab-ladder submit --strategies structures --cases 312-k8s-cluster-autoscaler --variants
none-short,none-long,counts-short,counts-long --priority 400 --by structures-312-r1 --every-variant`, then
`uv run sdlab-ladder job N --wait` and `sdlab-ladder show/diff 312-k8s-cluster-autoscaler --strategy structures --variant V`:

| variant | achievable? | before (22ef051, store) | job 305 (f76b167) | job 309 (b6f2b6e) |
|---|---|---|---|---|
| none-short | yes | FAIL 13/28 | **PASS 28/28** | **PASS 28/28** (node2) |
| none-long | yes, except the counter part (see below) | FAIL | FAIL | FAIL 27/28; `diff`: none |
| counts-short | no: data-limited | FAIL | FAIL | FAIL |
| counts-long | no: data-limited | FAIL | FAIL | FAIL (3 removed, 3 values wrong) |

**The none-long counter part is not passable as scored.** The truth counts kills with `flow(oom_killed)`, and the
scorer reads that from the engine's own flow counters. A found model can only write the counter as a rate:
`ready x table(mem)`, the kill move's formula. On two steps of none-long (704 and 1280, just before the announced
node failures) the engine limits ready's outflows, so the counted kills are 0.414 and 0.331 where the formula gives
0.519 and 0.412. I took the truth's flows, wrote the counter as the kill's own rate (scratch `s312/truthself.py`), and
scored the result. It **fails none-long at 2.02%** on this part and passes none-short. structures' counter is within
0.07% of the formula. This is a harness issue for the scorer's owner, not a method fault. Either compare a whole flow
whose truth is `flow(X)` against the formula of X on the states, or let a found counter read its own move's flow.

**Achievability.** `analyse 312` says "not analysed" on every variant. I counted the evidence instead:
- counts-short: 3 node joins and 1 removal, and 19 kills. The stage's delay (an exponential lag) from 3 joins has a
  relative SE of about 1/sqrt(3), or 58%, against the 10% tolerance. The kill table inherits 310/311's bound.
- counts-long: 14 joins and 12 removals give relative SEs of about 27% and 29% for the delay and the removal rate.
  The kill table is in the 310/311 regime (88-128 kills, an SE of about 10%; 311-structures.md).

## Diagnosis (none-short first, then none-long; scratch `s312/stages.py` scores each stage)

1. **capmin could not offer the dispatch MIN.** The pods' capacity binds on only 7 of 299 steps here (after the node
   failure), because the autoscaler keeps adding room. The theta grid stopped at the 95% quantile (theta 61.2 for
   66.7) and the 5% share rule refused the offer. The base then lost `queue -> inflight`, and cpu read the MIN. This
   was a method fault.
2. **The forward-stepwise blind spot on the request rows.** The queue's change is a small difference of large terms.
   The stepwise took `nodes` first (`queue -> responses_total = 101 nodes`), and the timeouts, retries and dispatch
   were lost. Best subset finds the row exactly, but rebuild.py only rewrites outside sides, and it wrote
   `retries -> outside = -0.08 queue + 1.0 retries`. This was a method fault.
3. **A junk co-flow made the pod rows unreadable.** In none-short, `pending -> ready` drew 0.535 queue per pod. In
   none-long, `pending -> oom_kills_total` drew 1.79 ready per unit. Every post-stage skips a row whose flows it
   cannot run. This was a method fault.
4. **room.py could not replace the base's plain `pending -> ready`.** It skipped pairs that already had a move. It
   also ranked its candidates on residuals that the floored sides had already bent, so retries or queue proxies won.
   On none-long its trimmed objective drove theta to 0.14 for 2, and its theta grid stopped below the rare binding
   regime. These were method faults.
5. **counted.py was blocked by a plain move into the counter.** Its table's quantile knots sat at 480.0, 481.1 and
   482.7. This was a method fault.
6. **No mechanism wrote nodes' inflow.** The inflow passes through the hidden DELAY1 (provisioning), so it is a lag
   of `max(0, pending - room)` and no function of the step's levels. The removal on none-long also needs the goal's
   floor `max(2, pods / 2)`, which binds on 84 of 1999 steps. This was a method fault (a new structure).

## Fixes kept

| type | mechanism | commit | where | how another strategy adopts it |
|---|---|---|---|---|
| **min-form: rare regime** | capmin's theta grid spans quantiles [max(1%, 5/T), 1 - that]. Each regime must hold on at least 1% of the steps **and** 5 steps (it was 5%). | f76b167 | `capmin.py` (MIN_SHARE, MIN_STEPS) | The same two lines in all 43 capmin copies (`grid = ...linspace(MIN_SHARE, 1 - MIN_SHARE ...)` and the share test). Regression risk: a MIN is now offered where it binds on 1-5% of steps. The kink price still guards. |
| **row-rebuild: moves** (extends 311's row-rebuild) | Rows far from exact (above 100 quanta; counters included as receivers) are rebuilt together. Each row's change, less the flows shared with rows outside the set, is fitted by best subset (at most 4 columns). Terms within the row's tolerance are pruned backward. A row best subset cannot make near exact leaves the set. Terms are paired column by column into same-unit moves, with what is left going to declared estimated sides. A term with no place drops its row. The flows are refitted jointly under the floor and kept when every row is near exact and BIC gains 6 log n. none-short: all five request flows exact. | f76b167 | `moves.py` (`apply`), before rebuild.apply | Copy `moves.py` with `rebuild._best_subset` and `repair._fit`. Call it on the linear answer before any single-row rebuild. It is needed by every strategy whose rows come from the shared forward stepwise. |
| **coflow-earn** (proposed in 307) | A co-flow's draw is dropped when the drawn stock's row is no worse without it (BIC, log n). A draw that pays is written out as an outflow of the drawn stock at per x the flow's rate, where the boundary allows one. | f76b167, b6f2b6e | `moves.py` (`coflows`) | Any strategy whose base writes `uses` (the vendored-combined family, lna family) and whose post-stages read rows with an `_amount` that returns None for co-flows. |
| **room: replace a stand-in** | room.py may replace a plain proportional or linear move X -> B already in the answer. Candidates are ranked with the free flows of the two rows projected out (a linear refit). theta's grid reaches all but the top 5 steps. c and theta are chosen on the untrimmed BIC (`OBJ`); `polish()` refits the numbers last, with the kills in. A candidate whose move number comes out ≤ 0 is skipped rather than ending the search. | f76b167, b6f2b6e | `room.py` | Copy room.py's `_free_basis`, `_theta_q`, the `plain_mv` replacement and OBJ. Regression risk: 311's round 1 chose the trimmed objective (an untrimmed room was 4.96 nodes - 1.26 ready). polish() now corrects the numbers, but 311 has not been re-run. |
| **counted: stand-in move, free knots** | A plain move into a counter is one more rate the counted fit must beat (it was a blocker). The table's inner knots are refined one at a time by golden section on the NNLS SSE. | b6f2b6e | `counted.py` (`_refine`, movers) | combined2's `counted.py`, milp `effects.py` and engine_forms `_table`: refine the quantile knots, and do not treat a plain counter inflow from a stock as "the counter has a move". |
| **hidden-delay stage** (new) | For a measured stock with an estimated outside inflow whose row is far from exact: inflow = H/tau, with H' = H + max(0, c + w.X) - H/tau and H0 ≥ 0. The outflow is a floored gap `max(0, c' + w'.X)`. Both blocks' columns are chosen forward on BIC (pairs on the first step), on a tau grid, then tau is refined by golden section and the columns pruned. Gauss-Newton runs on the hinges, with the inflow block's columns passed through the stage's first-order filter (`scipy.signal.lfilter`). The stage is kept when it beats both the answer's row and the same search with no stage by 6 log n. It is written as a found hidden stock `delay_S` (outside -> delay_S as an expression, delay_S -> S at 1/tau), and the scorer reads it as a hidden path. none-short: tau 2.0065; none-long: 2.00002. | f76b167, b6f2b6e | `delay.py`, after room.polish | Copy `delay.py` (it needs `hidden._amount`, `repair._fixed_side/_numbers/_sign`, `steps`, `exprs`). Call it last, after every stage that rewrites the rows it reads. It is needed by every strategy: no top-5 strategy wrote the stage on 312 (`diff --summary`: 9 of 10). |
| **subterm columns** | The stage's columns include each floored term `max(0, ...)` the answer's expressions already carry (the room the polished room move computes), written inline. The autoscaler asks for `pending - room`. | b6f2b6e | `delay._subterms` | Any row search that offers levels as columns can offer the answer's own `max(0, ...)` terms (evaluated by `exprs.amount`). |
| **goal-floor gap** | A floored outflow whose own-stock term is positive is refitted as `max(0, min(k S + rest, k S - m))`, a gap whose goal has a floor L = m / k. It is fitted by active-set Gauss-Newton over three regimes, and its columns are chosen forward with S always in. It is kept on BIC > 6 log n. none-long: floor 1.999997 (truth 2), `0.05 nodes - 0.025 ready - 0.025 pending`. | b6f2b6e | `delay._floor_goal`, `_clamped` | The same block suits floor.py's floored sides in any strategy (combined2 hinge.py, milp hinge.py, kalman_lna rows.py). The HPA's `max(3, ...)` is the same shape. |
| **guards** | moves/delay/room/counted keep the answer on any exception (try/except as elsewhere). Debug output is env-gated (`SDLAB_MOVES_DEBUG`, `SDLAB_ROOM_DEBUG`). | both | | |

## Risks and what is not done

- **No regression run** (per the plan). The largest risks are room.py's untrimmed objective and plain-move
  replacement (311, 310: 311 none-long passed with the trimmed fit), capmin's smaller share (every case with a
  MIN offer), and moves.py on any case with two or more far-off rows.
- The run time grew: none-long took 569 s on node2 (was 380 s at f76b167). The case timeout is 1800 s.
- The found `outside -> desired` reads `retries / 4.483` on none-short in some runs (the controller picks among
  collinear drivers). The whole-flow comparison passes. It is not fixed.
- counts-long's `outside -> pending` gap and mem drain are not diagnosed (data-limited, not a target).
- **Harness (reported, not changed):** the whole-flow comparison of a truth `flow(X)` counter uses the engine's
  limited amounts (see above), so 312 none-long cannot be passed by a counter written as a rate.
