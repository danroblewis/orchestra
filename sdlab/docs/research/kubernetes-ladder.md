# The kubernetes ladder: a web service grown one feature a rung

**Status:** rungs 1-18 committed (cases 300-317, tag `kubernetes`, commit d9b170a); the `kubernetes` set on the leaderboard and the Now board (commit 22d0b8e; the runs moved to the Mac in a2d77ba); first run done on rungs 1-7 (long variants), rungs 8-18 **in progress** (the Mac's watcher fills them in; see "Runs").
**Asked by:** the user (an SRE), 2026-10-19: "take Prometheus metrics and determine the relationships automatically. Start from a very simple web-service example and increase the complexity one feature at a time, up to several services calling each other, so we see where our approach breaks down. The small tests work, but the minimal 5-service Kubernetes model doesn't."

## The rungs

One step is 5 minutes (a day is 288 steps; the long run, 2000 steps, is Monday 00:00 to Sunday 22:40, with the weekend). Stocks carry Prometheus-style names and a `query` (the PromQL each measured stock stands for, approximation 1 of [k8s-model.md](k8s-model.md): a request stock is what the service handled in the step plus its backlog). Measured vs hidden is as a scrape would see it: everything below is scraped except the memory leak (rung 11+) and the cluster autoscaler's provisioning stage (rung 13+). Counters (`*_total`) are final stocks. Variants: none and counts at short (300) and long (2000); rungs 1, 4, 7, 14 and 18 also `meas` (5% Gaussian measurement error on every level, as a real scrape has). Each rung passes `sdlab-ladder check` and its true model passes its own scoring (`tests/test_ladder.py -k k8s`: 55 passed).

| rung | case | adds | stocks (measured + hidden), flows |
|---|---|---|---|
| 1 | 300-k8s-requests-in-flight | `inflight` fed by the measured traffic (load-test steps), completed at 0.5 | 1, 2 |
| 2 | 301-k8s-request-queue | a queue (the sidecar's pending requests) in front: dispatched at 0.6 | 2, 3 |
| 3 | 302-k8s-responses-counter | completions counted in `responses_total` (a counter, a final stock) | 3, 3 |
| 4 | 303-k8s-daily-traffic | the traffic is the daily cycle (peak 14:00) with a 30% weekend dip | 3, 3 |
| 5 | 304-k8s-timeouts-and-errors | timeouts (0.08 of the queue, gone) and 5xx errors (3% of inflight, into `errors_total`) | 4, 5 |
| 6 | 305-k8s-retries | timed-out requests go to `retries`; 60% come back into the queue, 40% give up | 5, 7 |
| 7 | 306-k8s-ready-replicas-cap | dispatch = min(0.6 x queue, 40 x ready); `ready` scaled by hand (announced +4 at 08:00, -4 at 20:00) | 6, 7 |
| 8 | 307-k8s-cpu-usage | `cpu` (millicores) = links from inflight (1.25) and ready (20) through a 10-minute window | 7, 9 |
| 9 | 308-k8s-hpa | the HPA replaces the hand scaling: up at once to ceil(cpu / 192.5) (max 16), down one pod a step below ceil(cpu / 157.5) (min 3) | 7, 11 |
| 10 | 309-k8s-pod-startup | the HPA sets `desired`; the Deployment creates `pending` pods, which start at 0.5 a step | 9, 14 |
| 11 | 310-k8s-memory-oom | a 1 MiB/step leak (hidden), `mem` per pod, OOM kills (a table of mem) back to pending, `oom_kills_total` | 11 + 1, 20 |
| 12 | 311-k8s-node-pool | `nodes` (4 pods a node): pending pods start only into the room left; announced node failures | 12 + 1, 20 |
| 13 | 312-k8s-cluster-autoscaler | the cluster autoscaler: nodes added for unplaceable pods after a DELAY1 (hidden), removed when under half used | 12 + 2, 23 |
| 14 | 313-k8s-two-services | (topology track, on rung 4's service) frontend calls catalog: a link from frontend_inflight | 6, 7 |
| 15 | 314-k8s-chain-of-three | catalog calls pricing | 9, 10 |
| 16 | 315-k8s-fan-out | frontend also calls cart | 12, 13 |
| 17 | 316-k8s-shared-database | pricing and cart query a shared Postgres: pgbouncer's wait queue and a pool of 80 connections (a MIN) | 14, 17 |
| 18 | 317-k8s-mesh-of-three | every feature of rungs 1-17 on three services (frontend -> catalog, cart; cart -> catalog), a shared node pool and autoscaler, the shared database | 36 + 4, 62 |
| 19 | sd-k8s-small (realistic, unchanged) | 5 services, a minute a step for a week | 34 + 40, 168 |
| 20 | sd-k8s-platform (realistic, heavy, node2 only) | 35 services | 227 + 252, 1,130 |

Rungs 14-17 deliberately go back to rung 4's simple service, so the topology is probed on its own; rung 18 joins the two tracks. sd-k8s-small and sd-k8s-platform already carried the tag (their hashes are unchanged: their files were not touched).

## Runs

`OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1 uv run sdlab-ladder run --strategies all --cases tag:kubernetes --exclude-cases tag:realistic --jobs 8 --timeout 600` on the Mac (44 strategies, 3,608 items), started 2026-10-19 22:58 and **stopped by me after 1,827 s at item 837 of 3,608** (the Mac was at load ~100-118 on 28 cores, from other agents' runs): the runner does every long variant first, so rungs 1-7 have their none-long, counts-long and meas-long cells, rung 8 most of them, rungs 9-18 none, and no short variant has run. The Mac's watcher (`--exclude-cases machine:node2`; tag kubernetes is in the Mac's share) runs the rest; until it has, the board shows those cells as not run. `tag:realistic` is excluded because sd-k8s-small and sd-k8s-platform are node2's (heavy). A first attempt on node2 (`--jobs 16`) was stopped after 169 items when the user asked for the runs on the Mac; those results come back with node2's sync and match these (same code).

The table below is from the store (latest current result per cell, `scratchpad table.py` over `store.latest()` with `store.staleness`), read 2026-10-19 23:30. Each cell is none-long then counts-long: P pass, E equivalent, F fail, X error, · not run. Fresh skill@20 is counts-long's, rungs 1-8 (rung 8 as far as it ran).

| strategy | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | first break (none/counts long) | meas-long fails | counts-long fresh skill@20, rungs 1, 2, 3, 4, 5, 6, 7, 8 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| archetypes | PP | PP | PP | PP | PP | PP | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.7 |
| blockwise | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 99.8 / 100.0 / 99.9 / 100.0 / 99.9 / 99.9 / 99.8 |
| censored | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 99.9 / 100.0 / 99.9 / 99.7 / 99.7 |
| coflow_hats | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| combined | PP | PP | PP | PP | PP | PP | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.7 |
| combined2 | PP | PP | PP | PP | PP | PP | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| combined_lean | PP | PP | PP | PP | PP | PP | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.7 |
| combined_misfit | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| combined_r2 | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| common_cause | FF | FF | FF | FF | FF | FF | FF | FF | 1 (k8s-requests-in-flight) | 1,4,7 | 98.4 / 99.2 / 100.0 / 99.3 / 100.0 / 99.3 / 99.1 / 99.3 |
| drifting_drain | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 99.8 / 100.0 / 99.9 / 100.0 / 99.9 / 99.9 / 99.8 |
| earned_pieces | PP | PP | PP | PP | PP | PF | FF | FF | 6 (k8s-retries) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| effect_hats | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| engine_forms | PP | PP | PP | PP | PP | PP | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 |
| gap_prior | PP | PP | PP | PP | PP | PP | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| held_out | PP | PP | PP | FF | FF | FF | FF | FF | 4 (k8s-daily-traffic) | 1,4,7 | 100.0 / 99.8 / 100.0 / 99.1 / 99.0 / 99.0 / 98.7 / 98.5 |
| hidden_transit | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 99.8 / 100.0 / 99.9 / 100.0 / 99.9 / 99.6 / 99.8 |
| inflow_effects | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| kalman_lna | PP | PP | PP | PP | PP | PP | FF | F· | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / - |
| latent_eras | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 99.8 / 100.0 / 99.9 / 100.0 / 99.9 / 99.9 / 99.8 |
| lna | PP | PP | PP | PP | PP | PP | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| lna_levels | PP | PP | PP | PP | PP | PP | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| lna_loops | PP | PP | PP | PP | PP | PP | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| lna_products | PP | PP | PP | PP | PP | PP | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| lna_pulses | PP | PP | PP | PP | PP | PP | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| lna_stack | PP | PP | PP | PP | PP | PP | FF | F· | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / - |
| loop_transit | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| mass_balance | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 99.8 / 100.0 / 99.9 / 100.0 / 99.9 / 99.9 / 99.8 |
| master_eq | PP | PP | PP | PP | PP | PP | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 99.9 / 100.0 / 100.0 / 99.8 / 99.8 |
| matrix | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 99.8 / 100.0 / 99.9 / 100.0 / 99.9 / 99.9 / 99.8 |
| matrix_v2 | PP | PP | PP | FF | FF | FF | FF | FF | 4 (k8s-daily-traffic) | 1,4,7 | 100.0 / 99.8 / 100.0 / 99.1 / 99.0 / 99.0 / 98.7 / 98.5 |
| odefit | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 4,7 | 100.0 / 99.8 / 100.0 / 99.9 / 100.0 / 99.9 / 99.9 / 99.8 |
| own_tables | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 99.8 / 100.0 / 99.9 / 100.0 / 99.9 / 99.9 / 99.8 |
| periodic_inflows | XX | XX | XX | PP | PP | PE | FF | XF | 1 (k8s-requests-in-flight) | 1,4,7 | - / - / - / 99.9 / 100.0 / 99.9 / 99.9 / 99.8 |
| realistic_flows | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| realistic_hats | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / 99.8 |
| recession | XP | PP | PP | XF | XF | XF | XX | XX | 1 (k8s-requests-in-flight) | 1,4,7 | 100.0 / 99.8 / 100.0 / 99.1 / 99.0 / 99.0 / - / - |
| schedules | PP | PP | PP | PP | PP | PP | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.7 / 99.8 |
| shared_noise | XX | XX | XX | XX | XX | XX | XX | XX | 1 (k8s-requests-in-flight) | 1,4,7 | - / - / - / - / - / - / - / - |
| sindy | FF | FF | FF | FF | FF | FF | FF | FF | 1 (k8s-requests-in-flight) | 1,4,7 | 98.5 / 98.8 / 99.9 / 99.4 / 99.8 / 99.4 / 99.1 / 98.5 |
| starved_coflows | PP | PP | PP | FF | FF | FF | FF | FF | 4 (k8s-daily-traffic) | 1,4,7 | 100.0 / 99.8 / 100.0 / 99.1 / 99.0 / 99.0 / 98.7 / 98.5 |
| structures | PP | PP | PP | PP | PP | PP | FF | F· | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 100.0 / 99.9 / - |
| symbolic_anchor | PP | PP | PP | PP | PP | PE | FF | FF | 7 (k8s-ready-replicas-cap) | 1,4,7 | 100.0 / 99.8 / 100.0 / 99.9 / 100.0 / 99.9 / 99.9 / 98.5 |

Rung 8 (307, CPU usage), counts and none long, as far as it ran: 70 fail, 4 errors, no pass (from the run's log).

## Where each strategy breaks, and why

**Rung 7 (MIN of the queue and the ready pods) breaks every strategy.** All 43 with a result there fail it (41 fail, recession and shared_noise error) on none-long as well as counts-long, so it is not noise; for 34 it is the first break. (`unified`, added by another agent during the run, has no long result yet.) Dispatch is `min(0.6 x queue, 40 x ready)`; for 545 of 2000 steps the pods' capacity binds. No strategy can write a MIN of two stocks (the distilled case 222, a drain at the MIN of a capacity and a level, has the same shape: 2 passes of 140 long cells, both engine_forms). What they do instead is worse than missing one flow: the move queue -> inflight no longer balances, so the move pairing that makes rungs 2-6 pass falls apart and almost every flow becomes a link or an exit (`show 306 --strategy structures`: `outside -> inflight = 0.95 x traffic`, `outside -> retries = 0.079 x queue`, `outside -> responses_total = 0.50 x inflight`, 20 pieces; blockwise and kalman_lna: 3 of 7 parts, 87 pieces; engine_forms: 0 of 7). Behaviour stays excellent (fresh skill@20 99.7-99.9%), so the leaderboard's skill does not show the break; the equations do.

**Earlier breaks (each a single mechanism):**

| rung | strategies | mechanism |
|---|---|---|
| 1 | common_cause, sindy | ignore the measured input: the traffic becomes an unexplained inflow in 100 pieces (`outside -> inflight = 280 (mean; 100 pieces)`), and the drain is biased (0.40 for 0.5) |
| 1 | shared_noise, periodic_inflows (rungs 1-3), recession | crash on a measured input (`KeyError: 'traffic'`, `'traffic' is not in list`): they index the input as if it were a stock |
| 4 | held_out, matrix_v2, starved_coflows | the smooth daily traffic is almost collinear with the levels it drives (inflight is ~1.8 x traffic, lagged), and their judge prefers dropping the input: they keep only `outside -> responses_total = 0.50 x inflight` (a link where a move should be), losing the queue and the inflow; common_cause writes the inflow as a link from inflight. With load-test steps (rungs 1-3) they pass |
| 6 | earned_pieces (counts-long) | the retries loop: `retries` turns over completely every step (0.6 back + 0.4 out = 1.0), so the split between the loop and the give-up exit is weakly identified; it finds `retries -> queue = 0.92` and no give-up. 14 others are only equivalent there for the same reason (the oracle's tolerance allows the split either way) |
| 1, 4, 7 (meas) | all but odefit (rung 1) | 5% measurement error: the regressions read levels with error on both sides (errors in variables), so matrix finds 1.22 x traffic and 0.61 x inflight for 1 and 0.5 (the ratio, the steady state, is right). **Caveat (harness):** the noise oracle (`noise_kf.py`) cannot linearise a case with a measured input (`linear_system` returns None; `sdlab-ladder show 300 --variant meas-long` raises there), so these cells get the bare 10% tolerance with no standard-error allowance; whether 22% is achievable at this noise is not decided (invariant 4b) |

No strategy passes rung 7 or anything above it on the long variants run so far; rungs 9-18 are not run yet and are expected to fail for the same reason (each contains rung 7's MIN), and the topology rungs 14-16 (no MIN) are the open question.

## What the unified algorithm must handle (from this ladder)

1. **Measured inputs as first-class columns**, never indexed as stocks (rung 1), and kept by the judge even when a smooth daily input is nearly collinear with its own downstream levels (rung 4): the input is known to be exogenous, so it should be preferred over a stock that only tracks it.
2. **Capacity limits: a MIN of a demand and a capacity term from different stocks** (rung 7, and every Kubernetes mechanism above it: pods' throughput, pending pods into the room left, the database pool). Without it the mass balance of the move it limits is lost and the rest of the model degrades into links and pieces.
3. **Stocks that turn over every step** (retries, rung 6): the split of a stock drained completely in one step needs the downstream balance, not the stock's own row.
4. **Measurement error** (meas variants): an errors-in-variables-aware fit (a Kalman or total-least-squares step) instead of OLS on noisy levels; and the harness needs the noise oracle for input-driven cases before these cells can be judged.
5. (Not yet tested by results) expressions with `ceil` and step functions (the HPA), DELAY stages (pod startup, node provisioning), table effects on a hidden leak (OOM kills), links between services (calls), and size: rung 18 has 36 measured stocks.

## Not done

- Rungs 8-18 and every short variant: not run yet (the watcher will). The kubernetes column group on the leaderboard updates as they land.
- sd-k8s-small: its current results are all errors (node2's watcher ran out of memory at 22:13: `BrokenProcessPool`; another agent has since marked it heavy, commit cc5f8d2); earlier valid results are in [k8s-model.md](k8s-model.md) and [blockwise.md](blockwise.md) (blockwise 96-98% skill@20).
- The scorer's noise oracle for input-driven meas variants (harness, reported, not changed).

## 310 after round 1 (coordinator, 2026-10-22)

Round 1 (`~/.sdlab/rung-progress.log`, 07:29Z): all five of the top 5 pass none-short and none-long; all five fail
counts-short and counts-long. `sdlab-ladder analyse 310` gives no verdict ("a truth this analysis does not cover":
switches, tables, effects), so the counts variants count as achievable until shown otherwise.

`sdlab-ladder diff 310 --summary --strategies combined2,milp,structures,kalman_lna,engine_forms --variants
counts-short,counts-long`: the counts failures are about memory, the same way in every strategy:
- `~ mem -> outside` too low (6 of 10 results, all 5 strategies);
- `ready -> pending × effect(mem)` (the OOM kill) missed or its table off (10 of 10 lines between them);
- then 309's known counts misses on `retries` (high/low) and `pending -> ready`.

One shared error across five independent methods points at the data, not a method: Poisson noise on `mem` (a
level in MiB, counted) biases a drain fitted against the noisy level low (errors-in-variables attenuation). Worth
trying in round 2 before strategy-specific changes: estimate `mem`'s drain on smoothed or instrumented levels
(lagged level as the instrument), or fit the drain and the inflow jointly by simulation error rather than by
one-step regression; check whether the OOM table is then found. If a measured bound shows the counts data
cannot fix these numbers, record it (`analyse` cannot), and the rung moves on with none-short/none-long.
On 309, three strategies now pass counts-long, so counts is not out of reach in general.

## 317 after round 1 (coordinator, 2026-10-22)

Round 1 (22:36Z): structures passes none-short 85/85 (1,043 s); every other cell fails (combined2 none-long 64/85,
the rest 17-49/76-85) or times out (engine_forms none-long). `sdlab-ladder diff 317 --summary --strategies
combined2,milp,structures,kalman_lna,engine_forms --variants none-short,none-long`: the misses are 310's and 312's
mechanisms repeated per service, not anything new: the three per-service hidden leaks (`outside -> *_leak`), the
cluster autoscaler's provisioning delay (`outside -> provisioned_d1 -> nodes`), the OOM kills (`*_ready -> *_pending
x effect(*_mem)`) and the memory drains. Run times are 400-1,710 s against the 1,800 s limit: at 36 stocks and 68 flows
the hidden-stock and effect searches look starved of time rather than wrong. Suggestions for round 2, before anything
new: (1) read how structures' none-short pass finds the hidden stocks and effects at this size
(docs/research/fixes/317-structures.md) and port it (copy, never import); (2) make sure each strategy's per-block
budget scales with the number of services (a block per service, as 313-316 passed) rather than one search over all 36
stocks; (3) the speed notes in docs/research/speed-profile-311.md apply here most.
