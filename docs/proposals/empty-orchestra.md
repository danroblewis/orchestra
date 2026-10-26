# Proposal: an empty Orchestra, and the task package as its first machines

Status: proposal, 2026-10-25 (revised the same day after the user's review). Done the same day: the
old ticket tracker, loop and merge gate were removed from Orchestra on 2026-10-25; their history
stays on the bus and in model versions 1–4 of projects that used them. It supersedes §4a of
`orchestra-kernel.md` (the first slice) and settles that document's open question about an item
store: **there is none**. Read with `orchestra-kernel.md` §2a (what a machine is), which still
holds.

## 1. The goal

**There is one system, and one system dynamics model of it.** It holds everything Orchestra
observes: the development process (tasks, AI agents, reviews, merges) and the target repository's
own domain, side by side. If the target is radio software, task management topics sit right next
to radio signal analysis topics.

**That is Orchestra's main use case:** find the feedback loops between the target's domain and
the processes used to develop it. For example: do our ticket workflows and AI coding agents
increase the number of radio signals we correctly identify? Separate systems would hide exactly
those connections. Large models are sliced for viewing with metadata, filters and graph
algorithms, never split.

**An empty Orchestra** runs with no task management at all. The user opts to load the first
**package** of machines Orchestra ships: task management and AI agent workflow. It is replaceable:
a developer can use their own task machines, from their own repository or a separate one.

What follows from it:
- **Orchestra knows no tickets and no tasks.** Their counts appear only as measurements, and
  through those in the model and its analyses.
- **A machine is outside Orchestra** (`orchestra-kernel.md` §2a). The task machine is a machine.
  It may be a program or an AI agent, and it may keep its own store, which Orchestra doesn't
  provide or read.
- **Machines talk through the event bus.** Orchestra doesn't decide what events mean.

## 2. What an empty Orchestra is

| Part | What it does |
|---|---|
| **Bootstrap host** | Orchestra's own machine: hosts the drivers and starts the machines packages declare |
| **Event bus** | Topics and subscriptions with leases (§3), through an adapter for the chosen backend |
| **Topic map** | Which machines publish to and subscribe to which topics (§3) |
| **Metrics store** | The time-series database: every series any collector or machine writes |
| **Model** | The one system dynamics model, with its versions |
| **Drivers** | How a machine is engaged: process, harness (AI agents), and later SSH, container, Kubernetes Job, HTTP |
| **Connectors** | Sync with external systems (§7) |
| **Supervisor** | The machine that connects a human to the system (§6) |
| **Web UI** | Core, Machines, Dynamics. Packages may add pages of their own |

Started empty, it shows the host and the Supervisor as its machines, the Core services, and a
small model of itself. That is the state the removal step (§10, step 1) works toward.

## 3. Topics, subscriptions and the topic map

This is the pattern of AWS SNS and SQS, GCP Pub/Sub, and Kafka:

- A **topic** holds events. Publishing appends to it. Publishers never know who reads.
- A **subscription** receives a copy of every event on a topic, and keeps its own position. Each
  machine that wants events has a subscription, so publishing and processing are separate.
- **Several consumers on one subscription compete** for its entries (load is shared). **Several
  subscriptions on one topic each get every event** (fan-out).

**Topics are whatever machines choose to make.** There are no topics per package, and none are
fixed by Orchestra beyond its own (the host's and the Core probes').

### Leases, acknowledgement and dead letters

An entry delivered to a consumer is **leased** to it:

| Operation | Effect |
|---|---|
| `ack` | Processed: the entry is done |
| `extend` | Still working: push the lease's expiry out again |
| `nack` | Failed: return it now (counts as a delivery attempt) |
| (no word before expiry) | The lease expires and the entry is redelivered |

After a set number of attempts the entry moves to the subscription's **dead-letter queue**, so a
machine can react to it.

What this gives us without building it ourselves:
- **No zombies** (AGENTS.md rule 2) becomes a property of leases: a consumer that crashes stops
  extending, and its work goes back.
- **The job** in `orchestra-kernel.md` §2a is a lease: delivered, being extended (running),
  acknowledged (finished), nacked (failed), expired (unknown, then retried), dead-lettered (lost).
- **Capacity** is how many consumers run on a machine's subscription.

### Where subscriptions are implemented: in the bus adapters

**Orchestra requires a subscription- and lease-aware pub/sub system.** Each backend's adapter
provides the semantics above, natively where the backend has them:

| Backend | What the adapter uses |
|---|---|
| Redis Streams | Consumer groups, `XACK`, `XPENDING` (idle time, delivery count), `XAUTOCLAIM` for expired leases, `XCLAIM` to extend. Dead letters written by the adapter |
| RabbitMQ | Quorum queues: ack, delivery limit, dead-letter exchanges. No explicit lease extension (a consumer timeout instead), so the adapter decides how to extend |
| Kafka | Share groups (KIP-932) for per-record acknowledgement; classic consumer groups only commit offsets |
| SQS, Pub/Sub | Visibility timeout or ack deadline, extend, redrive or dead-letter topics |
| File (default) | The adapter implements leases itself, so an empty Orchestra runs with no infrastructure |

One conformance suite, extending today's `tests/bus/`, holds every adapter to the same semantics.

Replay, for a machine that wants to rebuild its own state, is the backend's job too: it reads its
topic from an offset.

### The topic map

Orchestra keeps a map of which machines publish to and subscribe to which topics. It is the
skeleton of the model's structure and the first thing the Machines page and the Supervisor show.

**The map is observed, not only declared:**
- publishers, from the envelope's `source` on every event (§4);
- subscribers, from the backend itself (Redis consumer groups, RabbitMQ queues and bindings,
  Kafka groups), read by the adapter;
- what packages declare, as the expected map; a difference between declared and observed is
  worth showing.

### An API, or the backend directly

Undecided (open question 2). Orchestra may give machines its own client API (publish, subscribe,
ack, extend, nack) so they never touch Redis, RabbitMQ or Kafka directly and stay portable. But
machines may also want to use the backend however they like. If they do, the observed topic map
and the envelope still work, as long as they keep the envelope.

## 4. Events: CloudEvents

Every event has the **CloudEvents** envelope (CNCF), which Orchestra owns because Orchestra reads
it:

| Field | What it is | Who reads it |
|---|---|---|
| `id` | Unique | Everyone; duplicate detection |
| `type` | e.g. `task.created` | Subscriptions filter on it; collectors count by it |
| `source` | The machine instance that emitted it | The topic map, collectors, attribution in the model |
| `time` | When | Everything time-based |
| `subject` | Optional: what it is about, e.g. a task id | Filters; tracing one thing through the system |
| `correlationid` | Extension: the request or delivery it belongs to | Jobs, tracing |
| `causationid` | Extension: the event that caused it | Cause chains, the depth limit on runaway loops |
| `dataschema` | Optional: where `data`'s schema is | Programs that validate |
| `data` | The payload | Only the machines that agree on it |

**The payload belongs to the machines that use it.** Orchestra passes it through unread. Two
kinds of reader:

- **An AI agent is a universal machine.** A handler can be an agent with a prompt that says what
  to do with an event; it gets the whole event, whatever its format, and works it out. No schema
  is needed.
- **A program needs to know the shape.** Packages publish their event types, optionally as JSON
  Schema, and Orchestra can validate on publish when a schema is registered. A shared schema set,
  or a registry, matters for machines that are programs and for connectors.

Readers take the fields they know and ignore the rest, so adding a field never breaks one.

The existing history (ticket events without the envelope) stays readable; a small adapter wraps
old events in the envelope when they are read.

## 5. Packages

A **package** is a bundle of machines that Orchestra adds to the one system:

- **machines**: each with its engagement (driver and its configuration), the topics it subscribes
  to and publishes to, and its capacity;
- **event types**, optionally with schemas;
- **collectors**, if its machines don't publish their own metrics;
- **pages**, optionally: views of its own in the web UI;
- **metadata**: tags (for example `package: tasks`, `domain: development`) on its machines,
  topics and series, for slicing the model and filtering views. Metadata never separates; it only
  labels.

Where packages come from:
- **Shipped with Orchestra:** the task package, the first one. Its code lives in this repository
  but outside the core's imports, and its program machines run as separate processes started by
  the host's process driver.
- **The target repository:** most machines are configured and programmed there, next to the code
  they serve (`.orchestra/`), including the domain's own machines and metrics (the radio
  software's signal classifier, for example).
- **Another repository or package.**

Enabled in `orchestra.toml`, for example `[packages] enabled = ["tasks"]`. A developer replaces
the task package by enabling their own machines instead.

## 6. The Supervisor

**Humans still talk only to the Supervisor** (AGENTS.md rule 7). The Supervisor is the machine
that connects a human to the system: an AI agent normally, though the system can run with no AI
at all.

Its role changes a lot:
- **It understands the system dynamics model:** tools to read the model and its versions, query
  the metrics store, run simulations, and explain stocks, flows and loops.
- **It knows the machines:** the topic map, what each machine publishes and subscribes to, and
  what each package declares.
- **It knows the target repository**, so it can relate the domain's metrics to the development
  process.
- **It acts only by publishing events.** Adding a task is a `task.requested` event that the task
  machine handles; talking to a Coordinator or a Pipeline Manager is publishing what those
  machines subscribe to. Those are machines of the task package or of the user, not part of
  Orchestra.

**Proposal:** the Supervisor is part of an empty Orchestra (like the bootstrap host), since it is
the only human path in. With no AI, the same machine slot is filled by a plain program that turns
the CLI and the chat box into published events, so humans still have exactly one way in.

## 7. Connectors

The sync with external systems: Jira, GitHub, Slack, company buses. A **connector** has two
directions, as in Kafka Connect:

- a **source** brings external changes into our bus as events (what we called detecting or
  sensing);
- a **sink** sends our events out (speaking), under the outbox policy.

Stateful systems (Jira, GitHub) also need **reconciling**: compare what should be with what is,
and close the gap. That is the adapter framework of `events-and-data-infrastructure.md` §3
(sense, speak, reconcile) under a new name. Our event space stays separate from the company's;
connectors are the only crossings.

## 8. Stocks are discovered, not configured

The user's direction: give the model generator a large set of metrics and let it work out how
they relate. It ignores metrics that don't seem related enough to add flows for. Nobody writes a
query per stock.

So collectors stop deciding what is a stock. Their job is to expose plenty of plain, honest
series:

- **Every event, by type and source**, which the envelope makes possible for every machine at
  once.
- **Every subscription:** backlog (a stock), entries in flight (a stock), published,
  acknowledged, failed, expired and dead-lettered (flows). Every queue is a small model already.
- **Whatever levels machines publish**, such as the task machine's count of tasks in each state,
  or the domain's own measures (signals correctly identified).

The model generator takes the whole catalogue, development and domain together, and proposes
stocks, flows and bindings. A binding is the generator's output: usually one metric, sometimes a
PromQL expression for a hidden stock it found. Manual binding stays possible, as an exception.

**A first discovery strategy: conservation.** Find a level whose rate of change matches a
combination of counters (inflow minus outflow). Series that take part in no such relationship
stay out of the model. It is cheap, it explains itself, and the subscription metrics satisfy it by
construction, which makes them a good first test. Relating the development process to domain
measures (the main use case) needs more than conservation: lagged effects between flows and
stocks across eras. The SD Lab strategies come there, and they are still unproven on real data.

## 9. The task package, version 1

**The task machine** is a small program that behaves somewhat like an agent: it has no defined
interface, it does its own thing, and it is mostly left alone. A program first, because an agent
is too slow to test with; an agent can replace it later, or sit beside it.

- It subscribes to task requests and to work outcomes.
- It keeps its own state, in its own store. Orchestra doesn't read it.
- It decides what work to ask for: it publishes `work.requested` with the task as `subject`.
- It publishes `task.moved {from, to}` and its own levels as metrics, so the model can see it.

**The worker machine** subscribes to `work.requested`:
- for tests, the process driver runs a script;
- for real work, the harness driver runs an agent with the event and a prompt.

It publishes `work.finished` with an outcome (a claim), then the entry is acknowledged. If it
crashes, the lease expires and the work is redelivered; after the attempts run out, the entry is
dead-lettered and the task machine decides what that means for the task.

The task's states, and what the claims mean, are the task machine's business. Evidence keeps its
three levels (`orchestra-kernel.md` §2a): delivered, claimed, observed.

## 10. The order of work

Each step is reviewed before the next.

1. **Remove the old task system.** About 3,400 lines: the loop, the ticket store and ticket
   states, the gate, staging, the agents' ticket tools, the `run`, `ticket`, `milestone` and
   `staging` commands, and the Tickets page. Kept: the harness layer (the agent driver), roles
   and teams, the bus, metrics, the model, and the Core, Machines and Dynamics pages. The old
   history stays on the bus; model v4 stays as a past version describing the old system.
2. **The envelope.** CloudEvents on everything published; old events wrapped when read.
3. **Subscriptions in the adapters:** leases, ack, extend, nack, dead letters, in the file and
   Redis adapters first, with a conformance suite; then RabbitMQ and Kafka. Subscription metrics.
4. **The topic map,** observed and declared, on the Machines page.
5. **The empty Orchestra runs:** the host, the process driver, the Supervisor slot, its own small
   model.
6. **Packages:** the format, loading from `orchestra.toml`, and the task package's two machines
   with the process driver.
7. **The harness driver** for agent handlers (an event plus a prompt), with cost events; the
   Supervisor's model tools.
8. **Discovery v1:** conservation over the catalogue.
9. **The task package's page.**

## 11. Invariants that change

To be stated in the commits that change them, per AGENTS.md:
- **Rule 1** (only Orchestra changes ticket state): there are no tickets in Orchestra. The task
  machine owns its tasks' states.
- **Rule 2** (no zombies): becomes a property of leases on subscriptions.
- **Rule 3** (one worktree per ticket) and **rule 4** (merging is programmatic, by the gate): move
  to the task package, which has neither yet.
- **Rule 5** (state location): Orchestra's state is the bus, the metrics store and the model.
  Machines keep their own.
- **Rule 7** (humans talk only to the Supervisor): stays, with the Supervisor as part of an empty
  Orchestra and acting only by publishing events.
- **Rule 8** (milestones): moves to the task package.
- **Rule 9** (roles as data): machines are data, declared by packages; roles configure agent
  handlers.
- **New:** there is one system and one model; packages and metadata label, they never separate.

## 12. Open questions

1. **Connector** as the name for external sync, with source and sink?
2. **An Orchestra client API for machines** (publish, subscribe, ack, extend, nack over any
   backend), or machines use the backend directly and Orchestra only observes?
3. **The Supervisor with no AI:** a plain program in the same slot (proposed), or something else?
4. **Where package machines run:** always as processes started by the host, or may they run
   elsewhere and only connect to the bus?
5. **Metrics from machines:** may machines write to the metrics store directly, or only publish
   events that collectors turn into metrics?
6. **"Package"** as the name for a bundle of machines (the user called the task system a plugin,
   "in a sense")?
