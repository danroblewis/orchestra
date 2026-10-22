# 311 (k8s-node-pool): structures, round 1

**Status (2026-10-22, agent structures-311-r1): structures passes every achievable variant of 311.** none-short and
none-long PASS 26/26 at 542bc3d (pool job 299, both on the Mac). counts-short and counts-long fail. They are
data-limited by the same kill-rate bound as 310, so they are not targets. I kept four fixes, all inside
`sdlab/discovery/strategies/structures/`. I held the structures lock for the work and released it after the commit.

## Where the numbers come from

`uv run sdlab-ladder submit --strategies structures --cases 311-k8s-node-pool --variants
none-short,none-long,counts-short,counts-long --priority 400 --by structures-311-r1 --every-variant`, then
`uv run sdlab-ladder job N --json` (status, parts right, seconds, machine):

| variant | achievable? | job 294 (cae16d8, before) | job 299 (542bc3d, after) |
|---|---|---|---|
| none-short | yes | FAIL, 114 s, node2 | **PASS 26/26**, 130 s, Mac |
| none-long | yes | FAIL, 1159 s, node2 | **PASS 26/26**, 340 s, Mac |
| counts-short | no: data-limited | FAIL | FAIL 5/23, 251 s |
| counts-long | no: data-limited | FAIL | FAIL 14/23, 553 s |

Before the fixes, `sdlab-ladder diff 311-k8s-node-pool --strategy structures --variant none-short` showed
`pending -> ready` missing, both cpu flows replaced by `39.88 - 8.03 oom_kills_total` in and `139.1 - 38.2 nodes`
out, the HPA written as linear drifts, and mem's flows and the OOM kills lost.

**Achievability.** `analyse 311-k8s-node-pool` says "not analysed: a truth this analysis does not cover" on every
variant, so I applied the 310 bound. 311 carries 310's OOM structure unchanged (the same mem, leak and kill table).
Counting from the measured counter (`oom_kills_total` levels; my scratch script `kills.py`):

- counts-short: 9 kills on 4 kill steps. The kill rate's relative SE is about 1/sqrt(9), or 33%, against the 10%
  tolerance.
- counts-long: 88 kills on 46 kill steps, a relative SE of about 10.7%. That is the same regime as 310 counts-long
  (91 kills), where the kill flow reached 9.2% only with the truth's own knots given (310-milp-r2.md,
  310-combined2-r2.md).

job 299's counts-long diff fails on exactly that flow (`ready -> pending` table 13% off). It also loses
`outside -> pending` and `mem -> outside`. On 310 combined2 traced the mem drain to the kill table, but I did not
diagnose those two cells here, because they are not targets.

## Diagnosis (none-short, stage by stage; my scratch scripts `stages.py`, `post.py`, `cnt.py`)

1. **A fast-equilibrium row no single column explains.** The shared matrix's forward stepwise (regression.stepwise)
   adds one column at a time. cpu's change is a small difference of large terms, and no one of `inflight`, `ready`,
   `cpu` pays alone. The step-like columns `oom_kills_total` and `nodes` won the first two steps, and then nothing
   paid: the row had an SSE of 268148 against 0.054 for the exact three columns (`ss.py`). This was a method fault.
2. **Every post-stage was off.** A run with announced injections (311 is the first k8s rung with node failures)
   switched off controller.py, repair.py, hidden.py and counted.py for every stock (`if opts.get("injections"):
   return result`). The HPA therefore stayed a linear drift. This was a method fault.
3. **The room limit.** `min(0.5 pending, max(0, 4 nodes - ready))` is not a single-stock MIN, so capmin.py cannot
   offer it. I tried offering it to the base as a second capacity series. The shared matrix lets every row read an
   offered input, so its stepwise then broke rows the series has nothing to do with: inflight read `nodes` and
   `oom_kills_total`, and the queue MIN landed on `queue -> responses_total`. I reverted that and put the search
   after the base instead.
4. **The judge could not see expression rates.** The shared simulator (`simulate.Model` / `_Rate`) reads an
   `expr` rate as 0. Every stage after capmin.restore and controller.py was therefore judging a model without its
   MIN, controller and room flows. With the true kill table, the kill move made the judge's BIC worse (-8433 ->
   -8384), because the pods it moves were never seen to start again. With expressions run, the move gains
   (-22056 -> -22724). This was a method fault. It was hidden until 311 because nothing before needed a judged
   change on rows that carry an expression.

## Fixes kept (commit 542bc3d)

| type | mechanism | where | how another strategy adopts it |
|---|---|---|---|
| **row-rebuild** (best subset) | Every measured non-counter row whose one-step residual is above 100 x the quantum has its estimated outside sides refitted together, by exhaustive best subset (at most 4 columns, on BIC). The columns are a constant, the non-counter levels, the inputs and the capacity series it may read. Positive terms are written as the inflow and negative ones as the outflow. The result is checked under the engine's floor and kept on BIC > 2 log n. On none-short this gave cpu `1.25 inflight + 20 ready` in and `0.5 cpu` out, exactly. | `rebuild.py`, called after the base and before `floor.apply` | Copy `rebuild.py` (it needs `hidden._amount`, `repair._linear/_sign/_fixed_side`, `capmin.readers`, `steps.py`). Run it on the linear answer before any floored refit. Every strategy whose rows come from the shared forward stepwise has this blind spot. |
| **injection-aware post-stages** | `steps.injected/adjust`: each row reads the levels at a step's start with that step's injections in, and its change less what was injected (the engine's and judge's convention). controller.py, repair.py, hidden.py and counted.py no longer switch off on injections. | `steps.py`, `controller.py`, `repair.py`, `hidden.py`, `counted.py` | Wherever a post-stage returns early on `opts["injections"]`, use `steps.adjust(X, dy, run, opts, n)` instead. Every type-2 controller copy (combined2 switch.py, engine_forms controller.py, kalman_lna tracker.py, milp quantized.py) should be checked for the same early return. |
| **room-limited move** | A move X -> B (same unit, both rows above 100 x the quantum) at `k min(X, theta max(0, c Y - Z))`, with Y any measured stock or input (a capacity in any unit) and Z an occupant in X's unit. Candidates are ranked on the two rows' residuals over a (c, theta) grid. The best 3 are refined by golden section with every plain flow on the touched rows refitted (repair.py's active-set fit). The fit is **trimmed**: steps whose residual exceeds 5 MADs are left out, so the sparse OOM kills (a move the other way) do not bend the room. Without trimming the room was `4.96 nodes - 1.26 ready`, and with it `3.98 nodes - 1.0003 ready`. The move is kept on BIC > 6 log n. `room.polish`, the last stage, alternates a least-squares refit of (a, b, d) with the rows' plain flows held and an active-set refit of those flows with the room held. On none-short that gave `min(0.500005 pending, max(0, 4.00001 nodes - 1.000003 ready))`. Without the polish, the whole-flow error was 11.3% (fail). | `room.py`, `capmin._min_text`, `repair._fit(keep=)` | Copy `room.py` with `steps.py` and `exprs.py`. Call `room.apply` after the controller and before the counted/repair stages, and `room.polish` last. It needs a row reader that runs expressions. |
| **judge-runs-expressions** | `exprs.py` evaluates the engine's expression grammar (`sdtruth_expr.parse`) vectorized on the levels and inputs. The vendored judge's `Model` is now a subclass of the shared one that swaps an `exprs.Rate` in for every expression rate, and `hidden._rate_amount` reads expressions too. Flows of the other forms run exactly as before. | `exprs.py`, `_vendored/combined/judge.py`, `hidden.py` | Any strategy that judges or row-fits answers after writing MIN, controller or room expressions (all five top strategies carry capmin plus a controller). Check whether its judge runs on `sdlab.discovery.simulate.Model`. If it does, it has been reading those flows as 0. |

## Risks and what is not done

- **No regression run**, per the plan. The expression-aware judge changes what floor.py, counted.py and the final
  compare see on every case whose answer carries a MIN or a controller expression (306-310 and others). Those
  judgements were made against a model with those flows at 0, and now they are not. This is the largest regression
  risk. The rebuild runs only on rows above 100 x the quantum. The room move needs two such rows of one unit and a
  BIC gain of 6 log n.
- Both passes ran on the Mac. node2 was not exercised on this commit, and round 1 of 310 showed node2's
  time-capped search can differ.
- The structures search (`discover.py`) still finishes "no model in time" at its 90 s cap on 311, so the base is
  combined's every time.
- The HPA's clamps (`min(16, ...)` and `max(3, ...)`) are not written. Both bind nowhere on these runs, and the
  scorer passed the whole-flow comparison.
- counts-long's lost `outside -> pending` and mem drain are not diagnosed, because the variant is not a target.
