# Proposal: events, external systems, and data infrastructure

Status: draft, 2026-10-24, from a design conversation. Nothing built. Decisions marked
**Decided** were agreed in that conversation; the rest are recommendations.

Related:
- `system-dynamics-core.md` (stocks, flows, machines);
- `orchestra-for-the-whole-job.md` (sources, outbox, desk);
- `corporate-workflow.md` (GitHub reconciler);
- `../analysis-method.md`.

---

## 1. Orchestra's event system, in system dynamics terms

Orchestra has three things that matter here:
- **programmatic machines** that emit events, such as ticket transitions;
- **agents** bound to events through `wake_on` triggers;
- **probes,** which turn conditions into events.

Agents come in three kinds:
- **resident:** continuous sessions, pinged in place and auto-compacted;
- **ad hoc:** a fresh, isolated session per event, sometimes kept alive or re-enterable;
- **scheduled:** woken by the clock, with a resident or an ephemeral session (spec §4.3).

**Every event type is a flow:** its rate per hour is a flow rate. **Every subscriber's unhandled
events form a stock:** its queue depth. Volume doesn't decide whether events belong in a model.
- **Agent wake-ups are sparse but expensive.** Each is a flow with a co-flow on the budget, and
  cost × rate is often the most important number in the model.
- **Program events are dense.** They're the measurement backbone, the data that rates are fitted
  from.

| Agent kind | As a machine |
|---|---|
| Resident | A machine with a memory stock. Context fills per event; compaction drains it; quality is an effect of how full it is (context rot). |
| Ad hoc | A machine with no memory stock. Anything it should remember must live in a store or a re-enterable session. |
| Scheduled | Polling: a constant-rate flow driven by the clock, not by state. Choosing polling or events trades delay against cost. |

**The subscriber ladder.** This is the automation ladder from the work charter, applied to
subscriptions. Each subscription is handled by:
1. a **program filter**, which drops what doesn't matter;
2. a **cheap decision model** (rule-based or learned), which handles the routine cases;
3. an **agent**, only for what's left.

The model shows which subscriptions to demote: wake rate × cost per wake, against what the agent
adds.

## 2. Our event space, and company buses

**Decided:**
- Orchestra keeps its own event log as the source of truth.
- If a company event bus is ever used, our event and topic space stays **ontologically separate**
  from the business's core infrastructure. Our domain model is never defined by their topology.

Why the log stays ours:
- **Volume is tiny.**
- **The guarantees are Orchestra's own:**
  - ordering per subject;
  - replay after a crash;
  - the depth limit on chains of events causing events;
  - per-agent emission limits;
  - only Orchestra changes ticket state (invariant 1).

  A shared bus wouldn't enforce any of them.
- **A shared bus would let their names and schemas define our domain.**

Company buses connect through **bridges at the boundary**: an anti-corruption layer.
- **Inbound:** subscribe or poll their topics; translate into our event types; tag each event with
  its source and data class.
- **Outbound:** publish selected events into *their* topics and schema, through the outbox policy,
  because publishing on a company bus is speaking for me.
- **One mapping table** between their topics and our event types, and nothing beyond it.

## 3. Jira and event buses: one adapter framework

Jira works as an event bus:
- issue type + project + labels make a topic;
- description and comments are the message;
- filters (Jira's "queues") are subscriptions.

But Jira is also a **state store**: a state machine whose current state people read and edit. That
difference decides how each is integrated:

| | Event bus | Jira (also GitHub) |
|---|---|---|
| What it holds | A stream of events | Current state, plus the events that changed it |
| Integration | Translate events in and out | Translate events **and reconcile state** |
| The hard part | Naming and schemas | Who owns each field, conflicting edits, idempotency |

**One abstraction for both: an external system adapter** with three capabilities:
- **Sense:** subscribe or poll, producing events and state snapshots.
- **Speak or act:** write or publish, under the outbox policy.
- **Reconcile** (stateful systems only): compare desired state with actual, and close the gap.

Event buses need sense and speak. Jira and GitHub need all three; the GitHub PR reconciler in
`corporate-workflow.md` is the first instance. In system dynamics terms, these systems are
environment stocks, adapters are the flows that cross the boundary, and the rule stands: keep the
crossings few, and declare each one.

## 4. Where data lives

| Data | What it is | Where |
|---|---|---|
| **Events** | Immutable facts: transitions, firings, costs, normalized external events | An append-only, replayable log: the flow log |
| **Levels and rates over time** | Derived series for fitting, charts, discovery, checks | A time-series database |
| **Raw external snapshots** | What a sensor got from GitHub, Jira, Slack | Files or an object store, so any fit can be re-derived. Repeatable analysis needs the exact data window. |
| **Models, variants, analysis records** | Designed artifacts | Git |

**Stocks come from two directions, which check each other:**
- **Integrated from the event log:** start value + inflows − outflows.
- **Sampled directly by probes:** open PRs, review queue length.

Integration drifts when an event is missed. The software-foundry proposal measured work in
progress at −49 when the truth was 3. Sampled levels anchor the integrated ones, and the gap is a
data-quality signal.

**Don't pull external data constantly.** Sensors:
- poll on a schedule, within rate limits;
- backfill history once;
- then fetch only what's new.

The time-series database is the record. Models fit from it and never call GitHub or Jira
directly.

## 5. Which systems, and when

**Ruled out:**

| System | Why |
|---|---|
| Kafka | Operations far beyond the need (a JVM cluster for far under 100 events a second) |
| RabbitMQ (classic queues) | Messages are consumed and gone; we need replay. RabbitMQ **Streams** (3.9+) do replay, and are a fair backend. |
| Redis Streams | Weaker durability (fine as a cache) |
| Prometheus alone | Built for scraping; awkward backfill and out-of-order writes, short retention |

**Option A: Postgres + TimescaleDB.**
- An append-only events table, with LISTEN/NOTIFY for push.
- Hypertables for levels and rates.
- Later, the ticket and runtime stores too.

One server reachable from every machine, transactional, fewest moving parts.

**Option B (recommended): NATS JetStream + VictoriaMetrics.**
- **NATS:** a single binary. Durable streams with replay, hierarchical subjects (an `orchestra.*`
  namespace, separate from anything of the company's), and built-in key-value and object stores.
- **VictoriaMetrics:** a single binary. PromQL, backfill and out-of-order writes, long retention.
- **Why B:** SD Lab already has PromQL sensors (`sdlab/promql.py`) and Grafana works with it. Most
  of all, the same query language covers my own Orchestra data and the company's production
  metrics, which the target-system models in `system-dynamics-core.md` need.

Choose A for a single service and SQL.

**Path, without a rewrite:**
1. **Now:** two interfaces with file-based default implementations. Cheap, and no behaviour
   change.
   - `EventLog`: append, subscribe, replay from a point.
   - `MetricsStore`: write points, query a range.
2. **Separate the processes:** loop, harnesses, sensors, bus, time-series database. Moving one to
   another machine then becomes configuration. Tailscale is enough networking.
3. **Switch backends at the first trigger:**
   - Orchestra on a second machine (likely soon; it has been done before);
   - history beyond what files hold comfortably;
   - someone else needs to read the series (a Grafana dashboard for managers).

**Invariant changes this needs:**
- **AGENTS.md rule 5,** "State lives in `~/.orchestrator/<key>/`; only `orchestra/store/` touches
  it", becomes: state lives behind the store, `EventLog` and `MetricsStore` interfaces, whatever
  their backend.
- **Rule 2 (no zombies)** needs a lease or heartbeat once agents run on other machines, because a
  dead remote process can't move its own ticket back.

## 6. Decided direction for the event bus (2026-10-24)

- **A real `EventBus` interface** in Orchestra: append or publish, subscribe, replay from an
  offset, per-subject ordering, consumer groups.
  - A local implementation is the default (the current file log).
  - The loop, probes and agents' `wake_on` go through the interface only.
- **End-to-end acceptance tests against real backends:** Redis (Streams) and RabbitMQ (Streams),
  maybe Kafka.
  - The same suite runs against every backend, as the loop e2e tests run against every harness
    fake.
  - Backends run in containers.
  - The tests are opt-in, by environment variable, like the existing acceptance tests: never
    required for the default suite.
  - NATS JetStream stays a candidate, since §5 recommends it.
- **The interface must hold what Orchestra needs from any backend:**
  - replay for crash recovery and for re-deriving flows;
  - the cause-chain depth limit;
  - emission rate limits;
  - our own subject namespace (`orchestra.*`), kept separate from company topics.
- **The event log is the observation source for flows.** Every event that moves something between
  stocks is a flow observation, so the bus is where system dynamics data comes from.

## 7. Candidate first version of the system dynamics core (not decided)

A way to start without breaking what runs. Each step keeps the current loop working.

1. **`EventBus` interface and backends** (§6).
2. **Model types and a model store:** stocks, flows, machines, attributions, eras.
   - Declare Orchestra's own factory as a model: ticket states as stocks, transitions as flows,
     the worker, reviewer and gate as machines attributed to their flows.
   - Data only. The loop still runs as today.
3. **An observer:**
   - derives flow counts per interval, and stock levels, from the event log;
   - samples levels directly where it can;
   - writes both to a `MetricsStore` (files first).
4. **A first fitter:** the simplest strategies brought over from SD Lab (constant and
   proportional rates per flow, per era), to fit Orchestra's own flows from its own history.
5. **Validation of machine intent:** a machine's declared expected effect against the fitted
   equations across its era.
6. **Only then,** let the model drive behaviour: the loop as one set of machines on flows (the
   loop-as-event-bus topic in `teams-and-roles.md`).

## 8. Open questions

1. NATS + VictoriaMetrics, or Postgres + TimescaleDB? Recommendation B, not yet decided.
2. Which machine hosts the bus and the time-series database, and what are the retention and backup
   rules?
3. The decision model for demoted subscriptions: rule tables first, or a learned model? What
   "Jev" refers to in the conversation needs confirming.
4. Data classes on events (FedRAMP): which may cross which bridge, and which may reach which model.
5. SD Lab packaging (`orchestra.sd` or a dependency) interacts with where sensors and the
   time-series code live.
