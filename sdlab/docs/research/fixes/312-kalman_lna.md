# 312 (k8s-cluster-autoscaler): kalman_lna, round 1 (2026-10-22, agent kalman_lna-312-r1)

**Status: kalman_lna passes 312 none-short (28/28, ac5443e, pool job 313).** none-long gets every part right but one,
27/28. The miss is the scorer's: at the announced injections it evaluates the found counter on the levels before the
injection (item 7 below), and the truth's own equations miss that part by the same 2.018%. So no strategy can pass
none-long until the harness is fixed. counts-short and counts-long fail. Both are data-limited in the OOM part, so they
are not targets. Of the achievable variants, none-short passes, and none-long is blocked by the scorer.

## Where the numbers come from

- `uv run sdlab-ladder show|diff 312-k8s-cluster-autoscaler --strategy kalman_lna --variant V` (before: code 22ef05156f,
  the stored main-line rows of 2026-10-22 10:11-10:23Z).
- `uv run sdlab-ladder submit --strategies kalman_lna --cases 312-k8s-cluster-autoscaler --variants
  none-short,none-long,counts-short,counts-long --priority 400 --by kalman_lna-312-r1` (job 312 at febd195), then
  `uv run sdlab-ladder job 312 --wait` (attempt 1, febd195) and job 313 (attempt 2, ac5443e).
- Local checks ran on cached pre-rows answers (the strategy up to `rows.revise`, then rows and tracker, scored with
  `score.score`). Scripts were in the agent's scratchpad, not committed.

| variant | achievable? | before (22ef051) | job 312 (febd195) | job 313 (ac5443e) | complexity (truth 73) |
|---|---|---|---|---|---|
| none-short | yes | FAIL 20/28 | **PASS 28/28** (node2, 441 s) | **PASS 28/28** (Mac, 125 s) | 67 |
| none-long | yes, but blocked by the scorer (7) | FAIL 12/28 | FAIL 18/28 (node2, 725 s: the 400 s rows budget ran out) | FAIL **27/28** (Mac, 530 s): only `outside -> oom_kills_total [as a whole]`, 2.018% vs 2% | 65 |
| counts-short | no: data-limited (8) | FAIL 7/25 | FAIL 7/25 (Mac, 182 s) | FAIL 7/25 (Mac, 180 s) | - |
| counts-long | no: data-limited (8) | FAIL 12/25 | FAIL (node2, 1195 s) | FAIL 8/25 (Mac, 1030 s) | - |

ac5443e has not run on node2. Job 312 showed that node2 runs this strategy up to 3 x slower than the Mac. The rows budget
is now 600 s for a pass that takes 272 s on the Mac (single-threaded), so the margin should cover node2. That is not
proven until a run lands there.

## Diagnosis (rule 4b)

`analyse 312 --variant none-*` reports "hidden stock without noise: exact if identifiable". For counts-* it reports
"not analysed". Before this round, none-short failed 20/28 and none-long 12/28.

1. **queue -> inflight = min(0.6 queue, 40 ready) was lost on both none variants. This was a method fault.** The limit
   binds on 7 of 299 steps (none-short). capmin's theta grid and its regime check both ask for 5% of the steps (15),
   so the best theta it could offer was 61.24 (the grid's last point) instead of 66.67. The base search then read
   `queue -> inflight = 0.599 queue + 2.06 nodes`. That broke the queue and retries rows (`retries -> outside =
   -0.08 queue + 1 retries`). rows.py could not mend it either: it never sees capmin's series, and its own capped
   search runs once and was taken by the pod MIN.
2. **The nodes row had no form for a hidden DELAY1. This was a method fault.** The truth is
   `nodes' = 0.5 H - 0.05 max(0, nodes - max(2, (ready + pending) / 2))` with
   `H' = 0.075 max(0, pending - max(0, 4 nodes - ready)) - 0.5 H`. rows.py offered a schedule (15 blocks) and a junk
   outflow. A schedule standing in for hidden state is "fits, not robust" (the user's rule), so it can never pass.
3. **The removal's threshold is itself floored, max(2, pods / 2). This was a method fault on none-long.** The
   `max(2, ...)` binds on 84 of 1999 steps (ready falls to 3 while nodes drain). A single floored-linear outflow is 40%
   off there (rms). On none-short it never binds.
4. **The order's form is not exactly floored linear at the injections.** `max(0, pending - max(0, 4 nodes - ready))`
   equals `max(0, pending + ready - 4 nodes)` except where ready > 4 nodes. That happens on 2 steps of none-short,
   after the node-loss injections. An output-error fit carries those 2 steps' misfit through H for about 10 steps
   (0.045, 0.03, ...). It pulled every number: the delay to 2.10 and the order to 0.063 instead of 0.075.
5. **The data's rounding.** Levels are reported to 4 decimals. nodes holds exactly still for hundreds of steps, so the
   usual noise scale (the median of the smaller half of |r|) is 0 there, and the floored term's step threshold falls
   below the rounding. On none-short, 8 rounding steps joined the 20 real removal steps and the search read
   `(queue, ready, nodes)` for the true `(ready, pending, nodes)`.
6. **A rebuilt queue inflow read 1.0000034 x traffic.** That breaks the declared `input` rule (exactly 1 x the
   series), so it fails the result. rows.py rebuilt the queue's inflow side once its row was rebuilt.
7. **none-long: one part is the scorer's, not the method's (harness; reported, not fixed).** With everything else
   right, `outside -> oom_kills_total [as a whole]` misses by 2.018% against the 2% allowed. The found counter
   `0.009375 ready x table(mem)` matches the data to 1e-4 rms (relative). At step 704 (and 1280), the engine's
   recorded counter (`data["counters"]`, which `sim.amounts` uses for the truth's `flow(oom_killed)`) is computed
   after the injection at t 706 (ready - 3): 0.4144. The found flow is evaluated by `score._levels_at` on the level
   before the injection: 0.5191. Rows read the states with injections added (the engine's convention), and so do
   the data. milp (d0e2b96) and engine_forms (312-engine_forms.md) found the same miss: the truth's own counter,
   written as `ready x table(mem)`, fails it by 2.018%. **Needed fix (harness, not this agent's):**
   `score._levels_at` should add the announced injections to the levels a step's rates read, as `rows._data` does.
   Until then no strategy can pass 312 none-long.
8. **counts-short and counts-long: data-limited in the OOM part, so not targets.** They have the same OOM sub-model as
   310 and 311. counts-short has 19 kills on 7 steps, so the kill rate's relative SE is 1/sqrt(19) = 23% against
   10%. counts-long has 128 kills on 50 steps (8.8%), with mem up to 562, past the 512 and 560 corners. On 311 the
   truth's own table, refitted by free-knot Poisson ML at the same kill counts, missed the OOM move by 15-17%
   (311-combined2.md, 311-kalman_lna-r2.md). This round did not re-measure that bound on 312.

## Fixes kept (commits febd195 and ac5443e)

| type | mechanism | cells | how another strategy adopts it |
|---|---|---|---|
| **hidden delay** (new; the hidden-stock write-out of 310, generalised from a constant inflow to a floored order) | `delayed.py`, called from `rows.row` (`_with_delay`) on any row with an inflow side whose plain row and schedule or integrator are not at rounding. The model is `dS = a H + X_A lin - out` with `H_{t+1} = (1-a) H_t + max(0, C . x)`. (1) For each decay a on a 20-point log grid from 1/50 to 1, the order is read by **inverting the delay**: `u_t = (v_{t+1} - (1-a) v_t) / a`, with v the row less the current outflow. Every reader subset up to 3 (levels, inputs, a constant) gets a quick Gauss-Newton hinge fit. The best 6 at the 3 best decays are polished by **least trimmed squares on the full hinge loss** (scipy LM, refitted with the worst 5% of steps left out). The off steps pin numbers that the placed steps alone leave collinear. (2) The decay and the readers are chosen on the **one-step (equation) error**, trimmed 5%, so the hidden stock does not carry a misfit forward. Then a is refined by golden section, and a reader that does not pay log n is dropped. (3) The outflow and the linear part are read off the **one-step inflow** `v^_t = (1-a) v_{t-1} + a u^_{t-1}`. The steps an order misfit reaches are left out (a step it misses by more than 10 x the trimmed rms, until `(1-a)^k < 1e-3`), but never where the current outflow acts. They are polished on the one-step error (LTS). (4) This is done from two starts: the current outflow, and one read off the run's error. Rounds are compared on the one-step error. (5) Terms that do not pay are pruned. (6) It is kept where it beats the plain row by PRICE log T and the row's other forms by BIC. (7) It is written as the model's own hidden stock: `outside -> S_hidden` at `max(0, C . x)` (an expression, so the order's numbers are not scored), and `S_hidden -> S` at `a S_hidden`. Its levels go in `inferred_levels`. The joint `_together` refit leaves the row's flows alone, because its run error carries H's misfit. | none-short (with the two below) | Copy `delayed.py` and kalman_lna's rows.py from febd195 or later (`_with_delay`, `_delay_flows`, `_two_floors`, the `delay` branches in `_build` and `_together`, and the `full` levels block in `revise`). A strategy without rows.py can call `delayed.fit(X, y, floor, deadline, a_cols, b_cols, floored)` on any stock's one-step change, given a floored-row search `floored(z, a_cols, keep)`. The key ideas port on their own: read a DELAY1's input by inverting it, choose it on the equation error with trimming, and read the outflow off the one-step inflow. |
| **two-floor outflow** (the floored-rate family, type 3) | `delayed._second`: an outflow floored twice, `max(0, min(B . z, D . z))` (a threshold with its own floor, as `nodes - max(2, pods / 2)`). It is started on the steps the first floor overstates. Every D subset up to 3 readers is tried, the two regimes alternate (each active step goes to the lower arm), and it is kept on BIC by log n. It is written as one expression. | none-long's removal (not a pass, see 7) | `_second` with `outflow`/`rest` from delayed.py. It applies to any floored-row fit (combined2 `hinge.py`, structures `floor.py`, rows.py's `_floored`) as one more candidate after the single floor. |
| **offered limit in the rows** (capped move, 311) | `rows.revise(..., offered=cap)`: the `MIN(X, theta Y)` that capmin offered the base fit becomes a capped derived column of the rows, `min(1 X, max(0, theta Y))`, before the rows are read. It is marked `offered`, so the capped search still runs once for a limit of its own (here the pod MIN). | both none variants | Pass capmin's `cap` into whatever reads rows after the base fit, so a limit the base leaves unread is not lost. |
| **limit on few steps** (capmin guard, type 5) | `capsteps.py` is kalman_lna's variant of capmin.py (capmin.py itself stays identical to the other strategies' copies). The theta grid runs from quantile `min(5%, 5/n)`, and a regime needs `min(5% of T, 5)` steps, not 5%. The kink test (beyond every product of two levels) still has to pass. 312 none-short: theta 61.24 -> 66.667. | both none variants | Two lines in any capmin copy (structures and combined2 made the same change in f76b167 / f75e454, with 6 steps). |
| **resolution with exact zeros** (noise floor) | `delayed.noise`: 4 robust SDs from the median of the smaller half of the **nonzero** sizes. `rows._floored(..., strict=(1, 4))` reads the floored term's steps at 1 and 4 times that threshold (only for the delayed fit's calls, so other rows are unchanged). | none-short | Any threshold built on the median of the smaller half of |r| is 0 when a level holds exactly still. Take it over the nonzero values. |
| **input side fixed** (boundary input-kind, type 0) | `rows._sides` gives no rebuilt flow a side declared only `input`, and `_build` keeps the 1 x input flow (`_fixed_input`) and subtracts it from the row. | both none variants | Any row rebuild: treat the input side as held, not refitted. |
| **Gram-matrix subset fits** (speed; prune-budget family, type 10) | `_hinge_readers` first fits each reader subset from the scaled Gram matrix of the acting steps (a k x k solve, with lstsq where it is singular). The top candidates are still refitted by least squares (`_joint`). There were 6.6 million `lstsq` calls on none-long, most of the rows pass's time. Commit ac5443e. | none-long's time | Any best-subset search that ranks subsets by a least-squares fit on one fixed set of steps. |
| **budget** | rows TIME 200 -> 400 s (febd195), then -> 600 s (ac5443e). On node2, job 312's none-long ran out of 400 s: its derived rounds were undone and the pod and mem rows were lost (18/28). On the Mac the pass takes 272 s. | none-long | Constant in rows.py. A slower worker loses whole derived rounds. A budget counted in work rather than seconds would make the result machine-independent (not made). |

Checks: `uv run pytest tests/test_kalman_lna_delayed.py tests/test_kalman_lna_capped.py tests/test_kalman_lna_rows.py
tests/test_kalman_lna_derived.py tests/test_isolation.py tests/test_kalman_lna_tracker.py tests/test_kalman_lna_boundary.py
tests/test_ladder_kalman_lna.py tests/test_capmin.py tests/test_frozen.py` gives 32 passed and 1 failed. The failure is
`test_capmin.py::test_copies_identical`: 4 distinct capmin.py texts among the 44 copies. It comes from other strategies'
312 changes (structures f76b167, combined2 f75e454 edited their capmin.py). kalman_lna's capmin.py is unchanged; its
variant lives in capsteps.py. The new `test_kalman_lna_delayed.py` uses a synthetic machines/backlog case with its own
numbers: 4-decimal levels, injections, and orders and retirements both active. It checks the delay (0.25 +- 0.005), the
order's readers and numbers, the hidden-stock write-out, the fixed input side, and capsteps on a limit binding on fewer
than 5% of the steps (the old capmin fails that test).

## Risks and not done

- **No regression run on earlier rungs** (the plan: once, later). These changes reach every case rows.py sees:
  - the delayed form is tried on every unexplained row with an inflow side (kept only on BIC by PRICE log T);
  - capsteps offers limits that bind on as few as 5 steps (the kink test still guards);
  - the offered limit is a rows column;
  - TIME is 400 s.

  309-311's mem integrator rows are unchanged where the integrator is at rounding, because the delayed fit is
  skipped there.
- Discovery time goes up. On the Mac: none-short 125 s, none-long 530 s, counts-long 1030 s (the limit is 1800 s). On
  node2 at febd195, counts-long took 1195 s with a 400 s rows budget. With 600 s it may come close to the limit there.
- **counts-long fell from 12/25 to 8/25** (not a target). The pod rows and queue -> retries are lost. The counts
  variants fail far beyond the OOM part (queue/retries, the pod gaps, nodes). Those are method faults under counting
  noise, and they belong to the deferred noise round (the 311-kalman_lna-r2.md risk about cancelling coefficients
  applies too).
- The order of the nodes inflow on none-long reads `0.075 desired - 0.3 nodes` rather than
  `0.075 (ready + pending) - 0.3 nodes` (desired = ready + pending once the creation gap closes). It is not scored (an
  expression inflow to a hidden stock, as in the truth), and it is behaviourally the same on the run. A regression
  or noise run may show the difference.
- The counts variants are left as research (the same OOM items as 310 and 311).
