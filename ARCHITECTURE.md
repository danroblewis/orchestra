# Orchestra's architecture

This document explains how Orchestra works: its parts, how data moves through them, where state
lives, and where the code holds each of the rules in `AGENTS.md`. It describes `main` as of commit
`828da6d0`. It is written for the owner, for an SRE who has to run Orchestra, and for engineers
new to the code.

`SPEC.md` is the full design and goes into more detail. `AGENTS.md` lists the rules. Where this
document and the code disagree, the code is right and this document is out of date.

## What Orchestra is

Orchestra watches a system of **machines** from the outside and keeps one **system dynamics
model** of it. A machine is anything outside Orchestra that does actual work: a program, an AI
agent, a service, a person. Orchestra never runs a machine's logic and never asks a machine what
it is. It knows a machine by the **events** it publishes on an event bus. Separately,
**instruments** measure the running system and write **measurements** (time series) to a metrics
store; an instrument measures and never acts, and is not a machine. From the measurements it
discovers a model of **stocks** (quantities that accumulate, such as items waiting in a queue)
and **flows** (rates that fill or drain stocks, such as items finished per minute) and fits an
equation to every flow. System dynamics has no machines: how a machine's work relates to the
flows is not known, and Orchestra infers it, as hypotheses with their evidence, from the
machines' events. It shows all of this in a read-only web UI. Orchestra itself holds no machines,
no tickets, no tasks and no AI: those live in other packages, which plug in.

Some terms used throughout:

| Term | Meaning |
|---|---|
| **Machine** | Something outside Orchestra that does work, known by the CloudEvents `source` it publishes under (or as the producer or consumer of counted traffic). Several instances publish as `<machine>/<instance>`. A series never makes a machine. |
| **Instrument** | What measures the system and never acts: a `[[collect]]` script, a `[[scrape]]` URL, a `[[sources]]` store, a plugin's `Plugin.collectors`. Not a machine. Its points carry `instrument=<name>`. |
| **CloudEvents** | A standard envelope for events (`specversion`, `id`, `type`, `source`, `time`, optional `subject`, `data`). Orchestra reads the envelope; the `data` payload belongs to the machines. |
| **Series** | A metric name plus labels, with timestamped values, as in Prometheus. |
| **Counter** | A series that only goes up (apart from resets), named `..._total`. Discovery reads counters as flows. |
| **Level** | Any other series (a gauge): how much there is now. Discovery may find that a level is a stock. |
| **Stock** | A level whose changes are explained by flows. In system dynamics: an accumulation. |
| **Flow** | A rate that moves material into or out of a stock, or between two stocks. |
| **Association** | A hypothesis that a machine's work is measured by a flow, inferred from its events matching the flow's counter, with evidence and a confidence. Never declared. |
| **Model version** | A saved copy of the model. Past versions stay readable. |
| **State directory** | `~/.orchestrator/<key>/`, where Orchestra keeps a project's files. |

## The components

```mermaid
flowchart LR
  subgraph outside["Outside Orchestra"]
    M["Machines: programs, agents, services, people"]
    T["Measured targets: scripts, /metrics URLs"]
    R["Other stores: Prometheus API"]
  end
  subgraph host["orchestra run (host.py)"]
    EC["Event collector"]
    DI["Discovery thread"]
    LA["Launcher"]
    CO["Instruments: collectors and scrapes"]
    EP["Events endpoint (HTTP)"]
  end
  subgraph stores["Backends"]
    BUS[("Event bus")]
    MET[("Metrics store")]
  end
  subgraph state["State directory"]
    RT["runtime.json"]
    MS["model/"]
  end
  subgraph web["orchestra web (web/)"]
    BG["Background reads"]
    UI["Core, Machines, Instruments, Dynamics"]
  end
  PL["Plugins"]
  CLI["CLI (cli.py)"]

  M -- "POST /events, GET /events" --> EP
  EP -- "Events.publish, Events.after" --> BUS
  M -. "or the Python helper (Events.publish)" .-> BUS
  LA -- "starts, restarts" --> M
  CO -- "run or scrape" --> T
  CO -- "points, instrument=#lt;name#gt;" --> MET
  CO -- "health" --> RT
  EC -- "follows" --> BUS
  EC -- "orchestra_events_total (secondary)" --> MET
  DI -- "reads via catalogue" --> MET
  DI -- "reads, never writes" --> R
  DI -- "versions" --> MS
  LA -- "processes" --> RT
  EP -- "events_endpoint" --> RT
  BG --> BUS
  BG --> MET
  BG --> MS
  BG --> R
  UI --> BG
  PL -- "pages, routes" --> UI
  PL -- "processes" --> LA
  PL -- "collectors" --> CO
  CLI --> MS
  CLI --> BUS
  CLI --> MET
```

Each component, its module, and what it depends on:

| Component | Module | What it does | Depends on |
|---|---|---|---|
| **Configuration** | `orchestra/config.py` | Finds the repository root with git (a worktree resolves to its main repository), reads `orchestra.toml`, computes the project key and the state directory. `orchestra init` writes a starter `orchestra.toml`. | git, `tomllib` |
| **Event bus** | `orchestra/bus/`, facade `orchestra/events.py` | An append-only, ordered, replayable log per project. `Events.publish` wraps every event in the CloudEvents envelope (`events.envelope`). Offsets are integers counting events; `Events.after(offset)` returns everything after an offset. | config; a client library for server backends |
| **Metrics store** | `orchestra/metrics/` (`file.py`, `victoria.py`, `promql.py`) | Stores series: `write`, `raw`, `range`, `latest`, `series`, `dump`, `delete`. Every point carries a `project` label. Refuses points stamped more than 60 s in the future (`refuse_future`). `promql.py` is a tested PromQL subset for the file store. | config |
| **Runtime record** | `orchestra/runtime.py` | `<state>/runtime.json`: the running hosts, the one host that launches, the web server, and the launched processes. Every write takes a file lock. A record holds a pid and the process's create time, so a reused pid is not mistaken for it. | config, `psutil`, `fcntl` |
| **Event collector** | `orchestra/collectors.py` | Counts every event by type and source into `orchestra_events_total{type, source}`. Knows nothing about what events mean. | bus, metrics |
| **Bootstrap host** | `orchestra/host.py` | `orchestra run`: Orchestra's own machine, `orchestra-host`. Registers itself, publishes `orchestra.host.started`/`stopped`, writes `orchestra_host_up`, runs the event collector, rediscovers the model on a timer, and (in the one host that launches) runs the launcher and the instruments. | everything below |
| **Events endpoint** | `orchestra/endpoint/` (`__init__`, `validate`, `server`) | HTTP for machines in any language: `POST /events` checks one event's fields and publishes it through `Events.publish`; `GET /events?after=&types=&wait=&limit=` reads by offset, with a long poll. Served by the host that launches on `[events] listen` (127.0.0.1 and a port the system picks, by default), behind the project's token (`<state>/events.token`). Remembers recent ids, so a retried post is written once. | events (`Events`), runtime, the stdlib's `http.server` |
| **Launcher** | `orchestra/launcher.py` | Keeps running the commands that `[[machines]]` and plugins (`Plugin.processes`) declare. Knows them only as processes: a name, a command, a pid, an exit code. | config, runtime, the host's `publish` |
| **Instruments: collectors and scrapes** | `orchestra/collect/` (`spec`, `fetch`, `exposition`, `round`, `runner`) | Runs `[[collect]]` commands and reads `[[scrape]]` URLs (the project's and the plugins' `Plugin.collectors`) on intervals, parses the Prometheus text format, and writes the points labelled `project` and `instrument=<name>`, keeping the target's own labels (`machine` included; a target's `project` or `instrument` becomes `exported_project`, `exported_instrument`). Announces nothing on the bus. Keeps each instrument's health in the runtime record under `instruments`, and its log in `<state>/logs/instruments/<name>.log`. | metrics, runtime, launcher (log size) |
| **Sources** | `orchestra/sources/` | Reads other time-series stores in place (`[[sources]]`), never writes to them. Infers what to read from a store's schema, reads it for discovery's exact window, and records where every series came from. Also reads **counted traffic** (`sources/traffic.py`). | metrics (the own store), `sd/series.py`, HTTP |
| **Discovery** | `orchestra/sd/` (`rediscover.py`, `discover.py`, `strategies.py`, `netflow.py`, `attribute.py`, and helpers), `orchestra/sdlab/` | Builds the model from the series without being told what anything is. `sd/discover.py` is Orchestra's own "conservation" step; `sd/strategies.py` can add one of SD Lab's strategies on top. `sd/attribute.py` infers which machines may be associated with each flow, as hypotheses from their event counts. | sources (the catalogue), model store; `numpy` and friends for SD Lab (`sd` extra) |
| **Model store** | `orchestra/sd/store.py`, `orchestra/sd/model.py` | The one model and its versions: `<state>/model/vNNNN.json`, plus the latest discovery cached in `model/discovered.json`. | the state directory |
| **Web** | `orchestra/web/` | `orchestra web`: a FastAPI app with the Dashboard, Core, Machines, Instruments and Dynamics pages, and plugin pages. Background threads keep caches warm so page requests stay cheap. | bus, metrics, runtime, model store, sources, plugins |
| **CLI** | `orchestra/cli.py` | `init`, `run`, `web`, `events info\|endpoint\|copy`, `metrics backfill\|series`, `sd discover\|show\|fit\|versions`, `sources check\|infer\|preview`. | the rest, imported on use |
| **Plugins** | `orchestra/plugins.py` | Loads packages registered in the entry-point group `orchestra.plugins`. A plugin adds pages, a static directory, an API router, every-page scripts and stylesheets, declared machines, processes and instruments (`collectors`). One that fails to load, or whose name another plugin took, is reported and left out. | launcher (`Process`), collect (`Collector`) |

### Inside the host

`Host.run` (`orchestra/host.py`) starts these threads:

| Thread | Cadence | What it does |
|---|---|---|
| main | every 15 s | Writes `orchestra_host_up{machine="orchestra-host"}` (1 while running, 0 when stopping). |
| `collector` | every 2 s | Replays the whole bus once at start (`collectors.backfill`, which replaces the event counters), then reads new events and writes their counts. |
| `discovery` | 5 s after start, then every `[discovery] every` (default 5 min) | Calls `sd.rediscover.rediscover(..., skip_if_busy=True)` and logs the result. |
| `launcher` | every 1 s | Only in the host that holds `launcher` in the runtime record. Before its first tick it starts the events endpoint, so the processes it launches get its address; each tick runs `Launcher.tick()` and `Collecting.tick()`; when the host stops it stops the processes, then the endpoint. |
| `events-endpoint` | per request | Only in the launching host: a `ThreadingHTTPServer` (one thread per request, so a long poll holds up nothing). Each bus call takes one lock, since not every bus client library is thread-safe. |

Only one host launches per project. `Host._claim` takes `launcher` in the runtime record under the
lock, and only when no live process holds it. A second `orchestra run` still runs the event
collector and discovery, but starts no processes and no instruments. A host that takes over from a
dead one first stops whatever the dead one left running (`Launcher.reap_orphans`).

### The launcher

`orchestra/launcher.py` starts each process in the repository root, in a process group of its
own, with `ORCHESTRA_REPO`, `ORCHESTRA_MACHINE_LOG`, and the events endpoint's
`ORCHESTRA_EVENTS_ENDPOINT` and `ORCHESTRA_EVENTS_TOKEN` (the host's `Launcher.env`) set and its output sent to
`<state>/logs/machines/<name>.log`. A plugin's processes are named `<plugin>.<name>`.

- A process that exits is started again after a pause that doubles with each exit within a minute
  of starting (1 s up to 60 s).
- After five failing exits in a row, each within a minute of starting, it is given up on and
  `orchestra.process.gave_up` is published. It is tried again when its entry changes or the host
  restarts.
- `orchestra.toml` is re-read when it changes (checked every second). New entries start, removed
  ones stop, changed ones restart. The plugins are asked for their processes again at the same
  time.
- Stopping the host sends SIGTERM to each process group, then SIGKILL after its stop grace
  (10 s unless set).
- The host publishes `orchestra.process.started`, `orchestra.process.exited` and
  `orchestra.process.gave_up`, and keeps each process in `runtime.json` under `processes` for the
  Core page.

The launcher never decides that a process is a machine. A process becomes a machine only by what
it publishes on the bus; what it writes or serves as metrics makes it no machine.

## Data flows end to end

### A measurement, from an instrument to the model

Machines do not produce metrics. The metrics store is filled by instruments directly, kept apart
from the machines so the measurements can test what we believe about them:

1. A `[[collect]]` script that Orchestra runs on an interval and that prints the Prometheus text
   format.
2. A `[[scrape]]` URL that serves the Prometheus text format.
3. A plugin's `Plugin.collectors`, run like the project's and named `<plugin>.<name>` (a project
   entry of the same name wins).
4. A Python program that writes points itself through `orchestra.metrics.for_repo()`.

A `[[sources]]` store is an instrument too, read in place at each discovery and never copied
([below](#other-stores-and-counted-traffic)). The one series derived from the event log is
`orchestra_events_total{type, source}`, the event collector's count of the bus; it is secondary,
a count of what the machines said, not a measurement of the system. `docs/machines.md` is the
guide for writing machines and instruments. Here is the path for a script collector:

```mermaid
sequenceDiagram
  autonumber
  participant T as orchestra.toml
  participant R as Collecting (collect/runner.py)
  participant S as Script machines/disk.sh
  participant P as round.py and exposition.py
  participant M as Metrics store
  participant D as Discovery (sd/rediscover.py)
  participant W as Web (web/background.py)
  R->>T: re-read when the file changed
  loop every "every" seconds
    R->>S: run in repo root, in its own process group
    S-->>R: stdout in Prometheus text format
    R->>P: parse, add project and instrument=disk labels
    P-->>R: points, or the error that left none
    R->>M: write points (refuses points stamped in the future)
    R->>R: health to runtime.json (instruments), a line to logs/instruments/disk.log
  end
  Note over R,M: a failed round writes nothing and counts orchestra_collect_failures_total
  D->>M: read the window through the catalogue
  D->>D: discover stocks and flows, fit rates
  D->>D: cache discovered.json, save a version if the structure changed
  W->>M: read latest levels and history
  W->>D: read discovered.json
```

What happens at each stage:

- **Collect** (`orchestra/collect/`). A command runs without a shell, in the repository root,
  with a timeout (default 10 s, never more than `every`). A scrape is an HTTP GET. Text over
  10 MB, a non-zero exit, a timeout, or an HTTP answer other than 200 fails the round. A failed
  round writes nothing, logs why, and increments
  `orchestra_collect_failures_total{collector=<name>}` labelled `machine="orchestra-host"`, so a
  failing instrument does not look alive. The Instruments page shows the failure and the last
  error.
- **Parse** (`collect/exposition.py`, `collect/round.py`). Each point gets `project` and
  `instrument=<name>`, its provenance; every other label the target served is kept as it is,
  `machine` included (the measured system's own dimension), and a target label Orchestra would
  overwrite is kept as `exported_project` or `exported_instrument`, as Prometheus does. Counters,
  gauges and untyped series are kept. Of a histogram or summary only `_count` and `_sum` are kept. Non-numbers are dropped. A
  series named `orchestra_*` is refused, because that prefix is Orchestra's own. A point with no
  timestamp gets the time the round began.
- **Store** (`orchestra/metrics/`). The store adds nothing but refuses points stamped more than
  60 s in the future. A point like that would make its writer look alive until a time that has
  not come yet.
- **Discover** (`orchestra/sd/`). Every `[discovery] every`, the host reads the window and builds
  the model. See [A discovery run](#a-discovery-run-step-by-step).
- **Show** (`orchestra/web/`). The web server's background threads read the stocks' latest levels
  every 15 s and their history over the last hour, and the Dynamics page draws them beside the
  host's latest discovery.

### An event, from a machine to the Machines page and the event map

```mermaid
sequenceDiagram
  autonumber
  participant X as Machine baker/2
  participant H as Events endpoint (endpoint/)
  participant E as Events.publish (events.py)
  participant B as Event bus
  participant C as Event collector (host.py)
  participant M as Metrics store
  participant I as MachineIndex (web/machines.py)
  participant P as Machines page
  X->>H: POST /events {type orchestra.machine.started, source baker/2, data}
  H->>H: check the token and the fields, never data
  H->>E: publish(type, data, source)
  E->>B: append CloudEvents envelope
  H-->>X: 201 {id}
  X->>H: POST /events {type bread.baked, subject order-17, id}
  H->>E: publish, unless the id was written already
  E->>B: append envelope
  X->>H: GET /events?after=#lt;offset#gt;#amp;wait=30
  H->>B: read after the offset until an event comes
  H-->>X: events, next
  loop every 2 s
    C->>B: read after last offset
    C->>M: orchestra_events_total{type, source} += 1
  end
  loop every 5 s
    I->>B: read after last offset
    I->>I: fold envelope: machine, instance, type, time, subject
    I->>I: read data only of orchestra.machine.started
  end
  P->>I: GET /api/machines
  I-->>P: machines, publishes and listens edges, hand-offs
  P->>P: draw the event map and its loops (netgraph.js, loops.js)
```

A machine written in Python may call `Events.publish` itself (the optional helper) instead of
the endpoint; the envelope and everything after it are the same.

What the Machines page knows about a machine, and where it comes from (`orchestra/web/machines.py`):

| What | Where it comes from |
|---|---|
| The machine and its instances | The envelope's `source`: `baker/2` is instance `2` of machine `baker`. |
| What it publishes | The `type` of the events it emitted, counted over all time and the last day. |
| What it listens for, its mode, kind, package, name and group | Its own announcement, `orchestra.machine.started` (or the older `orchestra.machine.subscribed`). This is the one event type whose `data` Orchestra reads, because it is Orchestra's own. Mode and kind are kept per instance. |
| Its series | Series in the metrics store labelled `machine=<id>`, and remote series that the latest discovery bound to it, listed on the card of a machine seen on the bus. A series labelled `machine=X` never makes a machine X. |
| Last seen, and whether it is active | Its latest event or its latest write, whichever is later, never in the future. It is active while that is within 2.5 times its own observed cadence (the median gap between its recent events or writes), and never less than 2 minutes. |
| Hand-offs (dotted edges) | Inferred from envelopes alone: one machine acted on a `subject`, then another machine acted on the same subject. |
| Its log | The `data.log` path it announced, read only if it resolves to a regular file inside the repository or the state directory (`web/machine_logs.py`). |
| Counted machines and channels | Counted traffic from other systems' buses (below), merged in by `web/traffic.py`. |

Only machines seen on the bus are listed, with counted-traffic machines and plugin placeholders.
Instruments are not machines and are not listed; they have the Instruments page. Announcements
the host made on an instrument's behalf before 2026-10-27 (`orchestra.machine.started` with
`data.collector`) are ignored.

A plugin may declare machines (`Plugin.machines`). A declaration is a placeholder: it only adds a
machine nobody has seen yet, fills in the package and kind of one that did not announce them, and
says nothing about flows. What is observed always wins (`mount_plugins.declare` in `web/app.py`).

The event map is drawn in the browser. `static/netgraph.js` draws it, `static/loops.js` finds its
feedback loops (an independent set of cycles through each strongly connected part of the graph),
and `static/edge-color.js` colours the lines.

### Other stores and counted traffic

A project can read series that live in another time-series store without copying them. A
**source** is the project's own store (`sources/own.py`) or any server that answers the
Prometheus HTTP query API (`sources/prometheus.py`: Prometheus, VictoriaMetrics, Thanos, Mimir,
Chronosphere). Sources are declared under `[[sources]]` in `orchestra.toml`. The pipeline:

```mermaid
flowchart LR
  SP["[[sources]] spec.py, auth.py"] --> SC["schema.py: families, labels, interval"]
  SC --> VW["views.py: one view per family"]
  VW --> TR["transform.py: query script, optional"]
  TR --> RK["rank.py: score and cap"]
  RK --> INF["infer.py: cache in state/sources"]
  DS["[[series]] and presets"] --> CAT
  INF --> CAT["catalogue.py: read for the window"]
  CAT --> FE["fetch.py: per definition"]
  FE --> RD["Reading: dump, kinds, provenance, missing"]
```

- **Credentials** come only from an environment variable or a file outside the repository. A
  literal secret in `orchestra.toml`, `user:pass@` in a URL, or a secret file inside the
  repository refuses the source (`sources/spec.py`, `sources/auth.py`). Pages and logs show where
  a credential comes from, never its value.
- **Inference** (`sources/infer.py`) runs every `infer_every` (an hour by default) and caches
  what it decided in `<state>/sources/<name>.json`.
- **Reading** (`sources/catalogue.py`, `sources/fetch.py`) reads every definition for exactly
  discovery's window, on its grid, never finer than the series' own resolution. Remote series are
  named `<prefix>:<name>`, and their machines `<prefix>.<value>`.
- **A missing source.** If a source is refused, unreachable or past its deadline, discovery still
  runs on what arrived, but the result is never saved as a version. An outage therefore neither
  deletes stocks nor churns versions.
- **Provenance.** Every series in a model records its source, final query, kind, origin,
  resolution and unit (`sd/provenance.py`, `SeriesRef` in `sd/model.py`).

**Counted traffic** (`sources/traffic.py`) is how Orchestra sees machines on another system's bus
(a RabbitMQ broker, a Pub/Sub topic) whose messages it cannot or should not read. A `[[series]]`
definition marks what it counts with `traffic = { direction, channel, machine }`: `out` (produced
into a channel), `in` (consumed from it), or `backlog` (what waits in it). These machines are
known by counts, never by events. No envelope is ever made from a count. The web server reads
every traffic series over the last hour, once a minute (`Catalogue.counted`, `web/traffic.py`).
The Machines page draws each channel as a box and each producer or consumer edge as a double
line. A count with no producer or consumer named goes to a grey "unattributed" stub. That name
places the count on the Machines page only; discovery never reads it to associate a machine with
a flow. In discovery, a
channel's backlog is balanced first by its own traffic, and a count that fills several backlogs
becomes a copy flow (`sd/ends.py`).

### A discovery run, step by step

Discovery runs from three places, all through one function,
`orchestra/sd/rediscover.py:rediscover`: the host's timer, `orchestra sd discover`, and the
Dynamics page's "rediscover now" button. One run at a time per project, across processes, is
enforced by an `fcntl` lock on `<state>/discovery.lock`. The host skips its turn when the lock is
held; the CLI and the web page wait.

```mermaid
sequenceDiagram
  autonumber
  participant H as Host timer or CLI or web
  participant RD as rediscover.py
  participant CA as Catalogue (sources)
  participant CS as discover.py (conservation)
  participant NF as netflow.py
  participant ST as strategies.py
  participant BD as bounded.py subprocess
  participant MS as ModelStore
  H->>RD: rediscover(project, metrics)
  RD->>RD: take discovery.lock, align window to the step
  RD->>CA: read(start, end, step)
  CA-->>RD: own and remote series, kinds, provenance, missing
  RD->>ST: discover_with(strategy, deadline = 0.8 x every)
  ST->>CS: discover(series, window, step)
  CS->>CS: sample, resolution, liveness, leave out
  CS->>CS: stocks by counters, flows, restatements, passages
  CS->>NF: levels no counters balance
  NF-->>CS: stocks by fitted net flow, or reasons
  CS->>CS: fit each flow by Poisson MLE
  CS->>CS: associate machines by their event counts (attribute.py)
  CS-->>ST: conservation model
  alt SD Lab strategy and stocks left to explain
    ST->>BD: jobs as JSON on stdin, killed at the deadline
    BD-->>ST: SD Lab flows, or Late
    ST->>ST: merge with counters, or keep conservation's fits
  end
  ST-->>RD: model
  RD->>RD: annotate provenance, mark not_saved if a source is missing
  RD->>MS: write_discovery (model/discovered.json)
  RD->>MS: save new version if structure changed and nothing missing
```

The steps in detail. Constants are named so they can be found in the code.

1. **The window.** It defaults to the last 60 minutes (`[discovery] window`) on a 30 s grid
   (`[discovery] step`). `rediscover.aligned` moves the window to end on a multiple of the step,
   so runs a few seconds apart sample the same grid and agree.
2. **Reading.** `Catalogue.read` returns the own store's series as they are and each remote
   definition read for exactly this window. A series' declared kind (a remote counter, a named
   level) overrides the naming rule (`sd.series.Declared`).
3. **Sampling and resolution** (`sd/series.py`, `sd/resolution.py`). Every series is put on the
   grid. A series is a counter if its name ends in `_total` and it almost never falls. Each series
   gets its own **resolution**, the usual gap between its real points:
   - A count or a state (a counter, or a level of whole values) is read by holding its last
     value.
   - A smooth measurement (values that are not whole) is read linearly between real points, and
     a repeated value counts as the same observation polled again. A feed that changes every half
     hour but is polled every minute has a resolution of half an hour.
   - The choice is recorded per series (`discovery.resolution`; `resolution_s` and `read` on
     every `SeriesRef`).
   - A level slower than the grid is balanced on the stretches between its writes, not on single
     steps.
4. **Liveness** (`sd/live.py`). Liveness belongs to the writer, not to the series. The writer is
   provenance only (`sd.series.writer_of`: a series' `instrument` label, else its `machine` label,
   else, for Orchestra's event counters, the `source`); it is never read for association:
   - A writer is alive while its writes (any of its series, or Orchestra's count of its events)
     come no further apart than ten times the interval of its fastest scheduled series (and at
     least a minute).
   - A writer with no scheduled series is taken to be alive from its first write to the end of
     the window.
   - A gauge holds its value while its writer is alive and goes stale when the writer goes
     silent.
   - Balances and fits use only the steps where everything involved was live. A writer that was
     down cuts only its own series' windows.
5. **Leaving out.** These are set aside, each with a reason recorded in `left_out`:
   - Orchestra's own plumbing series (`orchestra_*`, except `orchestra_events_total`).
   - Series whose writer has been silent at the end of the window for more than five minutes
     (`live.RESTART_S`, counted only over time when anything at all was written, so a computer
     asleep does not count): gone or replaced.
   - Levels live for less than half of the window's data (`MIN_COVER`): too new to be a stock
     yet, so they stay inputs.
   - Counters that move together in all but 3% of steps (`SAME_STEPS`) and have one writer, or
     one of which is Orchestra's count of the other's events, become one counter.
   - Counters that differ only by instance are summed into one per writer.
6. **Stocks by counters** (`sd/discover.py`, `sd/balance.py`). A level is a stock when signed
   counters balance its changes: `Δlevel ≈ Σ inflows − Σ outflows` with R² ≥ 0.9 (`MIN_R2`). The
   search order is:
   1. A channel's backlog by its own counted traffic.
   2. The level's own writer's counters (a stock records its writer as `written_by`).
   3. Every counter.

   The search itself is a penalised local search from many starts. Further rules:
   - A level that changed in fewer than 5 steps (`MIN_EVENTS`) is no stock.
   - A level with only two values is a flag unless its balance is exact in 97% of steps
     (`FLAG_EXACT`).
   - After every balance is known, stand-in counters give way to the writer's own counters
     (`sd/restate.py`, `sd/parsimony.py`, `sd/collinear.py`).
   - Two levels that change alike are one stock measured twice: one keeps it, the other is
     recorded as its twin.
7. **Flows** (`sd/ends.py`, `sd/hops.py`, `sd/passing.py`, `sd/between.py`).
   - A counter that leaves one stock and enters another is a flow between them. Otherwise it
     comes from, or goes to, outside.
   - A counter that fills several stocks is a copy: one flow from outside into each.
   - A state that items leave within one step is joined back into the chain. It is bound to the
     level whose raw points show it, or kept as a hidden stock if no series measures it: a
     question about the system (something in it is not measured or not understood yet).
8. **The net-flow layer** (`sd/netflow.py`). A level no counters balance may still be a stock.
   Its change per unit of time is fitted by least squares among four forms: a constant drift,
   `c + b × level`, `c + a × X`, and `c + a × X + b × level`, where X is another stock or
   measured level. A form must:
   - have ten changes per parameter;
   - beat the constant by an AIC margin that grows with the number of forms tried, counted on
     independent stretches, and still beat it without its largest change;
   - for a term in the level itself, pass a Dickey–Fuller threshold;
   - survive four refutations: a steady trend in time, prediction of the held-out half of the
     window, explaining at least 40% of the changes (`MIN_NET_R2`), and the driver shifted a
     quarter of the window explaining clearly less (`SHIFTED`).

   An accepted stock gets an inflow and an outflow with origin `fitted`, method `least-squares`,
   and no counter. A refuted level stays an input, with the reason. Every accepted
   driver is a correlation, not a tested cause.
9. **Fitting flow rates** (`sd/discover.py:fit_flow`, `sd/drivers.py`). Each counted flow's
   rate is fitted by maximum likelihood on its own live window, using the exact point-process
   likelihood. AIC chooses among a constant, proportional to the source stock, and linear in
   another stock or measured gauge (`c + k × X`). Guards against false drivers:
   - A form that reads another series needs 10 events per parameter (`EVENTS_PER_PARAM`).
   - A driver slower than the grid counts its own intervals, not events.
   - A stock that only fills may not drive anything, and neither may a stock whose balance counts
     the flow's own events.

   A linear form on another stock is an **influence**: the link that closes feedback loops.
10. **Association with machines** (`sd/attribute.py`). Which machines may be associated with
    each flow, only as hypotheses inferred with evidence, stored in
    `flow.evidence["machines"]` (`hypotheses`, best first, and `why`). Each hypothesis names the
    machine, origin `inferred`, `by`, the event type and source, the counts, `equal_steps`,
    `corr`, `lag`, a `why` sentence and a `confidence` from 0 to 1. `by` is one of:
    - **its own events**: the flow's counter is itself one machine's event count
      (`orchestra_events_total` of one type and source);
    - **events on the bus**: a machine's events of one type (its instances summed), counted in
      `orchestra_events_total`, match the counter's increments step by step, at lag 0 or one step
      either way: equal in at least 90% of the steps either moved (`EQUAL_STEPS`; confidence
      that share), or correlated at least 0.9 (`MIN_CORR`) with totals within a factor 2
      (`RATIO`; confidence the correlation times the smaller ratio of the totals).

    Several machines may be hypotheses for one flow. Orchestra's own `orchestra.*` event types are
    never candidates. Hypotheses come only from event counts on Orchestra's bus. Who wrote a
    series (its `instrument` or `machine` label) is never read for this, nor is a counted-traffic
    counter's `machine` (from a definition or `[sources.producers]`: a label, so a declaration);
    counted-traffic producers and consumers are still machines on the Machines page, known by
    counts. Nothing declares an association: not configuration, not a plugin. It never changes
    a flow's equation or the model's stocks and flows. A flow with none reads "no machine
    associated yet". `Machine.attributed` lists the flows a machine is a hypothesis for, and
    `observed_by` its event counts. Limits: a match is a correlation in time, not a cause; two
    machines reacting to the same events both match; and discovery may not tell apart two similar
    flows between the same stocks, so a hypothesis may belong to a flow's twin.
11. **SD Lab, under a deadline** (`sd/strategies.py`, `sd/bounded.py`). With an SD Lab
    strategy (the default is `kalman_lna` when the `sd` extra is installed, otherwise
    `conservation`):
    - It runs only on the stocks that counters do not balance exactly, and on net-flow stocks
      (`handed`). If there are none, it does not run.
    - Stocks are grouped by the measured flows that join them, and each group is one job. The
      measured moves are passed as `known`, and the other gauges as `inputs`.
    - The jobs run in a separate Python process (`python -m orchestra.sd.bounded`) in its own
      session. The whole process group is killed at the deadline, which is 0.8 ×
      `[discovery] every` (`DEADLINE_SHARE`).
    - If it is late or fails, conservation's fits are kept and the model says so.
    - Otherwise SD Lab's flows are matched back to counters (and so to the machines associated
      with them). A flow no counter
      measures is kept as "unmeasured" only where a stock's balance is not exact. For a net-flow
      stock, SD Lab's flows replace the fitted net flow only if they predict held-out halves
      better (`sd/rival.py`).
12. **Versions** (`sd/rediscover.py`, `sd/store.py`).
    - Every run writes `model/discovered.json`, which the web page reads.
    - A new version `model/vNNNN.json` is saved only when the run found stocks, its structure
      differs from the current version, and no source was missing. Structure means the stock
      ids, and each flow's id, ends, form and inputs (`discover.structure`).
    - `ModelStore.save` also refuses a model with duplicate ids or dangling references
      (`Model.check`), and adds nothing if the body is identical to the current version.

```mermaid
flowchart TD
  A["Series in the window"] --> B{"orchestra_* plumbing?"}
  B -- yes --> LO["Left out, with reason"]
  B -- no --> C{"Writer silent at end over 5 min?"}
  C -- yes --> LO
  C -- no --> D{"Counter?"}
  D -- yes --> D1{"Same events as a kept counter?"}
  D1 -- yes --> LO
  D1 -- no --> CNT["Counter: candidate flow"]
  D -- no --> E{"Live for half the window's data?"}
  E -- no --> IN["Input, with reason"]
  E -- yes --> F{"Changed in 5 or more live steps?"}
  F -- no --> LO
  F -- yes --> G{"Counters balance it, R2 at least 0.9?"}
  G -- yes --> H{"Two-valued and not 97% exact?"}
  H -- yes --> LO
  H -- no --> STK["Stock by counters"]
  G -- no --> NF{"Net flow form survives refutations?"}
  NF -- yes --> STN["Stock by fitted net flow"]
  NF -- no --> IN
  CNT --> FL{"Used in a stock's balance?"}
  FL -- no --> LO
  FL -- yes --> FIT["Flow: Poisson MLE, AIC picks form"]
  STK --> SDQ{"SD Lab strategy and balance not exact?"}
  STN --> SDQ
  SDQ -- yes --> SDL["SD Lab job, deadline 0.8 x every"]
  SDQ -- no --> MOD["Model"]
  SDL --> MOD
  FIT --> AS["Associate machines: hypotheses from event counts"]
  AS --> MOD
  MOD --> V{"Structure changed and no source missing?"}
  V -- yes --> SAVE["Save model/vNNNN.json"]
  V -- no --> CACHE["discovered.json only"]
```

The flowchart is simplified. Twins, restatements, passages and copies (steps 6 and 7) rework
stocks and flows after the first balances are found.

### State layout

```mermaid
flowchart TD
  HOME["~/.orchestrator/ or ORCHESTRATOR_HOME"] --> PJ["projects.json: repo root to key"]
  HOME --> KEY["#lt;key#gt;/ : repo name plus 8 hex of its path hash"]
  KEY --> P1["project.json"]
  KEY --> P2["runtime.json: hosts, launcher, events_endpoint, web, processes, instruments"]
  KEY --> P9["events.token: the events endpoint's token, owner-only"]
  KEY --> P3[".lock and discovery.lock"]
  KEY --> P4["events.jsonl, when events url is file"]
  KEY --> P5["metrics.jsonl, when metrics url is file"]
  KEY --> P6["model/"]
  P6 --> P61["vNNNN.json: the versions"]
  P6 --> P62["discovered.json: latest discovery"]
  KEY --> P7["sources/#lt;name#gt;.json: inferred definitions"]
  KEY --> P8["logs/"]
  P8 --> P81["orchestra-host.log"]
  P8 --> P82["machines/#lt;name#gt;.log: launched processes"]
  P8 --> P83["instruments/#lt;name#gt;.log"]
  EXT1[("Server bus: stream orchestra.#lt;key#gt;.events")] -.-> KEY
  EXT2[("VictoriaMetrics: series with project label")] -.-> KEY
```

- The project key is the repository directory's name plus the first 8 hex digits of a SHA-256 of
  its real path (`config.project_key`). The state directory is created on first use, so a
  repository that already has an `orchestra.toml` does not need `orchestra init`.
- `.lock` guards `runtime.json`. `discovery.lock` allows one discovery at a time.
- Logs rotate once at 5 MB, to `.log.1`.
- Inside the repository, Orchestra writes only `orchestra.toml`, and only on `orchestra init`.
- With a server bus or VictoriaMetrics, the event log and the metrics live in those servers
  instead of `events.jsonl` and `metrics.jsonl`. Everything else stays in the state directory.

## Backends

Both backends are chosen in `orchestra.toml`. An environment variable overrides each one.

```toml
[events]
url = "file"          # or redis://host:6379/0, amqp://user:pass@host:5672/, kafka://host:9092
[metrics]
url = "file"          # or http://host:8428 (VictoriaMetrics)
```

### Event bus backends

`orchestra/bus/__init__.py:open_bus` picks the backend by URL scheme. `ORCHESTRA_EVENTS_URL`
overrides `[events] url`. Every backend keeps one stream named `orchestra.<key>.events`
(`bus.stream_name`).

| `[events] url` | Module | How offsets work | Extra |
|---|---|---|---|
| `file` (default) | `bus/file.py` | Line numbers in `<state>/events.jsonl`; each append is one write of one line. | none |
| `redis://`, `rediss://` | `bus/redis_streams.py` | A Lua script increments a counter and adds the event with stream id `<n>-0`, so ids are dense integers. | `bus-redis` |
| `amqp://`, `amqps://` | `bus/rabbitmq_streams.py` | A RabbitMQ stream queue numbers messages from 0. Appends use publisher confirms. The slowest backend to poll. | `bus-rabbitmq` |
| `kafka://` | `bus/kafka.py` | One topic with one partition, so the Kafka offset is the offset. Created with `retention.ms=-1`. | `bus-kafka` |

The conformance suite `tests/bus/` runs against every backend (the server ones opt in by
environment variable). `orchestra events copy --to URL` copies a log from one backend to another.
`deploy/dev/compose.yaml` starts the servers locally.

### Metrics backends

`orchestra/metrics/__init__.py:open_metrics` picks the backend. `ORCHESTRA_METRICS_URL` overrides
`[metrics] url`.

| `[metrics] url` | Module | Notes |
|---|---|---|
| `file` (default) | `metrics/file.py` | One JSONL file, `<state>/metrics.jsonl`. An in-memory index parses only the lines appended since the last read. A range carries the last value forward without limit. PromQL is answered by `metrics/promql.py`, a tested subset. |
| `http://`, `https://` | `metrics/victoria.py` | VictoriaMetrics over HTTP: `/api/v1/import` to write, `/api/v1/export` to read raw points, `delete_series` to delete. Every write is followed by `force_flush`, so it can be read at once. Ranges are stepped locally with the same carry-forward rule as the file store, so both answer `range` alike. |

Both backends refuse points stamped more than 60 s in the future. The conformance suite is
`tests/metrics/`. Remote stores read in place are a separate thing: `[[sources]]`, read through
`orchestra/sources/`.

### Optional extras

| Extra | What it adds |
|---|---|
| `bus-redis`, `bus-rabbitmq`, `bus-kafka`, `bus` | Client libraries for the server buses. |
| `sd` | numpy, scipy, numba, highspy, sympy: SD Lab's strategies and the Dynamics page's simulation (`sd/simulate.py`). |
| `sd-research` | More libraries for a few research strategies. |
| `dev` | pytest, httpx, ruff. |

## The web UI

`orchestra web` (`orchestra/web/app.py`) serves five pages of its own, plus any plugin pages. The
pages are read-only for humans. Two background threads (`web/background.py`) keep caches warm,
so most page requests do no expensive work:

| Cache | Refreshed | Source |
|---|---|---|
| Machine index | every 5 s | The bus, read after the last offset (`MachineIndex.update`). |
| Series list, last writes, write cadence | every 60 s | `metrics.dump` of the project's series. |
| Stock levels | every 15 s | `metrics.latest` for stocks in the own store; the catalogue for remote ones. |
| History (last hour) | every 15 s | Stock levels and flow rates, own and remote. |
| Counted traffic | every 60 s | `Catalogue.counted` over the last hour. |

| Page | What it shows | Main code |
|---|---|---|
| **Dashboard** (`/`) | Movable panels: Machines (what runs now) and Host (a Core status strip, CPU, GPU, memory, disk). Plugins may add panels. | `static/dashboard.js` |
| **Core** (`/core`) | The host and its processes, the bus and the metrics store, each probed against its real backend under a 4 s limit; a metrics catalogue and PromQL editor; an event explorer; logs. | `web/core.py`, `web/core_explore.py` |
| **Machines** (`/machines`) | Every machine seen on the bus (and counted-traffic machines and plugin placeholders), its instances, mode and kind, whether it is active, the event map with hand-offs and counted traffic, communication loops, and a dialog per machine with its series, last events (envelopes only) and log tail. | `web/machines.py`, `web/traffic.py`, `web/machine_logs.py`, `static/netgraph.js`, `static/loops.js` |
| **Instruments** (`/instruments`) | What measures the system, apart from the machines: each `[[collect]]`, `[[scrape]]` and `[[sources]]` entry (and a plugin's), with its kind (script, URL, source), target, interval, last write and points, failures, last error and log. Read from the runtime record's `instruments` and `orchestra.toml`, never by running an instrument. `/api/instruments`, `/api/instruments/<name>/log`. | `web/instruments.py`, `static/instruments.html` |
| **Dynamics** (`/dynamics`) | The model as a stock-and-flow graph, with feedback loops marked balancing or reinforcing, history charts, each stock's and flow's drawer (a flow's lists each machine hypothesis with its why, or "no machine associated yet"), a flows table with "machines (hypotheses)" and their confidence, a simulation from the start of the era and a projection forward, and stepping through saved versions. "Rediscover now" runs discovery in the background. | `web/dynamics.py`, `sd/simulate.py`, `static/sd-graph.js`, `static/sd-layout.js`, `static/layout-worker.js` |

The Dynamics page reads the host's cached discovery (`model/discovered.json`) or a saved version.
It never discovers on request, except when the "rediscover now" button is pressed. The Core page
is built to keep working when the rest of Orchestra does not: `web/core.py` and
`web/core_explore.py` import only the bus, the metrics store, the runtime record and the
configuration, and every probe runs in a thread pool with a time limit.

## The CLI

| Command | What it does | Writes |
|---|---|---|
| `orchestra init` | Registers the repository and writes a starter `orchestra.toml`. | `orchestra.toml`, state directory |
| `orchestra run [--once]` | Runs the bootstrap host. | runtime record, bus, metrics, model, logs |
| `orchestra web [--port --host]` | Serves the web UI (default `127.0.0.1:8000`). | `web` in the runtime record |
| `orchestra events info` | Says which backend holds the log, how many events it has, and where the events endpoint is. | nothing |
| `orchestra events endpoint [--env]` | Prints the events endpoint's URL and the token's file, or `export` lines for both. | `events.token`, if it did not exist |
| `orchestra events copy --to URL [--force]` | Copies the event log to another backend. | the target bus |
| `orchestra metrics series` | Lists the project's series. | nothing |
| `orchestra metrics backfill [--append]` | Replays the whole log into `orchestra_events_total`. | metrics |
| `orchestra sd discover [--strategy --minutes --step-s]` | Runs discovery now (same code path as the host). | `model/` |
| `orchestra sd show [--version]` | Prints the model with current levels. | nothing |
| `orchestra sd versions` | Lists the saved versions. | nothing |
| `orchestra sd fit [--version --step]` | Refits every counted flow over the whole history and saves a version. | `model/` |
| `orchestra sources check\|infer\|preview QUERY` | Probes the sources, runs an inference round, previews a query's fan-out. | `sources/` cache on infer |

## Plugins

A plugin is a package installed in the same environment as Orchestra. It registers a function in
the entry-point group `orchestra.plugins`. The function takes the project and returns a `Plugin`
(`orchestra/plugins.py`):

| Field | Where it goes |
|---|---|
| `pages` | Served at their paths and linked in the navigation. A path Orchestra already serves is refused. |
| `static` | Served at `/plugins/<name>/static`. |
| `router` | A FastAPI router mounted at `/api/plugins/<name>`. |
| `scripts`, `stylesheets` | Loaded on every page, after Orchestra's own. Scripts may register Dashboard panels (`Orchestra.panels`) and draw the cards of machines the package claims (`Orchestra.machineCards`). |
| `machines` | Declared machines (`Declared`). They fill in only machines not yet seen. |
| `processes` | `launcher.Process` entries that `orchestra run` keeps running as `<plugin>.<name>`. |
| `collectors` | Instruments (`collect.spec.Collector`: `Collector.scrape(name, url, ...)`, `Collector.collect(name, command, ...)`) that `orchestra run` reads like the project's own, named `<plugin>.<name>`. A project entry of the same name wins, and the host logs that. Not machines. |

Plugins are loaded in two places. The web app loads them once at start (`web/app.py:mount_plugins`).
The host loads them again each time `orchestra.toml` changes, to ask for their processes
(`Host._plugin_processes`) and instruments. A plugin that raises, one whose name an earlier plugin
took, and a script or stylesheet missing from a plugin's static directory are reported (`/api/plugins`, the host's log) and
left out, and it never takes the web app or the host down. Orchestra knows nothing of what a
plugin's routes or pages mean. The two plugins today are the task system (`~/orchestra-tasking`)
and the AI agents (`~/orchestra-agents`), both in their own repositories.

## The invariants, and where the code holds them

The ten rules are in `AGENTS.md`. This table shows where the code enforces each one, or follows
it by design. Few of the rules are checked by a test. Most hold because of how the modules are
divided.

| # | Rule, in short | Where it is held |
|---|---|---|
| 1 | No tickets, tasks or AI in the core | The core modules handle only envelopes, series, processes and models. `collectors.py` counts events by `type` and `source` and nothing else. Agents' harnesses live in `~/orchestra-agents`. |
| 2 | Machines are outside, known by their events | `web/machines.py` builds machines from envelopes only; a series' `machine` label lists the series on a machine's card but never makes a machine. Of `data`, it reads only `orchestra.machine.started` announcements, and ignores the host's old ones for instruments. Plugin declarations fill in only unseen machines (`web/app.py:declare`). `web/machine_logs.py` reads a log only inside the repository or the state directory. `launcher.py` knows processes, not machines. Counted machines come only from `sources/traffic.py`. |
| 3 | Every event carries the CloudEvents envelope | `events.envelope` is the only place events are built. `Events.publish` always uses it, and the events endpoint publishes only through it, passing `data` on unread. `event_time` and `event_source` read older flat events too. Counted traffic is read as series and never turned into events. |
| 4 | One system, one model | One `ModelStore` per state directory, with one sequence of versions. Discovery runs over every series of the project at once. Package and group are labels on the Machines page, never separate views. |
| 5 | State in `~/.orchestrator/<key>/`; bus and metrics in their stores | `config.Project` names every state path. Events go through `Events` over an `EventBus`, metrics through `MetricsStore`, the model through `ModelStore`, process records through `runtime`. `bus.stream_name` keeps Orchestra's own namespace. The `Source` protocol (`sources/__init__.py`) has only read methods. |
| 6 | Every equation records its origin | `Equation.origin` is a required field (`sd/model.py`). Conservation writes `fitted`/`poisson-mle`, the net-flow layer `fitted`/`least-squares`, and SD Lab `discovered`/`sdlab:<strategy>`. `sd/attribute.py` associates machines with flows only as inferred hypotheses with evidence and confidence (`flow.evidence["machines"]`), never from a label or a declaration; `Machine.attributed` holds flow ids as hypotheses. |
| 7 | Stocks are discovered, not configured; measurements are not machines | `Config` has no stock or flow bindings. `sd/discover.py` decides from the data alone. A series' declared kind (counter or level, from a `[[series]]` definition) is the only hint it takes. Instruments label points `instrument=<name>` (`collect/round.py`), announce nothing, and are shown on the Instruments page. A writer label is provenance only (`sd.series.written_by`). |
| 8 | The core stays up | `web/core.py` and `web/core_explore.py` import only the bus, the metrics store, the runtime record and the configuration. Every probe runs under `TIMEOUT` (4 s). Plugins that fail are left out. |
| 9 | Humans talk only to the Supervisor; UI and CLI read-only except observations | The web app has two POST routes: "rediscover" (an observation) and the Core page's bus probe. Any path that changes machines belongs to a plugin. The events endpoint is the bus reached over HTTP, for machines, as the Python helper is; the web UI and CLI gain no write from it (`events endpoint` only prints where it is). |
| 10 | One package, no path hacks | `pyproject.toml` packages only `orchestra`. No module changes `sys.path`. `orchestra/sdlab` is excluded from ruff (`extend-exclude`) and its README records its source commit. |

**Known departures** (as of `828da6d0`). These are places where the code goes further than the
table above says. They are listed here so nobody relies on the rule being absolute:

- `web/core_explore.py:_vm` sends the PromQL editor's queries straight to VictoriaMetrics' HTTP
  API, not through `MetricsStore` (rule 5).
- `sd/fit.py:running_intervals`, used only by `orchestra sd fit`, reads `loop_started` and
  `loop_stopped` events, which come from the old task loop (rule 1).
- Some CLI commands change stored data beyond rediscovery: `sd fit` saves a version,
  `metrics backfill` replaces the event counters, and `events copy` writes to another bus. The
  Core page's probe also appends an `orchestra.core.bus_probe` event (rule 9).

## Not built yet

These are plans, not features. Each is described in `docs/proposals/` or `docs/roadmap/`:

- Subscriptions with leases on the bus, and model tools for the Supervisor
  (`docs/proposals/empty-orchestra.md` §3, §10).
- Running machines on a clock (`docs/roadmap/decisions.md`, D7).
- The later slices of reading other stores: a cache of settled chunks, fingerprints and
  `sd verify`, a Sources page, command, OAuth2 and SigV4 auth, and SQL sources
  (`docs/proposals/time-series-sources.md`).
- The rest of event sources: a Pub/Sub preset, the topology poller, and bridges from Jira, Slack
  and others (`docs/proposals/event-sources.md`).
- Ghost machines, the environment as a flow's driver, and leverage points
  (`docs/proposals/environment-and-ghost-machines.md`).
- Eras, delays, non-linear forms, priors, and prospective model versions
  (`docs/proposals/system-dynamics-core.md`, `docs/proposals/orchestra-kernel.md`,
  `docs/roadmap/README.md`).
- Collectors that skip repeated values (the collectors' half of "each series' real resolution",
  `docs/roadmap/README.md` H1).

## Where to read next

- [USING_ORCHESTRA.md](USING_ORCHESTRA.md): running Orchestra on a project.
- [PLUGINS.md](PLUGINS.md): writing a plugin.
- [docs/machines.md](docs/machines.md): writing a machine (events, long-running programs) and its
  measurements (instruments: collectors, scrapes; naming).
- `SPEC.md`: the full design, with every rule of discovery.
- `AGENTS.md`: the rules that must not be broken.
- `docs/roadmap/README.md`: what comes next, and how it is judged.
