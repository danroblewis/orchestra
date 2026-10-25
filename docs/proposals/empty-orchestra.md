# Proposal: an empty Orchestra, and the task system as its first system

Status: proposal, 2026-10-25. Nothing here is built. It supersedes §4a of `orchestra-kernel.md`
(the first slice) and settles that document's open question about an item store: **there is
none**. Read with `orchestra-kernel.md` §2a (what a machine is), which still holds.

## 1. The goal

A version of Orchestra that runs with **no task system at all**: a pure, empty Orchestra. The
user opts to load their first **system**, a task management and AI agent workflow system. That
system is the first one Orchestra ships, and it is replaceable: a developer can use their own
task system, from their own repository or a separate one, instead.

What follows from it:
- **Orchestra knows no tickets and no tasks.** Their counts appear only as measurements, and
  through those in the system dynamics model and its analyses.
- **A machine is outside Orchestra** (`orchestra-kernel.md` §2a). The task machine is a machine.
  It may be a program or an AI agent, and it may keep its own store, which Orchestra doesn't
  provide or read.
- **Machines talk only through the event bus.** Orchestra delivers events and tracks leases on
  them; it doesn't decide what the events mean.

## 2. What an empty Orchestra is

| Part | What it does |
|---|---|
| **Bootstrap host** | Orchestra's own machine: runs the subscriptions, hosts the drivers, and starts the machines that systems declare |
| **Event bus** | Topics and subscriptions (§3), on a backend chosen by URL |
| **Metrics store** | The time-series database: every series any collector or machine writes |
| **Model** | The one system dynamics model, with its versions. Even an empty Orchestra has one: its own topics, subscriptions and host |
| **Drivers** | How a machine is engaged: process, harness (AI agents), and later SSH, container, Kubernetes Job, HTTP |
| **Connectors** | Sync with external systems (§6) |
| **Web UI** | Core, Machines, Dynamics. A system may add pages of its own |

Started empty, it shows the host as the only machine, the Core services, and a small model of
itself. That is the state the removal step (§9, step 1) leaves the repository in.

## 3. Topics and subscriptions

This is the pattern of AWS SNS and SQS, GCP Pub/Sub, and Kafka:

- A **topic** holds events. Publishing appends to it. Publishers never know who reads.
- A **subscription** receives a copy of every event on a topic that matches its filter, and keeps
  its own position. Each machine that wants events has a subscription, so publishing and
  processing are separate.
- **Several consumers on one subscription compete** for its entries (load is shared). **Several
  subscriptions on one topic each get every event** (fan-out).

### Leases, acknowledgement and dead letters

An entry delivered to a consumer is **leased** to it:

| Operation | Effect |
|---|---|
| `ack` | Processed: the entry is done |
| `extend` | Still working: push the lease's expiry out again |
| `nack` | Failed: return it now (counts as a delivery attempt) |
| (no word before expiry) | The lease expires and the entry is redelivered |

After a set number of attempts the entry moves to the subscription's **dead-letter queue**, and a
`delivery.dead_lettered` event says so, so a machine can react.

This replaces three things we would otherwise build:
- **No zombies** (AGENTS.md rule 2) becomes a property of leases: a consumer that crashes stops
  extending, and its work goes back.
- **The job** in `orchestra-kernel.md` §2a is a lease: delivered, being extended (running),
  acknowledged (finished), nacked (failed), expired (unknown, then retried), dead-lettered (lost).
- **Capacity** is how many consumers the host runs on a machine's subscription.

### Backends, honestly

Our `EventBus` today is an append-only log with read-by-offset (topics, in effect). Subscriptions
with per-entry leases are new. The backends differ:

| Backend | Per-entry ack and lease |
|---|---|
| Redis Streams | Native: consumer groups, `XACK`, `XPENDING` (idle time, delivery count), `XAUTOCLAIM` for expired leases, `XCLAIM` to extend. Dead letters by hand |
| RabbitMQ | Native on quorum queues: ack, delivery limit, dead-letter exchanges. No explicit lease extension (a consumer timeout instead). Streams have no per-entry ack |
| Kafka | Classic consumer groups commit offsets, not entries. Newer share groups (KIP-932) add per-record acknowledgement |
| SQS, Pub/Sub | Native: visibility timeout or ack deadline, extend, redrive or dead-letter topics |
| File (default) | None: Orchestra provides it |

**Proposal:** Orchestra implements subscriptions once, on top of any append-only topic, so the
semantics are identical on every backend and one conformance suite tests them. Its bookkeeping
(positions, leases, attempts) is itself kept in an Orchestra stream, so it survives restarts and
replays. Native implementations (Redis consumer groups, SQS) can come later behind the same
interface, tested by the same suite. Our volumes are small, so the generic version is enough for
a long time.

Replay for a machine that wants to rebuild its own state is already a property of the backend:
it reads its topic from an offset.

## 4. Events: CloudEvents

Every event has the **CloudEvents** envelope (CNCF), which Orchestra owns because Orchestra reads
it:

| Field | What it is | Who reads it |
|---|---|---|
| `id` | Unique | Everyone; duplicate detection |
| `type` | e.g. `task.created` | Subscriptions filter on it; collectors count by it |
| `source` | The machine instance that emitted it | Collectors, the Core explorer, attribution in the model |
| `time` | When | Everything time-based |
| `subject` | Optional: what it is about, e.g. a task id | Filters; tracing one thing through the system |
| `correlationid` | Extension: the request or delivery it belongs to | Jobs, tracing |
| `causationid` | Extension: the event that caused it | Cause chains, the depth limit on runaway loops |
| `dataschema` | Optional: where `data`'s schema is | Programs that validate |
| `data` | The payload | Only the machines that agree on it |

**The payload belongs to the system that defines it.** Orchestra passes it through unread. Two
kinds of reader:

- **An AI agent is a universal machine.** A handler can be an agent with a prompt that says what
  to do with an event; it gets the whole event, whatever its format, and works it out. No schema
  is needed.
- **A program needs to know the shape.** A system publishes its event types, optionally as JSON
  Schema, and Orchestra can validate on publish when a schema is registered, to catch bugs early.
  A shared schema set, or a registry, matters for systems made of programs and for connectors.

Readers take the fields they know and ignore the rest, so adding a field never breaks one.

The existing history (ticket events without the envelope) stays readable; a small adapter wraps
old events in the envelope when they are read.

## 5. Systems

A **system** is a bundle that Orchestra loads:

- **machines**: each with its engagement (driver and its configuration), its subscriptions (topic
  and filter), what it publishes, and its capacity;
- **event types**, optionally with schemas;
- **collectors**, if its machines don't publish their own metrics;
- **pages**, optionally: views of its own in the web UI.

Where systems come from:
- **Shipped with Orchestra:** the task system, the first one. Its code lives in this repository
  but outside the core package's imports, and its program machines run as separate processes
  started by the host's process driver.
- **The target repository:** most systems are configured and programmed there, next to the code
  they serve (`.orchestra/systems/`).
- **Another repository or package.**

Enabled in `orchestra.toml`, for example `[systems] enabled = ["tasks"]`. A developer replaces
the task system by enabling theirs instead.

## 6. Connectors

The sync with external systems: Jira, GitHub, Slack, company buses. A **connector** has two
directions, as in Kafka Connect:

- a **source** brings external changes into our bus as events (what we called detecting or
  sensing);
- a **sink** sends our events out (speaking), under the outbox policy.

Stateful systems (Jira, GitHub) also need **reconciling**: compare what should be with what is,
and close the gap. That is the adapter framework of `events-and-data-infrastructure.md` §3
(sense, speak, reconcile) under a new name. Our event space stays separate from the company's;
connectors are the only crossings.

## 7. Stocks are discovered, not configured

The user's direction: give the model generator a large set of metrics and let it work out how
they relate. It ignores metrics that don't seem related enough to add flows for. Nobody writes a
query per stock.

So collectors stop deciding what is a stock. Their job is to expose plenty of plain, honest
series:

- **Every event, by type and source**, which the envelope makes possible for all systems at once.
- **Every subscription, for free:** backlog (a stock), entries in flight (a stock), published,
  acknowledged, failed, expired and dead-lettered (flows). Every queue in every system is a small
  model already.
- **Whatever levels machines publish**, such as the task machine's count of tasks in each state.
  Orchestra lets machines write metrics as well as events.

The model generator takes the catalogue and proposes stocks, flows and bindings. A binding is the
generator's output: usually one metric, sometimes a PromQL expression for a hidden stock it found.
Manual binding stays possible, as an exception.

**A first discovery strategy: conservation.** Find a level whose rate of change matches a
combination of counters (inflow minus outflow). Series that take part in no such relationship
stay out of the model. It is cheap, it explains itself, and the subscription metrics satisfy it by
construction, which makes them a good first test. The SD Lab strategies come after, and they are
still unproven on real data.

## 8. The task system, version 1

**The task machine** is a small program that behaves somewhat like an agent: it has no defined
interface, it does its own thing, and it is mostly left alone. A program first, because an agent
is too slow to test with; an agent can replace it later, or sit beside it.

- It subscribes to `task.*` requests and to `work.*` outcomes.
- It keeps its own state, in its own store. Orchestra doesn't read it.
- It decides what work to ask for: it publishes `work.requested` with the task as `subject`.
- It publishes `task.moved {from, to}` and its own levels as metrics, so the model can see it.

**The worker machine** subscribes to `work.requested`:
- for tests, the process driver runs a script;
- for real work, the harness driver runs an agent with the event and a prompt.

It publishes `work.finished` with an outcome (a claim), then the driver acknowledges the entry.
If it crashes, the lease expires and the work is redelivered; after the attempts run out, the task
machine sees `delivery.dead_lettered` and decides what that means for the task.

The task's states, and what the claims mean, are the task machine's business. Evidence keeps its
three levels (`orchestra-kernel.md` §2a): delivered, claimed, observed.

## 9. The order of work

Each step is reviewed before the next.

1. **Remove the old task system.** About 3,400 lines: the loop, the ticket store and ticket
   states, the gate, staging, the agents' ticket tools, the `run`, `ticket`, `milestone` and
   `staging` commands, and the Tickets page. Kept: the harness layer (the agent driver), roles
   and teams, the bus, metrics, the model, and the Core, Machines and Dynamics pages. The old
   history stays on the bus; model v4 stays as a past version describing the old system.
2. **The envelope.** CloudEvents on everything published; old events wrapped when read.
3. **Subscriptions:** leases, ack, extend, nack, dead letters, with a conformance suite across
   backends, and the subscription metrics.
4. **The empty Orchestra runs:** the host with its subscriptions and the process driver; its own
   small model.
5. **Systems:** the bundle format, loading from `orchestra.toml`, and the task system's two
   machines with the process driver.
6. **The harness driver** for agent handlers (an event plus a prompt), with cost events.
7. **Discovery v1:** conservation over the catalogue.
8. **The task system's page.**

## 10. Invariants that change

To be stated in the commits that change them, per AGENTS.md:
- **Rule 1** (only Orchestra changes ticket state): there are no tickets in Orchestra. The task
  machine owns its tasks' states.
- **Rule 2** (no zombies): becomes a property of leases on subscriptions.
- **Rule 3** (one worktree per ticket) and **rule 4** (merging is programmatic, by the gate): move
  to the task system, which has neither yet.
- **Rule 5** (state location): Orchestra's state is the bus, the metrics store and the model.
  Machines keep their own.
- **Rule 7** (humans talk only to the Supervisor): the Supervisor belongs to a system. Humans'
  paths into an empty Orchestra need deciding (open question 4).
- **Rule 8** (milestones): moves to the task system.
- **Rule 9** (roles as data): machines are data, declared by systems; roles configure agent
  handlers.

## 11. Open questions

1. **Connector** as the name for external sync, with source and sink?
2. **Subscriptions:** implemented once by Orchestra over any topic (proposed), or only where a
   backend has them natively?
3. **One topic or several?** One topic per project with type filters is simplest. Several topics
   (per system) isolate systems from each other.
4. **How a human reaches an empty Orchestra.** Today it is the Supervisor, through `orchestra
   chat`. In an empty Orchestra, is there a built-in way to publish an event, or does every human
   path come from a system?
5. **Where a system's program machines run:** always as processes started by the host, or may a
   system run its machines elsewhere and only connect to the bus?
6. **Metrics from machines:** may machines write to the metrics store directly, or only publish
   events that collectors turn into metrics?
