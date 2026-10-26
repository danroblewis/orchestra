# Rules for working on Orchestra

Read `SPEC.md` first. It is the design. This file is the short list of rules
that must not be broken without updating the spec and saying so in the commit.

## Invariants

These replaced the old task system's invariants on 2026-10-25, when the ticket
tracker, loop and merge gate were removed (`docs/proposals/empty-orchestra.md`).

1. **Orchestra knows no tickets and no tasks, and runs no AI.** It has an
   event bus, a metrics store, a system dynamics model, a bootstrap host and
   the interfaces machines use (the bus, the metrics store, plugins). What
   machines do and what their events mean is theirs. An AI agent is a
   universal machine like any other: its harnesses live with the machines
   that run it (the agents: `~/orchestra-agents`), never here. Never add
   a domain concept (ticket, task, build, agent) to the core.
2. **Machines are outside Orchestra, and known only by observation.** A
   machine is its CloudEvents `source` (`<machine>/<instance>` for one of
   several instances), the events it publishes and listens for, how it says it
   is engaged (continuous, scheduled, ad hoc), and the series it writes. The Machines page, the collectors and the
   model read what is observed, never a machine's description of itself. The
   exceptions are what an instance announces in `orchestra.machine.started`:
   its mode, what it listens for, where its log is and which package it belongs
   to (the rest of the announcement is passed on to that package's card,
   unread), and the machines a plugin declares, which only fill in machines
   not seen yet and never override what is observed. A log is read only
   within the project's repository or state directory (`web/machine_logs.py`).
3. **Every event carries the CloudEvents envelope.** `orchestra.events`
   writes it; Orchestra reads the envelope and never the `data` payload, which
   belongs to the machines that use it.
4. **There is one system and one model.** Never split topics, models or views
   per package or per domain. Packages and metadata label; they never
   separate. The model changes by new versions; past versions stay readable.
5. **State lives in `~/.orchestrator/<key>/`, except the event log and the
   metrics, which live in the configured bus and metrics store.** Events go
   through `orchestra.events.Events` over an `orchestra.bus.EventBus`; metrics
   through `orchestra.metrics.MetricsStore`; the model through
   `orchestra.sd.store.ModelStore`; process records through
   `orchestra.runtime`. Nothing else touches a backend or those files
   directly. Orchestra's streams are named `orchestra.<key>.events` and never
   share a topic with anyone else's.
6. **Every equation records its origin** (fitted, discovered, or declared).
   A declared equation is an assumption until it is fitted. A machine's
   attribution to a flow is a hypothesis.
7. **Stocks are discovered, not configured.** Collectors expose plain series
   named for what they measure; the model generator decides what is a stock or
   a flow. Manual bindings are the exception.
8. **The core stays up.** `web/core.py` and `web/core_explore.py` import only
   the bus, the metrics store and the runtime record, and probe each under a
   time limit, so the Core page works when the model or every machine is
   broken.
9. **Humans talk only to the Supervisor.** The web UI and CLI are read-only
   for humans, except for observations: rediscovering the model (the Dynamics
   page's button, `orchestra sd discover`) re-reads the metrics and may save a
   model version, and changes no machine. The Supervisor is being rebuilt;
   until it returns, there is no human path that changes the system.
10. **One package, no path hacks.** Everything importable is under
    `orchestra/`. No `sys.path` manipulation. `orchestra/sdlab` is SD Lab's
    discovery research brought in as it was benchmarked (imports rewritten,
    nothing else; see its README): change it only deliberately, say so in the
    commit, and keep it out of lint. Machines and test systems live in
    their own repositories (the bakery: `~/orchestra-bakery`) and use Orchestra
    as a library, like any other program would; nothing in this repository is
    an example system.

## Conventions

- Python 3.12+, `uv` for everything, `pytest` for tests (run with `uv run
  python -m pytest`), `ruff` for lint and format.
- `tests/unit` is fast and pure. `tests/bus` and `tests/metrics` are
  conformance suites run against every backend (the server ones opt in by
  environment variable; see `tests/bus/README.md`). `tests/acceptance` runs against an empty Orchestra started by
  `scripts/acceptance_target.py` and skips unless `ORCHESTRA_TARGET_URL` is
  set.
- Keep modules small and single-purpose. If a file needs a section divider
  comment, it should be two files.
