# Orchestra

Orchestra observes a system of machines (programs, AI agents, services, people) through an event
bus and a metrics store, and keeps one system dynamics model of it: stocks, flows, feedback loops,
and hypotheses, with their evidence, about which machines drive which flows; and beside it, what
you expect the system to be (the intended model). Its aim is to find the loops between a project's own domain
and the processes used to develop it.

**Start with [SETUP.md](SETUP.md):** install, give the Supervisor (an AI agent) a few details, and watch it set Orchestra up.

**Documentation:** [orchestra/guide.md](orchestra/guide.md) (the operator's guide: every setting, store and integration), [docs/machines.md](docs/machines.md) (metrics and machines), [PLUGINS.md](PLUGINS.md) (write a plugin), [ARCHITECTURE.md](ARCHITECTURE.md) (how it works).

This is an **empty Orchestra**: the bus, the metrics store, the model, the bootstrap host and the
web UI, with no machines of its own. Machines come from other packages. A **plugin** is a package
installed in the same environment as `orchestra web` that registers itself in the entry-point
group `orchestra.plugins` (`orchestra/plugins.py`, `SPEC.md` §10.1): it adds its pages, API routes
and machine cards to the web UI. Plugins live in their own repositories, and PLUGINS.md (§8)
lists them.

- `SPEC.md` is the design of what exists.
- `AGENTS.md` is the list of rules that must not be broken.


## Install

Nothing needs cloning. Orchestra and the plugins you want go into one environment straight from
GitHub; a plugin is loaded only if it is installed beside the `orchestra` command:

```bash
uv tool install 'orchestra[sd,workflows,agents,bridges,desk,outbox] @ git+https://github.com/danroblewis/orchestra@main'
uv tool update-shell        # once: puts ~/.local/bin on the PATH (open a new terminal after)
orchestra --help            # Orchestra's commands, and each installed plugin's: orchestra workflows ...
```

`sd` is the system dynamics discovery; each other extra is a plugin, a package of its own in its
own repository (`orchestra-workflows`, `orchestra-agents`, `orchestra-bridges`, `orchestra-desk`,
`orchestra-outbox`), which the extra installs beside Orchestra. Name only the ones you want.
`workflows` is private: its extra installs only with access to its repository; the rest install
without it.
Work is followed as **items**: `workflows` records each piece of work as an item moving through a
workflow's steps, and its Items page shows where each one is, who acts next and what it waited on.
(`tasking`, the ticket system Orchestra was first tried with, remains an extra for demos.) A
plugin's command line is a subcommand of `orchestra`, named for the plugin (`orchestra workflows`,
`orchestra agents`, `orchestra desk`, `orchestra outbox`, `orchestra bridges`). The one command,
`orchestra`, lands in `~/.local/bin`, which `uv tool update-shell` adds to the PATH (`uv tool dir
--bin` says where it is).

The command is the whole of what is installed: running `uv tool install`
again replaces the tool, and a plugin left out of the brackets is uninstalled. `uv tool list
--show-with` shows what is there. To take newer commits, run the same command again with
`--reinstall --refresh`. Into a virtual environment instead, with `uv pip` or `pip`:

```bash
uv venv .venv && source .venv/bin/activate
uv pip install 'orchestra[sd,workflows] @ git+https://github.com/danroblewis/orchestra@main'
```

Orchestra alone from a checkout: `uv tool install /path/to/orchestra` (or `-e` for an editable one).
Each plugin's README says how to develop it against a local Orchestra checkout.

For working on Orchestra itself: `uv sync --extra dev` and `uv run orchestra ...`. Server event
buses need an extra: `--extra bus-redis`, `bus-rabbitmq`, `bus-kafka`, or `bus` for all three.
SD Lab's discovery strategies (`orchestra/sdlab`) need `--extra sd`.

## Use it on a project

```bash
cd my_project                # any git repository
orchestra init               # writes orchestra.toml and registers the project (once)
orchestra run &              # the bootstrap host: its event collector, discovery, your [[machines]] and [[collect]]
orchestra web                # the UI on http://127.0.0.1:8000
```

`orchestra.toml` picks the event bus (`[events] url`: file, Redis, RabbitMQ or Kafka) and the
metrics store (`[metrics] url`: file or VictoriaMetrics). `deploy/dev/compose.yaml` starts all of
them locally. Series that live in another store (Prometheus, VictoriaMetrics, Mimir, Chronosphere)
are read in place by naming it under `[[sources]]` (SPEC §4.4); `orchestra sources infer` shows
what Orchestra will read from it.
To connect an issue tracker, a chat, an alerting service or a Prometheus store, ask the Supervisor
([SETUP.md](SETUP.md)); its method is [orchestra/guide.md](orchestra/guide.md). What you expect the
system to be (the intended model, shown beside the discovered one) is described in SPEC §4.6.

Machines are your programs, and none needs to import Orchestra. Measurements come from
instruments, which are not machines: a script that prints measurements in the Prometheus text
format (`disk_free_bytes 1.2e11`, one per line) is declared under `[[collect]]` in
`orchestra.toml`, and `orchestra run` runs it on an interval and writes what it prints, labelled
`instrument=<name>`, to the project's store; a program that already serves Prometheus metrics is
read under `[[scrape]]` with its URL. Instruments are listed on the Instruments page, their series
in the Core explorers, and discovery reads them. A program that should run all the time goes under
`[[machines]]` and `orchestra run` keeps it running (inside commands Orchestra runs, `python` is
Orchestra's Python, even inside `sh -c`; use `uv run python` or `.venv/bin/python` for your
project's). Events go over HTTP: `orchestra
run` serves `POST /events` and `GET /events` and hands each process it launches the address and
a token (`ORCHESTRA_EVENTS_ENDPOINT`, `ORCHESTRA_EVENTS_TOKEN`), so `curl` is enough. Python
programs may use the optional helpers instead (`orchestra.events.Events.publish`,
`orchestra.metrics.for_repo()`). **[docs/machines.md](docs/machines.md)** is the guide: a script
collector, a scrape, a long-running program, naming, counters and levels, and labels.
The bakery, a separate repository, is a toy system of machines used to test Orchestra from the
outside (`docs/roadmap/use-cases.md`).

## Tests

```bash
uv run python -m pytest                     # unit, and the file backends
ORCHESTRA_TEST_REDIS_URL=redis://127.0.0.1:6379/15 uv run python -m pytest tests/bus   # see tests/bus/README.md
tests/sources/rig/rig.sh start              # a store to read in place; see tests/sources/README.md
uv run python scripts/acceptance_target.py --port 8123 &   # prints ORCHESTRA_TARGET_TOKEN to export
ORCHESTRA_TARGET_URL=http://127.0.0.1:8123 ORCHESTRA_TARGET_TOKEN=<token> uv run python -m pytest tests/acceptance
uv run python -m pytest tests/e2e           # opt-in: real installs and processes on free ports
uv run python -m pytest tests/screenshots   # opt-in: the approved frames, with node, puppeteer-core and Chrome for Testing
```
