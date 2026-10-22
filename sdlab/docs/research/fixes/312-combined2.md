# 312 (k8s-cluster-autoscaler), combined2, round 1 (2026-10-22, agent combined2-312-r1)

**Status: combined2 passes none-short (28/28 parts) at f75e454 and at 98b6324.** The other three variants fail. None
of them is achievable, and each limit was measured (below): counts-short and counts-long are **data-limited on the OOM
move**, as on 310 and 311. none-long is **score-limited**: the counter `oom_kills_total` is `flow(oom_killed)` in the
truth, and a found model cannot express that. Even the truth's own formula for it fails by 2.02%. One harness fix is
needed (last section).

| variant | achievable? | before (22ef051, store) | job 306 (f75e454) | job 311 (febd195, has 98b6324) |
|---|---|---|---|---|
| none-short | yes | FAIL: 3 removed, 2 added, 3 values wrong (#386978) | **PASS** (#386994) | **PASS**, 622 s (#387013) |
| none-long | no: the counter part is 2.02% off even for the truth's formula (tolerance 2%) | FAIL: 8 removed, 10 added (#386982) | FAIL 24/28: pods block, nodes (#386997) | FAIL 22/28: retries block, the OOM move 2.2% off, counter (#387017), 1005 s |
| counts-short | no: OOM move 32.9% off at the free-knot Poisson ML optimum | FAIL (#386974) | FAIL | FAIL (#387012) |
| counts-long | no: OOM move 19.2% off at the free-knot ML optimum; 12.3% even with the true knots | FAIL (#386984) | FAIL | FAIL: 4 removed, 1 added, 1 value wrong (#387016) |

Commands: `uv run sdlab-ladder job 306` / `job 311`, `uv run sdlab-ladder diff 312-k8s-cluster-autoscaler --strategy
combined2 --variant V`, `show ...` (read 2026-10-22).

## Diagnosis (rule 4b)

`analyse` reports "not analysed" on every variant (hidden stocks and a table). The rung's new parts are a DELAY1
provisioning stage feeding `nodes`, and `removed = 0.05 max(0, nodes - max(2, pods / 2))`. The faults found:

- **Nodes' inflow arrives through a hidden stage (method fault, every variant).** No pass could write it, so the rows
  wrote nodes' sides as linear drift (`outside -> nodes = -4.99 - 0.001 errors_total + 0.013 mem + 0.003 traffic`).
  Oracle check (scratch `c2_312/lagtruth.py`): the truth with nodes' sides replaced by junk, then lagrow, gives PASS 28/28 on
  none-short and none-long.
- **On none-long the removal's floor `max(2, ...)` binds on 84 steps.** A single floored rate fails there by 40.5% (as a
  whole). The floor never binds on none-short, so a single floor passes there.
- **The 312 limits bind rarely (method fault).** The cluster autoscaler adds nodes, so dispatch binds on 1.4% of
  none-long's steps (2.3% on none-short) and the pods' start on 4.6% (7.0%). Both are under capmin's 5% regime share.
  Only junk limits were offered on none-long: inflight -> nodes (a move across units) and retries -> ready.
- **A cross-unit move from the linear specialist.** On none-long, lna wrote `nodes -> ready`. That poisoned ready's row,
  so minrefit could not refit the pods' start.
- **A refined headroom offer could flip sign**, and `ready -> pending` was offered as a limit with k < 0.
- **counts variants: data-limited on the OOM move.** I ran 311's `freeknot.py` on 312 (scratch `c2_312/freeknot.py`): the
  truth with only the kill table fitted to `diff(oom_kills_total)` by Poisson ML.
  - counts-short: 7 kill steps / 19 kills. Free knots 32.9% off, capped 31.7%.
  - counts-long: 50 kill steps / 128 kills. Free knots 19.2% off, and even the true knots 12.3% off.
  - The free-knot fits are more likely than the true-knot ones. The tolerance is 10%.
- **none-long: the counter cannot pass.** In the truth, `outside -> oom_kills_total` is `flow(oom_killed)`, the realised
  flow. The engine scales ready's outflows when they exceed ready, so the realised flow differs from the rate formula.
  A found model reads `flow(id)` as 0 (`sim._ExprRate`), so a found model cannot write it. Scoring the truth with the
  counter written as its own formula (`1 x ready x table(mem)`) gives FAIL on none-long: `outside -> oom_kills_total [as
  a whole]` is 2.02% off. none-short passes because its scaling does not bite. With the fixes below, the post-linear
  pipeline on a traced none-long linear stage (scratch `c2_312/fromlin.py`) gets 27/28: everything except this part.
  The pool run at febd195 got 22/28 because its linear stage differed (retries block, a residual junk limit). That is
  not diagnosed, since the variant is not a target.

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|---|---|---|---|
| hidden-stage-inflow (new) | `lagrow.py`: a stock S's open outside inflow, where the row is unexplained, refitted as a DELAY1. The order u = max(0, c + w.Z) enters a hidden stage H, H' = u - H/tau, and S receives H/tau. For fixed tau and an active set, the inflow is linear in (c, w) through the filter (`scipy.signal.lfilter`), so u is fitted by active-set least squares. The out side's arms are refitted jointly in the same least squares. tau comes from a grid (1.25-14) and then golden section. Columns are chosen by forward BIC (up to 3) from the measured levels, inputs, and the **rooms** `max(0, aY + bZ)` of the model's own capacity limits. In and out alternate 4 times from two starts. The stage is kept where the row's BIC falls by 2 log n against both the model's sides and the same fit without the stage. Its `inferred_levels` are written. Found on 312: tau 2.0000, order 0.0750 pending - 0.0750 room | f75e454 (tau guard 98b6324) | copy `lagrow.py` (needs hinge.py's `columns`/`row_error`/`delta`/`fit_side`/`allowed_sides` and minrefit's `parse`); call `lagrow.apply(r, stocks, run, opts)` at the end of the pipeline, after any hidden-integrator pass |
| two-arm-floor (new) | `lagrow._two_arm`: an out side as `max(0, min(arm1, arm2))`. arm1 is one column plus a constant, arm2 is the single floored fit. Regimes come from active-set least squares started where the single floor overshoots. arm2's columns are re-chosen off arm1's steps (`hinge.fit_side`), up to 3 rounds. It is kept where BIC falls by 2 log n. none-long: `max(0, min(0.05 nodes - 0.1, 0.05 nodes - 0.025 ready - 0.025 pending))` | f75e454 | inside lagrow.py; usable alone via `lagrow.fit_out(y, pool, n, floor)` |
| limit-receiver-unit | `capmin._judge`: a limit's receiver must be a stock of the source's unit (the user's rule: a move carries one thing) | f75e454 | copy the `units` argument and check into the strategy's capmin.py |
| limit-min-steps | `capmin._lo`: a regime must hold on at least `MIN_STEPS` = 6 steps (still capped at 5% when that is less), and the theta grids span the same quantiles. The kink and gain stay the evidence | f75e454 | replace MIN_SHARE in the grid quantiles and the share check by `_lo(T)` |
| limit-sign-kept | `capmin._judge`: after the refine, the limit must still take from its source (k > 0) and enter its receiver | f75e454 | the two-line check after `gain > price and kink > price` |
| four-limits | `capmin.MAX_LIMITS` 3 -> 4: none-long's pods' start came 4th, after dispatch and two weaker offers | 98b6324 | constant |
| one-unit-moves | `combined2.one_unit_moves`, right after `capmin.place`: a move between measured stocks of different declared units is dropped, and the later passes refit the rows it touched (none-long: lna's `nodes -> ready`) | 98b6324 | copy the function; call it on the linear answer before the row passes |
| idle-flows-dropped | `combined2.idle_dropped`, last: a flow between measured stocks (or outside) whose evaluated amount is 0 on every step is removed (a limit whose room `max(0, -6e-7 mem - 0.118 pending)` is never open) | 98b6324 | copy the function (uses hinge.amount) |
| hiddenrow-per-stock | `hiddenrow.apply` no longer returns when the model has any hidden stock. It skips only the stocks that exchange with one | 98b6324 | the 3-line change in hiddenrow.py |

Tests: `tests/test_lagrow_combined2.py` (2). The first is a staged host pool: tau 3, `0.1 max(0, demand - 8)` orders, and
a two-arm leave, all recovered exactly (SSE 3e-27). The second has the same pool without a stage, and lagrow leaves it
alone. With them, the combined2 files `test_limits`, `test_hiddenrow`, `test_counted`, `test_rowrepair`, `test_hinge` and `test_switch`,
plus `test_isolation` and `test_frozen`, gave 21 passed before each commit.

## Left, and risks for the regression run

- **Harness fix needed (not mine to make):** a found model cannot express a counter of another flow (`flow(id)` reads
  as 0 in `sim._ExprRate`). Either a found `flow(id)` should read the found flow's realised amount, or the scorer should
  compare a truth `flow(id)` counter with the found flow's realised amount. Until then, 312 none-long cannot pass for
  any strategy: the truth's own formula fails by 2.02%.
- **Regression risks (306-311 not run, by the plan):**
  - (a) capmin now offers limits that bind on as few as 6 steps, up to 4 of them. More junk limits are possible on
    every case with a limit.
  - (b) one_unit_moves drops any cross-unit move the linear fit writes.
  - (c) lagrow may stage a row on other cases. It must beat the unstaged refit by 2 log n, and a tau at the 1.15
    bound is refused.
  - (d) idle_dropped removes flows that are zero on the record, so a floored flow that never opens on a short run goes.
- Run time: none-long took 1005 s of 1800 (lagrow costs about 50-170 s on none-long, mostly the two-arm and out-side
  searches).
