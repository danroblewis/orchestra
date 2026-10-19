# A ground-truth model of services on Kubernetes (sd-k8s-platform, sd-k8s-small)

**Status:** done (model, generator, tests, ladder cases); leaders' first results below.
**Asked by:** the user (an SRE), 2026-10-18: bring back the "lot of something" test (`k8s-fleet`, 400
services, stocks only, no truth) as a system dynamics model with a ground truth: services on
Kubernetes serving HTTP through load balancers, with requests, pods, HPA, resources, OOM kills,
nodes and the cluster autoscaler, databases, and a daily traffic cycle with weekend dips; at least
30 services; real Prometheus data to be swapped in later.

## What was built

| | sd-k8s-platform | sd-k8s-small |
|---|---|---|
| services | 35 (3 frontends, 15 APIs, 10 backends, 5 queue workers, 2 caches) | 5 (a frontend, 3 APIs, a backend) |
| databases, queues | 3 (2 with a replica), 5 | none |
| node pools | 2 (`general`: 8 vCPU nodes; `workers`: 4 vCPU) | 1 |
| stocks | 479: 227 measured, 252 hidden | 74: 34 measured, 40 hidden |
| flows | 1,130 | 168 |
| a run | 10,080 steps (a week of minutes) in ~35-40 s; the long run 20,160 | 10,080 in ~5 s |

Files:

- `sdlab/examples/k8s/platform.yaml`, `small.yaml`: the **service catalogue** (names, tiers and their
  default resources, calls per request between services, queries per database, queues produced and
  consumed, node pools, traffic, events). Every number in the model comes from it.
- `sdlab/examples/k8s/build.py`: the generator. `uv run python sdlab/examples/k8s/build.py` rewrites
  both examples (deterministic: a re-run writes the same bytes; `tests/test_k8s_model.py` checks the
  committed files are exactly what it writes).
- `sdlab/examples/k8s/report.py`: what happens in a run (every count below).
- `sdlab/examples/sd-k8s-*.json` (the page: measured stocks, each with a `query`, the PromQL it stands
  for), `sd-k8s-*/truth.model.json` (the truth), `truth.json` (the answer key), `machines/` (simulator,
  history, live feed).
- `sdlab/ladder/cases/realistic/sd-k8s-platform.yaml`, `sd-k8s-small.yaml`: realistic ladder cases.
- `tests/test_k8s_model.py`: compiles, deterministic, bounded, every mechanism fires.

**Time unit: one minute, a week's run (Monday 00:00 to Sunday 23:59), dt 1.** A minute is what
Prometheus dashboards show (rates over `[1m]`-`[2m]`, 15-30 s scrapes), and it resolves everything
slower than a request: HPA reactions (15 s sync, 5-minute scale-down window), pod startup (1-4
minutes), node provisioning (~4 minutes), the autoscaler's 10-minute unneeded time, memory leaks
(hours), the daily cycle and the weekend. A week shows the weekly pattern once; at ~3.5 ms a step the
platform's week takes ~35-40 s (the engine needed a speed-up for this, below). Requests themselves
(milliseconds) are far faster than a step: see "Requests at a minute's resolution".

## The model, mechanism by mechanism

Per service (`<svc>` is the service id with `_` for `-`). M = measured, h = hidden.

**Traffic.** A measured input `traffic` (requests a minute at the edge): `mean + daily sin (period
1440) + 12-hour harmonic + weekend dip (pulse_train, Saturday and Sunday) + a Friday 19:00 spike
(+90% for 45 minutes, pulse_train weekly)`. It peaks at 12:05 on weekdays (the daily sine peaks at
14:00, the harmonic at 10:00 and 22:00), troughs at 03:00 at ~0.3x the peak, and the weekend mean is
~0.75x the weekday's. `ingress` (M) is the edge load balancer's requests this minute; it routes
fixed shares to the frontends.

**Requests.**
- `<svc>_lbq` (h): requests at the service's load balancer (a Kubernetes Service / ingress upstream).
  It dispatches up to `2.5 x target load x ready pods` a minute (`lin(ready)`, so spreading by ready
  replicas: no ready pods, nothing dispatched); requests beyond that wait, and half the excess times
  out each minute (`0.5 lbq - 0.5 cap x ready`, floored at 0).
- `<svc>_inflight` (M): requests in the service this minute. Completions `1.0 x inflight x effects`:
  CPU throttling (a table of CPU per pod against the limit) and waiting on a saturated dependency (a
  table of the two busiest synchronous callees' LB queues and of each database's query queue). 5xx
  errors at 0.2%; timeouts while throttled (table of CPU per pod above the limit); requests lost when
  a pod is OOM-killed (the same table as the kills).
- `<svc>_retry` (h): failed requests; clients retry 60% a minute later (back into the LB queue, or the
  message queue for a worker: the retry loop), 40% give up.
- Downstream calls: `outside -> <callee>_lbq` at `calls per request x inflight x the caller's work
  effects` (links, as in sd-services): the dependency graph is the catalogue's `calls`.
- Workers pull from their queue (`mq_<queue>`, M) at `1.2 x CPU request's worth x ready pods`,
  throttled; producers publish `per request x inflight`.

**Pods** (a Deployment and its ReplicaSet):
- `<svc>_desired` (M, ceiling = maxReplicas): the HPA's desired replicas.
- `<svc>_pending` (h) -> `<svc>_starting` (h, startup 1-4 min, a DELAY1) -> `<svc>_ready` (M) ->
  `<svc>_terminating` (h, gone within a minute).
- The Deployment controller creates `desired - (pending + starting + ready + restarting)` and deletes
  the excess (pending first, then ready); exact flows (controllers act exactly; see below).
- The scheduler places pending pods `1.0 x pending x table(CPU requested %) x table(memory requested
  %)`: full speed below 88%, none at 97%.
- OOM kills: `ready -> <svc>_oom` (M: pods restarting after an OOM kill, i.e. the kill rate) at
  `table(memory working set)`: none below 92% of the limit, 25% of pods a minute at the limit, 80% at
  110%; the container restarts (`oom -> starting`) and goes through readiness again.
- A rolling update (schedule change, announced; weekly, Wednesday 14:00): `ready -> terminating` at
  15% of the ready pods a minute for 15 minutes, pausing while a quarter of the peak replicas are
  starting (maxUnavailable 25%); the controller re-creates them (surge).

**HPA** (on CPU, target 70% of the request; a 10% tolerance; up at once, down after a window):
`hpa_up = CPU / (request x 0.7 x 1.1) - desired` (k 1 a minute, floored), `hpa_down = 0.5 x (desired -
CPU_slow / (request x 0.7 x 0.9))` with `CPU_slow` (h) a SMOOTH of CPU over 5 minutes (the
stabilisation window) and a table on desired that stops it at minReplicas; maxReplicas is the stock's
ceiling. Note that `desired = CPU total / (request x target)` is linear in the total CPU stock: the
utilisation ratio cancels the replica count.

**Resources.**
- `<svc>_cpu` (M, millicores, the service's total): `0.5 x (CPU ms per request / 60) x inflight x work
  effects + 0.5 x 10m x ready - 0.5 x cpu` (a 2-minute rate window).
- `<svc>_cpu_pod` (h): CPU per ready pod, re-read each minute as `cpu x table(1 / ready)`: it drives
  throttling and the throttle-timeouts.
- `<svc>_mem` (M, MiB per pod, ceiling 1.5 x limit so it settles at the limit): follows `base +
  leaked + memory per (request a minute per pod) x inflight / ready` with a 2-minute lag.
- `<svc>_leak` (h, leaky services only: search-index 1.3 MiB/min, recommendations 0.6, order-worker
  0.5; in sd-k8s-small catalog 1.0): grows at a constant rate per pod; reset by OOM kills (the same
  table), diluted by new pods (`leak x starting x 1/ready / startup`), and replaced by a rolling update.

**Nodes** (per pool):
- `nodes_<pool>` (M), `cpu_requested_<pool>`, `mem_requested_<pool>` (M, % of allocatable: requests
  of scheduled pods over `nodes x allocatable`, plus daemonsets), `cpu_requested_slow_<pool>` (h, a
  SMOOTH over 10 minutes: the autoscaler's scale-down-unneeded-time).
- Cluster autoscaler up: `sum(pending x request / node allocatable) - nodes provisioning`, when CPU
  requested is above 85-92% (table) and under the pool's max; a DELAY3 of 4 minutes
  (`provisioning_<pool>_1..3`, h) to a Ready node.
- Down: 5% of the pool a minute while the 10-minute average is below 45-55% and the current one below
  55-65% (tables), never below the pool's min.
- A node failure (announced injection): one node gone, and its share of each service's ready pods back
  to pending.

**Databases** (platform only):
- `<db>_queue` (h): queries this minute; executed up to a capacity (1.25-1.6x the weekday peak);
  half the excess times out each minute.
- `<db>_conn` (M): connections in use = queries x latency x a slow-query factor that rises steeply
  above 70% of capacity, capped by the pool (one table of the queue).
- `<db>_replica_conn` (M): reads on the replica x latency.
- `<db>_lag` (M, seconds): writes add the replica's seconds of apply work; the replica applies 60 s a
  minute, slower under heavy reads. Lag builds when writes outrun the replica.

## What happens in the run (counts)

`uv run python sdlab/examples/k8s/report.py` (the default week and seed), 2026-10-19, on the committed model:

| | sd-k8s-small | sd-k8s-platform |
|---|---|---|
| run time (7 days) | 4.9 s | 38.9 s (machine at load ~100) |
| edge traffic, weekday peak / night trough / Friday spike, requests a minute | 17,873 / 5,381 / 24,528 | 58,772 / 18,170 / 81,129 |
| weekday / weekend mean | 12,111 / 9,035 | 40,304 / 30,063 |
| HPA: replicas added / removed | 277 / 289 | 1,970 / 2,046 (33 services) |
| desired replicas rose / fell (service-minutes) | 270 / 287 | 1,866 / 1,988 |
| widest replica ranges | catalog-api 3-22, catalog 2-20 | pricing 11-82, catalog-api 11-82, promotions 6-52 |
| at maxReplicas at some point | pricing | ml-model-server, templates |
| pods created / terminated; replaced by the rolling update | 302 / 279; 29 | 2,039 / 1,978; 101 |
| OOM kills | 22 (catalog, its leak; 1-6 a day) | 54: search-index 43 (leak, every day), order-worker 6, recommendations 4 (leaks), media 1 (load) |
| CPU throttling (minutes above 85% of the limit) | pricing 1,869 | ml-model-server 508, order-worker 3 |
| requests timed out while throttled | 64,400 | 111,815 |
| load-balancer timeouts; clients gave up (all services) | 632; 0.09% | 31,809; 0.08% |
| nodes (min-max), autoscaler added / removed | 2-6, 14.3 / 14.4 | general 6-20, 38.4 / 38.4; workers 7-12, 10.5 / 11.4 |
| minutes with CPU requested > 100% | 105 (up to 104%) | 5 (up to 102%) |
| node failure | Thursday 11:01, -1 node | same, pool general |
| databases | - | orders-db: 227,449 query timeouts (Friday spike), lag up to 1,266 s (median 40 s); users-db lag up to 175 s; connections up to 71 / 30 / 95 (orders / users / catalog) |

The daily cycle shows in every service's load, CPU, desired and ready replicas and in the node
count (general pool 10-14 nodes on a weekday, 6-12 at the weekend); the HPA follows the morning ramp
within a minute or two and scales down over ~10 minutes; the autoscaler adds nodes each morning and
removes them each night. The spike drives orders-db past capacity (queries time out, replication lag
to ~20 minutes) and media's memory to its limit (an OOM kill or a short crash loop, depending on the
seed: one kill in this run, 8 and a few minutes of LB timeouts in an earlier version), and
ml-model-server (maxReplicas below its peak need) throttles every weekday afternoon. search-index's
leak brings an OOM kill or a few every day; the rolling update resets it.

## Approximations (and what Kubernetes does instead)

1. **Requests at a minute's resolution.** A request lasts milliseconds; at a one-minute Euler step a
   stock drained at `1.0` a minute holds what arrived in the last minute. So `<svc>_inflight` is
   requests handled this minute plus any backlog, not the instantaneous in-flight gauge. By Little's
   law the gauge is `this / 60 x latency (s)`; the closest Prometheus series to the stock is
   `increase(http_server_requests_total[1m])` (as its `query` says). Queues that persist across minutes
   (LB queues, database queues, message queues) are modelled faithfully. Each hop adds a minute of
   pipeline delay (LB queue, then in flight), which a real call chain does not have.
2. **Ratios of stocks.** The engine's rates are linear in stocks times effects of single stocks, with
   no division. Per-pod quantities (`cpu / ready`, `inflight / ready`, requests over `nodes x
   allocatable`) use an effect table of `1/x` (exact at whole numbers up to 10, then at 12, 14, ...,
   200; linear between: within ~1.5%) on the replica or node count, and a hidden stock re-read each
   minute (a one-minute lag). The HPA needs no ratio (its target is linear in total CPU).
3. **ceil, min, max.** The HPA's `ceil(desired x ratio)` and its 10% tolerance are a band: it scales
   up only above 110% of target and down only below 90%, and lands at the band's edge rather than at
   `ceil`. minReplicas is a table stopping scale-down; maxReplicas is a ceiling. The scale-down
   stabilisation window (the max recommendation over 5 minutes) is a SMOOTH of CPU over 5 minutes and
   a 2-minute gap time, so scale-down is gradual, not one step after the window.
4. **Controllers act exactly; events are counted.** Real controllers create and delete whole pods
   exactly. With counting noise on those flows, a Poisson draw sometimes deleted all of a small
   service's pods, so the HPA, Deployment and cluster-autoscaler flows are `exact`. Pods and nodes are
   therefore fractional inside the truth (the measured levels are whole numbers, as the engine rounds
   every level under counting noise), while scheduling, startup, OOM kills, restarts and terminations
   are random, whole events.
5. **The memory limit** is a ceiling of `1.5 x limit`: under the engine's ceiling rule (the room is
   taken before the outflows) a stock drained at 0.5 a step settles at `max / 1.5`, the limit. A
   transient can overshoot by ~10%. The OOM kill is a probability per pod per minute rising from 92%
   of the limit; the kernel kills at the limit, and the pod that dies is the one with the most memory,
   whereas the model resets the average leak by the share of pods killed.
6. **Leaks per pod are averages.** New pods dilute the average leak; scale-down removes average pods.
7. **Scheduling** is pool-level occupancy (requests over allocatable), not bin-packing per node; pods
   placed in the same minute can overshoot 100% by a few percent (small: up to 104% for 157 minutes).
   The autoscaler adds nodes for pending pods' CPU only (memory is ample in both catalogues) and,
   when it removes nodes, pods are assumed to fit elsewhere (no eviction). A node failure is an
   injection whose pod losses are estimated from the expected replicas at that time.
8. **Database connections** are queries x latency x a slow-query factor, capped by the pool through a
   table; Poisson noise can read a few above the pool (max 75 against a pool of 50 on orders-db).
9. **Requests lost to OOM kills, calls and queries** are written as separate flows with the same
   equation and effects as completions (a flow cannot read another flow's amount), so each has its own
   counting noise.
10. **Retries** go back to the callee's LB queue (from the client), with no backoff beyond a minute and
    no circuit breaker; `retry 60%, give up 40%` bounds the retry loop's gain at 0.6.

## Metrics: which Prometheus series each measured stock stands for

Each measured stock carries its PromQL in `query` (in the page and the truth). Per service:

| stock | unit | Prometheus / kube-state-metrics |
|---|---|---|
| `<svc>_inflight` | requests | `sum(increase(http_server_requests_total{service=...}[1m]))` (approximation 1) |
| `<svc>_cpu` | millicores | `1000 * sum(rate(container_cpu_usage_seconds_total{container=...}[2m]))` |
| `<svc>_mem` | MiB | `avg(container_memory_working_set_bytes{container=...}) / 2^20` |
| `<svc>_desired` | pods | `kube_horizontalpodautoscaler_status_desired_replicas` |
| `<svc>_ready` | pods | `kube_deployment_status_replicas_ready` |
| `<svc>_oom` | pods a minute | `increase(kube_pod_container_status_restarts_total[1m])` for OOMKilled terminations |
| `ingress` | requests | `sum(increase(nginx_ingress_controller_requests[1m]))` (or the cloud LB's count) |
| `nodes_<pool>` | nodes | `kube_node_status_condition{condition="Ready",status="true"}` per pool |
| `cpu_requested_<pool>`, `mem_requested_<pool>` | % | `kube_pod_container_resource_requests / kube_node_status_allocatable` per pool |
| `<db>_conn`, `<db>_replica_conn` | connections | `pg_stat_activity_count{state="active"}` (postgres_exporter) |
| `<db>_lag` | seconds | `pg_replication_lag_seconds` |
| `mq_<queue>` | messages | `kafka_consumergroup_lag` (or RabbitMQ's messages ready) |

Hidden, though some are observable: LB queues (Envoy's `upstream_rq_pending_active` would show them),
retries, CPU per pod (derivable), the HPA's window, leaks, pending/starting/terminating pods
(`kube_pod_status_phase` shows them: they are hidden here to keep the measured set to what the user
listed), database query queues, node provisioning.

To use real data: export each measured series at one-minute steps for a week, name the columns by
the stock ids, and give the traffic at the edge as the measured input. The structure discovery then
looks for is the one this model has, with the same measured stocks.

## The engine

- **Speed (additive, bit-identical).** `sdtruth.Truth.run` searched every flow for every stock in
  every sub-step (O(stocks x flows), ~34 ms a step here). It now finds each stock's takers and each
  ceiling's inflows once, and compiles each flow's rate x effects once (the same arithmetic in the
  same order; a table's points sorted once): ~3.5 ms a step. `tests/test_engine_additive.py` (every
  ladder case, example and bench model recorded before the 2026-10-18 features) still gives
  bit-identical numbers.
- **A fix (additive).** A stock that a rounding error left at -1e-16 with nothing flowing out
  (possible with exact flows) divided by zero in the floor; it is skipped (`want > 0`). Runs that did
  not crash are unchanged.
- `realistic.py` passes the example's `inputs` and `dt` to the case (none of the 31 earlier examples
  has them, so their cases and hashes are unchanged).
- The generic example tests (`tests/test_sd_examples.py`) run a large example 5 weeks instead of 50x
  its length, and the live feed and history with longer timeouts; `tests/test_discovery.py`'s check
  that the discovery simulator steps every truth as the engine does now passes the inputs and
  ceilings (it passes for both k8s truths).

**Gaps found** (queue item 2d): auxiliaries (an algebraic variable without a stock: here each is a
stock re-read every minute, a one-step lag); an effect of a ratio of two stocks (here a `1/x` table);
MIN/MAX/CEIL in rates; a flow reading another flow's amount (a restarts counter equal to the kills);
the ceiling convention `max / (1 + k)`; the editor's Discover does not pass measured inputs (the
ladder does), so on the page the traffic is an unexplained inflow at `ingress`.

**The live run.** The editor's live feed reads one step of a recorded run per tick, with a minute per
tick to make it. A week of the platform takes ~40 s on a loaded machine plus the recording's size
(every flow's counters), so the k8s examples' `live.py` records a day of levels only and makes the
next, twice as long, recording in the background once a run passes half of one. A step then takes
~0.05 s; Import history runs the week (~40 s for the platform).

## Leaders on the two cases

(In progress: filled in from `uv run sdlab-ladder status` once the runs finish.)
