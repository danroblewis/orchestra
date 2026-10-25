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

1. The names: collector, machine, executor, job, item, intervention, factory. Keep, or change?
2. Does an item store belong in the kernel, or are items only ever external (GitHub, Jira), with
   stocks purely measured? Proposal: in the kernel, because machines need identity and leases.
3. Where inference lives: `orchestra.sd` inside this package, or a dependency built from the SD Lab
   strategies (AGENTS.md rule 10).
4. Which machine to port first.
5. How much of the coordinator and pipeline manager stays agent work, or becomes programs plus a
   decision model (the subscriber ladder).
