# Orchestra Specification

Orchestra observes a system and the **machines** working in it, and keeps a **system dynamics
model** of it. A machine is anything outside Orchestra that does actual work: a program, an AI
agent (a universal machine), a person. Machines talk over Orchestra's **event bus**.
**Instruments** (scripts, scraped URLs, other stores) measure the running system into its
**metrics store**, apart from the machines. From those measurements Orchestra builds and fits
one model of the whole system: stocks, flows, and the feedback loops between them. System
dynamics has no machines: how a machine's work relates to the model's flows is not known, and
Orchestra infers it, as hypotheses with their evidence.

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
   stocks and flows relate, and how the machines' work may relate to them.
2. **Machines are outside Orchestra.** Orchestra can't guarantee what a machine does; it knows a
   machine exists because it shows up on the bus. A machine may influence no flow, one or several,
   and several machines may contribute to one flow; which, is inferred, never declared.
3. **There is one system and one model.** Development and domain sit side by side. Large models
   are sliced for viewing with metadata, filters and graph algorithms, never split.
4. **Flows are observed, not proclaimed.** Equations are fitted or discovered from the measured
   history, and every equation records its origin. A machine's association with a flow is a
   hypothesis with its evidence.
5. **Stocks are discovered, not configured; measurements are not machines.** Metrics are
   objective measurements of the running system, kept apart from the machines whose work we hope
   influences them, so they can test what we believe. Instruments expose plain series; the model
   generator relates them. Who wrote a series never makes a machine, and never associates one
   with a flow.
6. **The core stays up.** The bus, the metrics store and the host are probed on their own, so the
   Core page works when the model or every machine is broken.

---

## 2. Machines and events

A **machine** does actual work, and is identified by the CloudEvents `source` it publishes under.
Several instances of one machine publish as `<machine>/<instance>` (`baker/1`, `baker/2`: one
machine, two instances). Orchestra knows a machine exists because it shows up on the bus (or, on
another system's bus, as the producer or consumer of counted traffic). A machine does not
produce metrics: what measures the system is an **instrument** (§4, §5.2), and a series
labelled with a name never makes that name a machine. A plugin may list machines it provides
(`Plugin.machines`) as placeholders, shown until they are first seen; they never override what is
observed and say nothing about flows. Orchestra's own machine is the **bootstrap host**,
`orchestra-host` (section 5).

**How a machine is engaged** is one of three modes, a property of how it is run, not of what it
is: **continuous** (long-running instances that take work as it comes), **scheduled** (run by
the clock) or **ad hoc** (a fresh instance per piece of work). An instance announces its mode,
what it listens for, what kind of thing it is (`data.kind`: program, agent, person or service),
which package it belongs to (`data.package`), the name to show it by (`data.name`) and its group
(`data.group`, or else `data.team`) when it starts (`orchestra.machine.started`, `data.mode`,
`data.listens_for`), and may say where its log is (`data.log`, a file path). The announcement is a
plain event: a machine sends it over HTTP like any other (§3.1), from its own `source`. A group is a label:
the Machines page shows it on each card and draws a group's machines near each other on the map,
but every machine stays on the one page and the one map (AGENTS.md rule 4). These
announcements are Orchestra's own event type, so Orchestra reads their `data`. The web server
shows an announced log only when its real path is a regular file inside the project's repository
or state directory (`web/machine_logs.py`), because anything that can publish could name any
file. The host starts and keeps running the commands a project or a plugin declares (§5.1), but
knows them only as processes: a process becomes a machine by what it publishes. The instruments
a project declares (§5.2) are not machines, and nothing is announced for them; announcements the
host made for them before 2026-10-27 (`data.collector`) are ignored by the Machines page. Running machines on
a clock is not built (`docs/roadmap/decisions.md`, D7).

**Predictions.** A machine about to change the system may say first what the change will do,
`orchestra.prediction.made` (§4.3, "Predictions"). It is the other Orchestra type a machine
publishes from its own `source`, and Orchestra reads its `data`, which Orchestra defines. No other
machine's `data` is read (AGENTS.md rule 3).

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
| `data` | The payload. It belongs to the machines that use it; Orchestra never reads it, except in its own types (`orchestra.*`), whose `data` Orchestra defines |

An event brought in from another system (a sync from its own log) keeps the `time` it happened
there and an `id` stable across re-imports (`envelope(time=, id=)`), so a sync can tell what the
bus already holds. Events written before the envelope (flat records with `ts`) stay readable; `event_time` and
`event_source` read either shape.

**Counted traffic.** A machine on another system's bus (a broker's producers and consumers, a
Pub/Sub topic's publishers and subscribers) is known by counts, not events: a series a source
reads there that a series definition marks as **traffic** (§4.4), what one machine produced into
or consumed from a **channel** per interval, or the channel's backlog. The machine it is
attributed to is a machine like any other (`<prefix>.<name>`), known by observation: a source
counted its traffic; a count no machine is attributed to is **unattributed**, and shown so.
Counted traffic is never turned into events: no envelope is made from a count, so the bus's volume
is unchanged and replay never lies (`docs/proposals/event-sources.md` §1).

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

A machine reaches the bus in one of two ways: through Orchestra's Python helper
(`orchestra.events.Events`), or over HTTP through the events endpoint (§3.1), which needs nothing
of Orchestra's. No one ever needs to import Orchestra's library (`docs/roadmap/decisions.md`
D16). Writing to a backend directly is not supported: the stream's offsets and the envelope are
Orchestra's to keep.

### 3.1 The events endpoint

`orchestra/endpoint/`. The host that launches (§5.1) serves a small HTTP interface to the bus, so
a machine in any language publishes and reads events with an HTTP client (`curl`, the standard
library of any language).

**Where it lives.** In the host, not the web server: machines are launched by `orchestra run`,
and `orchestra web` may not be running, so a machine can publish whenever the host is up. Only
the host that launches serves it (one per project); it starts before the launched processes and
stops after them, so a machine can publish until it is stopped. It listens on `[events] listen`,
`127.0.0.1:0` unless given (port 0: one the system picks); `"off"` serves none. Its address is in
the runtime record (`events_endpoint`: `url`, `pid`, `since`) and is handed to every launched
process in `ORCHESTRA_EVENTS_ENDPOINT`, with the token in `ORCHESTRA_EVENTS_TOKEN` (§5.1). A
machine the host did not launch runs `orchestra events endpoint` (or `eval "$(orchestra events
endpoint --env)"`), which prints both from the record and the state directory; a project that
wants a fixed address sets `listen = "127.0.0.1:<port>"`. If it cannot bind, the host says so in
its log and runs on without it (the core stays up).

**Publishing.** `POST /events` with one JSON object: `type` and `source` (required), `data` (any
JSON), `subject`, `time` (RFC 3339 with a timezone; normalised to UTC milliseconds), `id`,
`correlationid`, `causationid`. A structured-mode CloudEvent is the same object with `specversion`
`"1.0"` and `datacontenttype` `"application/json"`. The endpoint checks the fields and writes the
event through `orchestra.events.Events.publish`, which makes the envelope (AGENTS.md rules 3 and
5): it never reads `data`, and never touches a backend. It refuses, with a reason: an unknown
field; a missing or malformed `type` or `source` (`<machine>` or `<machine>/<instance>`); a type
starting `orchestra.` other than a machine's own announcements, `orchestra.machine.started` and
`orchestra.machine.subscribed`, and its predictions, `orchestra.prediction.made` (403); the source `orchestra-host` (403); text fields over their
limits (type and source 256 characters, subject and the extensions 1024, id 256); a body over
1 MB (413). The answer is `201 {"ok": true, "id", "duplicate": false, "event"}`. **Idempotency:**
no backend refuses a repeated id, so the endpoint keeps the ids of the bus's last 10,000 events
when it starts and of everything posted to it since; a post whose `id` is among them is answered
`200 {"ok": true, "id", "duplicate": true}` and not written again. A machine that retries with
the same `id` after a lost answer therefore writes once. A bus that fails answers 503.

**Reading.** `GET /events?after=<offset>&types=<a,b>&wait=<s>&limit=<n>` answers
`{"ok": true, "events": [...], "next": <offset>}`: the events after `after` (default 0; `end` for
the current end), at most `limit` (default 1000, at most 10,000), only of the listed types if
`types` is given, and the offset to read from next, which moves past what was read even when no
event matched. With `wait` (seconds, at most 30) it holds the request until a matching event
arrives or the time is up: a long poll. Offsets are the bus's own (§3). On the file bus a line
that cannot be read is skipped, so a page cut at `limit` there may repeat an event; a reader
de-duplicates by `id`.

**Security.** It binds to 127.0.0.1 unless told otherwise, and every request but `GET /health`
carries `Authorization: Bearer <token>`. The token is the project's: made the first time it is
needed, kept in `<state>/events.token` readable by its owner only, and the same across the host's
restarts, so a machine the host did not launch keeps working. Another local user's process cannot
read the token, so can neither publish nor read. Anyone who can read the state directory can
already write the file bus or the runtime record; the token adds no power beyond the Python
helper's.

**The model and experiments over HTTP** (`endpoint/api.py`). The same server, behind the same
token, serves the model and experiments (§4.5) to a machine in any language: `GET /language`,
`/model?version=&raw=` (equations in the language), `/model/versions`, `/eras` (each era's
versions and the last boundary's comparison), `/observability`, `/series?ids=&start=&end=&span_s=
&points=&limit=&after=` (each series summarised, its points on request, at most 5,000 a series
and 20,000 an answer, paged by `after`), `/predictions[/<id>]`, `/experiments?owner=&status=`,
`/experiments/<id>[/diff|/runs[/<run>]|/prediction]`; and `POST /equations/check`,
`/experiments` (create), `/experiments/<id>/edits`, `/runs` (forward, replay, inverse), `/commit`
and `/discard`, each body naming the machine's `source`. They answer what the Python API
(`sd.experiments.api.Experiments`) answers: `{"ok": true, ...}`, or `{"ok": false, "error"}` with
400, 403 (not the owner), 404, 409 (not a draft) or 422 (an edit or equation refused, with the
edit's `index`). Other methods are refused (405).

**How this fits rule 9.** Publishing is a machine's normal job, not a human's control of the
system: the endpoint is the bus, reached over HTTP, exactly as the Python helper is the bus reached
from Python. The web UI and the CLI gain no write: `orchestra events endpoint` only prints where
the endpoint is. A person who posts by hand is, to Orchestra, a machine named by the `source` they
give (kind `person`, if they announce it), as with the helper.

---

## 4. Metrics, instruments and the model

### 4.1 The metrics store

Measured series (`orchestra/metrics/`): name plus labels, like Prometheus, each carrying a
`project` label. A JSONL file by default, or VictoriaMetrics (`[metrics] url =
"http://host:port"`, or `ORCHESTRA_METRICS_URL`). The interface: `write`, `raw`, `range`,
`latest`, `series`, `dump`, `delete`. A range carries the last value forward at each step.

The metrics are objective measurements of the running system, not of the machines, and the
store is filled by **instruments** directly: a script the host runs (`[[collect]]`) or a URL it
reads (`[[scrape]]`), each printing the Prometheus text format, declared by the project or a
plugin (§5.2). An instrument measures and never acts; it is not a machine. Each point it writes
is labelled `instrument=<name>` (provenance: who measured it) and `project`, which every reader
selects by; every other label the target gave is kept, a `machine` label included (the measured
system's own dimension of the data). A Python program may also write series through
`orchestra.metrics.for_repo()`, the store the project's `orchestra.toml` configures; the label it
gives them says who wrote them, nothing more. Who wrote a series never makes a machine, and never
associates one with a flow (AGENTS.md rule 7). Orchestra's own count of the bus,
`orchestra_events_total` (§4.2), is the one series derived from the event log, and is secondary.
Names say what is measured (`bakery_shelf_loaves`, `orchestra_events_total`); whether a series is
a stock or a flow is the model's business. The `orchestra_` prefix is Orchestra's own: discovery
leaves those series out, and says so of one a program wrote. How to write an instrument is in
`docs/machines.md`.

Queries are PromQL: VictoriaMetrics answers them itself (scoped with `extra_label=project=<key>`);
the file store uses `orchestra/metrics/promql.py`, a tested subset.

### 4.2 Instruments, and the count of the bus

Orchestra's own collector (`orchestra/collectors.py`) counts every event on the bus by type and
source: `orchestra_events_total{type, source}`, the one series derived from the event log.
Discovery reads it to associate machines with flows (§4.3). The host runs it live (section 5); `orchestra
metrics backfill` replays the whole log. Only the last value of a series at an instant is written,
because stores disagree on the order of points that share one.

A project's own instruments, a command run on an interval (`[[collect]]`) or a URL read on one
(`[[scrape]]`), and a plugin's (`Plugin.collectors`), are in §5.2; another store read at each
discovery (`[[sources]]`) is in §4.4. The web UI lists them on the Instruments page
(`web/instruments.py`): what kind each is, its target, how often it is read, its last write, its
failures and last error, and its log.

### 4.3 The model

`orchestra/sd/`: stocks (each bound to a series), flows (each bound to a counter), equations
(each with its **origin**: `fitted`, `discovered`, `declared`, or `prior` for one carried from the
previous era's model, and its quality), the machines associated with flows as hypotheses, and eras.
There is **one model** per project; every change is saved as a new version
(`<state>/model/vNNNN.json`), the highest is current, and past versions stay readable. Each version
is the model of one era (below).

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
the SD Lab strategy is then given only the stocks counters do not balance exactly (a balance with
a residual, or no counters at all: the levels whose net flow conservation fitted, below), and
does not run where counters balance every stock exactly, since nothing is left to explain there.
It works on a grid no finer than the stocks it is given are read at (§4.3 step 1), once per group
of stocks joined by measured flows (a flow between groups is dropped), a group of fitted net flows
offered only the inputs those flows read, and in a process of its own that is stopped at the
deadline (`sd/bounded.py`; past it the model keeps conservation's fits and says so). It reads their
levels (on the time every series was written),
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
1. every series is sampled onto a grid of steps, read at its own resolution, and marked with when
   it was live (`sd/series.py`, `sd/resolution.py`, `sd/live.py`). A series' **resolution** is the
   usual gap between its real points: a count or a state (a counter, or a level of whole values)
   is read with its last value held, every write a real point, and one written only when it
   changes is as fine as its events; a smooth measurement (any value not whole) is read linearly
   between its real points, a repeat of the value it had being the same observation polled again
   (a feed that changes every half hour, polled every minute, has a resolution of half an hour).
   The choice is made per series and recorded (`discovery.resolution`, and `resolution_s` and
   `read` on every `SeriesRef`); a source's reporting interval is a floor. A level slower than the
   grid is balanced on the stretches between its writes, each compared with what the counters
   counted between those two instants, not on single steps (`units`, `Block`); Liveness is the machine's, not the series': a machine is
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
   evidence and the discovery notes). Each flow is fitted on its own window: when its counter
   and its stocks were live, cut further only by the stocks live for 95% of that time, which
   alone may drive it. A series that started late, or a machine that was down, cuts its own
   flows' windows, never the rest of the model's. A level live for less than half of the
   window's data (from the first time any series was live in the window, while anything was
   written) is too new to be a stock and stays an input, with the reason, until it covers
   enough: an instrument started ten minutes ago would otherwise be balanced on whatever counters
   moved in those ten minutes. A series whose machine has been silent at the end of the window
   for longer than a restart takes (five minutes of the time anything at all was written: a
   computer asleep writes nothing, and its machines' silence then is not theirs) is gone, or
   replaced, and is left out; one silent for less may be restarting, and keeps its stocks.
   Orchestra's own series but its event counters are left out too
   (`orchestra_core_*`, `orchestra_host_up`: plumbing, not a measure of the system). Counters
   that move together in all but 3% of steps are one when one is Orchestra's count of the
   other's events, or both are one machine's: the machine's own, then the shorter name, is kept;
   two machines' counts of the same events both stay (each machine's stocks take their own) and
   become one afterwards where they join two stocks (step 2). Counters that differ in a label whose
   values tell measured levels apart (pods started in us-east, and pods started or stopped in
   us-west) are never one, however often their events coincide (rolling deploys that reach every
   region in the same minutes), and never join one passage (step 3). Counters that differ only by
   instance (an ``instance`` label, or ``source`` ``baker/3``) are summed into one per machine,
   and a flow from such a sum is measured by every instance's series;
2. a level is a **stock** when counters, added or subtracted, balance its changes
   (`Δlevel ≈ Σ inflows − Σ outflows`, R² ≥ 0.9). A level that only takes two values is
   usually a flag (busy or not) and is a stock only when its balance is exact in 97% of steps (a
   shelf that holds nothing or one item). A level that changed in fewer than 5 steps is no
   stock, and a counter that counted fewer than 5 events carries no balance (on three steps a
   level and a counter coincide by chance as readily as a stock and its flow): such a counter
   may only complete a balance, and only to exact. The bar is on the balance's evidence, not on
   each counter: rarer counters alone carry a balance only when together they make it exact in
   every step and counted at least 5 events between them (a state work is sent back to: three
   rejections from review, one from the merge and four returns to work). The
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
   searched only when the machine's own do not balance the level. Before both, a channel's
   backlog (counted traffic, §4.4) is balanced by its own traffic: what was produced into the
   channel, less what its own consumer took from it; kept only within the tolerance, a prior the
   data must bear out (decision D4), since another consumer that keeps up counts a stand-in for the
   channel's inflow a moment late. A backlog its consumer keeps near empty barely moves, so its own
   changes are a scrape's timing jitter: it is kept when that declared traffic accounts for what
   went in (its error against the inflow's variance, R² ≥ 0.9, recorded beside the R² on the level
   itself), and it is never a flag. Then, with every balance
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
   counters), are one stock measured twice, unless each is balanced exactly by counters none of
   which counts the other's events (two services' pods in one region, alike through the region's
   outage, are two stocks): the machine whose counters make the balance keeps it, the other is recorded as its
   twin (never two backlogs a source declared: two queues one consumer acknowledges at once change
   alike and are still two). A level that only fills is a stock when its balance is exact, whatever feeds it (a
   terminal state, where other stocks' outflows end); one the system's flows explain only
   roughly is a tally of activity unless counters no ordinary stock uses balance it;
3. a counter that leaves one stock and enters another is a **flow** between them; otherwise it
   comes from or goes to outside. A counter that drains no stock and that several stocks each take
   as an inflow, explaining at least a quarter of each one's changes, is a **copy**: every event
   fills each of them (a topic's published count fills every subscription's backlog, a fanout
   exchange each bound queue), one flow from outside per stock (`<flow>><stock>`, with `copy_of`
   and `copies` in their evidence), one count and one fitted rate (`sd/ends.py`). A claim below the
   quarter is a contested end, recorded as before. A state each item leaves within a step (an order picked up and
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
   flow gets. A driver slower than the grid is known once per interval of its resolution, so the
   flow's events within one such interval are one observation of it, and the rule counts those
   intervals instead of events: a slow series never explains a fast flow at the fine grid. A linear form on a stock other than the flow's source is an **influence**,
   the link that closes feedback loops. A stock that only fills is offered to no flow (it stands
   in for time), nor is a stock whose balance counts the flow's own events (the same events, or
   at least half of them either way; `sd/drivers.py`): it is one off just before each of those
   events by construction (the free takers just before an order is placed), which beats any
   real driver on likelihood; the flow's evidence records such stocks as `not_drivers`. A stock the
   flow fills (its destination, or a backlog a copy of it fills) may drive it only the other way (the
   fuller, the slower: a capacity), since it is higher after a burst of the flow's own events; and
   a level read a minute after each event that explains the flow better than the level at the time
   follows what drives the flow rather than driving it. Both forms stay in the evidence as
   rejected, with why. Forms
   are scored with the exact point-process likelihood (each event against the levels just
   before it), because counts per step favour spurious forms when a flow drains the level it
   depends on;
5. machines are **associated** with each flow only as hypotheses with their evidence
   (`sd/attribute.py`, `flow.evidence["machines"]`): a machine whose own events of one type
   (`orchestra_events_total`, its instances summed) match the flow counter's increments step by
   step, at the same step or one either way, equal in at least 90% of the steps either moved, or
   correlated at least 0.9 with totals within a factor of two, each with its confidence; and a
   counter that is itself a machine's event count is that machine's. Every machine that matches
   is a hypothesis, so several may be for one flow, and a machine may be for none. Orchestra's
   own event types never are. Nothing declares an association (no configuration, no plugin), who
   wrote a series (its `instrument` or `machine` label, counted traffic's included) is never read
   for it, and it changes no equation and no stock or flow. A flow with none says **no machine
   associated yet**: a question about the system, not an answer. The limits: a match is a
   correlation in time, not a cause; two machines reacting to the same events both match; and
   discovery may not tell apart two similar flows between the same stocks, so a hypothesis may
   belong to a flow's twin. Who wrote a series is still read as provenance: a writer's series
   share when it was alive (step 1), and a level's own writer's counters are searched first (step
   2).

Last, a level no counters balance may still be a **stock by its fitted net flow**
(`sd/netflow.py`): something accumulates in it (a temperature, a river, a tide, a load, a backlog
nobody counts), and its change per unit of time is fitted by least squares among a constant
drift, `c + b × level` (relaxing toward a goal, or growing on itself), `c + a × X`, and
`c + a × X + b × level`, for X any stock or measured level, on stretches no finer than any series
the form reads. A form needs ten changes of the level per parameter, an AIC gain over the constant
of 2 plus `2 ln m` for the `m` forms tried, counted on the stretches that are independent evidence
(residuals that run in long swings count once per swing), the same gain without its one largest
change, a term in the level past the 1% Dickey–Fuller value while keeping at least half of itself
from one stretch to the next, and, fitted on either half of the window, a better prediction of the
other half than each simpler form it contains. A driver must change both ways in ten stretches (a
clock that only rises stands in for time). A level whose net flow nothing explains better than a
constant stays an input, and so does one that is another series measured again (its changes move
with that series', or its values and changes follow it, up to two stretches apart), each with the
reason. An accepted stock's net flow is an inflow (`c + a × X`, or its negative as an outflow) and
an outflow proportional to the stock (`−b × level`), origin `fitted`, method `least-squares`, with
no counter and no machine associated; with an SD Lab strategy its flows take their place. A hidden
stock an SD Lab strategy finds says what it is: something in the system not measured or not
understood yet.

Everything else is **left out, with the reason** (did not change, written in too few steps, no
counters balance it and no net flow explains it, not needed by any balance, the same as another
counter), recorded in the model version. Not yet: stocks no series measures,
delays, non-linear forms. The bakery (`~/orchestra-bakery`, its own repository) is a toy
system it is tested on.

Discovery reads every series through one catalogue (§4.4): the own store's as they are, and each
other store's for exactly its window and step. A series' declared kind (a remote counter, a
level a definition named) overrides the name rule (`sd.series.Declared`), and a counter read from
another store was counting before the window began, so its first sample is a baseline, not
events. When a source is missing the discovery is cached for the page with the reason, and never
saved as a version (§4.4).

**Eras** (`sd/eras.py`, `sd/prior.py`, `sd/compare.py`; goal G11). After a machine changes how
the system works (a prompt or role edited, the configuration changed, a deploy) it is a different
system, so a new **era** begins, and the era is the window the model is discovered in:

- **What begins one.** Orchestra knows no domain, so it is told, by the envelope alone (never
  `data`): `system.changed`, the generic mark any machine publishes when it changed the system
  (`source`: the machine; `subject`: what it changed, optionally), always does; `[discovery]
  eras_from` names more, as filters `type[:source=glob,subject=glob]` (default
  `["config.changed"]`, what the Supervisor publishes when it changes the configuration).
  Orchestra's own events (`orchestra.*`) never do. The host records each such event once as an
  era `e1`, `e2`, … (`model/eras.json`: start, label `type from source`, the cause event's id,
  type, source and subject) and announces it, `orchestra.era.started` (subject the era's id,
  `causationid` the cause's id). Before the first era there is none.
- **Discovery within the era.** The window is `[discovery] window`, but never reaching back
  past the current era's start: what came before is not evidence for the new system. An era
  younger than two steps is not discovered; its model is its prior.
- **The prior** (decision D4). The previous era's model is the new era's prior: its last
  discovery is saved as a version when the era begins (so it stays readable), and what the era
  discovers is merged with it (`sd/prior.py`). A flow in both, in the same form, keeps the era's
  form and its numbers pulled towards the prior's by a prior worth 20 events against the events
  the era counted (`Equation.prior`: the prior's era, weight, numbers, and the era's own); with
  fewer than 20 events in another form, the prior's equation stands (origin `prior`). A stock or
  flow only the prior has is carried (origin `prior`, `evidence.prior`) while the era is younger
  than `[discovery] prior_for` (default: the window), then dropped. So early in an era the model
  is mostly its prior, and the era's own evidence takes over as it accumulates.
- **The comparison** at the boundary (`sd/compare.py`, `discovery.era_comparison`): stocks,
  flows and loops that appeared or disappeared (and the ones still carried), each flow's form if
  it changed, and for each of a flow's numbers, before → after (the era's own number) with
  their standard errors (`sd/trust.py`'s spread times the number) and `z`, the difference over its
  standard error: changed when `|z| ≥ 2`. This is what the intended-effect test (G13) judges.
- **One model.** The structure is never split by era: each era has its versions of the one model
  (`Model.era`), with every era recorded in it (`Model.eras`). A version is saved when the
  structure changed or an era began.

**The model's own events** (`sd/announce.py`, `sd/diverge.py`; goal G12). After each of its
discoveries the host publishes, as `orchestra-host` (its own events, so it writes their `data`):

- `orchestra.model.changed`: stocks, flows or loops added or removed (`data.added`,
  `data.removed`: `{stocks, flows, loops}` as ids; `era`, `held`, `first_seen`). Discovery churns,
  so a structure is announced only after it has held for `[discovery] announce_hold` discoveries
  in a row (default 3), against the structure last announced (the host's first discovery sets it,
  unannounced), and at least `[discovery] announce_gap` (default 30 min) after the last
  announcement; a flip that comes back within the hold is never announced. Versions are saved as
  before, unaffected.
- `orchestra.model.diverged` and `orchestra.model.returned`: at each discovery the model
  predicts every stock from its level now (`sd/experiments/forward.py`, no change: the central
  run and its 10–90% band), its band widened by the Poisson spread of its flows' events since. A stock's
  **gap** is its level less the central prediction, in half-widths of that band, judged against
  the oldest prediction that still reaches now (so a wrong rate shows as a growing gap). A stock
  is out past 2 half-widths and **diverged** once it has been out at every check for `[discovery]
  diverge_after` (default 15 min); it **returns** inside 1. `data.stocks` names each with its gap,
  level, band and since; `data.diverged` every stock diverged now; `era` and `era_start`, so a
  listener tells a divergence after an announced change from an unexplained one (the
  unexplained-change test, docs/rationale/lifted-models.md §3.3). Needs `orchestra[sd]`.

**Predictions: the intended-effect test** (`sd/predictions.py`, `sd/verdict.py`, `sd/judge.py`;
goal G13; docs/rationale/lifted-models.md §3.1 and §3.2). Before a machine changes the system it
says what the change will do, as edits of the model, and once the change has run for the horizon
Orchestra judges it against what the era's discovery found.

- **Recording.** The machine publishes `orchestra.prediction.made` from its own `source`
  (directly over the events endpoint, with `sd.predictions.Predictions`, or by committing an
  experiment, §4.5, which publish it for it). `data`: `change`, the id of the event that will
  make the change (chosen beforehand: the change is then published with that `id`); `expect`, a
  list of edits, each `{"flow", "factor"}` (its rate × r; `"param"` for one number; 0 is the
  flow disappearing), `{"flow", "unchanged": true}`, `{"flow", "equation", "params"}` (the flow's
  whole rate becomes this equation, in the equation language of §4.5), `{"flow"|"stock"|"loop",
  "appears"|"disappears": true}`, `{"from", "to", "appears": true}` (a new flow between two
  stocks, `null` for outside; with `equation` and `params`, the rate it will have), `{"stock",
  "below"|"above"}` (its mean level over the horizon's second half); `[]` is the **null test**,
  the change should change nothing; `horizon_s` (or `horizon`, a duration); optionally
  `trajectories`, the predictor's own forward run of the stocks (`{"t": [seconds after the
  change], "stocks": {id: {central, lo, hi}}}`). An equation is checked for its syntax when the
  prediction is made, and against the model when it is judged. The prediction is an
  Orchestra type rather than a file Orchestra is handed so that one path serves every machine and
  the event log itself shows it came before the change. The host records each once, by its id,
  in `model/predictions.json` as it follows the bus (`waiting`; `invalid` with the reason when
  its `data` does not parse, so the machine can be told). A prediction changes no machine: it is
  a statement about the model (AGENTS.md rule 9).
- **Matching.** A prediction belongs to the era whose `cause` is its `change`; it waits until
  that change begins an era. One made after its change is judged, and marked `late`.
- **When.** After a discovery of the era made at least `horizon_s` after it began. While an
  expected edit rests on the prior (the era has no evidence of its own on that flow yet) it waits
  on, to twice the horizon, then is `undecided`. When another era begins before the horizon it is
  judged at once **`interrupted`**, from the era's last saved model and the levels until the next
  change, and `partial` says what the rules said from that.
- **Each expected edit** against the boundary comparison: a factor r is **met** when a number of
  the flow moved (`|z| ≥ 2`, the comparison's threshold) and every number is within 2 standard
  errors of r times its value before; **absent** when none moved; **different** when it moved
  elsewhere, or the flow appeared or disappeared instead. Discovery's choice of form churns on
  noise, so a flow whose **form changed** is judged by its law: the previous era's equation, run
  over the era's measured levels, predicts the era's count of its events, and a form change whose
  old law still predicts the count (Poisson, widened by the fit's dispersion and the old numbers'
  error, within 2 standard errors) is no change. An expected **equation** is judged by its law
  the same way: the predicted equation, run over the era's measured levels and inputs, must
  predict the era's count (met); when it does not but the previous era's law still does, it is
  absent; when neither does, different. Appearing and disappearing parts are read from the
  comparison (a flow still carried, not found in the era since it began, counts as gone).
- **Unpredicted changes**: every other flow that changed, changed form (and whose old law fails)
  or appeared or disappeared, and every stock or loop that appeared or disappeared, except the
  stocks at the ends of a flow predicted to appear or disappear and the loops through them.
- **The stocks** are run from their levels at the change over the horizon: with the
  prediction's own trajectories when given, else the previous era's model run forward with the
  predicted edits applied as a draft (`sd/experiments/expect.py`, `forward.py`; needs
  `orchestra[sd]`). A stock moved as simulated when its mean level
  over the horizon's second half is within 2 standard errors of the run, the error being the run's
  band and the spread of single readings about it (readings minutes apart are far from
  independent, and an error of their mean is too narrow: on synthetic queues it failed a third of
  the stocks that had moved as simulated). Only a clear departure counts.
- **The verdict**: **side effect** when an expected edit is different or anything changed that
  was not predicted (they are listed, with their numbers); else **no effect** when an expected edit
  is absent; else **passed** when every level expectation holds and every stock moved as
  simulated, and **model wrong elsewhere** when one did not. The null test passes when nothing
  changed.
- **The false-change rate.** Each verdict carries the threshold (`z` 2) and the rate a normal
  error crosses it (`nominal`, 4.55% a number), and, where the previous era is long enough (ten
  discovery steps a half, within the window), the share of flows flagged when its two halves are
  discovered apart and compared (`measured`): nothing was announced between them, so every flag
  there is false; `expected` is that share times the flows compared here.
- **Published**: `orchestra.prediction.judged`, by the host, `subject` and `causationid` the
  prediction's id, `correlationid` the change's. `data`: `verdict`, `prediction`, `change`, `era`,
  `era_start`, `horizon_s`, `until`, `judged_at`, `late`, `z`, `expectations` (each with its
  `status` and numbers), `unpredicted`, `stocks` (`from`: prediction or simulated, the rows with
  level, central, standard error, `z` and `out`; `reason` when not simulated), `compared`,
  `false_change`, and when interrupted `interrupted_by` and `partial`. Numbers, ids and codes,
  no prose.

**Observability** (`sd/observability.py`, `sd/linearise.py`; `GET /observability` on the events
endpoint, `/api/dynamics/observability`) says which stocks what is measured determines. The model is
linearised at its recent operating point (the mean levels and inputs of the last hour; a hidden
stock at 0): `dx/dt ≈ S·R·x`, with `S` the flows' ends and `R` each rate's slopes on the levels,
taken from the rates as the simulator computes them. The sensors are the stocks bound to a series
and the flows with a counter (a counter measures a rate, which its equation ties to the levels it
reads). A stock is **determined** when its direction has no part in the unobservable subspace (the
largest subspace inside the sensors' null space that the dynamics map into itself). For each
determined stock the report gives the shortest way its level reaches a sensor and the sensors it
relies on; for a measured stock, whether the counters and equations would determine it without its
own series; for an undetermined one, each new series or counter that would determine it, and
whether only the fitted numbers make it undetermined (the same test with random slopes on the same
structure). It flags unmeasured flows' numbers that show in the determined levels only in
combination, and numbers that multiply an undetermined stock. Controllability with respect to the
flows machines are hypothesised to affect is reported as structural and weak: it ignores floors and
caps. The answers are local: flows with effects, expressions, or a rate floored at 0 at that point
are named, and so is every flow taken as an outside input because it has no equation to read. A
stock determined through a counter is determined only as far as that flow's equation, a hypothesis,
is right.

What a change would do is asked of an **experiment** (§4.5), which replaced the scale-and-add
"what if" (and `orchestra sd whatif`, `POST /api/dynamics/whatif`) on 2026-10-27.

### 4.4 Other stores (sources)

`orchestra/sources/`. A project may read series that live in other time-series stores without
copying them (`docs/proposals/time-series-sources.md`, slice 1). A **source** is the own store or
a server answering the Prometheus HTTP query API (Prometheus, VictoriaMetrics, Thanos, Mimir,
Chronosphere):

```toml
[[sources]]
name = "work"
url = "https://tenant.example/data/metrics"
auth = { bearer_env = "WORK_TOKEN" }   # or bearer_file, header, basic, client_cert/client_key/ca_file
prefix = "work"                         # series work:<name>, machines work.<id>
machine = "service"                     # the canonical label that names machines
match = ['{__name__=~"http_.*"}']       # what to infer from (default everything, capped)
max_series = 200                        # per source; at most max_per_family (12) per family
[sources.labels]                        # canonical = spellings; the first a metric has wins
service = ["service", "app", "k8s_app"]
[sources.transform]
queries = "scripts/queries.py"          # optional: rewrites the candidates (JSON in, JSON out)
```

- **Credentials** come from an environment variable or a file outside the repository, read when
  a request is made. A literal secret in `orchestra.toml`, `user:pass@` in a URL, a secret file
  inside the repository, or an auth kind not built yet (command, OAuth2, SigV4) **refuses the
  source**, with the reason (`sources/spec.py`, `sources/auth.py`). Pages, logs and errors show
  the kind, where the credential comes from and whether it is there; never its value.
- **Series are inferred from the schema** every `infer_every` (an hour), cached in
  `<state>/sources/<name>.json` (`sources/infer.py`): families (names differing by a statistic
  suffix, or a `stat`/`statistic`/`quantile` label; a histogram's `_count`; a recording rule
  `…:sum`/`:avg` as a view of its base by that function), label aliases, each label's role
  (identity: one of the source's `identity` names, default pod/instance/container, or churning,
  or over 50 values; constant; grouping) and the reporting interval (`sources/schema.py`).
- **Views** (`sources/views.py`): of a per-pod statistic, the max of max, min of min, average of
  average (flagged unweighted) and max of p95/p99 (flagged an upper bound), never a sum; of a
  plain gauge the max and average (latencies, ratios) or the sum; of a counter, increments from
  raw samples, reset-safe, by grouping; of a recording rule, its function by grouping. **A count
  switches the type:** the pods reporting (`count by (G) (last_over_time(F[R]))`, R one and a half
  reporting intervals) is a level, with its turnover (the pods that started and stopped reporting,
  from the raw samples) as two counters that balance it exactly, so pods per service is a stock;
  and how many values of each grouping label report. One family counts each thing.
- **The query script** (any executable, from the repository root, with a timeout) gets the
  candidates as JSON on standard input and prints rewrites: new queries, drops with a reason,
  definitions of its own, pins (`sources/transform.py`). A failure fails the round.
- **Rank and cap** (`sources/rank.py`): each candidate is read over the window at its resolution;
  one that returns nothing or does not move is left out; the rest are scored (moves, stable,
  small, coarse, view) and taken round-robin across families up to the cap. A pin bypasses the
  ranking, not the cap. What is left out is kept with its score and why. A hand-written
  `[[series]]` (source, name, query, kind level|counter|rate, unit) is always read.
- **Reading** (`sources/catalogue.py`, `sources/fetch.py`): every definition is read for exactly
  discovery's window, on its grid but never finer than the series' resolution; counters and
  turnover from raw samples at their real times, rates integrated. Results take canonical labels,
  `machine = <prefix>.<value>` from the machine label (a remote `machine` or `source` label is
  prefixed too), and the name `<prefix>:<name>`; one that collides with an own series is refused.
  Each source is read on its own, with a timeout per request and a deadline; a source that fails
  is **missing**, and the stretches of the window in which it returned nothing are its gaps. Every
  range is re-runnable: a run after the machine slept reads its whole window like any other.
- **Provenance:** each `SeriesRef` in a model carries its `source` (`own` or a source's name),
  final `query`, `kind`, `origin` (inferred from which family and view, rewritten by
  `queries.py@<hash>`, or declared), `resolution_s` and `unit`; a stock bound to a count takes its
  unit; each equation lists the sources of the series it was fitted on (`sd/provenance.py`). The
  Dynamics page shows each source's state and why a discovery was not saved, and a stock's drawer
  its source, query and origin; the web server reads remote stocks' levels and history through
  the catalogue.

**Counted traffic** (`sources/traffic.py`; `docs/proposals/event-sources.md` §1–3). A series
definition may say what it counts on another system's bus:

```toml
[[series]]
source = "rabbit"
name = "rabbitmq_published_total"
select = '{__name__="rabbitmq_detailed_channel_messages_published_total"}'   # raw samples, reset-safe
by = ["vhost", "exchange"]                                                  # summed by these labels
kind = "counter"
traffic = { direction = "out", channel = "{exchange}" }   # out | in (counters), backlog (a level)
```

`channel` and `machine` are templates over each result series' labels (after the aliases), or
plain names; the channel is `<prefix>:<channel>` and the machine `<prefix>.<machine>`, which
becomes the series' `machine` label: the producer or consumer is a machine on the Machines page,
known by its counts. Discovery does not read that label to associate it with a flow (§4.3 step 5).
A count with no machine is unattributed, unless the source's `[sources.producers]` (channel =
machine) declares who produces into that channel: a broker's counts rarely name publishers. This
is metadata on the definition, never a label convention (a store's own `channel` label means
nothing). The reading records each series' traffic in its provenance (`SeriesRef.traffic`), and
the web server reads every traffic series over the last hour each minute
(`Catalogue.counted`, `web/traffic.py`) for the Machines page. A `select` (with `by`) declares a
counter read from raw samples, like an inferred counter's increments, so a publisher's channel
that closes and reopens is no reset.

A source may name a **preset** (`preset = "<file>"`, relative to the repository or absolute,
`sources/preset.py`): a TOML file of `[[series]]` definitions for one exporter (they read this
source) and `[source]` defaults the source table's own keys override. Presets ship with whatever
reads that store (the RabbitMQ preset is in `~/orchestra-bridges`), never with Orchestra.
`infer = false` reads only the declared series, never the schema. `settle` ends every read from a
source that long before now, so its series end together (VictoriaMetrics hides the newest 30 s from
range queries but not from raw reads, `-search.latencyOffset`). A counter read from raw samples
whose series began inside the window (a publisher's new channel: its first sample well after the
start and no larger than twice its largest increment) counts its first value; any other first
sample is a baseline.

`orchestra sources check` probes each source's endpoints and credentials; `orchestra sources
infer` runs an inference round and prints the families, what was kept and what was left out;
`orchestra sources preview QUERY [--source NAME]` reads a query's fan-out with sparklines. Not yet
built (the proposal's slices 2 and 3): the cache of settled chunks, the data script, fingerprints
and `sd verify`, the Sources page, command/OAuth2/SigV4 auth, SQL sources.

### 4.5 Experiments

`orchestra/sd/experiments/`; goals G5, G13 and G16. An **experiment** is a staged, editable copy
of the model that any machine (an AI agent or any other program) changes and runs, to see what a
change would do before making it, to test whether an equation explains what happened, or to ask
what would have had to be different for an outcome to have been. Machines use it through the
Python API (`sd.experiments.api.Experiments`) or the HTTP API beside the events endpoint (§3.1);
the web UI only reads it (§10; AGENTS.md rule 9).

**The equation language** (`language.py`). One written form for a flow's rate, which a machine
reads and writes alike: an expression in Python's syntax, per the model's time unit, over stock
ids (their levels), measured inputs (their values), the equation's named **parameters** (given
beside it: `{"equation": "k * min(waiting, 2 * bakers)", "params": {"k": 0.4}}`) and numbers; `+
- * / **`, unary minus, one comparison (1 or 0); and the functions `min`, `max`, `abs`, `exp`,
`log` (natural), `sqrt`, `clip`, `if_then_else`, `zidz`, `lookup(x, [[x0, y0], …])`, `smooth(x,
tau)`, `delay(x, tau)`, `observed()` (the flow's own measured rate) and SD Lab's (Vensim's)
`ceil`, `floor`, `integer`, `power`, `modulo`, `quantum`, `ln`, `log10`, the trigonometric
functions, `xidz`, `and_`, `or_`, `not_`. A name that is not a plain identifier, or is both a
stock and an input, is written `stock("id")` or `input("name")`. The text is parsed with Python's
`ast` into numpy closures; nothing is passed to `eval`, every name is checked against the model,
and the parse reports what the equation reads. A rate below 0 is 0; one that is not a number is
0 and counted. **Units are not checked.**

Every equation the model holds renders in the language and round-trips (`forms.py`): `c`,
`k * X`, `c + k * X` for the classic forms; SD Lab's rates with their numbers named as
`Equation.params` names them (`c + k1 * A + k2 * B`, `(goal - X) / time`, `(<expr>) /
per_step_of_time_unit`, effects as `clip` and `lookup` factors, a sum of parts as `max(0, …) +
…`); `observed()` for a flow with no equation. An equation written in the language is kept as
written (form `expr`, `spec: {"language": "orchestra", "text"}`), except the classic forms
written exactly so, which stay those forms.

**The engine** (`engine.py`) steps a model written in the language as SD Lab's simulator steps
the Dynamics page's projection (Euler steps; a stock's outflows share what it holds; levels
floored at 0; inputs held between points), for many columns at once (a band's members, an
inverse solver's candidates), with parameters set per column.

**The record** (`store.py`), `<state>/experiments/<id>.json`: `owner` (the machine's source;
only it edits, commits or discards; anyone reads and runs), `title`, `purpose`, `status`
(`draft`, `committed`, `discarded`), `base` (the model it was copied from, whole, with its label:
by default the current era's latest model, the host's latest discovery; or a saved version),
`draft`, `scenario`, `log` (every batch of edits, accepted or refused, with who and when), `runs`
(each run in full in `<id>.runs/<run>.json`), `prediction` once committed, and `origin` for a
draft the inverse solver made.

**Edits** (`edits.py`), applied as a batch, all or none: `add_flow`, `replace_flow` (a whole
equation, and optionally new ends), `remove_flow`, `set_params`, `add_stock` (a hidden stock with
an initial level), `remove_stock`, `set_level` (where a forward run starts a stock), `set_input`
(a forward run's scenario for an input: hold, value, scale, step, ramp or a series) and
`load_model` (the whole draft, in a simple form or as Orchestra writes models). Each is checked:
ids, ends that are stocks, equations that parse and read only what the draft has, parameters all
used; the whole draft again at the end. A refused batch changes nothing and says which edit and
why. **Origins** (AGENTS.md rule 6): an equation an edit writes is `declared`, with method
`experiment <id> by <source>`; one a `load_model` writes as the base has it keeps the base's own.
`views.diff` says what a draft changed of its base.

**Three runs**, each recorded with the experiment:

- **forward** (`forward.py`): the base and the draft from the measured levels now, `horizon_s`
  ahead; each stock's and flow's trajectory as the central run and a band (10th–90th percentile
  of runs with every flow's rate × `exp(z · rel)`, `rel` its recorded relative error,
  `sd/trust.py`: `sqrt(dispersion / events)` for a Poisson fit, the slope's error at its R² for a
  net flow, `1/sqrt(events)` but at least 0.1 for an SD Lab rate, 0.5 for a declared equation,
  so every equation an experiment wrote; z shared by id between the two runs); the **limits**
  (a stock reaching 0, or leaving bounds the caller gives, in the central run and in what share of
  the runs, and whether the experiment brings it); **not trusted here**, with the reason (a flow
  declared, carried from the prior, a net flow, replayed, fitted on few events, over a short time
  or at low R²; a stock touched by one, hidden, without a level now, whose base run since the era
  began misses its measured level by more than its own spread, whose run leaves the observed
  range, or one of whose changed flows runs outside what was seen);
- **replay** (`replay.py`): both over a past window (`start`/`end`, `span_s`, or an `era`),
  driven by its measured inputs and `observed()` flows, from the levels measured at its start,
  against what was measured: per stock the run's error over the level's spread, per counted flow
  the equation's one-step fit on the measured levels (Poisson deviance, and the share of a
  constant rate's deviance it removes), and the experiment against the base (better, same,
  worse). This is the backtest of an equation and the counterfactual replay;
- **inverse** (`inverse.py`): targets over a past window (a stock's mean `scale`d from the base
  replay's, its mean `level`, its highest `below` or lowest `above` a bound, a flow's `scale` or
  `total`; several at once) and holds (a flow's equation kept, a series' history kept); greedy
  forward selection finds the smallest set of changes (factors on numbers or whole rates, and
  optionally a new inflow or outflow of a target stock) under which a replay meets the targets
  within 5% and keeps the holds, the count of changes as the penalty and the base as the prior
  (D4), all candidates of a step run as columns of one batch, under a deadline (`deadline_s`, at
  most 300). It answers with a new draft (the caller's), whether the targets were reached (or the
  best approach), the **side effects** (every stock and flow not named that moved more than 5%,
  with how much), **alternatives** of the same size that also reach them, and a **uniqueness
  check**: the base and the solved model each fabricate the window's data (Poisson counts,
  `fabricate.py`), conservation discovers a model from each, and each flow's law is tested on the
  counterfactual data; the flows whose laws changed should be the solved ones. `ambiguous` when an
  alternative reaches the targets or the check disagrees. Its limits are said in the module: one
  change ahead (a pair that only works together is missed), factors between 1/10 and 10, a
  deterministic replay (the check is what says whether the data could show the solution), no new
  hidden stock as a candidate, and anything not targeted or held may move.

**Commit** (`api.commit`): a committed experiment becomes a G13 prediction (§4.3) of the change
its owner will make, published from its owner's source with the experiment's id as `subject`: a
flow whose classic numbers alone changed expects each `{"flow", "param", "factor"}`, any other
changed flow its whole `{"flow", "equation", "params"}`, a removed flow `disappears`, an added one
`{"from", "to", "appears", "equation", "params"}`; hidden stocks are not stated (no series could
show them). Its forward run over the horizon is the prediction's `trajectories`. The machine then
publishes its change carrying the returned `change` id, and the host judges it as any prediction.

Nothing here changes a machine, the model or a metric: an experiment is a statement about the
model (AGENTS.md rule 9 keeps humans to reading it).

---

## 5. The bootstrap host

`orchestra run` starts Orchestra's own machine (`orchestra/host.py`). In an empty Orchestra it:
- registers itself in `<state>/runtime.json` (`hosts`, by pid) and logs to `<state>/logs/orchestra-host.log`;
- publishes `orchestra.host.started` and `orchestra.host.stopped`;
- writes `orchestra_host_up{machine="orchestra-host"}` every interval;
- runs the event collector: replays the bus once at start, then follows it, recording the eras
  the bus begins and announcing each (`orchestra.era.started`, §4.3);
- rediscovers the model every `[discovery] every`, within the current era, and then publishes
  what is due about it (`orchestra.model.changed`, `.diverged`, `.returned`, §4.3);
- records the predictions machines make of their changes as it follows the bus, and after each
  discovery judges those due and publishes the verdicts (`orchestra.prediction.judged`, §4.3);
- keeps running the processes the project and the plugins declare (§5.1);
- serves the events endpoint (§3.1) while it launches;
- runs the instruments the project and the plugins declare (§5.2).

### 5.1 The launcher

`orchestra/launcher.py`. A project declares the commands it wants kept running in `orchestra.toml`:

```toml
[[machines]]
name = "telemetry"                                  # letters, digits, . _ -
command = "python machines/telemetry.py"            # split like a shell would, not run by one
restart = "always"                                  # always (default) | on-failure | never
stop_grace = 10                                     # seconds from SIGTERM to SIGKILL (default 10)
```

and a plugin in `Plugin.processes` (§10.1). The host starts each in the repository root, in a
process group of its own, with `ORCHESTRA_REPO` (the root) and `ORCHESTRA_MACHINE_LOG` (its log,
`<state>/logs/machines/<name>.log`, which receives its output) set, and, while the events
endpoint serves (§3.1), `ORCHESTRA_EVENTS_ENDPOINT` (its URL) and `ORCHESTRA_EVENTS_TOKEN`. A plugin's processes are named
`<plugin>.<name>` (in the runtime record, on the Core page and in their logs' names), so a
project's `[[machines]]` entry never takes a plugin process's place; a project entry named
`<plugin>.<something>` for a plugin with processes is refused, with a line in the host's log. One that exits is started again
after a pause that doubles with each exit within a minute of starting (1 s up to 60 s); after five
failures (non-zero exits) in a row, each within a minute of starting, it is given up on, which the
host's log, the process's log and the bus (`orchestra.process.gave_up`) say. It is tried again when
its entry changes or the host restarts. The host also publishes `orchestra.process.started` and
`orchestra.process.exited`. It re-reads the configuration (`orchestra.toml` with the private
overlay merged, §8) whenever either file changes, appears or goes (checked every second): a new entry starts, a removed one stops, a changed one restarts. The plugins are then
asked again for their processes (the config read first, since a plugin reads its own sections), so
adding or removing a plugin's section starts or stops what it declares. A file that does not parse,
or a plugin that fails to load, leaves what runs alone. Stopping the host (SIGTERM, SIGHUP or Ctrl-C) stops every process
group it started: SIGTERM, then SIGKILL after the process's stop grace (`stop_grace` in
`[[machines]]`, `stop_grace_s` in a `Process`; 10 s unless given, like systemd's
`TimeoutStopSec`). A host started again after being killed first stops what the previous one left
running, waits for each to exit up to its grace, kills what remains, and only then starts anything. Only one host launches for a project. It holds `launcher` in the runtime record (its
pid and its process's create time, so a reused pid is not taken for it), taken under the record's
lock only when nobody holds it or its holder is dead, and cleared only by that holder when it
stops. A second host, started while one runs, launches nothing and writes nothing of the
launcher's; one that takes the launch from a dead holder first stops what that holder left
running. Every process is in the runtime record (`processes`), which the Core page shows while
the launching host runs.

The launcher starts commands and nothing more: what a process does and which machine it is are
learned only from what it publishes (AGENTS.md rules 1 and 2). A process's name is not a machine
id.

### 5.2 Instruments: collectors and scrapes

`orchestra/collect/`. A project declares in `orchestra.toml` commands that print measurements and
URLs that serve them, and a plugin declares its own in `Plugin.collectors` (§10.1):

```toml
[[collect]]
name = "disk"                    # the instrument's id: letters, digits, . _ -
command = "machines/disk.sh"     # split like a shell would, not run by one
every = "60s"                    # default 60 s, at least 1 s
timeout = "20s"                  # default 10 s, never more than every

[[scrape]]
name = "app"
url = "http://127.0.0.1:9100/metrics"
every = "30s"
```

Each is an **instrument**: it measures the running system and never acts on it, so it is not a
machine (AGENTS.md rule 7). Nothing is announced on the bus for it and it is not on the Machines
page; the Instruments page lists it. Its name is its own: it may share a `[[machines]]` entry's
name (a scrape of the program that entry runs) without being that machine. A plugin's is named
`<plugin>.<name>`, and a project entry of that name takes its place, with a line in the host's
log; the plugins are asked for theirs again whenever the configuration (§8) changes.

The host that launches (§5.1) runs each on its interval, each round in a thread of its own; an
instrument whose last round is still running skips its turn. A command runs in the repository root,
in a process group of its own, with `ORCHESTRA_REPO` and `ORCHESTRA_MACHINE_LOG` set and its
standard error going to its log (`<state>/logs/instruments/<name>.log`); a URL is fetched with a GET.
The text, a command's standard output or a URL's body, is read as the Prometheus text exposition
format (`collect/exposition.py`): samples with labels and optional millisecond timestamps, `# HELP`
and `# TYPE` lines. Counters, gauges and untyped series are kept as they are; of a histogram or a
summary only `_count` and `_sum` are kept, its buckets and quantiles left out; a value that is not a
number is left out; a line that cannot be read is skipped and said once in the host's log. Each
point gets `project` and `instrument = <name>` (its provenance), and the round's start time when it
has no timestamp. Every other label the text gave is kept as it was, `machine` included: the
measured system's own dimension of the data. A label of the text that Orchestra sets (`project`,
`instrument`) is kept as `exported_<name>`, as Prometheus does, never overwritten. A series named
`orchestra_*` is refused, with a line in the host's log saying to rename it.

A round that fails (a non-zero exit, the timeout, which kills the command's group, a command that
cannot start, an HTTP answer other than 200, or text over 10 MB) writes nothing, adds a line to the
host's log and the instrument's, and is counted in `orchestra_collect_failures_total{collector}`,
labelled `machine="orchestra-host"`. A round that succeeds adds a line to the instrument's log.
Each instrument's health is in the runtime record (`instruments`: its kind, target, interval,
owner and log, its last write and how many points, its failures and its last error), written when
an instrument is added, removed, fails, first writes or writes a different number of points, and
otherwise at most every 5 s. The configuration (§8) is read again on the host's tick (every second) when
either of its files changed: an instrument added starts at once, one removed stops (a round under way finishes and
its points are dropped), one changed starts over, and an entry that cannot be used is left out
with a line in the host's log. Stopping the host kills a command under way and writes nothing
more.

Before 2026-10-27 the host announced each collector as a machine (`orchestra.machine.started`
with `data.collector`) and labelled its points `machine=<name>`. Those announcements are ignored
now, and the store is not rewritten: a collected series' history splits at the upgrade into the
old `machine=<name>` series and the new `instrument=<name>` one. Discovery reads both labels as
provenance, so stock and flow ids do not change.

Only the Prometheus text format is read. There is no push endpoint for measurements (D16; events have one, §3.1). A remote Prometheus server is
read where its data lives, not copied (§4.4).

---

## 6. Machines that are AI agents

Orchestra runs no AI. An AI agent is a machine like any other, a universal one, known by its
`source` and its events; what starts it and talks to its model belongs to the package that runs it, which
keeps its own harness (`~/orchestra-agents/SPEC.md`).

---

## 7. Storage

```
~/.orchestrator/                 (ORCHESTRATOR_HOME overrides)
  projects.json                  repository root → project key
  <key>/
    project.json
    orchestra.local.toml         the private configuration overlay, if the owner writes one (§8)
    runtime.json                 the hosts', the launcher's, the events endpoint's, the web server's, the launched processes' and the instruments' records
    events.token                 the events endpoint's token (§3.1), readable by its owner only
    web.token                    the web UI's token (§10.2), readable by its owner only
    events.jsonl                 the event log, when [events] url = "file"
    metrics.jsonl                the metrics, when [metrics] url = "file"
    model/vNNNN.json             the model's versions
    model/eras.json, announce.json, predictions.json   the eras recorded, what the host last announced, the predictions and their verdicts (§4.3)
    experiments/<id>.json        each experiment: its base, draft, scenario, edit log, runs and prediction (§4.5)
    experiments/<id>.runs/<run>.json   each run of it in full
    sources/<name>.json          each source's latest inference: its definitions, what was left out, its families (§4.4)
    logs/orchestra-host.log
    logs/machines/<name>.log     each launched process's output (§5.1)
    logs/instruments/<name>.log  each instrument's standard error and rounds (§5.2)
```

The project key is the repository directory's name plus a hash of its path. Nothing is written
inside the repository except `orchestra.toml`.

---

## 8. Configuration

`orchestra.toml` at the repository root (`orchestra init` writes a starter):

```toml
[events]
url = "file"            # or redis://, amqp://, kafka://
listen = "127.0.0.1:0"  # the events endpoint (§3.1): host:port, port 0 picked by the system; "off"
[metrics]
url = "file"            # or http://host:8428 (VictoriaMetrics)
[web]
auth = "on"             # the web UI asks for the project's token (§10.2); "off" only on a loopback bind
[discovery]             # strategy, window, step, every, [discovery.options]
strategy = "kalman_lna"
eras_from = ["config.changed", "role.changed:source=supervisor"]   # begin an era, besides system.changed (§4.3)
prior_for = "60m"       # how long a new era carries what it has not found of its prior (default: window)
announce_hold = 3       # discoveries a structure change holds before orchestra.model.changed
announce_gap = "30m"    # the least time between two orchestra.model.changed
diverge_after = "15m"   # how long a stock is out of its band before orchestra.model.diverged
[[machines]]            # the commands `orchestra run` keeps running (§5.1)
name = "telemetry"
command = "python machines/telemetry.py"
[[collect]]             # a command whose output is measurements, run on an interval (§5.2)
name = "disk"
command = "machines/disk.sh"
[[scrape]]              # a URL that serves measurements, read on an interval (§5.2)
name = "app"
url = "http://127.0.0.1:9100/metrics"
[[sources]]             # another store, read where its data lives (§4.4)
name = "work"
url = "https://tenant.example/data/metrics"
auth = { bearer_env = "WORK_TOKEN" }
[[series]]              # a hand-written definition from a source (§4.4)
source = "work"
name = "checkout_errors"
query = 'sum(rate(http_errors_total{svc="checkout"}[5m]))'
kind = "rate"
```

Unknown sections are ignored, so files written for older versions still load, and a package of
machines may keep its own settings here (other packages' sections).

### 8.1 The private overlay

A project's configuration is `orchestra.toml` with a **private overlay** merged over it, when
there is one (`orchestra/overlay.py`, `Project.read_config`). It holds what must not land in a
repository others share (docs/roadmap/decisions.md D10): the owner's channels, templates,
identities, instruments. It is read from the file `ORCHESTRA_CONFIG_OVERLAY` names (relative to
the repository root unless absolute; a missing file is then an error), else from
`orchestra.local.toml` in the state directory (§7) if it is there. A file inside the repository
is never read as an overlay. With no overlay, the configuration is `orchestra.toml` alone.

- Tables merge key by key; the overlay's value wins.
- Arrays of tables, at any depth (`[[machines]]`, `[[collect]]`, `[[scrape]]`, `[[sources]]`,
  `[[series]]`, a plugin's), merge by `name`: an overlay entry named as one of the repository's
  replaces it whole; any other is appended.
- An overlay entry `{ name = "x", enabled = false }` removes the repository's `x`.
- Anything else is replaced.

`[overlay]` in the overlay is not merged: `secret` lists keys (`desk.me`, `machines[pager]`,
`machines[pager].command`; a key covers what is under it) whose values are never shown.
`/api/project` lists both files and each key of the merged configuration with `from` (`repo` or
`overlay`) and its value unless secret, and the entries the overlay removed. Credentials never
go in either file; they come from the environment or files, as §4.4 says.

Everything that reads the configuration reads the merged one: `load_project`, the host, the
launcher and the instruments re-read it when either file changes, appears or goes
(`Project.config_stamp`), and plugins get it as `project.config.raw` without knowing there is an
overlay.

### 8.2 Changing the configuration

Plugins never open, parse or edit `orchestra.toml` or the overlay themselves. They read
`project.config` (the merged result; `raw` is all of it), follow changes with
`project.config_stamp()` and `project.reload_config()`, and change a setting through
`project.config_edit` (`orchestra/config_edit.py`; Python objects, no web API):

- `set(key, value, target=...)`, `set_many({key: value, ...}, target=...)` and
  `unset(key, target=...)`, with `key` dotted (`tasks.workers`);
- `add_entry(array, entry, target=...)`: adds the entry named `entry["name"]` to an array of
  tables (`machines`, `gate.unit`), or sets the given fields on it;
- `remove_entry(array, name, target=...)`.

`target` is `"repo"` (`orchestra.toml`, which the team shares) or `"overlay"` (the private file,
created `0600` on its first change). In the overlay an entry merges whole, so `add_entry` there
starts from the repository's entry of that name, and `remove_entry` there writes
`enabled = false` when the repository has the entry. Each change edits the target's text through
`tomlkit` (comments and layout kept), then reads the merged result as Orchestra does (its
settings, `[[machines]]`, `[[collect]]`, `[[scrape]]`) and as the caller's `check` does (a
plugin's own reader): one that makes any of them say something new is refused with what they said.
It is written whole, `project.config` is reloaded, and a `Change` is returned: the file, its text
before and after, one line of what changed (no values for the overlay), and the keys of the merged
configuration whose value changed (none, with a note, when the overlay's value still wins).
`dry_run=True` returns the change unwritten, `apply(change)` writes it unless its file changed
since, and `restore(change)` puts the file back. Orchestra commits nothing: committing a change to
`orchestra.toml` is the caller's choice, and the overlay is outside the repository.

---

## 9. CLI

| Command | What it does |
|---|---|
| `orchestra init` | Register the repository and write `orchestra.toml` |
| `orchestra run` | Run the bootstrap host, the processes the project and plugins declare, and the instruments |
| `orchestra web [--port] [--host]` | Serve the web UI, behind the web token (§10.2); print a link that logs in |
| `orchestra web token [--rotate]` | Print the web token; `--rotate` replaces it and ends every session |
| `orchestra events info\|endpoint [--env]\|copy --to URL` | The event log; where the events endpoint is, and its token (§3.1) |
| `orchestra metrics backfill\|series` | Replay the log into event counters; list series |
| `orchestra sd discover [--strategy S] [--minutes N] [--step-s S]\|show\|fit\|versions` | The model: discover it from the metrics, show, refit, list versions |
| `orchestra sd predictions [--json]` | The predictions recorded and their verdicts, by era; read only |
| `orchestra sources check\|infer\|preview QUERY` | Other stores (§4.4): probe them, infer what to read, read a query's fan-out |

`orchestra sd whatif`, `sd predict`, `sd eras` and `sd observability` were removed on 2026-10-27
(the owner does not use command lines): machines ask what a change would do, predict, and read the
eras and the observability report through the APIs (§3.1, §4.5), and the web UI shows them.

---

## 10. Web UI

Read-only for humans. Navigation: Dashboard, Machines, Instruments, Dynamics, Experiments, Core.

- **Dashboard:** panels as sections of one page on a 12-column grid (`static/dashboard.js`, with
  gridstack.js): the viewer drags a panel by its title bar and resizes it from its edges and
  corners, panels pack upward so one sits under another with no gap, and a panel can be hidden
  and brought back from Panels (in the navigation); positions and sizes are kept in the browser,
  and a narrow window has one column. A panel may give its starting size. Orchestra's own panels are **Machines** (a short list of
  what runs now: the machines that announced themselves continuous, and any other that published
  in the last two minutes; a click opens its dialog) and **Host** (a Core status strip; the
  host's CPU, GPU, memory and disk). A package adds panels of its own (`Orchestra.panels`, from its
  every-page script; §10.1).
- **Machines:** every machine seen on the bus (never one a series names, never an instrument) with its instances, how each is engaged and what kind
  it is (a machine whose instances differ says so: agent ×2, program ×1; what it listens for is the union over its
  instances, and its package, name and card are each instance's latest, so an instance that says less erases nothing
  another said), whether it is active (last
  seen, by its own events alone, within two and a half beats of its own cadence and at least two
  minutes; the cadence is the gap observed between its bursts of events, so a job that runs
  rarely is active between its runs; never by a write to a series, whatever its labels, and never
  by anything stamped in the future), the event map (by default machines only: an
  arrow where one publishes an event type the other listens for, one line with two arrowheads where
  two talk both ways, thicker with more traffic, the event types on hover; or with the event types
  as boxes; event families, the name up to its first dot, can be hidden; dotted, the hand-offs
  inferred from the envelope: one machine acted on a subject after another did, which connects
  machines that announce nothing, such as a system brought in from outside; and **counted
traffic** (§2, §4.4): each channel a box with what waits in it, each producer → channel and channel
→ consumer a double line labelled with its rate per minute, a count no machine is attributed to
coming from or going to a grey "unattributed" stub), its feedback loops, and the flows of the
latest discovery each machine is hypothesised to be associated with, with their confidence (§4.3,
`sd.attribute`; a series is never a machine's, whatever it is labelled). A machine known by counted traffic is marked counted on its card, with its rates and
backlogs per channel; its last seen is its last interval with a nonzero count (active within five
minutes, which allows for the store's scrape interval and the minute between reads). Clicking a machine
  (its card or its node) opens its dialog: instances, what it publishes and listens for, its
  hypothesised flows with their evidence, its last events (envelopes only) and the tail of its announced log,
  refreshed while open. With eras recorded (§4.3) the map and the cards are of the current era by
  default, from its events alone (an announcement before it still says what a machine is and listens
  for); a menu picks a past era, the time before any, or all time
  (`/api/machines?era=`).
- **Instruments:** every instrument (`web/instruments.py`): a script (`[[collect]]`), a URL
  (`[[scrape]]`) or a source (`[[sources]]`), the project's and the plugins', with its target, how
  often it is read, its last write and how many points, its failures and last error, and its log;
  read from the runtime record and `orchestra.toml`, never by running or querying one.
- **Dynamics:** the model as a stock-and-flow network (stocks with their level, tank fill and
  sparkline; a valve per flow with its equation and the machines associated with it, as
  hypotheses with their confidence, or "no machine associated yet"; influences as dashed +/− links),
  its feedback loops marked balancing or reinforcing, the stocks' history, and drawers with each
  stock's and flow's history (a flow's observed rate against its equation's prediction). A
  stock's drawer also runs the equations (`sd/simulate.py`, SD Lab's simulator): from the measured
  levels at the start of the era to now, and from now a horizon the viewer chooses; flows with no
  form the simulator steps are replayed from their observed rates, and named. Its flows are split
  into what fills it and what drains it (drawn below zero). It shows the host's latest discovery
  and steps through saved versions. With eras recorded, a timeline of them picks the era shown (a
  past era's last version: `/api/dynamics/model?era=`), and under it what changed at the era's
  start (before → after, appeared, disappeared, carried from the prior); each flow says how much
  of it is the prior's and how it changed. Under that, the predictions made of the change that
  began the era shown (and, with the current era, those still waiting for their change), each
  with its verdict and evidence (`/api/dynamics/predictions?era=`). It says in plain words what the window and the step are and
  what each decides, shows each series' resolution and read (held or linear) beside it in the
  stocks table and the list of what was left out, and a stock's drawer its resolution, its balance
  or, for a stock no counters balance, its fitted net flow.

The model's graph frames **the system**. There is one system: every stock and auxiliary is
inside it, and only the environment (the clouds flows come from and go to) is outside, so what
crosses the frame is what the model does not explain. Subsystems (perhaps feedback loops in boxes
of their own) are a later question. A **rediscover now** button reruns discovery in the background (an observation: it
re-reads the metrics and may save a version, as the host does every 5 minutes). With eras, the
timeline's era says which experiments were made on its model and which predicted the change that
began it (each linking to its page), and each prediction links to the experiment it came from;
`/dynamics?era=<id>` opens an era.

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
- **Experiments** (§4.5): what machines did with the model, read under `/api/experiments` (the
  list, `?owner=&status=&era=`, each with its latest run and its prediction's verdict),
  `/api/experiments/<id>` (its draft with equations in the language, scenario, edit log, runs and
  prediction), `.../diff`, `.../runs`, `.../runs/<run>` (in full), `.../runs/<run>/measured` (a
  forward run's stocks as measured, before its now and since, up to its horizon or the present)
  and `.../prediction`. The list page (`/experiments`) shows each experiment's machine (linking to
  its card), title and purpose, status, base version and era, latest run and when, and verdict,
  filtered by machine, status and era (an era's: made on its model, or predicting the change that
  began it). An experiment's page (`/experiments/<id>`) shows the prediction it became (what it
  expects, the change id, the era the change began, linked, and the verdict with its evidence:
  passed, no effect, side effect, model wrong elsewhere, interrupted), its edits as an equation
  diff against its base (flows replaced, added and removed, each equation before and after side
  by side with its numbers; stocks added and removed; input scenarios and starting levels), every
  run (forward: per stock the base and the experiment from now over the horizon with their bands,
  the hour measured before now and what was measured since, the limits hit and the not-trusted
  reasons above the charts; replay: per stock measured against both simulations and the error of
  each, per flow the one-step fit with better, same or worse; inverse: the targets, what was
  held, the changes found and the new draft's diff, the side effects by size, the alternatives,
  the uniqueness check and an unmistakable warning when `ambiguous`), and the edit log in order,
  refused batches with the edit that failed and why. Charts are `static/charts.js` with bands.
  These pages follow the browser's light or dark setting; the others are dark. The web UI changes
  no experiment (AGENTS.md rule 9): machines make and run them.
- **Core:** the host (with the processes it keeps running: state, restarts, command), the bus and
  the metrics store, each probed against its real backend within a time limit; explorers for the
  metrics (a catalogue of every series with the project's label, naming any series in the file
  store that lacks it, and a PromQL editor) and the events (types, volumes, sources); logs (the
  host's, Core's, the event stream and each launched process's). It imports only the bus, the metrics store and the runtime record.
  Its Configuration panel (`/api/project`, fetched on its own, so the rest of the page does not
  depend on it) lists the configuration's files and each key with the file it came from (§8),
  never the value of a key the overlay marks secret.

### 10.1 Plugins

A package installed beside Orchestra (a task system, for example) may add pages and API routes of
its own (`orchestra/plugins.py`). It names a function in the entry-point group
`orchestra.plugins`; the function takes the project and returns a `Plugin`: its pages (a path, a
title for the navigation, an HTML file that may use `/static/app.js` and `/static/style.css`), a
static directory (served at `/plugins/<name>/static`), a FastAPI router (at
`/api/plugins/<name>`), the processes `orchestra run` should keep running for it (`processes`:
`orchestra.launcher.Process`, §5.1: a name, a command, a restart policy and a stop grace), the
instruments it reads measurements from (`collectors`: `orchestra.collect.spec.Collector`, §5.2),
the machines it provides (`machines`: placeholders shown until first seen, which never override
what is observed and say nothing about flows), and scripts from its static directory that every page loads after its own
(for what must be visible wherever the viewer is, such as the way to reach the package's own pages).
From those scripts a package may register Dashboard panels (`Orchestra.panels`) and draw the cards
of the machines it claims (`Orchestra.machineCards`: what is inside Orchestra's machine-card
frame, a few words for the Dashboard's machine list, and the machine's dialog). Its look is in its
own stylesheets, files from its static directory that every page links in its head after
Orchestra's (`stylesheets`): Orchestra's has nothing of any package's domain. `/api/plugins` lists
the pages, which the navigation adds after Orchestra's own, and any plugin that failed to load.
A plugin that fails, one whose name an earlier plugin took, a page at a path Orchestra serves, or
a script or stylesheet missing from its static directory is left out and reported, never fatal. A plugin is
the package's, not Orchestra's: its routes are its own, and Orchestra knows nothing of what they
mean. They are behind the same login as Orchestra's (§10.2), and a plugin adds no route outside it.

### 10.2 Authentication

Anyone who reaches the web UI could otherwise use every page and every plugin's writes, and a
server on `127.0.0.1` is reached by more than its owner: a tunnel or proxy on the same computer
publishes it, other local users reach it, and any web page a browser visits can send it requests.
So every route asks for the project's **web token**: Orchestra's pages and `/api/*`, the static
files, the websocket, and every plugin's pages, static directory and router. `GET /health` alone
is open. One ASGI middleware in front of the whole app checks it (`web/auth.py`); no page and no
plugin does, so none can forget to, and the Core page stays independent of the model and the
plugins (rule 8).

- **The token** is the project's, made the first time it is needed and kept in
  `<state>/web.token`, readable by its owner only, never in the configuration. It is not the
  events endpoint's token (§3.1): a machine that may publish may not use the UI. `orchestra web`
  prints it, with a link that logs in (the token after `#`, which the browser keeps);
  `orchestra web token` prints it again, and `--rotate` replaces it, taking effect at once.
- **Browsers** log in once at `/login` and keep a session cookie, `orchestra_<key>`: the expiry
  signed with HMAC-SHA256 under a key derived from the token (so a rotation ends every session),
  HttpOnly, SameSite=Strict, 14 days, Secure when reached over HTTPS. `POST /logout` drops it.
  **Programs** send `Authorization: Bearer <token>` on every request.
- **CSRF.** A request carried by the cookie that is not GET, HEAD or OPTIONS, and every websocket,
  must come from the server's own origin: `Origin` (or `Referer`) names the `Host` that was asked,
  and `Sec-Fetch-Site` is neither `cross-site` nor `same-site`; otherwise `403`, before any handler
  runs. A bearer request needs no check, since a browser never sends that header by itself.
- **Guessing.** Five wrong tokens (login or bearer) within a minute from one peer address, and
  further tries answer `429` until the oldest is a minute old. The peer is the connection's, never
  `X-Forwarded-For` (uvicorn runs with `proxy_headers=False`); a logged-in browser is not affected.
- **Behind a tunnel** it works unchanged: the tunnel passes `Host` through, so the page's `Origin`
  matches it. Forwarded headers decide nothing, except that `X-Forwarded-Proto: https` marks the
  cookie Secure.
- **`[web] auth = "off"`** serves without a login, and only on a loopback bind (`orchestra web`
  refuses to start otherwise). It is not the default even there, for the reasons above. When off,
  a request with a forwarding header (`Forwarded`, `X-Forwarded-*`, `X-Real-IP`, `Cf-*`) or a
  `Host` that is not a loopback name is refused, as is an unsafe request from another origin, so a
  tunnel or a rebinding DNS name in front of it finds it closed.

---

## 11. Package layout

```
orchestra/
  cli.py  config.py  overlay.py  config_edit.py  toml_text.py  events.py  runtime.py  host.py  launcher.py  collectors.py  plugins.py  tokens.py
  bus/       file, redis_streams, rabbitmq_streams, kafka
  endpoint/  the events endpoint (§3.1): the token and the record, validate, server, api (the model and experiments)
  collect/   instruments, a project's and the plugins' collectors and scrapes: spec, fetch,
             exposition (the Prometheus text format), round, runner
  metrics/   file, victoria, promql
  sources/   other stores, read in place: spec, preset, auth, prometheus, own, schema, views,
             transform, rank, infer, fetch, traffic (counted traffic), catalogue, report (the CLI's text)
  sd/        model, store, fit, series and live (sampling, when a series was written), balance,
             collinear and restate (a level's balance), ends, inputs, drivers (which stocks may
             drive a flow), discover (conservation), attribute (machines associated with flows,
             as hypotheses), rates, strategies, simulate, rediscover, trust (each flow's
             spread and what is not trusted), provenance (where each series in a model came from), linearise and observability
             (which stocks what is measured determines), eras, prior and compare (eras, the
             previous era's model as a prior, the boundary before → after), loops, announce and
             diverge (the model's own events), predictions, verdict, judge and predictions_report
             (the intended-effect test: the record, its rules, when and from what, the CLI's text)
    experiments/  §4.5: language, forms, compile, engine (the equation language and its
             stepper), store, edits, views, history, scenario, forward, replay, inverse,
             fabricate, expect (to and from predictions), reads, api (the Python API)
  sdlab/     SD Lab's discovery research: ~70 strategies (needs the sd extra)
  web/       app, auth (the login, §10.2), core, core_explore, machines, instruments, traffic (counted traffic), dynamics, static/
tests/
  unit/  bus/  metrics/  sources/  acceptance/  e2e/ (slow, opt in: ORCHESTRA_E2E=1)
```
