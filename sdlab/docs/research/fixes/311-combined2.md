# 311 (k8s-node-pool), combined2, round 1 (2026-10-22, agent combined2-311-r1)

**Status: combined2 passes every achievable variant of 311.** none-short and none-long PASS 26/26 at afb19cf (pool
job 301). counts-short and counts-long fail and are **data-limited on the OOM move**, as on 310 (measured below), so
they are not targets.

| variant | achievable? | before (cae16d8, store) | job 296 (2c902c6) | job 298 (f6ac855) | job 301 (afb19cf) |
|---|---|---|---|---|---|
| none-short | yes | FAIL (pods block, OOM, mem) | **PASS 26/26**, 251 s | **PASS 26/26** | **PASS 26/26**, 251 s |
| none-long | yes | FAIL 12/23, 562 s | **PASS 26/26**, 517 s | FAIL (deletion, OOM move, mem drain) | **PASS 26/26**, 548 s |
| counts-short | no: OOM move 15.4% off at the free-knot ML optimum (tol. 10%) | FAIL | FAIL 9/23, 174 s | FAIL 9/23 | FAIL 9/23, 174 s |
| counts-long | no: OOM move 17.2% off at the free-knot ML optimum | FAIL | FAIL 6/23, 433 s | FAIL, 4 values wrong | FAIL 15/23 (recall and precision 100%: 4 values wrong), 423 s |

Commands: `uv run sdlab-ladder job 296` / `298` / `301`, `uv run sdlab-ladder show 311-k8s-node-pool --strategy
combined2 --variant V` and `diff ... --variant V` (read 2026-10-22). Job 298's none-long failure was real, not load:
the linear fit at f6ac855 had written the pods' limit series into ready's outflow and left no `pending -> ready`
move, so counted could not place the OOM move (traced locally). The fix is limit-placement (below). With it, the
post-linear pipeline passes 26/26 on all three linear answers traced this round (two none-long, one none-short;
scratch `c2_311/fromlin.py`).

## Diagnosis (rule 4b)

`analyse` says "not analysed" on the counts variants (a hidden stock and a table), and on the none variants gives
only the usual collinearity notes (no data limit). The diffs at cae16d8:

- **The pods block (a method fault, every variant).** The new rung's start is `min(0.5 pending, max(0, 4 nodes -
  ready))`, and it binds on 172 of 299 steps (none-short) and 1,094 of 1,999 (none-long): it is the pods block, not
  a corner. capmin offered only one limit (the best by its kink: `queue -> inflight`, MIN(queue, 66.7 ready)) and
  only of the form MIN(X, theta Y), so the start was fitted as `0.012 x pending` (none-short) or `-0.03 x pending`
  (none-long) and the rest of the block bent around it (created at -21.6 x pending, the HPA switches lost on
  none-long).
- **The rows read node failures as flow (a method fault).** `hinge.columns` / `row_error`, which every post-pass
  uses (hinge, switch, counted, rowrepair, hiddenrow), took each step's change as it was, with no announced
  injection taken off: the 3 pods moved ready -> pending and the node lost at t = 130 (706, 1282) were read as
  flows.
- **No pass could evaluate a MIN.** `hinge.amount` returned None for an expression rate, so after capmin.restore
  the rows of queue, inflight, pending and ready could not be evaluated, and counted could not place the OOM move
  on ready / pending (the peers it tries must have rows it can evaluate).
- **Oracle check (scratch, not a result):** the traced none-short answer with only the true start put in, then the
  tail passes (counted, rowrepair, hinge, hiddenrow): PASS 26/26. So these three were all that stood in the way.
- **counts-short and counts-long: data-limited on the OOM move.** As on 310 (`310-combined2-r2.md`): the truth's
  model with only the kill table fitted to the measured `diff(oom_kills_total)` by Poisson maximum likelihood
  (scratch `c2_311/freeknot.py`, the 310 r2 script on 311): counts-short (4 kill steps, 9 kills) free knots
  15.4% off, capped free knots 15.4%, even the true knots 16.4%; counts-long (46 kill steps, 88 kills) free knots
  17.2%, capped 17.2%, true knots 6.5% (pass only with the truth's knots given, which no method has). The free-knot
  fits have higher likelihood than the true-knot ones (52.99 vs 53.79 -log L on counts-long). Tolerance 10%, no
  standard-error allowance. Neither counts variant is a target (the proxy's 310 rule: data-limited by a measured
  bound).

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|---|---|---|---|
| headroom-limit | `capmin.offer`: a capacity may be the room left in a pool, `MIN(X, theta x max(0, beta Y - Z))`, Z a non-final stock of X's unit (the room is in X's unit), Y any measured stock or input; beta from quantiles of Z / Y (and 5% past the largest) then golden section, theta by golden section inside; the same gain, kink (against every product of two columns), share and receiver rules as the plain MIN(X, theta Y), and the best of both kinds by kink. The residual sums of squares are by projection on the fixed design (`_Proj`, rss(B + m) without a refit), which keeps the larger search at 31 s (none-short) and 97 s (none-long). Restored as `min(k * X, max(0, k theta beta * Y + -k theta * Z))`. Found here: pending, nodes, ready, receiver ready, beta 3.98 / 3.93 | 2c902c6 | copy combined2's `capmin.py` (its `offer`, `_search`, `_judge`, `_Proj`, `_room`, `_min_text`, `restore`); a strategy that passes the cap to oefit passes `capmin.plain_cap(cap)` |
| several-limits | `capmin.offer` runs the search again with each limit found among the design's columns, for a source not yet limited, up to MAX_LIMITS = 3; the first is returned as before, the others under `cap["more"]`, every one registered in `opts["capmin"]` (its readers: its source and receiver) and written back by `restore` | 2c902c6 | as above |
| injection-aware-rows | `hinge.columns` returns `Levels` (a dict with `inj`: each stock's announced injections a step, the engine's convention: added before the step's flows) and adds them to the levels the step's rates read; `hinge.delta(levels, x, n)` is the change less them. Every row in hinge, switch (now built on `hinge.columns`), counted, rowrepair and hiddenrow uses `delta`, and rates read `cols` (not the raw levels) | 2c902c6 | any copy of hinge.py and the passes on it: replace `np.diff(levels[x][:n + 1])` by `hinge.delta(levels, x, n)` and `levels[a][:n]` read as a rate by `cols[a][:n]` |
| expr-amounts | `hinge.amount` evaluates an expression rate of numbers, measured names, + - * /, unary minus, min and max (`hinge.expr_amount`, a small AST walker); one with a comparison (a switch), `ceil` or an unmeasured name is still not evaluated, so switch rows stay out of the refits | 2c902c6 | copy `expr_amount` and the `amount` change into the strategy's hinge.py |
| limit-refit (minrefit) | `minrefit.py`: for each move written as a limit, `min(k * X, c * Y)` or `min(k * X, max(0, a * Y + b * Z))`, on the block of its unit (non-final rows the passes can evaluate): the limit's numbers and the block's free linear flows (counted's rule) fitted together by active-set least squares (the limit's steps split into the demand arm, the capacity arm and the capacity's floor, each free flow's into where it is positive, refitted until they settle), alternated 4 times with the floored side refit (`hinge.refit_row`), then a backward elimination: each term of the block's free flows (a flow's last term: the flow) dropped in turn, the rest refitted jointly, kept where the block's BIC falls. Kept only where the block's BIC falls against the answer as it came. On none-long it dropped `12 - 4 nodes` from the deletion and a junk `pending -> ready = 0.001 nodes` that made up for a limit 1-2% off, and the start came out `min(0.5000 pending, max(0, 4.0000 nodes - 1.0000 ready))` | 2c902c6 | copy `minrefit.py` with counted.py and hinge.py; call `minrefit.apply(r, stocks, run, opts)` after the passes that place the block's other flows (combined2: after the last `hinge.apply`, before `hiddenrow.apply`) |
| limits-in-repair | `counted._repair_once`: where the rows hold a limit, it and the moves are refitted together (`_refit_limits`, minrefit's joint fit) in place of `_refit_moves` (the moves alone, with the rough limit held, fell into a worse active set: none-long rows SSE 0.038 -> 104), and the best of the rounds is kept. Without it counted judged every OOM placement with the offer's rough limit and chose "none" on none-long | 2c902c6 | strategies with combined2's / structures' `counted.py`: the `_refit_limits` and `_repair_once` change (needs minrefit.py) |
| limit-placement | `capmin.place`, right after the linear fit: each offered series is read only by the flow it limits, the move from its source to its receiver. Its terms in any other flow are dropped (a flow left empty goes), and the move is added where it is missing, at the coefficient the offer fitted on the source's row (`k`). A limit with no receiver is never added (an outflow may not be declared). Job 298's none-long had the pods' limit at -0.51 x the series on ready's outflow and no start move; the queue's limit also sat in mem's drain on every none-long trace | afb19cf | copy combined2's `capmin.py` and call `capmin.place(identify(...), cap)` before the passes that refit the rows |
| limit-series-not-input | `boundary.Data.outside`: the measured inputs from outside, without capmin's offered series; every "measured" kind, the declared input side's choice (`enforce_sides`) and the measured-inflow candidates use it. With three series offered, job 296's counts-long had queue's declared input fixed at 1 x the pods' limit series | f6ac855 | any boundary.py copy in a strategy that offers capmin series: `self.outside` in `Data` and `set(data.outside)` for `set(data.inputs)` |

Tests: `tests/test_limits_combined2.py` (5: a waiting / running / hosts pool with a host failure as injections; the
rows take the injections off exactly; MIN/MAX expressions evaluated, switches not; the headroom limit offered with
beta within 0.2 of 4; the limit's numbers refitted exactly from 0.61 / 3.83 / -0.96; an offered series dropped from the flows it does not
limit and its move added). Before each commit these passed
with `tests/test_counted_combined2.py`, `test_rowrepair_combined2.py`, `test_hinge_combined2.py`,
`test_switch_combined2.py`, `test_hiddenrow_combined2.py`, `test_isolation.py`, `test_frozen.py` (18), and after the
boundary change the seven `tests/test_boundary_*` / `test_composites_boundary.py` files (409 passed).

Local diagnostics, not results: the pipeline traced stage by stage on none-short and none-long (scratch
`c2_311/trace.py`, single-threaded), the tail passes re-run on the traced stages and re-scored (`c2_311/post.py`):
none-short and none-long 26/26 in the pipeline's order before the pool job.

## What is left, and risks for the regression run

- **counts variants (not targets):** counts-short is 9/23 at afb19cf; its diff went from "1 removed, 2 added, 6
  values wrong" at cae16d8 (result #386923) to "2 removed, 4 added, 5 values wrong" (#386964): worse. On counts-short the headroom search offers weak limits first (`desired` under `max(0, 0.005 cpu - pending)`, share
  0.05; `queue` under `max(0, 242 nodes - retries)`), which the fit takes up. counts-long at afb19cf has the whole structure (recall and
  precision 100%); its four wrong values are the OOM table (36% off: the data limit), mem's drain (0.29 against 0.5:
  the one-step fit of a fast row under counting noise, `hidden-row-output-error` in 310-combined2-r2.md), and cpu's
  two numbers 11% off (1.11 x inflight, 0.446 x cpu; not diagnosed). A price on the headroom limit's extra number (beta) in the offer, or a kink margin over the plain form, is
  the obvious next step; it changes what is offered everywhere, so it belongs with the regression / noise round.
- **Regression risks (no earlier rung was run, by the plan):** (a) the injection-aware rows change every post-pass
  on a case with injections (rung 023-injection, any k8s rung with injections); (b) `hinge.amount` now evaluates
  MIN expressions, so the floored refit and counted now see rows of queue / inflight they skipped before (306-310);
  (c) capmin may now offer up to three limits, and a headroom one, on any case: the linear fit is offered more
  series; (d) counted's repair keeps the best round. 306-310 are the first to check.
- (e) capmin.place drops an offered series from every flow but the one it limits, on every case with a limit
  (306-310: queue's limit read by other rows).
- The capmin offer now costs 31 s (none-short) / 97 s (none-long) on 311 (14 stocks); none-long ran 548 s of 1800 s.
