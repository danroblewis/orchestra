# Orchestra Specification

Orchestra observes a system of **machines** and keeps a **system dynamics model** of it. A
machine is anything outside Orchestra that does something: a program, an AI agent, a service, a
team of people. Machines talk over Orchestra's **event bus** and write measurements to its
**metrics store**. From those measurements Orchestra builds and fits one model of the whole
system: stocks, flows, and the feedback loops between them, with each flow attributed to the
machines believed to cause it.

Its main use case is finding the feedback loops between a project's own domain and the processes
used to develop it: do our workflows and AI agents change the measures the project exists for?

This version is an **empty Orchestra**: the bus, the metrics store, the model, the bootstrap host
and the web UI, with no machines of its own beyond the host, and no AI: an AI agent is a machine
like any other, run by whatever runs it. Task management lives in its own repository
(`~/orchestra-tasking`), the AI agents in another (`~/orchestra-agents`);
each adds its pages here as a plugin (§10.1). How they left is in
`docs/proposals/empty-orchestra.md`.

This document is the design of what exists. `AGENTS.md` lists the rules that must not be broken;
`docs/proposals/` holds what is proposed and not yet built.

---

## 1. Principles

1. **System dynamics first.** Everything Orchestra does serves the model: what is measured, how
   stocks and flows relate, and which machines change them.
2. **Machines are outside Orchestra.** Orchestra can't guarantee what a machine does; it knows a
   machine only by what it observes: events on the bus and series in the metrics store.
3. **There is one system and one model.** Development and domain sit side by side. Large models
   are sliced for viewing with metadata, filters and graph algorithms, never split.
4. **Flows are observed, not proclaimed.** Equations are fitted or discovered from the measured
   history, and every equation records its origin. A machine's intended effect is a hypothesis.
5. **Stocks are discovered, not configured.** Collectors expose plain series; the model generator
   relates them.
6. **The core stays up.** The bus, the metrics store and the host are probed on their own, so the
   Core page works when the model or every machine is broken.

---

## 2. Machines and events

A **machine** is identified by the CloudEvents `source` it publishes under. Several instances of
one machine publish as `<machine>/<instance>` (`baker/1`, `baker/2`: one machine, two instances)
and label their metrics `machine=<machine>, instance=<instance>`. A machine may publish to the
bus, listen to it, write metrics, all of these, or none (a machine that only changes measures
others write is still a machine). Orchestra's own machine is the **bootstrap host**,
`orchestra-host` (section 5).

**How a machine is engaged** is one of three modes, a property of how it is run, not of what it
is: **continuous** (long-running instances that take work as it comes), **scheduled** (run by
the clock) or **ad hoc** (a fresh instance per piece of work). An instance announces its mode,
what it listens for, what kind of thing it is (`data.kind`: program, agent, person or service)
and which package it belongs to (`data.package`) when it starts (`orchestra.machine.started`,
`data.mode`, `data.listens_for`), and may say where its log is (`data.log`, a file path). These
announcements are Orchestra's own event type, so Orchestra reads their `data`. The web server
shows an announced log only when its real path is a regular file inside the project's repository
or state directory (`web/machine_logs.py`), because anything that can publish could name any
file. The host starts and keeps running the commands a project or a plugin declares (§5.1), but
knows them only as processes: a process becomes a machine by what it publishes. Running machines on
a clock is not built (`docs/roadmap/decisions.md`, D7).

Every event carries the **CloudEvents 1.0** envelope (`orchestra.events.envelope`):

| Field | What it is |
|---|---|
| `specversion` | `1.0` |
| `id` | Unique |
| `type` | e.g. `bread.baked`; Orchestra's own start with `orchestra.` |
| `source` | The machine that emitted it |
| `time` | RFC 3339, milliseconds |
| `subject` | Optional: what the event is about |
| `correlationid`, `causationid` | Optional extensions: the request it belongs to, the event that caused it |
| `data` | The payload. It belongs to the machines that use it; Orchestra never reads it |

An event brought in from another system (a sync from its own log) keeps the `time` it happened
there and an `id` stable across re-imports (`envelope(time=, id=)`), so a sync can tell what the
bus already holds. Events written before the envelope (flat records with `ts`) stay readable; `event_time` and
`event_source` read either shape.

**Subscriptions.** Until the bus adapters provide subscriptions with leases
(`docs/proposals/empty-orchestra.md` §3), a machine reads the bus by offset and announces what it
listens for in `orchestra.machine.started` (the older `orchestra.machine.subscribed` with
`data.types` is read too). The Machines page draws
the graph of publishers, event types and listeners from what it observes.

---

## 3. The event bus

An append-only, replayable, ordered log per project (`orchestra/bus/`), behind the `EventBus`
interface: `append`, `read(since, limit)` → (events, end offset), `end`, `close`. Offsets are
integers counting events. A machine that follows the bus calls `Events.after(offset)`
(`orchestra/events.py`), which returns every event after the offset and the offset to read from
next; `read` returns only the last `limit`. The stream is named `orchestra.<project key>.events` and never shares a
topic with anyone else's.

| `[events] url` | Backend |
|---|---|
| `file` (default) | A JSONL file in the state directory |
| `redis://host:port/db` | Redis Streams (Lua-assigned integer offsets) |
| `amqp://user:pass@host:port/` | A RabbitMQ stream queue |
| `kafka://host:port` | One Kafka topic with one partition |

`ORCHESTRA_EVENTS_URL` overrides the file. One conformance suite (`tests/bus/`) runs against every
backend; server backends need their client library (`orchestra[bus-redis]`, `[bus-rabbitmq]`,
`[bus-kafka]`). `orchestra events copy --to URL` moves a log between backends.

---

## 4. Metrics, collectors and the model

### 4.1 The metrics store

Measured series (`orchestra/metrics/`): name plus labels, like Prometheus, each carrying a
`project` label. A JSONL file by default, or VictoriaMetrics (`[metrics] url =
"http://host:port"`, or `ORCHESTRA_METRICS_URL`). The interface: `write`, `raw`, `range`,
`latest`, `series`, `dump`, `delete`. A range carries the last value forward at each step. Machines
write their own series, labelled `machine=<id>` so they can be attributed, through
`orchestra.metrics.for_repo()`: the store the project's `orchestra.toml` configures, adding the
`project` label every reader selects by. Names say what is measured (`bakery_shelf_loaves`,
`orchestra_events_total`); whether a series is a stock or a flow is the model's business. The
`orchestra_` prefix is Orchestra's own: discovery leaves those series out, and says so of one a
program wrote. How to write a machine's series is in `docs/machines.md`.

Queries are PromQL: VictoriaMetrics answers them itself (scoped with `extra_label=project=<key>`);
the file store uses `orchestra/metrics/promql.py`, a tested subset.

### 4.2 Collectors

Orchestra's own collector (`orchestra/collectors.py`) counts every event on the bus by type and
source: `orchestra_events_total{type, source}`. The host runs it live (section 5); `orchestra
metrics backfill` replays the whole log. Only the last value of a series at an instant is written,
because stores disagree on the order of points that share one.

### 4.3 The model

`orchestra/sd/`: stocks (each bound to a series), flows (each bound to a counter), equations
(each with its **origin**: `fitted`, `discovered` or `declared`, and its quality), machines
attributed to flows, and eras. There is **one model** per project; every change is saved as a new
version (`<state>/model/vNNNN.json`), the highest is current, and past versions stay readable.

**Fitting** (`sd/fit.py`): each flow's count per step is Poisson with mean `c × time`
(constant) or `k × the source stock's level × time` (proportional, the exact integral of the
level), fitted by maximum likelihood; the form with the higher likelihood is kept, with its
standard error and dispersion.

**Discovery** builds the model from the metrics store without being told what anything is. It
runs with a **strategy** (`[discovery] strategy` in `orchestra.toml`, or chosen for one run on the
Dynamics page): `conservation`, Orchestra's own (below), or one of SD Lab's ~70
(`orchestra/sdlab`, brought in from SD Lab's discovery research; `kalman_lna` by default when the
`sd` extra is installed; `combined2` and `matrix_v2` are the other strong ones). With an SD Lab
strategy, conservation still runs first and finds the stocks and the counters that measure flows;
the SD Lab strategy then works from the stocks' levels (on the time every series was written),
with the measured moves handed to it as what is already **known** of each step, so it explains
only the residual (hidden stocks, unmeasured inflows and drains, the inputs that drive them); the
other measured gauges are its inputs (`sd/inputs.py`: not flags nor a stock's twin, one per
machine with the instances summed; conservation's fit reads the same gauges), and stocks are
grouped by the measured flows that join them. Its flows are
matched back to the counters and their machines (`sd/strategies.py`); several between the same
ends become one with one rate of several terms; one that no counter measures is kept, as
unmeasured, only where the stock's balance is not exact (a strategy that ignores `known` invents
flows for stocks whose counters already explain every step, and those are dropped and recorded).
Its richer forms (gap, linear in several stocks or inputs, expressions, effects) are kept in
each equation's `spec`, and its hidden stocks are drawn dashed. The host gives a strategy a
deadline below `[discovery] every`, and one discovery runs at a time per project across
processes (the host skips a scheduled run while the CLI or the web page is discovering). Every
run's window starts and ends on multiples of the step (`sd/rediscover.py`), so runs a few
seconds apart sample the same grid and agree.

Conservation (`sd/discover.py`):
1. every series is sampled onto a grid of steps, and marked with when it was live
   (`sd/series.py`, `sd/live.py`). Liveness is the machine's, not the series': a machine is
   alive between writes (any of its series, or Orchestra's count of an event it published) no
   further apart than ten times the interval of its fastest series written on a schedule (at
   least a minute); a longer silence is it down or not yet started. A machine none of whose
   series is on a schedule writes only when something happens, so its silence says nothing, and
   it is alive from its first write to the end of the window. A gauge that is not re-written
   because nothing changed holds its value while its machine is alive (a count of loaves on the shelf in
   a quiet quarter of an hour), and goes stale only when the machine goes silent: its
   value from before the silence is not carried past it, so it is live from its first write in
   each stretch its machine was alive. A counter is live whenever its machine is, and before its
   first point it had counted nothing. A level's balance and a flow's fit use only the steps in
   which the level and the counters involved were all live; the stock records how many steps
   that was, and how long its value was held on its machine's word (`held`, in the stock's
   evidence and the discovery notes). A series whose machine is silent at the end of the window
   (gone, or replaced) is left out, and so are Orchestra's own series but its event counters
   (`orchestra_core_*`, `orchestra_host_up`: plumbing, not a measure of the system). Counters
   that move together in all but 3% of steps are one when one is Orchestra's count of the
   other's events, or both are one machine's: the machine's own, then the shorter name, is kept;
   two machines' counts of the same events both stay (each machine's stocks take their own) and
   become one afterwards where they join two stocks (step 2). Counters that differ only by
   instance (an ``instance`` label, or ``source`` ``baker/3``) are summed into one per machine,
   and a flow from such a sum is measured by every instance's series;
2. a level is a **stock** when counters, added or subtracted, balance its changes
   (`Δlevel ≈ Σ inflows − Σ outflows`, R² ≥ 0.9). A level that only takes two values is
   usually a flag (busy or not) and is a stock only when its balance is exact in 97% of steps (a
   shelf that holds nothing or one item). A level that changed in fewer than 5 steps is no
   stock, and a counter that counted fewer than 5 events carries no balance (on three steps a
   level and a counter coincide by chance as readily as a stock and its flow): such a counter
   may only complete a balance that counters above the bar carry, and only to exact. The
   counters are found by a local search on an objective of squared error plus a penalty per
   counter (change one coefficient, or swap one counter for another), run from many starts
   (least squares on all counters rounded to ±1, nothing, each counter alone, the best pairs)
   with the best kept, on the counters' Gram matrix so each candidate move is cheap
   (`sd/balance.py`). A balance exact in every step earns back most of one penalty, so the rare
   counter that completes it (a refund among a hundred orders) is kept. A small set of chosen
   counters that cancels to nothing is dropped, and one that equals an unchosen counter is
   replaced by it (`sd/collinear.py`). The level's own machine's counters are searched first
   (its record of its transitions, with Orchestra's counts of its events): when they balance it
   within the tolerance, that is its balance, and another machine's counter never replaces one
   of them (an oven's own counters come before the board's, however exactly they
   coincide); it enters only to explain the residual the machine's own leave. Every counter is
   searched only when the machine's own do not balance the level. Then, with every balance
   known, the stand-ins give way (`sd/restate.py`): Orchestra's event counter to the
   machine counters that sum to it, when one is another stock's or the level's own machine's
   (among sets that sum to it alike, the level's own machine's parts before another machine's
   copy of one of them); another machine's counter that no other stock claims to the level's
   own counters that sum to it; and two machines' counts of one flow, one leaving a stock and
   the other entering another, to one counter in both balances (one that a stock of its own
   machine holds before another machine's copy, then the one stamped first). Last, two or three
   of a balance's counters whose signed sum one unused counter counts by itself (each a moment
   before or after the other: running totals never more than an event apart) give way to it
   (`sd/parsimony.py`: the customers' orders less the app's are the takers' own orders taken),
   never the level's own machine's counters, never for Orchestra's event counter. A restated balance must still
   fit as a stock's. Two levels that change alike in 97% of steps, or that the same counters
   balance (two machines' counts of the same events being one counter), or, judged on the
   levels themselves, whose changes correlate by 0.9 or whose values are equal in 97% of the
   steps either held something (a copy a moment behind, balanced by its own machine's
   counters), are one stock measured twice: the machine whose counters make the balance keeps it, the other is recorded as its
   twin. A level that only fills is a stock when its balance is exact, whatever feeds it (a
   terminal state, where other stocks' outflows end); one the system's flows explain only
   roughly is a tally of activity unless counters no ordinary stock uses balance it;
3. a counter that leaves one stock and enters another is a **flow** between them; otherwise it
   comes from or goes to outside. A state each item leaves within a step (an order picked up and
   at once accepted or rejected; a ticket rejected and back in progress a second later) is empty
   at almost every step of the grid, so it is no stock, and the chain through it would run past
   it or split through outside. It is joined through again (`sd/hops.py`, `sd/passing.py`): a
   machine's two counts of one move (kept as one, being the same events within a step) are
   split back into its two hops, and a drain to outside and fills from outside of other stocks
   whose counts are the same items, the fills never ahead of the drain nor more than a step
   behind (the drain of at least 5 events; a rarer counter only completing it exactly, and a
   rarer fill, the few orders sent back, only when a free counter of its machine with 5 events
   is the other way out or the measured state below vouches for it: the passage is judged on
   all its evidence, so it does not come and go with the one event that takes the fill over the
   bar at the edge of a window), become a flow into the state and flows out of it. The state is the measured level whose raw points
   rise at the inflow's events and fall at the outflows' (`sd/between.py`: the grid misses it,
   the raw points do not); with none (no level is written, or one never reads above zero), a
   stock measured by no series, drawn as hidden. The drain and the fill are each claimed by one
   stock alone, other members are the drain's or the fill's machine's, no in and out but those
   two count the same events, Orchestra's event counters take no part, and no stock is both
   drained and filled by one passage. The stock and its flows record it (`passing`, `through`);
4. each flow's rate is fitted by maximum likelihood, choosing by AIC among constant, proportional
   to its source, and linear in any stock or any measured gauge that is not a stock (`c + k ×
   X`; the gauges are those `sd/inputs.py` offers, recorded in the equation's inputs as
   `input:<name>`). A form that reads another stock or an input is offered only with 10 events
   per parameter (20 for `c + k × X`, on any X): below that a level that happened to be high
   beats the constant on likelihood alone, and the constant or the source's proportion is all a
   flow gets. A linear form on a stock other than the flow's source is an **influence**,
   the link that closes feedback loops. A stock that only fills is offered to no flow (it stands
   in for time), nor is a stock whose balance counts the flow's own events (the same events, or
   at least half of them either way; `sd/drivers.py`): it is one off just before each of those
   events by construction (the free takers just before an order is placed), which beats any
   real driver on likelihood; the flow's evidence records such stocks as `not_drivers`. Forms
   are scored with the exact point-process likelihood (each event against the levels just
   before it), because counts per step favour spurious forms when a flow drains the level it
   depends on;
5. each flow is attributed to the machine named by its counter's `machine` (or, for event
   counters, `source`) label.

Everything else is **left out, with the reason** (did not change, written in too few steps, no
counters balance it, not needed by any balance, the same as another counter), recorded in the
model version. Not yet: stocks no series measures,
delays, non-linear forms, eras. The bakery (`~/orchestra-bakery`, its own repository) is a toy
system it is tested on.

---

## 5. The bootstrap host

`orchestra run` starts Orchestra's own machine (`orchestra/host.py`). In an empty Orchestra it:
- registers itself in `<state>/runtime.json` (`hosts`, by pid) and logs to `<state>/logs/orchestra-host.log`;
- publishes `orchestra.host.started` and `orchestra.host.stopped`;
- writes `orchestra_host_up{machine="orchestra-host"}` every interval;
- runs the event collector: replays the bus once at start, then follows it;
- rediscovers the model every `[discovery] every`;
- keeps running the processes the project and the plugins declare (§5.1).

### 5.1 The launcher

`orchestra/launcher.py`. A project declares the commands it wants kept running in `orchestra.toml`:

```toml
[[machines]]
name = "telemetry"                                  # letters, digits, . _ -
command = "uv run python machines/telemetry.py"     # split like a shell would, not run by one
restart = "always"                                  # always (default) | on-failure | never
```

and a plugin in `Plugin.processes` (§10.1). The host starts each in the repository root, in a
process group of its own, with `ORCHESTRA_REPO` (the root) and `ORCHESTRA_MACHINE_LOG` (its log,
`<state>/logs/machines/<name>.log`, which receives its output) set. One that exits is started again
after a pause that doubles with each exit within a minute of starting (1 s up to 60 s); after five
failures (non-zero exits) in a row, each within a minute of starting, it is given up on, which the
host's log, the process's log and the bus (`orchestra.process.gave_up`) say. It is tried again when
its entry changes or the host restarts. The host also publishes `orchestra.process.started` and
`orchestra.process.exited`. It re-reads `orchestra.toml` whenever the file changes (checked every
second): a new entry starts, a removed one stops, a changed one restarts; a file that does not
parse leaves what runs alone. Stopping the host stops every process group it started (SIGTERM, then
SIGKILL after 10 s); a host started again after being killed first stops what the previous one left
running. Only one host launches for a project. It holds `launcher` in the runtime record (its
pid and its process's create time, so a reused pid is not taken for it), taken under the record's
lock only when nobody holds it or its holder is dead, and cleared only by that holder when it
stops. A second host, started while one runs, launches nothing and writes nothing of the
launcher's; one that takes the launch from a dead holder first stops what that holder left
running. Every process is in the runtime record (`processes`), which the Core page shows while
the launching host runs.

The launcher starts commands and nothing more: what a process does and which machine it is are
learned only from what it publishes (AGENTS.md rules 1 and 2). A process's name is not a machine
id.

---

## 6. Machines that are AI agents

Orchestra runs no AI. An AI agent is a machine like any other, known by its `source`, its events
and its series; what starts it and talks to its model belongs to the package that runs it, which
keeps its own harness (`~/orchestra-agents/SPEC.md`).

---

## 7. Storage

```
~/.orchestrator/                 (ORCHESTRATOR_HOME overrides)
  projects.json                  repository root → project key
  <key>/
    project.json
    runtime.json                 the hosts', the launcher's, the web server's and the launched processes' records
    events.jsonl                 the event log, when [events] url = "file"
    metrics.jsonl                the metrics, when [metrics] url = "file"
    model/vNNNN.json             the model's versions
    logs/orchestra-host.log
    logs/machines/<name>.log     each launched process's output (§5.1)
```

The project key is the repository directory's name plus a hash of its path. Nothing is written
inside the repository except `orchestra.toml`.

---

## 8. Configuration

`orchestra.toml` at the repository root (`orchestra init` writes a starter):

```toml
[events]
url = "file"            # or redis://, amqp://, kafka://
[metrics]
url = "file"            # or http://host:8428 (VictoriaMetrics)
[discovery]             # strategy, window, step, every, [discovery.options]
strategy = "kalman_lna"
[[machines]]            # the commands `orchestra run` keeps running (§5.1)
name = "telemetry"
command = "uv run python machines/telemetry.py"
```

Unknown sections are ignored, so files written for older versions still load, and a package of
machines may keep its own settings here (other packages' sections).

---

## 9. CLI

| Command | What it does |
|---|---|
| `orchestra init` | Register the repository and write `orchestra.toml` |
| `orchestra run` | Run the bootstrap host, and the processes the project and plugins declare |
| `orchestra web [--port]` | Serve the web UI |
| `orchestra events info\|copy --to URL` | The event log |
| `orchestra metrics backfill\|series` | Replay the log into event counters; list series |
| `orchestra sd discover [--strategy S] [--minutes N] [--step-s S]\|show\|fit\|versions` | The model: discover it from the metrics, show, refit, list versions |

---

## 10. Web UI

Read-only for humans. Navigation: Dashboard, Machines, Dynamics, Core.

- **Dashboard:** panels as sections of one page on a 12-column grid (`static/dashboard.js`, with
  gridstack.js): the viewer drags a panel by its title bar and resizes it from its edges and
  corners, panels pack upward so one sits under another with no gap, and a panel can be hidden
  and brought back from Panels (in the navigation); positions and sizes are kept in the browser,
  and a narrow window has one column. A panel may give its starting size. Orchestra's own panels are **Machines** (a short list of
  what runs now: the machines that announced themselves continuous, and any other that published
  in the last two minutes; a click opens its dialog) and **Host** (a Core status strip; the
  host's CPU, GPU, memory and disk). A package adds panels of its own (`Orchestra.panels`, from its
  every-page script; §10.1).
- **Machines:** every machine seen on the bus with its instances and how it is engaged, the event map (by default machines only: an
  arrow where one publishes an event type the other listens for, one line with two arrowheads where
  two talk both ways, thicker with more traffic, the event types on hover; or with the event types
  as boxes; event families, the name up to its first dot, can be hidden; dotted, the hand-offs
  inferred from the envelope: one machine acted on a subject after another did, which connects
  machines that announce nothing, such as a system brought in from outside), its feedback loops, and each machine's metrics. Clicking a machine
  (its card or its node) opens its dialog: instances, what it publishes and listens for, its
  series' latest values, its last events (envelopes only) and the tail of its announced log,
  refreshed while open.
- **Dynamics:** the model as a stock-and-flow network (stocks with their level, tank fill and
  sparkline; a valve per flow with its equation and machine; influences as dashed +/− links),
  its feedback loops marked balancing or reinforcing, the stocks' history, and drawers with each
  stock's and flow's history (a flow's observed rate against its equation's prediction). A
  stock's drawer also runs the equations (`sd/simulate.py`, SD Lab's simulator): from the measured
  levels at the start of the era to now, and from now a horizon the viewer chooses; flows with no
  form the simulator steps are replayed from their observed rates, and named. Its flows are split
  into what fills it and what drains it (drawn below zero). It shows the host's latest discovery
  and steps through saved versions.

The model's graph frames **the system**. There is one system: every stock and auxiliary is
inside it, and only the environment (the clouds flows come from and go to) is outside, so what
crosses the frame is what the model does not explain. Subsystems (perhaps feedback loops in boxes
of their own) are a later question. A **rediscover now** button reruns discovery in the background (an observation: it
re-reads the metrics and may save a version, as the host does every 5 minutes).

Both graphs are drawn by one renderer (`static/netgraph.js`). The Dynamics graph is laid out by
ELK's layered algorithm (`static/sd-layout.js`: the system as a box of its own, in layers along
its flows), its unconnected groups packed side by side to fill the view's shape (no group sits among
another's lines), refined by springs so nothing is left far from what it is connected to, busy
stocks keep room for their flows and a labelled flow is long enough for its label, then untangled
by a local search in a worker (`static/layout-worker.js`: moves, jumps and swaps of nodes and
groups) so that no two lines cross (flows, dashed influences and cloud stubs alike) and none runs
behind a box unless avoiding it would shrink the drawing below readable size; nodes glide to each stage. Edge labels sit where they cover no box and no
other label (`placeLabels`); the Machines page's event map uses d3's forces, its lines in
their machine's colour, toned down (`static/edge-color.js`: solid, it publishes; dashed, it
listens; near-grey, not seen in 24 hours; full colour on hover). A layout keeps its shape: only
new nodes are placed (the known ones held still), every position is remembered per viewer,
dragging moves one node, and "tidy" or "reset" lay it out again on purpose. The layout is measured
(`static/layout-score.js`) by `tests/layout` on saved models (`tests/fixtures/dynamics`). On the Dynamics page each stock has at most one source cloud and one sink cloud. A cloud is
placed by rule: just outside the frame, level with its stock, on the side whose stub (and the
influences into it) crosses fewest lines and boxes, nearest first, a crossing worth at most 300 px
more stub; it follows its stock when it moves, never pinned elsewhere (a cloud far from the boundary means nothing). A stock with flows across the boundary is drawn toward the
nearest side, and those flows are drawn thinner and dimmer, so a boundary crossing is a short,
quiet stub (still visible: it is what the model does not explain). A measured level that a rate reads but no counters balance is an **auxiliary**: inside the
system, drawn round so it does not read as a stock. Loops (`static/loops.js`, the same for both graphs) are
not every cycle: a graph's feedback structures (its strongly connected parts) are found, and in
each an independent loop set (the shortest cycle through each link, kept only when it adds a link,
after Oliva 2004), with cycles through the same nodes merged as routes of one loop; all other
cycles are combinations of these. On the event map two machines that talk both ways are an
exchange, listed apart, and a loop has at least three machines ("communication cycles"). On the
Dynamics page each loop is balancing or reinforcing and either "items circulate" (every link
material moving along a flow) or "information" (a level steering a rate). Clicking one highlights
it. Pages read only the web server's background caches
(`web/background.py`) and the host's cached discovery, never the stores on request.
- **Core:** the host (with the processes it keeps running: state, restarts, command), the bus and
  the metrics store, each probed against its real backend within a time limit; explorers for the
  metrics (a catalogue of every series with the project's label, naming any series in the file
  store that lacks it, and a PromQL editor) and the events (types, volumes, sources); logs (the
  host's, Core's, the event stream and each launched process's). It imports only the bus, the metrics store and the runtime record.

### 10.1 Plugins

A package installed beside Orchestra (a task system, for example) may add pages and API routes of
its own (`orchestra/plugins.py`). It names a function in the entry-point group
`orchestra.plugins`; the function takes the project and returns a `Plugin`: its pages (a path, a
title for the navigation, an HTML file that may use `/static/app.js` and `/static/style.css`), a
static directory (served at `/plugins/<name>/static`), a FastAPI router (at
`/api/plugins/<name>`), the processes `orchestra run` should keep running for it (`processes`:
`orchestra.launcher.Process`, §5.1), and scripts from its static directory that every page loads after its own
(for what must be visible wherever the viewer is, such as the way to reach the package's own pages).
From those scripts a package may register Dashboard panels (`Orchestra.panels`) and draw the cards
of the machines it claims (`Orchestra.machineCards`: what is inside Orchestra's machine-card
frame, a few words for the Dashboard's machine list, and the machine's dialog). Its look is in its
own stylesheets, files from its static directory that every page links in its head after
Orchestra's (`stylesheets`): Orchestra's has nothing of any package's domain. `/api/plugins` lists
the pages, which the navigation adds after Orchestra's own, and any plugin that failed to load.
A plugin that fails, or a page at a path Orchestra serves, is left out, never fatal. A plugin is
the package's, not Orchestra's: its routes are its own, and Orchestra knows nothing of what they
mean.

---

## 11. Package layout

```
orchestra/
  cli.py  config.py  events.py  runtime.py  host.py  launcher.py  collectors.py  plugins.py
  bus/       file, redis_streams, rabbitmq_streams, kafka
  metrics/   file, victoria, promql
  sd/        model, store, fit, series and live (sampling, when a series was written), balance,
             collinear and restate (a level's balance), ends, inputs, drivers (which stocks may
             drive a flow), discover (conservation), rates, strategies, simulate, rediscover
  sdlab/     SD Lab's discovery research: ~70 strategies (needs the sd extra)
  web/       app, core, core_explore, machines, dynamics, static/
tests/
  unit/  bus/  metrics/  acceptance/
```
