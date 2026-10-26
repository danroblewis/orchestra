# Orchestra

Orchestra observes a system of machines (programs, AI agents, services, people) through an event
bus and a metrics store, and keeps one system dynamics model of it: stocks, flows, feedback loops,
and which machines drive which flows. Its aim is to find the loops between a project's own domain
and the processes used to develop it.

This is an **empty Orchestra**: the bus, the metrics store, the model, the bootstrap host and the
web UI, with no machines of its own. The task system (tickets, the agent loop, the AI agent
harnesses, the merge gate) was removed on 2026-10-25 and lives in its own repository,
`~/orchestra-tasking`, which adds its pages to the web UI as a plugin (`orchestra/plugins.py`).

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
(`orchestra.metrics`); they appear on the Machines page and in the Core explorers.
`~/orchestra-bakery` (its own repository) is a toy system of machines used to test Orchestra
from the outside.

## Tests

```bash
uv run python -m pytest                     # unit, and the file backends
ORCHESTRA_TEST_REDIS_URL=redis://127.0.0.1:6379/15 uv run python -m pytest tests/bus   # see tests/bus/README.md
python scripts/acceptance_target.py --port 8123 &
ORCHESTRA_TARGET_URL=http://127.0.0.1:8123 uv run python -m pytest tests/acceptance
```
