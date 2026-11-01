# Rules for working on Orchestra

Read `SPEC.md` first. It is the design. This file is the short list of rules
that must not be broken without updating the spec and saying so in the commit.

## Invariants

These replaced the old task system's invariants on 2026-10-25, when the ticket
tracker, loop and merge gate were removed (`docs/proposals/empty-orchestra.md`).
Rules 2, 3, 4, 5, 6, 7 and 9 were amended on 2026-11-01 for the intended model
(`docs/proposals/intended-model.md` §8).

1. **Orchestra knows no tickets and no tasks, and runs no AI.** It has an
   event bus, a metrics store, a system dynamics model, a bootstrap host (with
   a launcher that keeps declared commands running) and the interfaces
   machines use (the bus, the metrics store, plugins). What
   machines do and what their events mean is theirs. An AI agent is a
   universal machine like any other: its harnesses live with the machines
   that run it (the agents: `~/orchestra-agents`), never here. Never add
   a domain concept (ticket, task, build, agent) to the core.
2. **Machines are outside Orchestra, and known by their events.** A machine
   does actual work: a program, an AI agent (a universal machine), a person.
   The discovered model names no machine in a stock, flow or equation; it lists the machines that
   hold a flow's hypotheses (rule 6). The declared layer stored beside it (the intended model)
   names machines, never in a stock, flow or equation. A machine's relationship to the
   model's flows is not known: it may influence no flow, one or several, and
   several machines may contribute to one flow. Relating actual work to the
   model, by inference, is what Orchestra is for. Orchestra knows a machine
   exists because it shows up on the bus: its CloudEvents `source`
   (`<machine>/<instance>` for one of several instances), the events it
   publishes and listens for, and how it says it is engaged (continuous,
   scheduled, ad hoc); or the producer or consumer a series definition
   attributes counted traffic to on another system's bus
   (`orchestra/sources/traffic.py`): known by counts, never by events. A
   machine does not produce metrics, and a series never makes a machine
   (rule 7). The Machines page and the model read what is observed, never a
   machine's description of itself. The exceptions are what an instance
   announces in `orchestra.machine.started`: its mode, what it listens for,
   its kind (program, agent, person, service), where its log is, which
   package it belongs to, and the name and group (or team) to show it by
   (SPEC §2; the rest of the announcement is passed on to that package's
   card, unread), and the machines a plugin declares
   (`Plugin.machines`): placeholders that only fill in machines not seen yet,
   never override what is observed, and say nothing about flows. The owner may declare machines
   (the intended model, `orchestra/sd/intended/`), through a plugin or by confirming a proposal.
   A declaration persists until retracted. A declared machine is shown as declared, and as heard
   only once its `source` is on the bus; its declared envelope and `spec` are shown as the
   declaration, apart from what is observed, and never override what is observed, never make a
   machine exist in the observed layer, and say nothing about flows.
   Instruments may be attached to a declared machine
   (`docs/proposals/instruments-on-machines.md`): declared provenance saying
   which series measure it and which label counts its replicas. Being
   measured never makes a machine seen or active. Measured instances are
   counts of a label's values: never instances in the observed layer, never a
   `source`, never active. A log is
   read only within the project's repository or state directory
   (`web/machine_logs.py`). The launcher (`orchestra/launcher.py`) starts the
   commands a project (`[[machines]]` in `orchestra.toml`) or a plugin
   (`Plugin.processes`) declares and knows them only as processes (a name, a
   command, a pid, an exit code): a process is a machine only by what it
   publishes. **The provider is never the machine:** a plugin's
   infrastructure processes (schedulers, hosts, runtimes, relays) are never
   machines. They never announce themselves, never publish under their own
   name and never write metrics directly (the plugin declares an instrument,
   `Plugin.collectors`, that reads them); they act on the bus only as the
   machines they implement, each of which announces what it listens for.
   (The task system's scheduler, decision D17; the agents' host,
   2026-10-27.)
3. **Every event carries the CloudEvents envelope.** `orchestra.events`
   writes it; Orchestra reads the envelope and never the `data` payload, which
   belongs to the machines that use it. The exceptions are Orchestra's own
   event types that machines publish to it: `orchestra.machine.started` (rule
   2's announcement), `orchestra.prediction.made` (a machine's prediction of
   a change's effect, which Orchestra records and judges; the owner,
   2026-10-27) and `orchestra.intent.requested` (the owner's request from a
   page, published as `owner`, rule 9). Counted traffic is never turned into events: no envelope is made
   from a count.
4. **There is one system and one model.** Never split topics, models or views
   per package or per domain. Packages and metadata label; they never
   separate. The model changes by new versions; past versions stay readable.
   The model's versions are of two kinds: discovered (`vN`: stocks, flows,
   equations) and declared (`dN`: the intended model); a change to one never
   makes a version of the other, and a comparison names one of each.
5. **State lives in `~/.orchestrator/<key>/`, except the event log and the
   metrics, which live in the configured bus and metrics store, and what every
   project on the machine shares about another store it reads (its request
   rate and daily count, `~/.orchestrator/stores/<store>/`, `sources/limits.py`).** Events go
   through `orchestra.events.Events` over an `orchestra.bus.EventBus`; metrics
   through `orchestra.metrics.MetricsStore`; the model through
   `orchestra.sd.store.ModelStore`; the intended model through
   `ModelStore.intended()` (`project.intended`), in `<state>/model/intended/`,
   written only by the host and the web server; nothing else opens anything
   under it; process records through
   `orchestra.runtime`. Nothing else touches a backend or those files
   directly. Orchestra's streams are named `orchestra.<key>.events` and never
   share a topic with anyone else's. Other stores (`[[sources]]`) are read
   only through `orchestra.sources`, never written; what is kept of them
   (each source's inferred definitions) lives in the state directory.
6. **Every equation records its origin** (fitted, discovered, or declared).
   A declared equation is an assumption until it is fitted. A machine is
   associated with a flow only as a hypothesis, inferred with its evidence
   and confidence (`orchestra/sd/attribute.py`: its events on the bus matching
   the flow's counter); several machines may be hypotheses for one flow.
   Nothing declares the association, not configuration and not a plugin, and
   it never changes a flow's equation or the model's stocks and flows.
   A machine's draft expected effect is an unpublished prediction, not an
   association; the expected flows drawn from it carry no machine.
7. **Stocks are discovered, not configured; measurements are not machines.**
   A stock, effect or flow may be declared, and a discovered one marked
   expected (the intended model): an expectation drawn beside the discovered
   model, never a part of it. A declaration binds no series, is not (yet)
   handed to discovery, changes no equation, and is matched to what discovery
   finds only by the `link` op; marks derived from labels (candidates) are
   display only. Metrics are objective measurements of the running system, kept apart from
   the machines whose work we hope influences them, so they can test what we
   believe. Instruments (`[[collect]]`, `[[scrape]]`, `[[sources]]`, a
   plugin's `Plugin.collectors`: collectors, scrapes, sources, detectors)
   measure and never act; they are not machines, are not announced on the
   bus, and are shown on the Instruments page. A collected point is labelled
   `instrument=<name>` (provenance), and the target's own labels are kept,
   `machine` included. A machine's existence is never inferred from who wrote
   a series, and a flow is never associated with a machine from a
   measurement's label. Attaching an instrument to a declared machine is
   declared provenance, like the `instrument=<name>` label: it is kept in the
   declared layer, never written on a point, never read by discovery or by
   `sd/attribute.py`, and never binds a series to a stock, a flow or a
   machine's flow. An attachment never makes a machine; it only gives series
   to a machine the owner declared. The metrics store is filled by instruments directly;
   `orchestra_events_total`, Orchestra's count of the bus, is the one series
   derived from the event log, and is secondary. Instruments expose plain
   series named for what they measure; the model generator decides what is a
   stock or a flow. Manual bindings are the exception. A hidden stock or a
   flow no machine is associated with is a question about the system, not an
   answer.
8. **The core stays up.** `web/core.py` and `web/core_explore.py` import only
   the bus, the metrics store and the runtime record, and probe each under a
   time limit, so the Core page works when the model or every machine is
   broken.
9. **Humans talk only to the Supervisor.** The web UI and CLI are read-only
   for humans, except for observations: rediscovering the model (the Dynamics
   page's button, `orchestra sd discover`) re-reads the metrics and may save a
   model version, and changes no machine; and a closed list of intended-model
   page controls that carry no values: `expect`, `unexpect`, `ignore`, and
   `confirm` and `discard` on a stock, effect or flow. Each records a
   declaration with its provenance and changes no machine, no configuration
   and no discovered version. A machine's `confirm`, `discard` and kind switch
   are requests: published as `orchestra.intent.requested` from `owner`,
   changing nothing until the Supervisor acts. Any human path that changes the
   system belongs to a plugin (the Supervisor in `~/orchestra-agents`; the
   task plugin's operator controls, `docs/roadmap/decisions.md` D1), never to
   this repository.
10. **One package, no path hacks.** Everything importable is under
    `orchestra/`. No `sys.path` manipulation. `orchestra/sdlab` is SD Lab's
    discovery research brought in as it was benchmarked (imports rewritten,
    nothing else; see its README): change it only deliberately, say so in the
    commit, and keep it out of lint. Machines and test systems live in
    their own repositories (the bakery: `~/orchestra-bakery`) and use Orchestra
    as a library, like any other program would; nothing in this repository is
    an example system. A plugin reads and changes configuration only through
    Orchestra's objects (`project.config`, `project.reload_config()`,
    `project.config_stamp()`, `project.config_edit`), never by opening, parsing
    or editing `orchestra.toml` or the overlay itself: otherwise a setting in
    the private overlay never reaches it, and its changes skip the checks.
    A project's own plugins and overrides are loaded by file from
    `.orchestra/plugins/` and `.orchestra/overrides/`, never by adding to
    `sys.path`.

## Conventions

- Python 3.12+, `uv` for everything, `pytest` for tests (run with `uv run
  python -m pytest`), `ruff` for lint and format.
- `tests/unit` is fast and pure. `tests/bus`, `tests/metrics` and `tests/sources` are
  conformance suites run against every backend (the server ones opt in by
  environment variable; see `tests/bus/README.md`). `tests/acceptance` runs against an empty Orchestra started by
  `scripts/acceptance_target.py` and skips unless `ORCHESTRA_TARGET_URL` is
  set.
- Keep modules small and single-purpose. If a file needs a section divider
  comment, it should be two files.
