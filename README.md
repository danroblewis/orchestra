# Orchestra

Orchestra observes a system of machines (programs, AI agents, services, people) through an event
bus and a metrics store, and keeps one system dynamics model of it: stocks, flows, feedback loops,
and which machines drive which flows. Its aim is to find the loops between a project's own domain
and the processes used to develop it.

This is an **empty Orchestra**: the bus, the metrics store, the model, the bootstrap host and the
web UI, with no machines of its own. Machines come from other packages. A **plugin** is a package
installed in the same environment as `orchestra web` that registers itself in the entry-point
group `orchestra.plugins` (`orchestra/plugins.py`, `SPEC.md` §10.1): it adds its pages, API routes
and machine cards to the web UI. Two exist: the task system `orchestra-tasking` (package
`tasking`, plugin `tasks`: tickets, a scheduler that offers work over the bus, the merge gate;
[github.com/danroblewis/orchestra-tasking](https://github.com/danroblewis/orchestra-tasking),
private) and the AI agents that fill its roles, `orchestra-agents` (package `orchestra_agents`,
plugin `agents`: the Supervisor, Coordinator, worker and reviewer roles on Pi, Claude Code or
Codex; private). How the task system left this repository is in `docs/proposals/empty-orchestra.md`.

Each plugin has a demo, one command from its checkout. `uv run demo/run.py` in
`orchestra-tasking` runs the task system with programs only (a shell worker and a program
reviewer on four tickets), and shows the pages the plugin adds and the hand-offs on the Machines
page. The same command in `orchestra-agents` is the sample: a Haiku reviewer, Coordinator and
Supervisor beside a program worker on one queue of fifteen tickets, with a system dynamics model
discovered from the run. The sample models the task pipeline itself; it has no domain of its own,
so no loop between a domain and its process appears there yet (`docs/roadmap/use-cases.md`,
UC-3b, is the sample that will).

- `SPEC.md` is the design of what exists.
- `AGENTS.md` is the list of rules that must not be broken.

## Install

```bash
uv tool install /path/to/orchestra          # or: uv tool install -e /path/to/orchestra
```

For working on Orchestra itself: `uv sync --extra dev` and `uv run orchestra ...`. Server event
buses need an extra: `--extra bus-redis`, `bus-rabbitmq`, `bus-kafka`, or `bus` for all three.
SD Lab's discovery strategies (`orchestra/sdlab`) need `--extra sd`.

## Use it on a project

```bash
cd my_project                # any git repository
orchestra init               # writes orchestra.toml and registers the project (once)
orchestra run &              # the bootstrap host: Orchestra's own machine and its event collector
orchestra web                # the UI on http://127.0.0.1:8000
```

`orchestra.toml` picks the event bus (`[events] url`: file, Redis, RabbitMQ or Kafka) and the
metrics store (`[metrics] url`: file or VictoriaMetrics). `deploy/dev/compose.yaml` starts all of
them locally.

Machines are your programs. Publish events with the CloudEvents envelope
(`orchestra.events.Events.publish`) and write metrics labelled `machine=<id>`
(`orchestra.metrics`); they appear on the Machines page and in the Core explorers. A machine
announces itself when it starts with `orchestra.machine.started`, carrying how it is engaged
(`mode`), what kind of thing it is (`kind`), what it listens for (`listens_for`) and where its
log is (`log`); the rest is observed (`SPEC.md` §1).
The bakery, a separate repository, is a toy system of machines used to test Orchestra from the
outside (`docs/roadmap/use-cases.md`).

## Tests

```bash
uv run python -m pytest                     # unit, and the file backends
ORCHESTRA_TEST_REDIS_URL=redis://127.0.0.1:6379/15 uv run python -m pytest tests/bus   # see tests/bus/README.md
python scripts/acceptance_target.py --port 8123 &
ORCHESTRA_TARGET_URL=http://127.0.0.1:8123 uv run python -m pytest tests/acceptance
```
