# Orchestra

Orchestra observes a system of machines (programs, AI agents, services, people) through an event
bus and a metrics store, and keeps one system dynamics model of it: stocks, flows, feedback loops,
and which machines drive which flows. Its aim is to find the loops between a project's own domain
and the processes used to develop it.

**Documentation:** [USING_ORCHESTRA.md](USING_ORCHESTRA.md) (add your metrics, connect your machines, configure), [PLUGINS.md](PLUGINS.md) (write a plugin), [ARCHITECTURE.md](ARCHITECTURE.md) (how it works).

This is an **empty Orchestra**: the bus, the metrics store, the model, the bootstrap host and the
web UI, with no machines of its own. Machines come from other packages. A **plugin** is a package
installed in the same environment as `orchestra web` that registers itself in the entry-point
group `orchestra.plugins` (`orchestra/plugins.py`, `SPEC.md` §10.1): it adds its pages, API routes
and machine cards to the web UI. Two exist: the task system `orchestra-tasking` (package
`tasking`, plugin `tasks`: tickets and a scheduler that offers work over the bus;
[github.com/danroblewis/orchestra-tasking](https://github.com/danroblewis/orchestra-tasking),
private) and the AI agents that fill its roles, `orchestra-agents` (package `orchestra_agents`,
plugin `agents`; private). Each repository's README says what it holds. How the task system left
this repository is in `docs/proposals/empty-orchestra.md`.

Each plugin has a demo, one command from its checkout (`uv run demo/run.py`; each demo's README
says what runs). The task system's runs programs only, and shows the pages the plugin adds and the
hand-offs on the Machines page. The agents' is the sample: AI agents beside a program worker on one
queue of tickets, with a system dynamics model discovered from the run. The sample models the task
pipeline itself; it has no domain of its own, so no loop between a domain and its process appears
there yet (`docs/roadmap/use-cases.md`, UC-3b, is the sample that will).

- `SPEC.md` is the design of what exists.
- `AGENTS.md` is the list of rules that must not be broken.


**New here? Start with [QUICKSTART.md](QUICKSTART.md).**

## Install

Nothing needs cloning. Orchestra and the plugins you want go into one environment straight from
GitHub; a plugin is loaded only if it is installed beside the `orchestra` command:

```bash
uv tool install 'orchestra[sd] @ git+https://github.com/danroblewis/orchestra@main' --with 'orchestra-tasking @ git+ssh://git@github.com/danroblewis/orchestra-tasking'
uv tool update-shell        # once: puts ~/.local/bin on the PATH (open a new terminal after)
orchestra --help            # Orchestra's commands, and each installed plugin's: orchestra tasks ...
```

Name Orchestra exactly as the plugins do, `git+https://github.com/danroblewis/orchestra@main`:
pip refuses two different URLs for one package. The plugins' repositories are private, so they come
over SSH with your GitHub key; add a `--with` for each one you want (`orchestra-bridges`,
`orchestra-outbox`, `orchestra-agents`, `orchestra-desk`). A plugin's command line is a subcommand
of `orchestra`, named for the plugin (`orchestra tasks`, `orchestra agents`, `orchestra desk`,
`orchestra outbox`, `orchestra bridges`), so `--with` is all a plugin needs. The one command,
`orchestra`, lands in `~/.local/bin`, which `uv tool update-shell` adds to the PATH (`uv tool dir
--bin` says where it is).

The command is the whole of what is installed: running `uv tool install` again replaces the tool,
and a plugin whose `--with` is left out is uninstalled. `uv tool list --show-with` shows what is
there. To take newer commits, run the same command again, every `--with` included, with
`--reinstall --refresh`. Into a virtual environment instead, with `uv pip` or `pip`:

```bash
uv venv .venv && source .venv/bin/activate
uv pip install 'orchestra[sd] @ git+https://github.com/danroblewis/orchestra@main' \
    'orchestra-tasking @ git+ssh://git@github.com/danroblewis/orchestra-tasking'
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
python scripts/acceptance_target.py --port 8123 &   # prints ORCHESTRA_TARGET_TOKEN to export
ORCHESTRA_TARGET_URL=http://127.0.0.1:8123 ORCHESTRA_TARGET_TOKEN=<token> uv run python -m pytest tests/acceptance
```
