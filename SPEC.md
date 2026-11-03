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

This version is an **empty Orchestra**: the bus, the metrics store, the model with the declared
layer beside it (what the owner expects, the intended model, §4.6), the bootstrap host and the
web UI, with no machines of its own beyond the host, and no AI: an AI agent is a machine like any
other, run by whatever runs it. The machines' work and how it is organised live in plugins, each
in its own repository, which add their pages here (§10.1). How the core was emptied is in
`docs/proposals/empty-orchestra.md`.

This document is the design of what exists. `AGENTS.md` lists the rules that must not be broken;
`docs/proposals/` holds the proposals; each says in its status line what of it is built.

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
the clock) or **ad hoc** (a fresh instance per piece of work).

**The announcement.** When an instance starts it announces itself with `orchestra.machine.started`
from its own `source`. It is a plain event: a machine sends it over HTTP like any other (§3.1). It
is Orchestra's own event type, so Orchestra reads its `data` (`web/machines.py`). This is the one
full statement of the fields Orchestra reads; every other document points here. The events
endpoint refuses an announcement whose `data` is not an object, whose `listens_for` is not a list
of event types, or whose `mode`, `kind`, `log`, `package`, `name`, `group`, `team` or `process` is not a
string (`endpoint/validate.py`); a reader takes any other shape already on the bus as empty
(`events.announcement`):

| `data` field | What it says | Kept per |
|---|---|---|
| `mode` | how it is engaged: `continuous`, `scheduled` or `ad hoc` | instance (its latest announcement) |
| `kind` | what kind of thing it is: `program`, `agent`, `person` or `service` | instance (its latest announcement) |
| `listens_for` | the event types it reads | machine (the union of its instances') |
| `log` | where its log is, a file path | instance |
| `package` | the package it belongs to, whose card draws it | instance; the machine shows the latest instance's that names one |
| `name` | the name to show it by | instance (one that drops it has none); the machine shows the latest instance's that names one |
| `group`, or else `team` | its group, a label | instance, as `name` |
| `process` | the launcher entry that started it (`ORCHESTRA_PROCESS`, §8: a `[[machines]]` entry's name, or `<plugin>.<name>`), shown as "started by the launcher as <name>"; `events.announcing` and `Events.announce` add it | instance (one that drops it has none); the machine lists its instances' (`processes`) |
| `collector` | marks an announcement the host made for an instrument before 2026-10-27: ignored | — |

A machine whose instances differ in mode or kind says so (`agent ×2, program ×1`), never just the
last one to announce. Everything else in the announcement (`about`) is passed to the package's card
unread (scalars and lists only), merged across the instances, the latest instance's over the
others. An instance that announces only what it listens for and what it is (a part of a machine
implemented elsewhere) so never erases what another instance said of the machine. A group is a
label: the Machines page shows it on each card and draws a group's machines near each other on
the map, but every machine stays on the one page and the one map (AGENTS.md rule 4). The announced
`group` and `package` each make a partition of the map's machines when two values or more are said
(`/api/machines` `subsystems`, §10, named by the field): a machine whose instances announced two
groups is in two, and so drawn outside every box. The web server
shows an announced log only when its real path is a regular file inside the project's repository
or state directory (`web/machine_logs.py`), because anything that can publish could name any
file. The host starts and keeps running the commands a project or a plugin declares (§5.1), but
knows them only as processes: a process becomes a machine by what it publishes. `process` says
which process published and nothing more: a launched process that never announces is no machine,
the name makes none, and the launcher never reads what a process announces. The instruments
a project declares (§5.2) are not machines, and nothing is announced for them; announcements the
host made for them before 2026-10-27 (`data.collector`) are ignored by the Machines page. Running machines on
a clock is not built (`docs/roadmap/decisions.md`, D7).

**The intended model.** The discovered model names no machine in a stock, flow or equation; it
lists the machines that hold a flow's hypotheses (§4.3). The declared layer stored beside it
(§4.6) names machines, never in a stock, flow or equation. A declared machine is shown as
declared, and as heard only once its `source` is on the bus; its declaration never overrides what
is observed and never makes a machine exist. The owner's page requests are published as
`orchestra.intent.requested` from `owner`, the third Orchestra type a machine (here, the person)
publishes.

**Predictions.** A machine about to change the system may say first what the change will do,
`orchestra.prediction.made` (§4.3, "Predictions"). It is one of the Orchestra types machines
publish (rule 3's list), from its own `source`, and Orchestra reads its `data`, which Orchestra defines. No other
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
bus already holds. Events written before the envelope (flat records with `ts`) stay readable; `event_time`
reads either shape.

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
listens for in `orchestra.machine.started`. The Machines page draws
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
starting `orchestra.` other than a machine's own announcement, `orchestra.machine.started`,
and its predictions, `orchestra.prediction.made` (403); the source `orchestra-host` (403); text fields over their
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

**The model over HTTP** (`endpoint/api.py`). The same server, behind the same token, serves the
model (§4.5) to a machine in any language: `GET /language`,
`/model?version=&raw=` (equations in the language), `/model/versions`, `/eras` (each era's
versions and the last boundary's comparison), `/observability`, `/series?ids=&start=&end=&span_s=
&points=&limit=&after=` (each series summarised, its points on request, at most 5,000 a series
and 20,000 an answer, paged by `after`), `/predictions[/<id>]`, `/intended?version=` and `/intended/design`
(the intended model's declared layer and its summary, §4.6); and `POST /equations/check` and
`POST /intended` (one call to the
declared layer: `{source, author, turn, message, quote, reason, request?, ops}`, applied whole or
refused with the op's `index`, §4.6). They answer what the Python API
(`sd.reads.ModelReads`, `project.intended`) answers: `{"ok": true, ...}`, or `{"ok": false, "error"}` with
400, 404 or 422 (an op refused, with its `index`). Other methods are refused (405). The
`/experiments` routes were removed on 2026-11-01 (§4.5).

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
`latest`, `series`, `dump`, `recent`, `delete`. A range carries the last value forward at each step.
`recent(prefix, matchers, since, keep)` answers every series whose name starts with `prefix`,
whose labels match `matchers` (`=`, and `=~` for a regular expression over the whole value), with a
point at or after `since`, and its last `keep` points; no backend reads anything older than `since`
(the export's `start` on VictoriaMetrics), and `tests/metrics` holds every backend to it.

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
Discovery reads it to associate machines with flows (§4.3). The host runs it live (section 5), replaying the
whole log into it at every start. Only the last value of a series at an instant is written,
because stores disagree on the order of points that share one.

A project's own instruments, a command run on an interval (`[[collect]]`) or a URL read on one
(`[[scrape]]`), and a plugin's (`Plugin.collectors`), are in §5.2; another store read at each
discovery (`[[sources]]`) is in §4.4. The web UI lists them on the Instruments page
(`web/instruments.py`): what kind each is, its target, how often it is read, its last write, its
failures and last error (or, without one, what its last round printed last on standard error:
"last run said: …"), its log, and whether it is `simulated` ("simulated: placeholder numbers")
or a `draft` (with `expires`: "draft until … · left out of discovery"; §5.2).

An instrument may say how it made the series it prints (**views**, `collect/views.py`, §5.2), as
a source's definitions do: a `count` of things in a place (naming the place label), the `moves`
between places (naming the labels of the place entered and left) or the `starts` and `stops` of
one place, an `aggregate` over places that overlap, an `age`. The catalogue gives each matching
point of that instrument the record `{source: "own", instrument, view, ...}` in the reading's
provenance, and discovery reads it as it reads a source's (§4.3). A view describes how a series
was made, never a machine or a flow (rules 6 and 7): it changes no equation.

A view also names the parts its series become, once, on the server (`sd/titles.py`), and every
page shows that title (the Dynamics, Machines and Instruments pages, the diff between versions):
where a count's other labels spell its place label's value part by part, they are the place in
words, in the order they spell it (`pile="write.held"`, `step="write"`, `place="held"`). A title
says the place and the state only (the owner, 2026-11-02: "I don't know what 'deliveries'
means"): a stock is what is said of what sits there, and where ("held at write"; "at write" when
nothing is said of it); an `age` series of the same labels is the "age at" it ("age at write
(held)"); a move between places is named by the things it leaves and enters ("write → ci"; inside
one, "write: waiting → held"), "(sent back)" when it goes to a thing fewer moves from outside than
the one it leaves ("ci → write (sent back)"), a value in angle brackets as outside ("outside →
write"; one word for one idea, never "the start"), any other value no place spells in its words;
a hidden state between such moves by the first and last things its items pass ("between write and
sail_check"; never its places' states joined), with the places it spans listed in its evidence
(`spans`) and its drawer, or by what is said of what sits there when they enter and leave one
("waiting at sail"). What narrows a title is said beside it as **tags**, never in it: a list of
short strings, on the part's evidence (`tags`) and as `tags` on every stock and flow of
`/api/dynamics/model` (`[]` when none), on `/api/machines`' `model_parts`, on an instrument's
series (`/api/instruments/…/series`, beside its `title`) and on a removed part of the diff. Each
tag is either `label=value`, a label of the series its place does not spell (`workflow=delivery_sail`;
a move's labels other than its places'), in the series' label order, or, bare, the noun its count
view declares (`noun = "deliveries"`, a plural of one to four plain words: `deliveries`), after the
labels; the noun a series' name ends in (`workflow_pile_items`: items) is its unit, said by neither.
Two parts whose titles read alike are told apart by the tags they do not share ("held at write"
twice, `workflow=delivery_sail` and `workflow=hotfix`): chips on the pages, and in running text
after the title ("held at write · workflow=hotfix"); two moves that read alike with the same tags
are said by their places' own parts ("ci (waiting) → write (waiting)"). A part's identifier is its
key (§4.6) and its id, shown in its drawer and on hover, never as its name. No label's name is
known to the core (rule 1), and label values keep their spelling (`sail_check`).
Such a part's evidence says `named: "places"`. A series its own name and labels say in words is
named so on the server too, with `named: "words"`: Orchestra's count of the bus by its type and
source ("item.closed events (supervisor)"), and a series whose one label is a word of its name
followed by a plural noun by that noun on the label's value (`git_branch_commits{branch="main"}`:
"commits on main").

### 4.3 The model

`orchestra/sd/`: stocks (each bound to a series), flows (each bound to a counter), equations
(each with its **origin**: `fitted`, `discovered`, `declared`, or `prior` for one carried from the
previous era's model, and its quality), the machines associated with flows as hypotheses, and eras.
There is **one model** per project; every change is saved as a new version
(`<state>/model/vNNNN.json`), the highest is current, and past versions stay readable. Each version
is the model of one era (below).

**Fitting** is part of discovery (`sd/discover.py`, `fit_flow`): each counted flow's events in
the window are fitted by Poisson maximum likelihood to a constant rate or a rate that reads the
source stock's level (or another stock or input), the form with the better likelihood is kept,
with its standard error and dispersion, and its equation records `origin: fitted`,
`method: poisson-mle`.

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
Where its flows describe the whole change rather than the residual, a stock whose counters
balance it with an R² of 0.98 or more keeps its counters' fits and gets no unmeasured flow; and a
stock that only fills (an accumulator: every term of its balance adds, and its level never fell
in the window, as a repository's commits with no force-push) gets no flow out of it.
Its richer forms (gap, linear in several stocks or inputs, expressions, effects) are kept in
each equation's `spec`, and its hidden stocks are drawn dashed. The host gives a strategy a
deadline below `[discovery] every`, and one discovery runs at a time per project across
processes (the host skips a scheduled run while the CLI or the web page is discovering). Every
run's window starts and ends on multiples of the step (`sd/rediscover.py`), so runs a few
seconds apart sample the same grid and agree.

Conservation (`sd/discover.py`):
1. every series is sampled onto a grid of steps, read at its own resolution, and marked with when
   it was live (`sd/series.py`, `sd/resolution.py`, `sd/live.py`). A series' **resolution** is the
   usual gap between the points where it changed: a count or a state written only when it changes
   is as fine as its events, and a measurement polled every minute that its feed changes every half
   hour has a resolution of half an hour. Every series is read with its last value held: a repeat of
   the value it had is an observation that nothing changed, never a gap to draw a line across (until
   2026-10-28 a smooth measurement was read linearly between its changes, and a gauge polled every
   30 s that changed twice in an hour became two ramps any steadily rising counter matched: the
   metrics lab's review r1, F9). The resolution is recorded (`discovery.resolution`, and
   `resolution_s` and `read` on every `SeriesRef`); a source's reporting interval is a floor. A
   level written less often than the grid is balanced on the stretches between its writes, each
   compared with what the counters counted between those two instants, not on single steps
   (`units`, `Block`), and never on the stretches between its changes, which are no observations.
   A counter on a schedule that moves only every few writes, steadily (a store reporting once a
   minute, read every 30 s), is as fine as its moves (`counted_every`); a level whose balance needs
   such a counter is balanced on the stretches between that counter's writes (`sd/coarse.py`),
   every series read at the same two instants from its own points, and a balance judged on a slow
   counter's writes whose misses are timing (they cancel from one
   stretch to the next: lag-1 autocorrelation −0.3 or less) fits at R² 0.5 rather than 0.9 (its
   held-out bar 0.25 when both halves chose its counters), its other evidence unchanged. A series on a schedule whose last sample
   is a little before the window's end (a late store, `settle`) has data only until it
   (`arrived_until`): a balance it is in is judged only on the steps before, where all its series
   have data, never on steps that read it as unchanged (`sd/live.py` `arrived`). Liveness is the machine's, not the series': a machine is
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
   (`orchestra_core_*`, `orchestra_host_up`: plumbing, not a measure of the system), and so are
   the event counts of Orchestra's own events: a type in its namespace (`orchestra.*`: a machine
   started or quiet, the model changed or stalled), whoever published it, or anything the host
   (`orchestra-host`) published. They say what Orchestra did, not the system's work, and the host
   is never a machine (AGENTS.md rule 2), so none is a flow. Told by the namespace and the
   source, never by a list of names (`sd/series.py`, `orchestra_events`): the source
   `orchestra-host` is reserved for the host, and nothing else may publish under it. Counters
   that move together in all but 3% of steps are one when one is Orchestra's count of the
   other's events, or both are one machine's: the machine's own, then the shorter name, is kept;
   two machines' counts of the same events both stay (each machine's stocks take their own) and
   become one flow afterwards where they join two stocks, each stock still balanced by its own
   (step 2). Counters that differ in a label whose
   values tell measured levels apart (pods started in us-east, and pods started or stopped in
   us-west) are never one, however often their events coincide (rolling deploys that reach every
   region in the same minutes), and never join one passage (step 3). Counters that differ only by
   instance (an ``instance`` label, or ``source`` ``baker/3``) are summed into one per machine,
   and a flow from such a sum is measured by every instance's series;
2. a level is a **stock** when counters, added or subtracted, balance its changes
   (`Δlevel ≈ Σ inflows − Σ outflows`, R² ≥ 0.9) on evidence that holds (`sd/identify.py`,
   `sd/accept.py`; below). Every counter in a balance is in the level's own unit (`sd/units.py`:
   a `unit` label, the unit the source declared, or the name's by Prometheus' convention, `_count`
   counting observations): coefficients are ±1, so CPU seconds never balance a queue of messages,
   nor bytes a count, nor KiB bytes. A level that only takes two values is
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
   counter that completes it (a refund among a hundred orders) is kept; every start's result is
   completed before the best is chosen, so an exact balance that needs a rare counter beats a
   stand-in's near miss (another instrument's count of both ways out of a state, one a step late). A small set of chosen
   counters that cancels to nothing is dropped, and one that equals an unchosen counter is
   replaced by it (`sd/collinear.py`). A balance with more counters than the level's changes
   can test sheds those that add nothing they can test: the changes over the whole window test
   fewer counters than half the steps the level changed in, and always two (an inflow and an
   outflow). Beyond that, squared error no longer tells a counter from a coincidence, and a
   counter is taken out (the least counted first, until the limit) when no step pins it on its
   own (one the balance fits, where it moved and no other counter of the balance moved the level
   the same way) and without it as many steps are exact. A counter whose removal leaves fewer
   steps exact stays, so an exact balance is never reduced (a quiet shelf baked, sold, discarded
   and eaten from at once). A balance assembled from the level's own machine's counters and
   another's on their residual is held to the limit as a whole, shedding only the other's
   (`sd/balance.py`, `supported`). The level's own machine's counters are searched first
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
   machine holds before another machine's copy, then the one stamped first), unless a measured
   level in their unit is the one less the other (either way round, within half a unit) in every
   step where it and both are live, and moved by a whole unit in a step where they differ,
   however seldom it moves (a shelf left within seconds), and both rose and fell by at least one
   of its unit in those steps (a buffer fills and drains; a tally that never falls is a count, never a
   buffer: the one test, `between.fills_and_drains`, the state of a passage below is put to):
   that level is the buffer between them, and they are its inflow and outflow. Right after the join, and again once every balance is final, a stock whose own
   writer's count was joined to another writer's takes its own back, so it is identified on
   its own counters: no stock is balanced by another instrument's count of its events while its
   own exists. The two
   stay one flow and its co-flow, with one rate, each measured by its own writer's series. Once
   every balance is final, Orchestra's event counter in a balance, where another writer's counter
   that a balance holds counted the same moments, is filed
   under that counter: the balance keeps it (its stamps may be the ones that fit a level read
   just after), and it measures that flow's co-flow, never a flow of its own (rule 7: the bus
   count is secondary). The same moments are both: the counter, or a counter it stands for,
   names the event's machine as a label value (`by="merge_gate"` for `source="merge_gate"`), and
   the two count alike (at least 5, totals that agree, the same steps or up to a step apart
   either way: the bus hears a landing before the ticket instrument counts it). Timing alone is
   no evidence: two machines on one period count in the same steps every time. A bus count with
   no such counter stays a flow. Last, two or three
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
   outage, are two stocks), and only when the levels themselves match (their changes spread
   within 20% of each other, and their difference is in most steps within half the level's spread,
   a tenth of its size or a step's change) or they are one series read twice (one name, a source's
   prefix aside, and the same labels): two warehouses drained in proportion to one order stream
   change in step and are two stocks (`levels_match`): the machine whose counters make the balance keeps it, the other is recorded as its
   twin (never two backlogs a source declared: two queues one consumer acknowledges at once change
   alike and are still two). A level that counts a stock's servers busy is that stock's
   capacity, not a second stock (`sd/capacity.py`: the head chef busy, inspections started less
   inspections done, inside the orders inspecting; two chefs, 0 to 2). Judged on the series' own
   writes, never the grid, within a second plus the longer of the two write intervals: at 80% of
   its writes it reads what its counters imply (as a passage's level must), at all but 3% it holds
   no more than the stock, 80% of its outflows' events are some of the stock's outflows' (totals
   within 3%), the stock's own writer counts what fills it, and that is no counter another
   stock's balance takes nor (unless it is the stock's own inflow) one counting the same events.
   It is judged once the stocks are final (after hops and passages), left out with why, and shown
   in the stock's drawer (`capacity_of`: capacity k, the share of time busy, the mean occupancy,
   its counters). A level fed by another stock's flow (a shelf the inspections passed fill, the
   state after a stock) stays a stock, and so does another machine's count of its own work (an
   agent's turns beside the tickets in review: which machine serves a flow is a hypothesis, rule
   6), and a server who reports later than a write interval after the stock's writer. A level that only fills is a stock when its balance is exact, whatever feeds it (a
   terminal state, where other stocks' outflows end); one the system's flows explain only
   roughly is a tally of activity unless counters no ordinary stock uses balance it.

   R² on a level's changes does not identify a balance: chosen from thousands of signed pairs, a
   balance picks up counters that explain a per cent or two of any level by chance (a GC count,
   CPU seconds, the scrapes of `/metrics`), and a proxy that moves with the true flow step by step
   (requests for the messages they produce) fits as well while drifting from it (the metrics lab's
   review r1, F1, F2 and F7). So each balance is **identified** (`sd/identify.py`) and kept only on
   the evidence (`sd/accept.py`), measured on the lab's ten windows and their nulls:
   - **units**: judged on at least 12 units (steps, or stretches between a slow level's writes),
     and 6 per counter; an exact balance on at least 5, and 2 per counter (a queue a few minutes
     into an era);
   - **the halves' vote**: the balance is searched again on each half of the window; a counter of it
     that the search on a half the level and the counter moved in did not choose again (nor a
     counter of the same events, or one whose changes correlate 0.9 with it there) is dropped, and
     the rest must still fit at R² 0.9;
   - **exact** (97% of the units anything moved in explained to within half an event, on at least 5
     of them) is its own proof: a coincidence is not exact for an hour. Short of exact, the balance
     each half chose must predict the other half at R² 0.5 or better, its running residual must
     spread no more than half the level's own spread (the level reproduced over time: a true
     balance's misses are timing and cancel, a proxy's accumulate), and the **shift null** (the
     level moved circularly in time against the same counters, 9 shifts, searched the same way)
     must fit as well in no more than a fifth of the shifts. A balance its source declared (a
     channel's backlog and its own traffic) is chosen by no search: only its units and running
     residual are measured.
   A level whose balance fails is left out with the reason (`discovery.refused` keeps each refused
   balance's measurements), and its net flow is still fitted. A **count of reporters balanced by
   its own turnover** (`orchestra/sources/views.py`'s `count`, `starts` and `stops`, passed as the
   reading's provenance) is exact by construction, so no evidence (`sd/construction.py`): it is a
   stock only as a count of pods in a place (a deployment, node, namespace, service, job, phase or
   condition), marked `by_construction` with no R² and not counted in `discovery.stocks`; split by
   what happened to a request (an HTTP status code, a method, an outcome) it is left out. A
   **place's level and its moves** are the same construction declared by an instrument (§4.2):
   an instrument's count of a place and its moves, from one record (`count` naming its `place`
   label, whatever that label is called), so its balance is recorded, not fitted. Its own moves
   (those whose entered or left label names the place, every other label they share equal) are
   its balance, taken as declared before any search and never chosen; it is marked
   `by_construction` with no R² and nil trust, kept whatever else it is split by (its instrument
   named its place), and its moves are the flows between the places, each marked
   `by_construction` in its `evidence`, two of an instrument's moves never taken for one flow.
   The flows' rates are fitted like any other's: they, the loops they close and agreement with
   an outside measurement are the evidence about the place, never its balance. A level an instrument says is an `aggregate` or an `age` is no
   stock candidate. If the moves miss some of the level's changes, the level is searched like any
   other and the reason says what the construction fitted. A hidden
   state (no series measures it, step 3) records no R² either (`balance_r2` null, `measured`
   false);
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
   the raw points do not), never an age, an aggregate or a statistic of what it holds, nor a
   level in a unit no counter is in (the oldest item's seconds, `sd/discover.py`), that rose no more often than the inflow counted, that at each of its
   own writes reads what the counters imply (the items moved in less those moved out up to then,
   give or take a second for the order of two writers' writes, apart from the items there
   before), at 80% of the writes where it, or the counters throughout that second, say something
   is there (a state sampled coarsely misses the items that come and go between its writes, and
   so do the counters' totals at those writes; a pile that reads empty while the counters say an
   item is in, or moves while they say nothing moved, is another state), whose matched rises
   and falls moved at least a quarter of the items the counters moved, or else beat chance (a
   binomial tail over its rises and its falls, each matched by chance with the share of its own
   writes within the tolerance after an event, below one in a thousand: the bakery's 11 of 77
   orders accepting) or read the items its writes could not have missed, one at least (UC-2's
   REJECTED, seen once at any step; one rise and one fall of 2 of 52 written every 149 s, or a
   flag on its own clock beside a busy counter, do neither), and that
   both rose and fell by at least one in the window (the test
   is by magnitude, in the level's own unit, whatever that is: a level that only rises, the test
   reports read, 5 to 10, is a tally; one whose moves are all under one, a gate's duration of
   tenths of a second or a count scaled to fractions, moves no whole unit; a duration that moves
   by whole seconds passes it, the buffer between two counters being kept to their unit by unit
   instead). A stage that fills and does not drain inside the window (its first items still in
   it at the window's end) is therefore no measured state there; with none (no level is written, or one never reads above zero), a
   stock measured by no series, drawn as hidden (`after_<in>`, the level the counters imply).
   The drain and the fill are each claimed by one
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

Every stock records **how far to trust it** (`sd/stocktrust.py`, `evidence.trust`), measured at
discovery and saved with the model version: the kind of evidence it stands on (`conservation`,
`net_flow`, `passage`, `unmeasured`, `by_construction`), each measurement, and the weakest as one
`score` from 0 to 1 with a `level` (high from 0.8, medium from 0.5, low from 0.2, else very low)
and why. A passage's: the lesser of the share of its rises and falls that came at its counters'
events and the share of the items its counters moved that those rises and falls moved (`4 of 50
moves matched` scores 0.08, not 1.0; a version saved before the items were kept has only the
first), its steps in step, and its units. A balance's: the shift null (1 at the least p-value its shifts can give, 0 at p = 1), the
held-out R² (an exact balance's own R² on each half), the level reproduced (one less the running
residual's spread over the level's), its units (`1 − e^(−units/20)`), and whether both halves chose
the same counters (0.6 when not: its flows are not identified; when each half balanced it on
counters the other did not choose, exact or not, "two balances fit"). A net flow's (`sd/netnull.py`): the
same, for its fitted form, with the shift null refitting the whole procedure over the same drivers on
the level moved in time, and its R². Hidden states and counts by construction score 0. Net-flow
stocks are kept, whatever their score: a coincidental driver is the data's to cure with more
relevant series (the owner, 2026-10-27), and its low trust says so. The host also records each
stock's **persistence** (`sd/persistence.py`): the share of the last 12 discoveries that found it
with the same counters (or the same net-flow form and driver), a component of the score once 3 are
remembered; successive windows overlap, so it measures stability as the window slides, not
independent confirmation. The Dynamics page and `orchestra sd discover` show the score beside each
stock, and the stock's drawer every measurement.

That score is the stock's **identity** trust: its accounting holds. Beside it, never folded into
it, each measured stock records its **behaviour** trust (`sd/behaviour.py`,
`sd/equations/heldout.py`, `evidence.trust.behaviour`): the model run forward from half-way, two
thirds and five sixths of its own window, its inputs held as a forward run holds them, against the
measured level; the RMS miss over the level's spread (`error`), the same for the level held
(`hold_error`), how the miss grows with the horizon (`growth`, `z`), and `score = 1 / (1 + error)`.
The equations were fitted on the whole window, so it is held out in time, not in fitting. It is
shown wherever the identity trust is, and a forward run widens each stock's band by it (in
quadrature, `± z × growth × h`), so that the band covers the truth about as often as it says.

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

**A quiet window** (`sd/quiet.py`). A stock that stops moving still holds its quantity. A stock
of the current version that a discovery did not find is quiet when its series is still: written up
to the end of the window (its last point within two steps or three of its own write intervals of
it) and moving fewer than 5 times in it (a level's changes, a counter's events); a hidden stock,
when every counter of its flows is still, however discovery left them out (unmoved, too few, or
folded into another counter of the same few events). A quiet stock is carried into the discovery
from that version with the flows that reach it, marked `evidence.quiet` (the version, and since
when: the last time its series moved, else the window's start), before the structures are
compared, so a quiet window never saves a poorer version. A series that stopped being written
inside the window has stopped, not gone still, and a stock that moved and no longer balances is
not quiet: both go as before. When nothing else changed, no version is saved and the record
(`discovery.quiet`, `stands`) and the page say "quiet since <time>: vN stands, nothing refitted",
the time from the record's `since` in the viewer's own zone.

**A window too quiet for any counter** (`sd/rediscover.py`, `widen`). When a discovery finds no
stock because no counter it read counted 5 events in the window (a low-traffic system: a sprint
board, whose last hour may hold no move at all), the window is doubled with its step (the grid
keeps its number of steps), up to 7 days, never past the era's start and no further than the
oldest point read, and discovered again before "no model" is said; `discovery.widened` says
which windows were read, and the page says the window the model was fitted over.

**Eras** (`sd/eras.py`, `sd/prior.py`, `sd/compare.py`; goal G11). After a machine changes how
the system works (a prompt or role edited, the configuration changed, a deploy) it is a different
system, so a new **era** begins, and the era is the window the model is discovered in:

- **What begins one.** Orchestra knows no domain, so it is told, by the envelope alone (never
  `data`): `system.changed`, the generic mark any machine publishes when it changed the system
  (`source`: the machine; `subject`: what it changed, optionally), always does; `[discovery]
  eras_from` names more, as filters `type[:source=glob,subject=glob]` (default
  `["config.changed"]`, the conventional type any machine may publish when it changes the
  configuration).
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
  is mostly its prior, and the era's own evidence takes over as it accumulates. A part of the prior
  marked `simulated` (§5.2), and a flow reading one, is never carried or blended: a placeholder
  never seeds the next era (dropped, with why `simulated`).
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
  predicts every stock from its level now (`sd/equations/forward.py`, no change: the central
  run and its 10–90% band), its band widened by the Poisson spread of its flows' events since. A stock's
  **gap** is its level less the central prediction, in half-widths of that band, judged against
  the oldest prediction that still reaches now (so a wrong rate shows as a growing gap). A stock
  is out past 2 half-widths and **diverged** once it has been out at every check for `[discovery]
  diverge_after` (default 15 min); it **returns** inside 1. `data.stocks` names each with its gap,
  level, band and since; `data.diverged` every stock diverged now; `era` and `era_start`, so a
  listener tells a divergence after an announced change from an unexplained one (the
  unexplained-change test, docs/rationale/lifted-models.md §3.3). Needs `orchestra[sd]`.
- `orchestra.model.stalled` and `orchestra.model.resumed` (`sd/stall.py`): work that stopped
  moving, in the model's terms alone. From the same history (series read, no simulator), over the
  last `[discovery] stall_after` (default 15 min): a **stock** is stalled when its level rose
  while every outflow drained less than `[discovery] stall_share` (default 0.1) of its usual rate
  (its mean over the history before that window) and at least one outflow usually drains it; a
  **flow** is stalled when its usual rate is above zero and every rate within the window is zero.
  One event per item, `subject` `stock:<id>` or `flow:<id>` (a listener wakes on one item:
  `orchestra.model.stalled:stock:queue`), `data` `kind`, `id`, `name`, `since`, `window_s`, `per`
  (the time unit of the rates), a stock's `level`, `rose_by` and `outflows` (`{flow, rate,
  usual}`), a flow's `rate` and `usual`, `era`, `era_start`. Once per stall; `resumed` (the
  stall's fields with `stalled_since`) when the item is judged again and moves. An item the
  history does not cover on both sides of the window is not judged. What a stall means for the
  work is the listener's to say (rule 1).

**Predictions: the intended-effect test** (`sd/predictions.py`, `sd/verdict.py`, `sd/judge.py`;
goal G13; docs/rationale/lifted-models.md §3.1 and §3.2). Before a machine changes the system it
says what the change will do, as edits of the model, and once the change has run for the horizon
Orchestra judges it against what the era's discovery found.

- **Recording.** The machine publishes `orchestra.prediction.made` from its own `source`
  (directly over the events endpoint, with `sd.predictions.Predictions`, or through the
  Supervisor's `confirm` of a declared expected effect, which publishes it for it). `data`: `change`, the id of the event that will
  make the change (chosen beforehand: the change is then published with that `id`); `expect`, a
  list of edits, each `{"flow", "factor"}` (its rate × r; `"param"` for one number; 0 is the
  flow disappearing), `{"flow", "unchanged": true}`, `{"flow", "equation", "params"}` (the flow's
  whole rate becomes this equation, in the equation language of §4.5), `{"flow"|"stock"|"loop",
  "appears"|"disappears": true}`, `{"from", "to", "appears": true}` (a new flow between two
  stocks, `null` for outside; with `equation` and `params`, the rate it will have), `{"stock",
  "below"|"above"}` (its mean level over the horizon's second half), `{"stock", "rises"|"falls":
  true}` (its slope after the change, by least squares over the horizon, against its slope over as
  long before; met when the difference is `|z| ≥ 2` in that direction, `different` the other way,
  `absent` when the slope held though the level rose: a declared machine's expected effect,
  §4.6); `[]` is the **null test**,
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
  predicted edits applied as a draft (`sd/equations/predicted.py`, `forward.py`; needs
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

A part discovery marked `simulated` (§5.2) is never an unpredicted change or side effect.

The experiments, through which a machine asked what a change would do, were removed on 2026-11-01
(§4.5): a change's effect is stated as a prediction and judged on the eras.

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
  `<state>/sources/<name>.json` with the window inferred over (`sources/infer.py`,
  `sources/cache.py`). **Only the host's discovery and the CLI infer**; the web server and the
  judge read the cache. One round at a time across processes (a lock); a failed or partial round
  is retried after 5 minutes, four times longer each next time, while the cached definitions
  stand; after three rounds that failed for their cost, or one refused because `match` selects
  more than `max_names` (2,000) metric names (a big tenant is never listed whole), none runs until
  the source's settings change. A round over a narrower window never replaces a broader one. A
  source that declares `[[series]]` infers every 6 h unless `infer_every` says otherwise. A round has a budget
  (`infer_requests`, 1500; `infer_deadline`, 300 s) and its reads are **batched across families**
  (`sources/listing.py`: names from `label/__name__/values`, series in batches of names split on a
  422 and stopped at the cap, histogram buckets never listed, a name over the limit across an HA
  pair's replicas listed and read at one, what was too big remembered for a day; `sources/census.py`, `sources/survey.py`: samples, churn,
  duplicates in few queries; `sources/batch.py`: parts joined with `or`, tagged by
  `label_replace`, under the source's `series_per_query`). A family a round cannot read keeps the
  last round's verdict or is `unknown` and left out, never guessed. Families (names differing by a statistic
  suffix, or a `stat`/`statistic`/`quantile` label; a histogram's or summary's `_count`, typed
  under its own name or its base's; a recording rule `…:sum`/`:avg` as a view of its base by that
  function, read on its own interval), label aliases, each label's role (identity: one of the
  source's `identity` names, default pod/instance/container, a label naming one object (an id,
  an address, an image or version), churning, or over 50 values; constant; grouping) and the
  reporting interval (`sources/schema.py`); a label naming a **unit** (`unit`, `resource`, or
  values that are units) is kept in every view, and each definition carries its unit (metadata,
  else the name's suffix). **A name is a hint; the samples decide** (`sources/behaviour.py`): a
  gauge that never falls but at resets (a drop to half or less, crash loops included) and whose
  name counts events is a counter, a counter that falls by halves is a gauge, a gauge whose
  samples are counts of their own is a delta, a native histogram is a counter by its count, and
  timestamps, clocks, info metrics and Prometheus' `up`/`scrape_*` are never levels or flows. A
  family that only rose in the window is judged over `history` (24 h) as well, and a type once
  judged changes only when the samples decide it. A scrape job or replica label is read at one
  value when its values scrape the same targets (instance without the port, EC2 host names as
  addresses, node labels) and agree: a counter's increase each quarter of the window within 5%
  (`sources/duplicates.py`).
- **Views** (`sources/views.py`): of a per-pod statistic, the max of max, min of min, average of
  average (flagged unweighted) and max of p95/p99 (flagged an upper bound), never a sum; of a
  plain gauge the max and average (latencies, ratios) or the sum; of a counter, its increase by
  grouping; of a recording rule, its function by grouping, except a rule over a counter, which is
  left out for the counter (one flow). Levels are read with `last_over_time(…[R])`, R the larger
  of 2.5 reporting intervals and one interval plus 30 s. **A count switches the type:** the pods
  reporting (`count by (G) (last_over_time(F[R]))`) is a level, with its turnover (the pods that started and stopped reporting,
  from the raw samples) as two counters that balance it exactly, so pods per service is a stock;
  and how many values of each grouping label report. One family counts each thing.
- **The query script** (any executable, from the repository root, with a timeout) gets the
  candidates as JSON on standard input and prints rewrites: new queries, drops with a reason,
  definitions of its own, pins (`sources/transform.py`). A failure fails the round.
- **Rank and cap** (`sources/rank.py`): each candidate is read over the window at its resolution;
  one that returns nothing or does not move is left out, and so is one equal at every point to
  another family's (a count of the same pods, a `_count` beside its `_total`); the rest are
  scored (moves, groups moving apart, stable, small, coarse, view) and taken in two rounds:
  every family's coarsest up to 60% of the cap, then the rest best first, splits whose groups
  move apart leading. Each definition records the grouping labels it merges. A pin bypasses the
  ranking, not the cap. What is left out is kept with its score and why. A hand-written
  `[[series]]` (source, name, query, kind level|counter|rate, unit) is always read. A
  `[[series]]` may declare a stock (`stock = "<name>"`, `role = "level" | "inflow" | "outflow"`):
  discovery tries the declared counters as that level's balance before any search, and judges it
  by the same evidence (`sd/pins.py`; it records `declared`, its origin, and is searched like any
  level when it does not fit).
- **Reading** (`sources/catalogue.py`, `sources/fetch.py`, `sources/plan.py`): every definition is
  read for exactly discovery's window, on its grid but never finer than the series' resolution;
  each family once per aggregation at the finest grouping its views need, every view derived
  exactly (`sources/regroup.py`); counters server-side as `sum by (G) (increase(x[S]))`, S the
  step holding two samples, accumulated; turnover and declared `select`s from raw samples at
  their real times, each selector read once; rates integrated. Results take canonical labels,
  `machine = <prefix>.<value>` from the machine label (a remote `machine` or `source` label is
  prefixed too), and the name `<prefix>:<name>`; one that collides with an own series is refused.
  Each source is read on its own, with a timeout per request, a deadline and a budget
  (`max_requests`), at its request `rate` and under its daily cap (`max_requests_per_day`), both
  **per store** (its URL and tenant headers) and shared by every project and process on the
  machine through `~/.orchestrator/stores/` (`sources/limits.py`); 429, 502, 503 and 504 are
  retried after `Retry-After` or a jittered backoff (`sources/transport.py`). **Reads are
  incremental** (`sources/readcache.py`): discovery keeps what it read in
  `<state>/sources/<name>.reads.json` and asks only for the steps since (and five minutes before, further for late series),
  reading the whole window again hourly; a read refused for its size is not asked again for an
  hour, and one refused for its series is not split by time unless that sheds series.
  A source with at most a tenth of its definitions unread is **partial** (the rest used, the
  failed named); one that fails beyond that is **missing**, and the stretches of the window in
  which it returned nothing are its gaps. Every
  range is re-runnable: a run after the machine slept reads its whole window like any other.
- **Provenance:** each `SeriesRef` in a model carries its `source` (`own` or a source's name),
  final `query`, `kind`, `origin` (inferred from which family and view, rewritten by
  `queries.py@<hash>`, or declared), `resolution_s` and `unit`; a stock bound to a count takes its
  unit; each equation lists the sources of the series it was fitted on (`sd/provenance.py`). The
  Dynamics page shows each source's state and why a discovery was not saved, and a stock's drawer
  its source, query and origin; the web server reads remote stocks' levels and history through
  the catalogue **only while a page asks for them**, at discovery's step, from the host's read
  cache and then only what is newer, in one round per source from its own share of the store's
  rate (`web_share`), slowing down when the store throttles it.

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

### 4.5 The equation language and the forward run

`orchestra/sd/equations/`; goals G5 and G13. What prediction judging (§4.3), the divergence check
(§4.2) and the behaviour trust need to run a model's equations: the language every rate is
written in, the engine that steps it, and the forward run.

**Experiments were removed on 2026-11-01** (the owner: "get rid of that and the code associated
with it"). An experiment was a staged copy of the model a machine edited and ran forward, replayed
over a past window or asked the inverse question of, and could commit as a prediction; the web
UI's Experiments pages went first (§10), then the Python API (`sd.experiments.api`), the
`/experiments` routes of the events endpoint's HTTP API, the record in `<state>/experiments/`,
the edits, the replay, the inverse solver and the agents' `experiments` and `replay` tool groups.
What replaced them: the declared layer's expected effects (§4.6) and the Supervisor's design
tools in `~/orchestra-agents` (`declare_expected_effect`, and `confirm`, which publishes
`orchestra.prediction.made` through Orchestra's `Events`), and for any machine
`sd.predictions.Predictions` or a direct `orchestra.prediction.made` (§4.3). Predictions are made,
recorded, judged and shown on the Dynamics page as before. An old `<state>/experiments/`
directory is ignored: nothing reads it, and nothing deletes it.

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
floored at 0; inputs held between points), for many columns at once (a band's members), with
parameters set per column.

**The forward run** (`forward.py`): a base model and a draft of it (the base with a
prediction's expected edits applied, `predicted.py`; or the base itself) from the measured levels
now, `horizon_s` ahead; each stock's and flow's trajectory as the central run and a band (10th–90th
percentile of runs with every flow's rate × `exp(z · rel)`, `rel` its recorded relative error,
`sd/trust.py`: `sqrt(dispersion / events)` for a Poisson fit, the slope's error at its R² for a
net flow, `1/sqrt(events)` but at least 0.1 for an SD Lab rate, 0.5 for a declared equation,
so every equation a prediction wrote; z shared by id between the two runs), widened by each
stock's held-out replay error (`heldout.py`); the **limits** (a stock reaching 0, or leaving
bounds the caller gives, in the central run and in what share of the runs, and whether the draft
brings it); **not trusted here**, with the reason (a flow declared, carried from the prior, a net
flow, replayed, fitted on few events, over a short time or at low R²; a stock touched by one,
hidden, without a level now, whose base run since the era began misses its measured level by
more than its own spread, whose run leaves the observed range, or one of whose changed flows runs
outside what was seen). `forward.trajectories` is a prediction's `trajectories` from it.

**Reading the model** (`sd/reads.py`, `ModelReads`): the model with its equations in the
language (`views.py`), its versions, the eras, the observability report, the predictions and
series, for a machine (the agents' model tools) and the HTTP API (§3.1) alike. Nothing here
changes a machine, the model or a metric.

### 4.6 The intended model

`orchestra/sd/intended/` (docs/proposals/intended-model.md). The **declared layer** holds what
the owner intends and what a plugin or inference proposes, beside the discovered model, and the
**comparison** of the two. It runs nothing (AGENTS.md rule 1): a declared machine is not started,
a declared stock binds no series, a declared flow changes no equation, and discovery never reads
it (rule 7).

- **Elements.** Stocks and effects (`name`, `description`, `unit`, `near`, `note`, `found_as` set
  only by `link`, `measure`: the plugin's options and the chosen one; an option's fields `key`,
  `title`, `how`, `kind`, `instrument`, `simulated`, `cost`, `caveat`, `clearance`, `provenance`,
  `commit`, `first_points`, and what it names as text, `system`, `series`, `url`, `command`, its
  credential only as `bearer_env`, an environment variable's name, and a url never with a password), flows (`from`, `to`: declared or
  discovered stock keys, `null` outside), targets (`{op: below|above|within, value, hi?, over_s}`,
  judged on the mean over `over_s`: a level, or a flow's count over the window; met, missed or
  unknown, never met on simulated parts), expected marks and ignores (by key), machines (the
  envelope `id` (the `source`, `^[a-z][a-z0-9_]{1,40}$`), `title`, `description`, `tags`,
  `kind` universal | programmatic, `managed` orchestra | external, `engagement {mode, at, tz,
  missed}`, `receives`, `emits`, `reads`, checked; `spec` stored as sent, unread), event types,
  P5's attachments, a machine's expected effect (a draft prediction in §4.3's grammar, never an
  association) and aliases, and subsystems (`docs/proposals/subsystems.md` §5, step 3:
  `declare_subsystem` `{id?, name, note?, label, value}`, a name for a label's value, never a
  writer's label (`NOT_IDENTITY`) or `simulated`/`draft`, each value named by one; or `{id?, name,
  note?, members: {stocks: [keys], flows: [keys], machines: [ids]}}`, parts gathered that no label
  groups, at least one, each part in one subsystem at a time; the same id again replaces it, under
  the owner's guard; `retract`, `confirm`, `discard` on `part: "subsystem"`; no page control
  declares one). Only a declared one is drawn: a name titles its group's box, "named by <who>", the
  raw value said on the box title's hover; the gatherings make one partition, `declared`, listed and
  chosen first, its stocks and flows matched by key, a flow it does not name placed by its ends and a
  machine by its hypotheses, a member no longer in the model a ghost in its box, a declared
  machine's `tags` naming one (its id or name) placing that machine in its box on the map. A
  subsystem binds no series and changes no equation, hypothesis or key. Every element carries its `state` (proposed or declared), its
  `provenance` (`author`, `via`, `at`, `source`, `turn`, `message`, `quote`, `reason`, `request`;
  a page control's `control`, `page`, `from`; `via` and `at` are set by the store, never given)
  and its change id (`c<seq>.<i>`). What the owner asks for is declared at once, a re-declared
  proposed stock or effect included; a machine always enters proposed. A revision by the owner
  with a quote applies at once to a stock or effect, and to a machine or attachment while it is
  still proposed (recorded as `latest`: added, removed, before); on a confirmed machine or
  attachment, and by any other author, it is a pending change until `confirm` or `discard` names
  it. A proposal or pending change is confirmed or discarded by the owner (a page, or a plugin
  quoting the owner) or with `provenance.request` (answering the owner's request), never by its
  author alone. A plugin answers the owner's request (`provenance.request`) only with the op asked
  for: the request must be one the web server noted, unanswered, about the same part and id, with
  the same control and, when it names one, the same change; any call citing a request that is not
  open, whatever its ops, is a 422. A request is answered only by an op that answers it (the
  journal line's `answered`), never by a call that merely cites it. A revision answering a
  `switch_kind` request (it sets `kind` and nothing else) applies at once, even on a confirmed
  machine, recorded in `latest.request`. A confirmation records who gave it (`confirmed`: `by:
  owner` when the owner asks, or `by: owner, via: request, request` when it answers the owner's
  request). What is the owner's (an element, mark, target or described event type the owner
  declared, or an element the owner confirmed) is retracted, unmarked, re-described or re-targeted
  only by the owner or in answer to the owner's request ("the owner declared this: ask the
  owner"); another author's re-mark of the owner's mark leaves it as it is, and a target set by id
  is guarded by who set it (`target_by`). A key is expected or ignored, never both: one mark
  replaces the other, under the same guard. A declared stock or effect named by a declared flow, a
  keyed target, a machine's expected effect or a pending change that would set one is not
  retracted or discarded until those change; an event type a machine receives or emits is not
  retracted until the machine changes. Once a machine is confirmed, a new expected effect waits as
  a pending change; new edits drop the linked prediction. Where the owner's pending change and
  another's touch the same fields, the other carries `overridden_by` (on read) and is confirmed
  only when the owner asks for it or the owner's request names it. The owner's re-declaration of
  a declared flow is a revision (a non-owner's is a 422). A call `via: page` is one control of rule
  9's closed list (400 otherwise); a call is `via` a `plugin` (in process), the `endpoint` (over
  the events endpoint) or a `page` (inference's `host` joins once inference writes here). What is
  enforced: `author: owner` from a plugin or the endpoint is the caller's assertion, backed by its
  `quote` (refused without one), and any holder of the events token can make it; the pages show
  who made it ("the owner (quoted), per <source>"), keeping "you" for the owner's own page
  controls.
- **Keys.** A discovered part is matched by key, never by id: a stock's series name and labels
  without instrument, machine, source, project, instance, simulated and draft; a flow's ends' keys
  and its counter's key. A stock no series measures is keyed by the level its counters imply,
  where discovery keeps it (`evidence.level`, a state between counters); only a stock with
  neither, SD Lab's hidden stocks (named after other stocks' ids), is keyed by its id
  (`stock:<id>`), which follows arrival order. Parts carried from the prior are not the era's own.
- **Storage.** `model/intended/`: `journal.jsonl` (every accepted call, append-only),
  `dNNNN.json` (the whole layer after each call; `dN` and `vN` are separate numberings, rule 4;
  a `dN` that cannot be parsed is reported as unreadable, 500, never as missing), `diff/` (the
  structural diff cached as `d{N}-v{M}-v{K}-{era}-h{hold}.json`, `hold` the `announce_hold` its
  suggestions settled by; `vlive` for an unsaved latest discovery, each of its pairs kept until a
  newer discovery), `requests.jsonl` (each request noted before it is published, taken out again if
  the publish fails), `announced.json`. An append first ends a torn last line. Reached only through `ModelStore.intended()` (`project.intended`), written
  only by the host and the web server (rule 5). Present, heard, recording, measured, met,
  candidates and verdicts are derived on read, under a time limit (`missing` names what was not
  read in time); an op carrying one is refused.
- **The comparison.** Changes since the previous version by default (`since=`, `off`; a value
  that is not a version's number is a 400, an unknown version a 404): new and removed keys, the expected set present or a ghost, a declared flow's matches as candidates when
  an end is outside or two flows match; suggestions settle after `[discovery] announce_hold`
  saved versions, came-and-went and ignored are collapsed groups; the model has stabilised when
  no suggestion is unsettled. A past `vN` is paired with the `dN` current when it was saved. The
  latest discovery is shown as the newest `vN` when its structure is that version's; otherwise it
  is compared with `vN` and labelled "the latest discovery". A declared flow's ends are declared
  ids or discovered keys, never discovered ids. Every unsettled suggestion is a `+` row until it
  settles, is expected or is ignored (`status` `new` against the base, else `suggestion` with the
  version its run began), ringed unless `since=off`; `suggestions` lists them. A removed part that
  was simulated says so (`simulated: true`). `intended.predicted` lists the flows the declared
  machines' expected effects predict, one entry per machine and edit (`machine`, `edit`), as ghost
  flows with no association (`machines: []`, rule 6). A draft's names (`stock`, `from`, `to`)
  are resolved one way everywhere (`intended/names.py`): a declared id through its `found_as`
  (without one, "waits for a link" when its measure has a chosen option, else "waits for a
  series"), or a discovered key; otherwise, a discovered id included, "not in the model" (an
  unresolved end of a flow is named: "orders_open: not in the model"). A draft names keys; a
  plugin publishing a draft as
  `orchestra.prediction.made` turns them into the era's ids. A target on an effect found only as
  an input is judged on that input's series. A recording is read for the project's own points. A
  declared stock or effect whose chosen option is simulated reads `simulated: true`, and its
  recording `simulated: true`.
- **The API.** `project.intended.apply(ops, provenance)` (all ops or none; `IntentError` with
  the op's `index`), `read`, `diff`, `design`; over HTTP `POST /intended`, `GET /intended` and
  `GET /intended/design` on the events endpoint (§3.1). `design()` reads presence by id for a
  declaration and by key for a mark, lists a declared stock or effect with no `found_as` as absent
  before any model exists, and says a machine is heard as the Machines page does (its id or an
  alias among the observed machines: the web server gives the ids it has observed, counted
  traffic's included; in process, Orchestra's count of the bus), lists every open request, and
  says why when the comparison failed (`comparison_error`). The ops: `declare_stock`,
  `declare_effect`, `declare_flow`, `set_target` (its comparison is `target`, since `op` names the
  op), `expect`, `unexpect`, `ignore`, `unignore`, `link`, `alias`, `propose_machine`,
  `revise_machine`, `declare_event`, `set_expected_effect`, `record_prediction`,
  `record_measurement`, `confirm`, `discard`, `retract`, `propose_attachment`,
  `revise_attachment`.
- **Attachments** (docs/proposals/instruments-on-machines.md). `propose_attachment {machine,
  instrument, match?, instance_label?}` says which series measure a declared machine: the
  instrument's (as the Instruments page names it; refused when there is none), narrowed by
  `match` `{prefix?, labels: {label: value | "=~regex"}}`, a source's labels canonical after
  `[sources.labels]`; `instance_label` names its replicas (refused when every source definition
  the match selects sums it away). It enters proposed and is declared by `confirm`; discarding
  or retracting its machine removes it. Derived on read, never stored (`sd/intended/measured.py`,
  `web/measured.py`): a series is **measured** while its last point is within `max(1 h,
  active_within(cadence))` of its last `BEATS` points (`orchestra/cadence.py`), else quiet; an
  attachment's instances are its instance label's values (more than `[intended] max_instances`,
  50, list none), per attachment and never unioned; a machine shows the largest measured count
  of its declared attachments. The web server reads what each attachment selects every minute
  and when the layer changes (`MetricsStore.recent` for the own store, the sources' catalogue for
  a source, over the last hour), under a time limit. `/api/machines` gives each declared machine
  `measured` (`attachments`, `measured`, `last_measured`, `instances`, `instruments`, `unknown`)
  and `comparison` (`heard`, "measured, never heard", "attached, nothing measured", "declared,
  neither heard nor measured", "series unknown"). Being measured never makes a machine seen or
  active, and an attachment is never read by discovery or `sd/attribute.py` (rules 2, 7).
- **Announced.** After each accepted call the host publishes `orchestra.intent.changed` as
  `orchestra-host`, one event per element the call touched (`subject` `<part>:<id>`, `data`
  `{version, via, ops}` with that element's changes), following the journal, so a call the web
  server wrote is announced once it is up. Delivery is at least once per element: a publish that
  fails partway through a call repeats the elements already sent, so a listener de-duplicates by
  `version` and change ids. Intent events are records about a declaration, never
  hand-offs on the Machines page.
- **Declared names.** A declared stock or effect linked to a discovered stock (`link`, its
  `found_as` that stock's key), or a declared flow found as one discovered flow by its ends and
  declared with a `name` of its own (not the "<from> → <to>" made when none is given), lends its
  `name` to that part, once it is declared (a proposal lends none); a part two declarations name
  takes the owner's, else the first's (`sd/intended/display.py`). `model.intended.names`
  (`{stocks: {id: {name, part, id, provenance, linked?}}, flows: {…}}`) lists them, and each such
  stock and flow of `/api/dynamics/model` (and of `/api/machines`' `model_parts`) carries it as
  `declared_name`. The pages show it as the part's name, the generated title beneath it as its
  identifier, with "named by <who>" from the declaration's provenance ("you", "the owner (quoted),
  per supervisor"). It is display only: it binds no series, changes no title, key or equation, and
  no page control sets it (rule 9): a plugin (the Supervisor) declares it, `declare_stock {id,
  name}` then `link {part: "stock", id, found_as: <key>}`, or `declare_flow {id, from, to, name}`.
- **The pages** (§10): `GET /api/dynamics/model?since=` gains `model.intended`, `/api/machines`
  gains each machine's `intent` (a declared machine not heard is appended, `unseen`, with no
  observed values: no `subscribes`, `publishes` or `mode`) and `comparison` (`heard`, or
  "declared, neither heard nor measured"), and `intended_edges`, `intended_types`; `/api/intended`, `/versions`, `/journal`, `/diff`,
  `/design`, `/script` (an option's script: the first word of its command that is a file inside
  the repository or the state directory, past an interpreter outside them; 404 no entry, 403 only
  outside files). A refusal is `{ok: false, error}` with its status (a non-integer `version`, `d`
  or `after` is a 400). Each attachment row under a machine's `intent` carries the owner's
  unanswered request (`requested`: the latest still open), each machine and attachment who
  confirmed it (`confirmed`), and each pending change `overridden_by` when the owner's overrides it. The page controls (rule 9): `POST /api/intended/control` records an observation
  (`expect`, `unexpect`, `ignore`, `confirm` or `discard` on a stock, effect or flow; a mark is
  stored by `key`, or by the key of the part with that `id` in the latest model, and an `expect`
  or `ignore` of a key no latest model has is refused), and `POST /api/intended/request`
  publishes the owner's request (`confirm`, `discard` on a machine or attachment, `switch_kind`
  on a machine; it must name a declared element, and for `change` one of its pending changes; a
  `confirm` or `discard` with no change is of a proposed element, 409 otherwise) as
  `orchestra.intent.requested` from `owner`, which the Supervisor answers by applying with
  `provenance.request`.

---

## 5. The bootstrap host

`orchestra run` starts Orchestra's own machine (`orchestra/host.py`). In an empty Orchestra it:
- registers itself in `<state>/runtime.json` (`hosts`, by pid) and logs to `<state>/logs/orchestra-host.log`;
- publishes `orchestra.host.started` and `orchestra.host.stopped`;
- writes `orchestra_host_up{machine="orchestra-host"}` every interval;
- runs the event collector: replays the bus once at start, then follows it, recording the eras
  the bus begins and announcing each (`orchestra.era.started`, §4.3);
- rediscovers the model every `[discovery] every`, within the current era, and then publishes
  what is due about it (`orchestra.model.changed`, `.diverged`, `.returned`, `.stalled`,
  `.resumed`, §4.3);
- says when a machine falls silent on the bus (`orchestra/quiet.py`): an instance with a cadence of
  its own (at least 3 beats, the Machines page's rule, `orchestra/cadence.py`) silent longer than
  it stays active by that cadence is announced once, `orchestra.machine.quiet` (`subject` the
  machine; `data` `machine`, `instance`, `last_seen`, `usual_gap`, `quiet_for`, `mode`), until it is
  heard again. Observed only: the one thing read from its announcement is its mode, and an
  instance engaged ad hoc is never called quiet. Orchestra's host, and instances already quiet
  when the host starts, are not announced;
- records the predictions machines make of their changes as it follows the bus, and after each
  discovery judges those due and publishes the verdicts (`orchestra.prediction.judged`, §4.3);
- announces each accepted call to the intended model's declared layer, once, as
  `orchestra.intent.changed` (one event per element the call touched, following the journal, so
  a call the web server wrote while it was down is announced once it is up), and after each
  discovery and declaration writes the current comparison's structural diff to the cache (§4.6);
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

and a plugin in `Plugin.processes` (§10.1). Inside commands Orchestra runs, `python` is
Orchestra's Python (`sys.executable`), even inside `sh -c`, whatever is first on the PATH, so
Orchestra and the plugins are importable: every process it starts gets its environment from
`launcher_env.child_env`, whose PATH begins with a directory where `python` and `python3` are that
Python (`launcher_env.python_dir`), and a first word `python` or `python3` is replaced by it
(`launcher_env.own_python`). The project's own is `uv run python` or `.venv/bin/python`. A
`[[collect]]` command follows the same rule, and
either may be a string or a list of words. The host starts each in the repository root, in a
process group of its own, with `ORCHESTRA_REPO` (the root) and `ORCHESTRA_MACHINE_LOG` (its log,
`<state>/logs/machines/<name>.log`, which receives its output) and `ORCHESTRA_PROCESS` (its name
there, `<plugin>.<name>` for a plugin's, which a machine's announcement passes on as `process`, §2)
set, and, while the events
endpoint serves (§3.1), `ORCHESTRA_EVENTS_ENDPOINT` (its URL) and `ORCHESTRA_EVENTS_TOKEN`. A plugin's processes are named
`<plugin>.<name>` (in the runtime record, on the Core page and in their logs' names), so a
project's `[[machines]]` entry never takes a plugin process's place; a project entry named
`<plugin>.<something>` for a plugin with processes is refused, with a line in the host's log. One that exits is started again
after a pause that doubles with each exit within a minute of starting (1 s up to 60 s); after five
failures (non-zero exits) in a row, each within a minute of starting, it is given up on, which the
host's log, the process's log and the bus (`orchestra.process.gave_up`) say. It is tried again when
its entry changes or the host restarts. A plugin's process may name the settings it reads at start
(`Process.config_keys`, dotted keys of the merged configuration): a change under them restarts
it, and tries again one given up on. The host also publishes `orchestra.process.started` and
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
the launching host runs; their logs stay readable there after it stops (§10, Core).

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
simulated = true                 # optional: a placeholder; its points are labelled simulated="true"
draft = true                     # optional: an option being tried; its points are labelled draft="true"
expires = "2026-11-08T00:00:00Z" # with draft: when its plugin removes it (data only)
[collect.views]                  # optional: how it made its series (§4.2), for discovery
items = { view = "count", place = "place", where = { kind = "step" } }
item_moves_total = { view = "moves", starts = "to", stops = "from" }

[[scrape]]
name = "app"
url = "http://127.0.0.1:9100/metrics"
every = "30s"
```

A **simulated** instrument (P4's placeholder ramp) is read by discovery only while an entry with
`simulated = true` names it; afterwards its series are left out ("simulated, expired") and its
points stay. Every stock, flow and machine hypothesis fitted from a simulated series is marked
`simulated: true` in its `evidence` in the saved version (`sd/simulated.py`), with the series that
caused it (`simulated_from`: `{series, as}`, `as` one of `series`, `counter`, `end`, `input`), and
every equation fitted from one carries `quality.simulated = 1` (it reads a simulated stock or input,
is fitted on a simulated counter, or is a net flow's on a simulated level); the key (§4.6) and the
ids and names of parts and inputs leave the label out (`series.NOT_NAMED`), so a real series takes
over the placeholder's expected mark and its input's name. A plugin's
collector may be simulated too. A **draft** instrument's series are left out of discovery
(`left_out`: "draft"), while its entry exists and after it is gone. The core honours the flag and
nothing more: `expires` is data for the plugin, which removes the entry then or clears the flag
when the option is chosen; points written after that are ordinary and join the same stock (the key
leaves `draft` out). Both flags are read only on Orchestra's own series: a `[[sources]]` series
keeps its own labels, and is never marked simulated. The judge's split-half discovery (§4.3)
selects series the same way (`sd.simulated.discovered`). Which plugin collectors are simulated
is read from the collectors the caller runs (the host's, the web server's loaded plugins', loaded
again once the configuration changed); only a caller with none (the CLI) loads the plugins for it.
The web server reads `orchestra.toml` and the overlay again when either changed since it last read
them (`config.fresh_config`) before it reads which entries are simulated or an option's entry.

**Views** (`views`, a table by series name; a value is one view or a list, the first whose
`where` labels a series carries is taken; `collect/views.py`): `count` with `place`; `moves` with
`starts` and `stops`; `starts` or `stops` with `place`; `aggregate`; `age`. A plugin passes the same
table, `Collector.collect(name, command, views={...})`. A table that cannot be read leaves the entry
out with the reason (a plugin's: its `Collector` raises `ConfigError` when made). Discovery reads the
views of the instruments in the runtime record and of `orchestra.toml`'s entries (§4.3).

Each is an **instrument**: it measures the running system and never acts on it, so it is not a
machine (AGENTS.md rule 7). Nothing is announced on the bus for it and it is never a machine on the
Machines page; a declared machine's dialog names the instruments attached to it (§4.6), and the
Instruments page lists it. Its name is its own: it may share a `[[machines]]` entry's
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
`instrument`, `simulated`, `draft`) is kept as `exported_<name>`, as Prometheus does, never
overwritten. A series named
`orchestra_*` is refused, with a line in the host's log saying to rename it.

A round that fails (a non-zero exit, the timeout, which kills the command's group, a command that
cannot start, an HTTP answer other than 200, or text over 10 MB) writes nothing, adds a line to the
host's log and the instrument's, and is counted in `orchestra_collect_failures_total{collector}`,
labelled `machine="orchestra-host"`. A round that succeeds adds a line to the instrument's log.
Each instrument's health is in the runtime record (`instruments`: its kind, target, interval,
owner and log, its declared `views`, which discovery reads there for a plugin's instruments, its last write and how many points, its failures and its last error), written when
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
  stores/<store>/                what every project on this computer shares about another store it reads: its request rate and daily count (sources/limits.py, AGENTS.md rule 5)
  python/<id>/                   python and python3 scripts that run Orchestra's own Python, for what the launcher starts (launcher_env.python_dir)
  <key>/
    project.json
    orchestra.local.toml         the private configuration overlay, if the owner writes one (§8)
    runtime.json                 the hosts', the launcher's, the events endpoint's, the web server's, the launched processes' and the instruments' records
    .lock                        held while runtime.json is read and written
    discovery.lock               one discovery at a time, across processes
    config.lock                  held from the check to the write of a configuration change (project.config_edit)
    events.token                 the events endpoint's token (§3.1), readable by its owner only
    web.token                    the web UI's token (§10.2), readable by its owner only
    events.jsonl                 the event log, when [events] url = "file"
    metrics.jsonl                the metrics, when [metrics] url = "file"
    model/vNNNN.json             the model's versions
    model/discovered.json        the latest discovery, cached for readers
    model/recent_stocks.json     the stocks of the last discoveries, for each new stock's persistence (sd/persistence.py)
    model/<record>.lock          held while a record is read and written (versions, intended, intended-announce, eras, …)
    model/intended/              the intended model (§4.6): journal.jsonl, dNNNN.json, diff/, requests.jsonl, announced.json
    model/eras.json, announce.json, predictions.json   the eras recorded, what the host last announced, the predictions and their verdicts (§4.3)
    experiments/                 ignored: what the experiments kept, until they were removed on 2026-11-01 (§4.5); nothing reads or deletes it
    sources/<name>.json          each source's latest inference: its definitions, what was left out, its families (§4.4)
    sources/<name>.attempt.json  when its last inference round ran and failed, so the next waits (sources/cache.py)
    sources/<name>.reads.json    what the last reads of it returned, so the next asks only for the steps after (sources/catalogue.py)
    sources/<name>.lock          one inference round at a time, across processes
    logs/orchestra-host.log
    logs/machines/<name>.log     each launched process's output (§5.1)
    logs/instruments/<name>.log  each instrument's standard error and rounds (§5.2)
```

The project key is the repository directory's name plus a hash of its path. Inside the
repository, Orchestra writes only `orchestra.toml`, on `orchestra init` and through
`project.config_edit`, and the private overlay when the owner points `ORCHESTRA_CONFIG_OVERLAY`
at a file inside it (a relative path is read against the repository root, `config.overlay_file`).

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
eras_from = ["config.changed", "deploy.finished:subject=billing*"]   # begin an era, besides system.changed (§4.3)
prior_for = "60m"       # how long a new era carries what it has not found of its prior (default: window)
announce_hold = 3       # discoveries a structure change holds before orchestra.model.changed
announce_gap = "30m"    # the least time between two orchestra.model.changed
diverge_after = "15m"   # how long a stock is out of its band before orchestra.model.diverged
stall_after = "15m"     # how long a stock rises with its outflows stopped (or a flow stays at zero) before orchestra.model.stalled
stall_share = 0.1       # an outflow below this share of its usual rate counts as stopped
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

`[overlay]` in the overlay is not merged: `secret` lists keys (`desk.owner`, `machines[pager]`,
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
settings, `[[machines]]`, `[[collect]]`, `[[scrape]]`), as every loaded plugin's `Plugin.check`
does (each judging only its own sections; what it says is prefixed with its name) and as the
caller's `check` does: one that makes any of them say something new is refused with what they
said. A plugin that does not load, or whose check fails, refuses nothing and is listed in the
change's `warnings`; the plugins are loaded for this once per process.
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
| `orchestra metrics series` | List series |
| `orchestra sd discover [--strategy S] [--minutes N] [--step-s S]\|show\|versions` | The model: discover it from the metrics, show it, list versions |
| `orchestra sd predictions [--json]` | The predictions recorded and their verdicts, by era; read only |
| `orchestra sources check\|infer\|preview QUERY` | Other stores (§4.4): probe them, infer what to read, read a query's fan-out |

Machines ask what a change would do, predict, and read the eras and the observability report
through the APIs (§3.1, §4.5), and the web UI shows them.

---

## 10. Web UI

Read-only for humans, except for observations: the Dynamics page's rediscover button and the
intended model's closed list of page controls (§4.6, AGENTS.md rule 9). Navigation: Dashboard, Machines, Instruments, Dynamics, Core.

- **Dashboard:** panels as sections of one page on a 12-column grid (`static/dashboard.js`, with
  gridstack.js): the viewer drags a panel by its title bar and resizes it from its edges and
  corners, panels pack upward so one sits under another with no gap, and a panel can be hidden
  and brought back from Panels (in the navigation); positions and sizes are kept in the browser,
  and a narrow window has one column. A panel may give its starting size. Orchestra's own panels are **Machines** (a short list of
  what runs now: the machines that announced themselves continuous, and any other that published
  in the last two minutes; a click opens its dialog) and **Host** (a Core status strip; the
  host's CPU, GPU, memory and disk). A package adds panels of its own (`Orchestra.panels`, from its
  every-page script; §10.1).
- **Machines:** every machine seen on the bus or counted, and every declared one (never one a series names, never an
  instrument; a declared machine with instruments attached is "measured, never heard" until heard, §4.6) with its instances, how each is engaged and what kind
  it is (a machine whose instances differ says so: agent ×2, program ×1; what it listens for is the union over its
  instances, and its package, name and card are each instance's latest, so an instance that says less erases nothing
  another said), whether it is active (last
  seen, by its own events alone, within two and a half beats of its own cadence and at least two
  minutes; the cadence is the gap observed between its bursts of events, so a job that runs
  rarely is active between its runs; never by a write to a series, whatever its labels, and never
  by anything stamped in the future), the event map (by default machines only: an
  arrow where one machine handed something on to the other, one line with two arrowheads where
  two talk both ways, thicker with more traffic, the event types on hover; or with the event types
  as boxes; event families, the name up to its first dot, can be hidden. A hand-off is inferred
  from the envelope alone: one machine acted on a subject right after another's event about it,
  credited to an event type the receiver announced it listens for when there is one. What a
  machine announces it listens for is a declaration, not a hand-off: an event type → machine line
  is solid only when a hand-off through that type to that machine was observed on some subject in
  the era (the API's `handoffs`, by `via` and `to`), and a machine → machine arrow only when one
  from that publisher was; a listener that announced the type and received nothing through it
  keeps a faint dashed **declared listener** line, so the announcement stays visible without
  reading as traffic (two machines that publish and listen for the same type are not thereby
  talking: the workflows plugin's `offer.*` events, worker → merge gate). Dotted, a hand-off through
  a type the receiver never announced, which connects machines that announce nothing, such as a
  system brought in from outside (`static/machine-graph.js`). **A hub's protocol** is folded: a
  machine that exchanges event types both ways with at least two others (it publishes a type each
  of them listens for, and listens for a type each of them publishes; observed or announced,
  found once on the server, `web/hubs.py`, and served as the API's `hubs`, so the page and the
  Supervisor read one answer) is a hub and they are its members (the widest first: a member of a hub is no hub
  itself, so roles that pass the hub's type to each other, as the task loop's do, stay roles and
  what they hand each other stays drawn); the types between the hub and a member, and those
  the hub both publishes and listens for (its own bookkeeping), are its protocol, the plumbing every
  member shares (a workflow's planner and its roles). By default each member has one thin dotted
  line to the hub, labelled by the protocol's families, and "show the protocol" draws its types;
  no type's name is known to the core. What a hub relays is a hand-off: a subject handed to the hub
  by one machine and on by it, over its protocol, to another (the API's `relays`, which holds only
  those through a hub) is an arrow from
  the one to the other "through" the hub. A machine's line to itself is drawn only for a hand-off
  to itself, never for a type it both publishes and listens for. A hand-off arrow is labelled by
  what was handed on; and **counted
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
  (`/api/machines?era=`). On a desktop the map is as tall as the viewport less the header and its
  own bar and legend (600 to 1100 px). **A focus** (`static/focus.js`, `Orchestra.focus`): a page
  extension may offer a part of the system (a workflow) as a chip above the map; picked, the map
  draws only the machines it names and what passes among them (the hub and relay rules unchanged),
  each machine outside that hands work in or takes it out as a small grey named stub at the edge,
  and the cards are filtered the same way, with a bar ("showing <title>: n of N machines · show
  everything"). A focus is a view of the one map, never a separate one: it hides, and changes
  nothing computed; it is kept in the hash (`#focus=<title>`) and restored when offered again.
- **Instruments:** every instrument (`web/instruments.py`): a script (`[[collect]]`), a URL
  (`[[scrape]]`) or a source (`[[sources]]`), the project's and the plugins', with its target, how
  often it is read, its last write and how many points, its failures and last error, and its log;
  read from the runtime record and `orchestra.toml`, never by running or querying one; and **hung
  on**: the declared machines it is attached to, with their matches, "shared" where two machines
  select one series, "series unknown" while what they select cannot be read (§4.6).
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
crosses the frame is what the model does not explain. A part of it may be shown on its own (a
**focus**, as on the Machines page; the owner, 2026-11-02: "they deserve to be shown on their own,
but they are inherently interconnected to the whole system"): the stocks a page extension names by
their series keys, every flow from or to them, a stock outside drawn as a grey named stub just
outside the frame beside the stock inside, and the tables filtered the same way; the loops, the
hypotheses and the counts stay those of the whole model. **Subsystems** (`sd/subsystems.py`,
`docs/proposals/subsystems.md`): `/api/dynamics/model` reports `model.subsystems`, every partition
of the model by a label its stocks' series carry (never who wrote them, nor `simulated` or
`draft`; two values at least): per value its stocks, the flows inside it and the machines whose
hypotheses lie in it; the unassigned; the machines spanning groups; and the flows crossing between
each pair of groups (`count`, the simulated apart), the default first (the most flows kept inside a
group, then the fewest crossing). Derived on read, display only, saved in no version. **Boxes**
(`static/subsystem-boxes.js`; the owner, 2026-11-02: "sub 1. yes, boxes on"): the diagram's bar has
a "boxes" control beside tidy and reset, off or one of the partitions the API reports ("workflow ·
2 boxes · 0 crossing", the default first), on by the default when the page opens. Each group is a
box inside the system's frame, titled by its value, laid out by ELK as a compound node and kept
apart from the other boxes; a place or an auxiliary is in a box only when every flow it ends or
drives is inside it; the clouds keep the cloud rule; an unassigned stock sits outside every box,
inside the frame. A flow between two boxes is drawn box to box (dashed when simulated), its ends
named by their boxes, and each pair's count is written between them ("1 flow between delivery and
hotfix", its count alone where the gap is narrow). A machine whose hypotheses lie in two groups is
outside every box and said so ("in two subsystems: outside the boxes"; the owner: "a machine should
only belong to one subsystem ... if it needs to belong to 2, it is probably outside of the box").
No nesting. A box's title is a focus chip of the core's own offer: pressed, only that subsystem is
shown, its box kept, what crosses its edge a grey stub named for the box it leads to; a plugin's
focus is drawn inside the boxes it touches. The partition label's tag is left off the parts inside
their box. A change of boxes is laid out as reset lays it out; each partition keeps its own saved
layout (`dynamics.v2|boxes=<label>`); the choice is in the hash (`#boxes=<label>` or `off`, beside
`focus=`). At phone width the list has a heading per group (a chip, as the box's title), then
"between subsystems", then "outside every subsystem". The declared subsystems (§4.6) are served
beside the derived partitions, declared first when present (`with_declared`,
`sd/intended/subsystems.py`). A page extension may offer a partition
(`Orchestra.subsystems.offer({title, groups: [{title, machines, events, stocks, flows}]})`,
`static/subsystem-offers.js`, the same keys as a focus): listed after the API's partitions on both
pages ("· offered"), placed by the same rules, display only, kept in the page's memory and stored
nowhere. **The Machines map's boxes** (step 3): `/api/machines` reports `subsystems` of the same
shape over machines, event types and hand-offs (`web/machine_subsystems.py`): the model's
partitions (the declared first) carried to the machines by their flow hypotheses (never a series'
`machine` label), then one partition per announced field that groups machines (`group`,
`package`, §2); per group its machines and the event types every machine on which is in it;
`between`, the event types whose machines are in several groups; the unassigned machines and event
types; `spanning`, a machine in two groups; and per pair of groups the hand-offs crossing
(`count`: pairs of machines, `subjects`). The map's bar has the same "boxes" control, on by the
default at open; each group is a box around its machines and its event types, pulled toward its own
spot (replacing the announced groups' ring anchors while on) and kept apart from the others and
from what is not its own; a hand-off between boxes is drawn across, each pair's count written
between them ("1 hand-off between a and b · 3 subjects"); spanning and unassigned machines sit
outside every box; a box title is a focus chip; a change of boxes is laid out as reset lays it out,
each partition with its own layout (`machines.<view>|boxes=<label>`) and `#boxes=` in the hash; at
phone width the list has a heading per group, then "between subsystems", then "outside every
subsystem". The diagram on a desktop is as tall as
the viewport less the header and the legend (600 to 1100 px). A **rediscover now** button reruns discovery in the background (an observation: it
re-reads the metrics and may save a version, as the host does every 5 minutes). With eras, the
timeline's era shows the predictions of the change that began it, with their verdicts;
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
listens; near-grey, not seen in 24 hours; full colour on hover). A layout keeps its shape while
its structure does: a refresh of the same nodes and edges moves nothing, and dragging moves one
node. A new structure (the first drawing, a new version, a focus) is laid out exactly as "reset"
lays it out, from scratch and fitted (the owner, 2026-11-02: "load the page and it already be in
the position it would be after hitting Reset"; not while a node is being dragged, after it);
"tidy" lays it out again around the viewer's placements. The layout is measured
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
exchange, listed apart, and a loop has at least three machines ("communication cycles", made of
observed hand-offs only: a declared listener closes no cycle). On the
Dynamics page each loop is balancing or reinforcing and either "items circulate" (every link
material moving along a flow) or "information" (a level steering a rate). Clicking one highlights
it. Pages read only the web server's background caches
(`web/background.py`) and the host's cached discovery, never the stores on request.
- **Experiments: removed on 2026-11-01** (the page, `/experiments/<id>` and `/api/experiments*`;
  then the machines' side, §4.5). The owner's way to say what a change should do is now the declared layer's expected effects (§4.6) and `orchestra.prediction.made` (§4.3).
- **Core:** the host (with the processes it keeps running: state, restarts, command), the bus and
  the metrics store, each probed against its real backend within a time limit; explorers for the
  metrics (a catalogue of every series with the project's label, naming any series in the file
  store that lacks it, and a PromQL editor) and the events (types, volumes, sources); logs (the
  host's, Core's, the event stream and each launched process's). It imports only the bus, the metrics store and the runtime record.
  Its bus probe appends an `orchestra.core.bus_probe` event (`data` `note`, from `orchestra-host`)
  and reads it back by offset: the web server's own event type, beside the owner's
  `orchestra.intent.requested`.
  A launched process's log (the launcher's own `<state>/logs/machines/<name>.log`, for a project's
  `[[machines]]` and a plugin's `Plugin.processes` alike) is opened from its row in the host card
  (with its last exit code and restarts, and a mark when the log's last lines look like an error or
  a traceback, a cheap guess) and stays listed after the host stops. Such processes are not machines
  (AGENTS.md rule 2): a plugin's scheduler is read here, never on the Machines page. The tail is the
  last 200 lines, newest at the bottom, refreshed every few seconds, with earlier lines on request
  up to 2000; it is found by the process's name, read from the end within 1 MB, only within the
  state directory or the repository and under the page's time limit, and a missing or unreadable
  log is a note, not an error. `GET /api/core/processes/<name>/log?lines=` returns it (`lines`
  oldest first, `more`, `size`, `path`, `previous` (the rotated `.log.1`), `error`, `note`);
  `/api/core/logs/sources` and `/api/core/logs?source=` list and read every log the page shows.
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
A plugin may also ship a guide (`guide`: a markdown file in its package) written for an AI
operator that configures it for the owner; `orchestra.guides.collect` and `/api/guides` return
Orchestra's own guide (`orchestra/guide.md`: its settings, instruments, machines, the overlay)
first, then each plugin's, and Orchestra reads nothing in them (PLUGINS.md §4.7.1).
**A project's own plugins and overrides** (`orchestra/plugins.py`, `orchestra/overrides.py`;
docs/proposals/agent-first-machines.md §10.1). Orchestra's environments are not editable installs,
so a project patches in place. `.orchestra/plugins/<name>/__init__.py` (or `<name>.py`) is a plugin
with the same contract, `plugin(project)`, loaded after the installed ones by file location as
`orchestra_local.<name>`, never through `sys.path` (AGENTS.md rule 10). `.orchestra/overrides/<name>.py`
replaces one attribute of an installed package: its header names `TARGET` (`module:attribute`),
`PACKAGE` (`dist==version`, the version it was written against), `KIND` (`wrap`: `override(original)`
is called once and returns what takes the attribute's place; `replace`: `override` itself takes
it) and `ISSUE` (where the fix is asked upstream). It is applied only while that exact version is
installed (otherwise **stale**, not applied, so it never outlives the fix), wherever plugin code
runs: on every `plugins.load` and before a plugin command (`commands.run`, which is how the launcher
starts plugin processes). Applied once; a changed file is applied again from the kept original; a
removed or stale one is taken out. Each is reported in `/api/plugins` (`local`: name, file, status
applied | stale | failed | loaded, error; an override's target, package, installed version and
issue) and listed on the Core page. The limit: a copy taken with `from x import y` before the
override was applied keeps the original.

A plugin that fails, one whose name an earlier plugin took, a page at a path Orchestra serves, or
a script or stylesheet missing from its static directory is left out and reported, never fatal. A plugin is
the package's, not Orchestra's: its routes are its own, and Orchestra knows nothing of what they
mean. They are behind the same login as Orchestra's (§10.2), and a plugin adds no route outside it.

A plugin's command line is a subcommand of `orchestra` (`orchestra/commands.py`): an entry point in
the group `orchestra.commands`, named for the plugin, naming `main(argv: list[str]) -> int | None`,
which `orchestra <name> [args...]` calls with the rest of argv (`ORCHESTRA_PROG` and `sys.argv[0]`
set to `orchestra <name>`). It is apart from `orchestra.plugins` because it is given no project and
must work before one exists. One that fails to load fails alone; a name of Orchestra's own
subcommands is refused with a warning. Plugins ship no console scripts of their own.

### 10.2 Authentication

Anyone who reaches the web UI could otherwise use every page and every plugin's writes, and a
server on `127.0.0.1` is reached by more than its owner: a tunnel or proxy on the same computer
publishes it, other local users reach it, and any web page a browser visits can send it requests.
So every route asks for the project's **web token**: Orchestra's pages and `/api/*`, the static
files, any websocket, and every plugin's pages, static directory and router. `GET /health` alone
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
  cli.py  commands.py  config.py  overlay.py  config_edit.py  toml_text.py  events.py  runtime.py  host.py  launcher.py  collectors.py  plugins.py  tokens.py
  bus/       file, redis_streams, rabbitmq_streams, kafka
  endpoint/  the events endpoint (§3.1): the token and the record, validate, server, api (the model)
  collect/   instruments, a project's and the plugins' collectors and scrapes: spec, fetch,
             exposition (the Prometheus text format), round, runner
  metrics/   file, victoria, promql
  sources/   other stores, read in place: spec, preset, auth, prometheus, own, schema, views,
             transform, rank, infer, fetch, traffic (counted traffic), catalogue, report (the CLI's text)
  sd/        model, store, fit, series and live (sampling, when a series was written), balance,
             collinear and restate (a level's balance), units (a balance's terms in the level's
             unit), identify, accept and construction (the evidence a balance must show),
             stocktrust, netnull and persistence (each stock's trust), behaviour (its projection's), ends, inputs,
             drivers and driverchoice (which series may drive a flow, and which does), path, discover (conservation), attribute (machines associated with flows,
             as hypotheses), rates, strategies, simulate, rediscover, trust (each flow's
             spread and what is not trusted), provenance (where each series in a model came from), linearise and observability
             (which stocks what is measured determines), eras, prior and compare (eras, the
             previous era's model as a prior, the boundary before → after), loops, announce and
             diverge (the model's own events), predictions, verdict, judge and predictions_report
             (the intended-effect test: the record, its rules, when and from what, the CLI's text),
             reads (the model as a machine reads it, §4.5)
    equations/  §4.5: language, forms, compile, engine (the equation language and its
             stepper), views, history, heldout, forward, predicted (a prediction's draft);
             experiments, which kept these, were removed on 2026-11-01
  sdlab/     SD Lab's discovery research: ~70 strategies (needs the sd extra)
  web/       app, auth (the login, §10.2), core, core_explore, machines, instruments, traffic (counted traffic), dynamics, static/
tests/
  unit/  bus/  metrics/  sources/  acceptance/  e2e/ (slow, opt in: ORCHESTRA_E2E=1)
```
