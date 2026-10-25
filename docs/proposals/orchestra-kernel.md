# Proposal: Orchestra's kernel, and the task system decomposed into machines

Status: proposal, 2026-10-24, for the session of 2026-10-25. Builds on the decided principles at
the top of `system-dynamics-core.md`:
- system-dynamics-first;
- machines attributed to flows;
- equations observed, not proclaimed.

Nothing here is decided until the user agrees it.

---

## 1. The question

What are Orchestra's fundamental building blocks, such that:
1. the task system can be rebuilt from them as small machines, and
2. other factories can be built from the same blocks: the desk, alerts, reviews, status?

There are two ways to bring the task system across:

| Option | What it does | What it costs |
|---|---|---|
| **The lazy way** | Declare today's whole loop one machine, and attribute it to the flows found. | Nothing changes. Nothing can be measured per part, improved per part, or reused. |
| **The real way** | Find the minimal primitives, rebuild the task system as about eight small machines on them, and migrate one machine at a time. | Real work, but every part becomes observable, replaceable and testable as an intervention. |

This proposal takes the real way, migrated so the current loop keeps working throughout.

## 2. The kernel: twelve primitives

Each is an interface with a simple default implementation, like `TicketBackend` today. The kernel
knows nothing about tickets, code or agents in particular.

| # | Primitive | What it is | Default implementation |
|---|---|---|---|
| 1 | **Event log** (`EventBus`) | Append, subscribe, replay from an offset, per-subject ordering, consumer groups. Facts only. | Today's JSONL log; Redis or RabbitMQ Streams, Kafka, NATS in tests |
| 2 | **Clock** | Time as an event source: schedules emit events. Scheduled agents become machines triggered by clock events. | In process |
| 3 | **Item store** | Things with identity and attributes: a ticket, a PR, an alert, a build. Machines act on items; stocks count them. Today's ticket store becomes one item type. | JSON files behind the store interface |
| 4 | **Collectors** | Measurements that become stock levels and flow counts. Three kinds: **count** (items matching a predicate, from the item store); **counter** (events of a type, from the log: a flow observation); **probe** (a sampled value from a command or an outside system). | In process |
| 5 | **Metrics store** | The history of every collector's series. The current value of a stock is a query. | Files; later VictoriaMetrics or Timescale (`events-and-data-infrastructure.md`) |
| 6 | **Model store** (the factory) | Stocks, each bound to a collector series; flows; equations, each with its **origin** (fitted, discovered, or declared assumption) and confidence; eras; loops; machine attributions. | Files in git, SD Lab's format extended |
| 7 | **Inference** | History becomes topology and flow equations, per era, with confidence. The SD Lab strategies come here: the simplest (constant and proportional rates per flow) first. | A Python package |
| 8 | **Machines** | Identity, a trigger, an executor, a capacity, and a cost. Attributed to one or more flows. The trigger is an event pattern, a clock event, or a condition on a stock. A machine may only move items along flows it's attributed to, choosing among each flow's declared outputs (invariant 1, generalized). | Data, like roles and agents today |
| 9 | **Dispatcher** | Turns triggers into **jobs**: capacity per machine, **leases** on the items a job holds (no zombies: an expired lease returns the item), retries, timeouts, backpressure, and budget admission. A bus alone isn't enough; delivery is the bus's job, while capacity, leases and cost are ours. | In process; consumer groups underneath |
| 10 | **Executors** | How a job runs. **Program:** a subprocess or function. **Agent:** a harness session, resident or ephemeral; the existing `orchestra/harness` layer. **Person:** my outbox or to-do list. Every run reports outputs, cost and a transcript reference. | Existing harnesses |
| 11 | **Adapters** | External systems: sense, speak (through the outbox policy), and reconcile (stateful systems only). GitHub, Jira, Slack, company buses. | Per system, each with an e2e fake |
| 12 | **Ledger and interventions** | Every job's cost is a counter, and the budget is a stock with an admission limit. An **intervention** is a planned change: attribute a machine to a flow, or change its capacity or policy, with a **target** (the expected change in the flow's equation or a stock's behaviour), a horizon, and a kill criterion. It starts an era. The verdict comes from re-fitting, not from the machine's report. | Records in the model store |

**Should running AI agents be in the kernel?** As an *executor kind*, yes: the universal machine is
the point of the system. The kernel defines the `Executor` interface; the agent executor is the
existing harness layer. The kernel never depends on agents in particular. A factory made only of
programs is a valid factory.

**A queue, or a worker?** Both, layered. The event log delivers, with consumer groups giving
competing consumers. The dispatcher decides who may take what:
- which machine has capacity;
- which item is under lease;
- whether the budget admits the job.

That's the difference between a queue and a factory floor.

**Naming.** The user asked for a word for "experiment or change". The proposal is
**intervention**, which is the system dynamics and causal-inference term. A time-boxed
intervention meant to be reverted could be called a **trial**.

## 2a. What a machine is (revised 2026-10-25)

The user's framing, adopted here:
- **A machine is outside both Orchestra and the model.** It may be:
  - one of our scripts;
  - a Kubernetes job;
  - a shell command on another host;
  - a container;
  - an RPC endpoint;
  - a team of people;
  - a physical device.
- **Orchestra can't instantiate most machines, and can't guarantee what any of them does.**
- **A machine may not respond at all.**
- **We know a machine's outcomes only through the metrics we collect.**

So Orchestra holds a **model of the machine**, never the machine.

### Perspectives considered

| Perspective | What it says about a machine | Verdict |
|---|---|---|
| **Black box, defined by its boundary** (cybernetics: Ashby; also system dynamics) | Know a machine by what it takes in, which flows it affects, and how it's observed. Its inside is unknown. | **The core.** Matches "outcomes only through metrics". |
| **State machine** | The machine has a lifecycle: idle, busy, down. | Wrong level for the machine. Right for a **job**: a request's lifecycle as the driver sees it. A machine's availability is a measured stock, not a state we hold. |
| **Actor model** (Erlang, Akka) | A machine is a mailbox: send it messages. | Fits machines that read our bus; can't cover a device, a team, or another team's cron. Reading our queue is one way to engage a machine, not the definition of one. |
| **Controller / reconcile** (Kubernetes operators) | Write desired state; controllers converge; observe status. | **Right for engaging machines.** A request is a declared intent, and a reconciler watches what actually happened. No pretence that a call succeeded. |
| **Digital twin** | Keep a model of the machine fitted to its observations. | **This is our machine record:** capacity, service rate and effect on flows, fitted, not declared. |
| **Workflow engine** (Temporal) | Activities with retries and an illusion of exactly-once. | Not ours. We observe outcomes instead of guaranteeing them. Usable as one way to drive a machine. |

### The definition: five separate things

1. **Machine** (a record, our model of an external thing). Its fields:
   - **identity** (id, name, owner, description);
   - **boundary:** the items or requests it can take, and the flows it's **attributed** to, as
     hypotheses;
   - **observability:** the collectors that evidence its activity and its effects;
   - **fitted characteristics:** capacity, service rate, cost, and effect on its flows, each with
     an origin and a confidence;
   - **engagement:** zero or more ways to send it a request.

   **A machine with no engagement is still a machine**: the company's reviewers, SAIL, another
   team's cron. It's observed and attributed, never invoked. "Environment" is just machines we
   don't control.
2. **Request** (a work order): an event on the bus that **asks** a machine to act, with a
   correlation id. Every invocation, of every machine, is a request. A request is a declared
   intent; it guarantees nothing.
3. **Driver:** code in Orchestra that delivers a request to a machine through some medium, then
   watches its status. Examples:
   - agent harnesses (Pi, Claude Code, Codex);
   - local process; SSH command; container; Kubernetes Job;
   - HTTP or RPC with polling;
   - a Slack or Jira message to people;
   - the outbox (for me);
   - a device API;
   - "the machine reads our bus itself": the trivial driver.

   Interface: `submit(request) → handle`, `watch(handle) → status`, `cancel(handle)`, and its
   capabilities.
4. **Job:** a request's lifecycle as its driver sees it: `submitted`, `running`, `finished`,
   `failed`, **`unknown`**, `lost`. `unknown` is a normal, expected state. Jobs carry leases on the
   items they hold, and expiry returns the items. That's how "no zombies" survives remote and
   silent machines.
5. **Evidence**, at three levels, never mixed:
   - **delivered:** the driver handed it over;
   - **claimed:** the machine or agent reported something, such as `report_ticket`. A claim is an
     observation of low trust;
   - **observed:** a collector measured the effect.

   **Only observed evidence moves flows, or counts toward fitting and interventions.** Correlation
   ids let collectors link an observed outcome to a request where possible, such as a PR naming its
   ticket. Otherwise attribution is statistical, by era.

### Engagement modes apply to every machine, not just agents

The three agent kinds are **engagement modes**. They're properties of how we engage a machine,
not of the machine:

| Mode | Agents | Other machines |
|---|---|---|
| **Continuous** | A resident session receiving requests | A long-running deployment consuming a stream; a daemon; a team's channel |
| **Ad hoc** | A fresh session per request, optionally re-enterable | `docker run`, a Kubernetes Job, an RPC call, an SSH command |
| **Scheduled** | Clock-triggered requests | The clock primitive emits requests, through whichever driver the machine uses |

**An AI agent is one kind of machine:** the universal one, driven by the harness driver. Everything
true of agents, apart from harness details, is true of machines.

### The bootstrap machine

One machine is registered by Orchestra itself at startup, and tracked by Orchestra: **Orchestra's
own host.** It runs the dispatcher and **hosts the drivers.** Every other machine is engaged
through it, or merely observed.

- **It's a machine like any other.**
  - Its flows: requests → delivered, and delivered → finished, failed or unknown.
  - Its collectors: dispatch rate, latency, driver failures, unknown jobs.
  - Its effect is fitted like everyone else's. Orchestra models itself.
- **It decides nothing about outcomes.** It delivers requests and records job status and claims.
  Collectors and the model decide what happened. That keeps it from becoming the old `loop.py`
  under a new name.
- **Its first drivers:** agent harnesses (exists), local process (exists in effect), SSH command,
  container, Kubernetes Job, HTTP. Each driver gets an e2e fake, as harnesses do now.
- **More hosts later.** A second Orchestra host on another computer is another bootstrap-like
  machine that registers itself, hosts its own drivers, and holds leases. That's the multi-machine
  path.

### What this changes in §2

- Primitives 8–10 (machines, dispatcher, executors) become **machine records, requests, drivers,
  jobs, and the bootstrap host**.
- The dispatcher is part of the bootstrap host.
- "Executor kinds" are drivers.
- The machine table in §3 stays valid. Each row now names its **driver** (agent harness, or local
  process), its **engagement mode**, and its **collectors**.
- New rows are possible with no kernel change: "company reviewers" (no driver, observed only); a
  Kubernetes test runner (Kubernetes Job driver).

## 3. The task system, decomposed

**Items:** ticket, worktree, build, gate run.

**Stocks:** counts of tickets by state: open, in progress, ready for review, tested, in review,
rejected, approved, merging, done, blocked, cancelled. These are counts over the item store. The
"active" states are tickets under a lease.

| Machine | Executor | Attributed to the flows | Trigger |
|---|---|---|---|
| **Worker** | agent | open → ready for review or blocked; rejected → ready for review | A ticket in open or rejected, with worker capacity |
| **Test runner** | program | ready for review → tested | A ticket enters ready for review |
| **Reviewer** | agent | tested → approved or rejected | A ticket enters tested, with reviewer capacity |
| **Batcher** | program | approved → merging (takes a batch) | Approvals waiting, a batch is full, or the oldest is past its wait |
| **Gate** | program | merging → done, rejected, or approved | A batch is formed |
| **Stager** | program | none: acts on builds | A build lands |
| **Worktree keeper** | program | none: acts on worktrees | A ticket is first taken, or becomes terminal |
| **Recovery** | program | in progress → open; in review → ready for review | A lease expires, or startup |
| **Coordinator** | agent | outside → open (create, split); open → cancelled; blocked → open | Ticket created, blocked, rejection threshold |
| **Pipeline manager** | agent | outside → open (fix tickets) | Gate base broken, flaky tests, staging failed |
| **Supervisor** | agent | outside → open | A message from me |

What this buys:
- Testing becomes its own flow. Today it's buried inside the review step; split out, it's
  measurable.
- Each machine can be replaced or measured on its own. For example:
  - a reviewer with a cheaper model, as an intervention;
  - a program-only pre-check;
  - two worker slots instead of one.
- The same primitives build the desk's factories with no new kernel code: alerts, reviews given,
  status, production commands.

## 4. Migration, in order: the loop keeps working throughout

**Progress (2026-10-25, branch `sd-kernel`):** steps 1–4 are built and tested.

| Step | Commit | What |
|---|---|---|
| 1 | `9d8e8cc` | `EventBus` with file, Redis Streams, RabbitMQ Streams and Kafka backends; 45/45 conformance tests across all four |
| 2 | `e14ed25` | Metrics store (file, VictoriaMetrics); ticket collector with anchoring; `orchestra metrics` |
| 3–4 | `99cef93` | `orchestra.sd`: model, model store, Orchestra's factory declared, Poisson fitter; `orchestra sd` |

The engagement side of machines (requests, drivers, jobs, the dispatcher) is not built yet.

1. **`EventBus`, with backends and the shared e2e suite** (`events-and-data-infrastructure.md` §6).
2. **Collectors and the metrics store.**
   - Counts of tickets by state, counters per transition event, and probes.
   - Backfill from the existing `events.jsonl`, so Orchestra's own history becomes series.
3. **The model store.** Declare Orchestra's factory: stocks bound to series, flows, and today's
   loop steps as machines with their attributions. **Descriptive only.**
4. **Inference v1:** fit constant and proportional equations per flow from Orchestra's own history.
   Report confidence honestly, because this data is sparse.
5. **The dispatcher and executors as primitives.**
   - Port **one machine at a time** out of `loop.py`, each behind the e2e tests that run against
     the fakes: the stager or test runner first, then the reviewer, the worker, and the gate last.
   - `loop.py` shrinks to nothing.
6. **The first intervention on Orchestra itself.** For example, reviewer slots from 1 to 2, with a
   target written down beforehand and a verdict from re-fitting.

## 4a. First slice: a basic task and work system on the kernel (proposed 2026-10-25)

What exists so far *observes* the old loop: bus, collectors, metrics, model, fitter. Nothing yet
*does* work through the new primitives. The first slice is the smallest task and work system built
only from them, running beside the old loop and visible in the web UI.

**Items and stocks.**
- A task is an **item**: id, kind, attributes, and which stock it's in.
- A **stock is a bin of items**: its level is the count, written by the collector.
- Items are the bookkeeping; stocks are the measurement of it.

**Flows are the allowed moves.**
- The model declares which moves exist.
- Every move is one event, `item_moved {item, flow, from, to, machine, job, evidence}`. The
  collector generalises from `ticket_transition` to it.
- Nothing moves an item along an undeclared flow (invariant 1, generalised).

**Machines engaged through the dispatcher, in the bootstrap host.** Each tick:
1. For each machine with an engagement, free capacity, and budget, apply its **take rule**:
   which stocks it takes from, in what order.
2. Lease the item.
3. Put a **request** on the bus with a correlation id.
4. Hand it to the machine's **driver**, which creates a **job**.

When the job ends, its **claim** names an output of the flow. The dispatcher moves the item there,
recorded with `evidence: claimed`.
- A lease that expires (job `unknown`, `lost`, or past its timeout) returns the item along a
  recovery flow. That is "no zombies" without a recovery machine.
- **Claims move items for bookkeeping; observed evidence judges them.** A later verifier machine
  (tests, review, a collector) records `evidence: observed`. Fitting and interventions weigh
  evidence; the dispatcher doesn't.

**The smallest factory to prove it:**
- **Stocks:** backlog → doing → done, or failed; failed → backlog (retry).
- **Machines:** the dispatcher's take moves backlog → doing; a worker moves doing → done or failed.
- **Two drivers:**
  - `process`: a shell command, so the mechanics are proven without spending tokens;
  - `harness`: an agent through the existing harness layer. The local Pi model costs nothing.
- **Cost events per job** (tokens, dollars where known), so spend becomes a measured flow at last.

**In the web UI: a Factory page.**
- Stocks with live levels.
- Flows with fitted rates and their origin.
- Machines with running jobs and their state, including `unknown`.
- The items in each stock.

This is where the replacement becomes visible as it's built.

**Then grow it toward today's task system, one machine at a time:** worktree keeper, test runner,
reviewer, batcher, gate. Each is a machine with a driver and a take rule, until the old loop has
nothing left to do.

## 5. Invariants that change

To be stated in the commits that change them, per AGENTS.md:
- **Rule 1** ("only Orchestra changes ticket state"): only the dispatcher applies a machine's
  output, and only along flows the machine is attributed to.
- **Rule 2** (no zombies): leases on items, held by jobs. Expiry returns the item, which also
  covers remote machines.
- **Rule 5** (state location): state lives behind the item, event, metrics and model store
  interfaces.
- **Rule 9** (roles as data): machines are data too. Roles become how agent executors are
  configured.
- **New:** an equation's origin is always recorded. A declared equation is labelled an
  assumption until it's fitted.

## 6. Open questions for the user

1. The names: collector, machine, request, driver, job, bootstrap host, item, intervention, factory.
   Keep, or change?
2a. Is the bootstrap host the right first machine? Its first six drivers, in what order?
2b. The job status vocabulary, especially `unknown` and `lost`, and lease lengths per driver.
2. Does an item store belong in the kernel, or are items only ever external (GitHub, Jira), with
   stocks purely measured? Proposal: in the kernel, because machines need identity and leases.
3. Where inference lives: `orchestra.sd` inside this package, or a dependency built from the SD Lab
   strategies (AGENTS.md rule 10).
4. Which machine to port first.
5. How much of the coordinator and pipeline manager stays agent work, or becomes programs plus a
   decision model (the subscriber ladder).
