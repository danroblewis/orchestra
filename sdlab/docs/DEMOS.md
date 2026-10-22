# Demos: operational uses of discovered models

Demos of the ideas in `OPERATIONALIZATION.md`, built into the SD Lab app at `/demos`. Each demo runs on a
**simulated** system whose true model is known (the kubernetes ladder cases and new demo scenarios), so it can show
what the found model says beside what really happened: the demos are honest about accuracy, not only pictures.

Ground rules:
- Demos never change a ladder case, a simulation or a strategy. A demo's "change" (a bad deploy, a new event) is
  applied to an in-memory copy of a case's true model.
- A demo uses a model a strategy already found and stored (a passing result), so it loads in seconds instead of
  waiting for discovery. It names the result (strategy, result id, commit).
- Demo code lives in `sdlab/demos/` (Python) and `sdlab/static/demos*` (page); nothing in the ladder imports it.

Effort: S = about a day or less, M = a few days, L = a week or more.

| # | demo | what it shows | ideas | effort | status |
|---|---|---|---|---|---|
| 1 | **Residual watch** | A service runs on; at a moment its retry rate changes (a bad deploy). Yesterday's model keeps predicting; the gap grows on one stock and an alarm names the flows that touch it, beside the true change. | 3, 4 | S | built |
| 2 | **Daily model diff** | Two "days" of a service, the second changed; the git-style diff of the two found models beside the true change: found, missed and false edits. Needs the found-vs-found diff (F2). | 1, 7 | S-M | built ([doc](demos/daily-diff.md)) |
| 3 | **What-if before rollout** | Change a number in the found model (a retry share, a capacity, an autoscaling divisor) and see the simulated effect on the stocks, beside the true model's response to the same change. | 31, 25, 50 | S | built |
| 4 | **Capacity projection** | Ramp traffic forward through the found model; mark when each capped flow saturates and the headroom left today. | 23, 24 | S-M | built ([doc](demos/capacity.md)) |
| 5 | **Risk calendar** | The next 30 days of known events (weekly peaks, a launch, planned maintenance) through the model; a calendar marks the days a stock crosses a limit. | 29 | M | built ([doc](demos/risk-calendar.md)) |
| 6 | **Metastability scan** | The retry loop in the found model; load spikes swept to find the tipping point where the system stays broken after the spike: a safe-load envelope. | 16, 20 | M | built ([doc](demos/metastability.md)) |
| 7 | **Hidden stock as a clue** | 310's memory leak: discovery infers an unmeasured stock; the demo shows its inferred level beside the true leak, what it reads and feeds, and the metric to add. | 19, 53 | S | built |
| 8 | **Leverage: small change, big effect** | Every number in the found model nudged 10%, ranked by how much it moves a goal (errors, OOM kills, queue); the true model's response to the top ones beside it. | 38 | S | built |
| 9 | **Always-on discovery** | A service streams live; the model on screen improves over time (anytime results), confidence rising, a change caught mid-stream. | 10, 11, 13 | M | planned |
| 10 | **Before/after attribution** | A simulated SRE project lowers retry amplification; the before model on the after traffic is the counterfactual; the measured improvement with its uncertainty. | 36, 37 | M | built ([doc](demos/attribution.md)) |
| 11 | **Canary guard** | Baseline and canary copies of a service, the canary slightly worse; both fitted, their numbers compared with error bars: stop or go. | 32 | M | built ([doc](demos/canary.md)) |
| 12 | **Blast radius across services** | On 316's shared database, slow one stock and watch it spread through the multi-service model, beside the truth. Needs 316 passing. | 22, 33 | M | built ([doc](demos/blast-radius.md)) |
| 13 | **Agent work as stocks** | Tickets (backlog, in progress, review, done) simulated with agents as the flows; the discovered model's agent throughput, rework loop and bottleneck. Needs a new simulated system. | 42, 44, 45 | M-L | built ([doc](demos/agent-work.md)) |
| 14 | **Game-day microworld** | Be on call in a simulated incident (scale, shed load, change retries); the true model responds; compare afterwards with what the found model predicted. | 57 | L | planned |
| 15 | **Fleet view** | Many simulated services (promlab's fleet): model health, unexplained diffs and confidence per service, the maintenance staff's view. Needs per-service discovery at scale. | 8, 9 | L | planned |

## How the built demos work

All four start from a scenario (`sdlab/demos/scenarios.py`): a kubernetes case, a variant, and the stored result of
a strategy that passed it. The true model comes from the case (`cases.truth_model`) and runs in the truth engine
(`sdtruth.Truth`); the found model runs in the scorer's simulator for found models (`ladder/sim.found_model`), with
the case's measured inputs (traffic).

- **Residual watch.** The true model with one rate changed from step T (a schedule change on a copy) makes "today's"
  data. Yesterday's found model predicts each step from the measured levels (one step ahead); the residual per
  stock is measured change minus predicted change, scaled by its spread before T. A two-sided CUSUM per stock
  raises the alarm; the alarmed stock's flows are the suspects.
- **What-if.** The found model's numbers are listed by flow (proportional and linear coefficients, constants, the
  numbers in its expressions). An edited number is simulated forward beside the unedited model; the same edit,
  applied to the true flow between the same stocks where there is one, runs in the truth engine for comparison.
- **Hidden stock.** The found model's hidden stock (matched to the truth's by the scorer, `scores.hidden_match`) is
  simulated with the model and drawn beside the truth's hidden level; its flows and the stocks that read it are
  listed, and the proposed metric is the quantity it tracks.
- **Leverage.** Each number of the found model is raised 10% in turn; the change in a goal (a stock's final level
  or mean) is ranked; the top ones are applied to the true model too.

## What the built demos found (2026-10-22, 310 scenario, milp's stored passing result)

- **Residual watch, noise-free:** each of the four changes (faster retries, slower pod starts, a worse leak, more
  errors) is caught 0-1 steps after it happens, on the right stock, with no false alarm, and the changed flow is
  among the suspects every time (`tests/test_demos.py`).
- **Residual watch, counted measurements:** unreliable. A model fitted on noise-free data, fed noisy levels one step
  at a time, makes biased predictions (most at the OOM threshold), so it false-alarms on `ready` / `cpu` and misses
  most changes, even with thresholds calibrated on a quiet day; averaging residuals over blocks helps only partly.
  This is the counts variants' data limit seen from operations. Next: track the state with a filter (Kalman, as
  kalman_lna does) instead of trusting each noisy level.
- **What-if:** on proportional flows the found model and the true model agree to under 1% (retries → queue 0.6 → 0.9);
  on the autoscaler's divisor (192.5 → 150) mean desired pods go 12.27 → 13.15 found, 12.26 → 13.16 true.
- **Hidden stock:** the inferred leak follows the true one at R² 0.99996 from measured levels alone.
- **Leverage:** for OOM kills, the found model's top levers agree with the true model's on direction and size where the
  equations are written alike (memory drain −9.5 vs −9.1; the leak +5.8 vs +6.1; traffic +4.6 vs +5.1); where the true
  equation is written differently the match is marked approximate (≈) or "no match".

Page: `/demos` (`sdlab/static/demos.html`, `demos.js`); API: `/api/demos` (`sdlab/demos/routes.py`).

## What the other built demos found (2026-10-22, by parallel agents; details in docs/demos/)

- **2. Daily model diff** (313, lna): 3 of 4 day-2 changes found right with no false edit (a busier call, a slower
  service, a new cache flow); a new client retry is missed (lna puts it in the wrong service). On 310 engine_forms'
  day-2 discovery fails at other traffic (a quiet day shows 12 false edits): a diff is only as good as both days'
  discovery.
- **4. Capacity projection** (311): with the case's 3 nodes every found model matches the truth's headroom and peak
  queue within 6%. None has the autoscaler's maximum of 16 pods (the data never reached it), so with 6 nodes they
  over-promise: at 2x traffic a peak queue of about 8,500 against the truth's 16,635. The page marks that region
  "fits, not proven past it".
- **5. Risk calendar** (311, 30 days): with 3 nodes the launch and the maintenance days are flagged by both models, no
  miss, no false alarm; with 5 nodes the found model misses the launch day (past its data).
- **6. Metastability scan** (310, 311): the cases as built are never metastable (slow recovery, up to about 7 h); with
  retries amplified (a what-if) they tip. 310's found models lack the dispatch cap (it never bound in their data) and
  call every stuck spike safe; 311's have it (it bound in 32% of steps) and match the envelope 35-36 of 36.
- **10. Before/after attribution** (310): noise-free, the refit finds exactly the number the project moved (retry
  share 0.6 -> 0.2998) and the effects match the truth (-397 failed requests vs -397); with counted noise the moved
  number is found in 23 of 24 runs but refits are biased and the OOM-kill effect cannot be measured.
- **11. Canary guard** (310, counted noise, 10 seeds): 0 of 10 false stops at 1000 steps; +5% errors stopped 9 of 10,
  +5% slower completions 10 of 10, +15% timeouts 4 of 10, +30% 10 of 10; shorter canaries (300 steps) stop for the
  wrong reason more often.
- **12. Blast radius** (314, 315): noise-free found models propagate a slowdown exactly as the truth; counts-fitted
  models with a false cross-service link show a false spread (all three other services ~50% when one stops, truth 0).
- **13. Agent work as stocks** (a new simulated ticket system): per-agent throughput (12 a day) and the rework share
  (0.20) found exactly; the merge gate (52.8 a day) is missed or misread because the agent count changed only once,
  so in a busier month both found models promise 8-9% more than the truth delivers.

Common lesson: a found model is reliable inside the region its data visited and with clean data; outside that region
(a cap never reached) or with counted noise, the demos show where it goes wrong, which is what an operator needs to
know before trusting it.
