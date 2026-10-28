# Configuring Orchestra: the operator's guide

For an AI operator (the Supervisor) setting up Orchestra in the owner's repository. It says what
each setting is for, when to choose each value, how they interact, the pitfalls, how to check a
setting took, and which choices are the owner's. Each installed plugin has a guide of its own
(`GET /api/guides` lists them all). Full reference: `USING_ORCHESTRA.md` in Orchestra's
repository.

Orchestra is an event bus, a metrics store and a system dynamics model discovered from the
metrics. It runs no AI and knows no tickets: plugins add those. What you configure here is
**what is measured** (instruments), **what is kept running** (machines), **where events and
metrics live**, and **how the model is discovered**.

## Where settings live

- `orchestra.toml` at the repository root: the project's settings, committed and shared.
- The **private overlay**, `~/.orchestrator/<key>/orchestra.local.toml` (or the file
  `ORCHESTRA_CONFIG_OVERLAY` names): the owner's own (identities, channels, personal instruments,
  a local VictoriaMetrics). Never committed. Merged over `orchestra.toml`: tables key by key (the
  overlay wins); arrays of tables (`[[machines]]`, `[[collect]]`, `[[scrape]]`, `[[sources]]`,
  `[[series]]`, a plugin's arrays) by `name`, an overlay entry replacing the repository's of that
  name whole; `{ name = "x", enabled = false }` in the overlay removes the repository's `x`.
  `[overlay] secret = ["desk.me"]` hides those values from pages (private, not a credential).
- **Credentials never go in either file.** They come from environment variables or files outside
  the repository (`[[sources]]` `auth = { bearer_env = "..." }`). A literal secret in a
  `[[sources]]` entry refuses the source.
- Sections Orchestra does not know are ignored: each plugin keeps its own section here.

Choose the target by audience: what every clone of the repository should run goes to the
repository; what only the owner wants, or what names the owner, goes to the overlay. When unsure,
the overlay is the safe default: nothing reaches the team.

## Changing a setting and checking it took

Change settings only through `project.config_edit` (`set`, `set_many`, `unset`, `add_entry`,
`remove_entry`, each with `target="repo"` or `"overlay"`; `dry_run=True` to see the diff first).
It keeps the file's comments and **refuses** a result that Orchestra's readers or any loaded
plugin's check object to (`orchestra.config_edit.problems`, `Plugin.check`): `[events]`,
`[metrics]`, `[web]` and `[discovery]` values, every `[[machines]]` entry, every `[[collect]]` and
`[[scrape]]` entry, and each plugin's own sections. You pass no `check=` for a plugin: its check
runs by itself, and its refusal starts with its name. A refusal says why; fix the value, do not
work around it. A plugin whose check could not run is named in the change's `warnings`: then
check its sections by hand, by its guide.

What `config_edit` does not prove is that the thing works. After a change, look:

- **Instruments** (`GET /api/instruments`, the Instruments page): each `[[collect]]`/`[[scrape]]`
  with when it last wrote, its points and `last_error`; `errors` lists entries left out and
  `[[sources]]` refused with the reason (sources are checked here, not by `config_edit`). The
  instrument's log: `GET /api/instruments/<name>/log`.
- **Processes** (`GET /api/core`, the Core page): each `[[machines]]` entry's pid, exits, and
  whether it was given up on. Its log: `~/.orchestrator/<key>/logs/machines/<name>.log`.
- **Machines** (`GET /api/machines`): a process is a machine only once it publishes on the bus.
- **The configuration as read** (`GET /api/project`): each key and whether it came from the
  repository or the overlay.

`orchestra run` follows both files live: a `[[machines]]`, `[[collect]]` or `[[scrape]]` entry
added starts within a second, one removed stops, one changed restarts. `[events]`, `[metrics]`,
`[web]` and `[discovery]` are read at start: those need `orchestra run` and `orchestra web`
restarted, which is the owner's to do.

## The owner's choices, not yours

Propose these, say what follows from each, and wait for the owner:

- Moving the bus or metrics off `file` (`[events] url`, `[metrics] url`): it needs a server
  running, an extra installed (`orchestra[bus-redis]` and so on) and a restart, and moves where
  history is kept.
- `[web] auth = "off"`, or any `listen` off loopback: who can reach the system.
- Committing a change to `orchestra.toml` (Orchestra never commits), and anything that pushes.
- Anything with cost: a test suite run every few minutes on a laptop, a long e2e suite, a
  `[[sources]]` read of a paid store, instruments that hit paid APIs.
- Credentials: which environment variable or file holds one. Never ask for the value itself.
- Anything a plugin's guide marks as the human's (letting agents change code, outbound messages).

## `[events]` and `[metrics]`: where they live

```toml
[events]
url = "file"               # file, redis://host:6379/0, amqp://user@host:5672/, kafka://host:9092
listen = "127.0.0.1:0"     # the HTTP endpoint machines publish to; port 0: any free one; "off": none

[metrics]
url = "file"               # file, or http://host:8428 (VictoriaMetrics)

[web]
auth = "on"                # "off" only on a loopback bind
```

`file` is right for one person on one computer: nothing to run. VictoriaMetrics suits months of
history or several projects (every point carries a `project` label). `ORCHESTRA_EVENTS_URL` and
`ORCHESTRA_METRICS_URL` override the files; set them for every process or they read different
stores. Leave `listen` alone unless a machine must reach the endpoint from another computer.

## `[discovery]`: how the model is found

```toml
[discovery]
strategy = "kalman_lna"    # the default with orchestra[sd]; "conservation" without it
window = "60m"             # how far back each discovery looks
step = "30s"               # the grid: the finest change it sees
every = "5m"               # how often the host rediscovers
eras_from = ["config.changed"]   # events that begin an era, besides system.changed
announce_hold = 3          # discoveries a structure change must hold before orchestra.model.changed
announce_gap = "30m"
diverge_after = "15m"
```

The defaults suit a system that runs all day. A level becomes a stock only after it has been
written for half the window, changed in at least 5 steps, with counters that counted at least 5
events each: so the first model appears about an hour after instruments start, and a series that
changes for a few seconds at a time is invisible on a 30 s grid. A demo wants a short window and
a fine step (`window = "10m"`, `step = "5s"`); a slow system (tickets, deploys) a longer window.
`every` below a minute costs CPU for little: discovery's deadline is 80% of it. Change these only
for a reason you can name.

## Instruments and machines

An **instrument** measures and never acts: `[[collect]]` (a command run on an interval that
prints measurements), `[[scrape]]` (a URL serving them), `[[sources]]` (another store read in
place). Its series are labelled `instrument=<name>`. A **machine** does work and is known by its
events on the bus: `[[machines]]` only keeps a command running; it is a machine once it publishes.
Something that only prints numbers is an instrument, never a `[[machines]]` entry. A program that
serves `/metrics` is both: `[[machines]]` to run it, `[[scrape]]` to read it (they may share a
name).

### `[[collect]]`: a command whose output is measurements

```toml
[[collect]]
name = "disk"              # letters, digits, . _ -; unique among instruments
command = "machines/disk.sh"   # split like a shell would, NOT run by one; or a list of words
every = "60s"              # at least 1 s; default 60 s
timeout = "20s"            # default 10 s, never more than every (a larger value is cut to it)
```

The command prints the Prometheus text format, one `name value` (optionally `name{label="x"}
value`) per line, and exits. No shell runs it: pipes, `&&` and `$VAR` need a script, or
`["sh", "-c", "..."]`. A file in the repository is named with a slash (`./x.sh`,
`machines/x.sh`). **Pitfall: the 10 s default timeout.** Anything slower (a test suite, a
`git log` over a big history, a network call) needs `timeout`, and `every` at least as long.

### The test-report instrument: counting the tests

The most useful first instrument in any repository with tests. Run mode runs the suite each round
and reads the report that run wrote:

```toml
[[collect]]
name = "tests"
command = "python -m orchestra.instruments.test_reports --run 'uv run pytest -q' --kind e2e=@e2e --history .git/test-history.json"
every = "10m"
timeout = "6m"
```

- **The command inside `--run`** is run by `/bin/sh` in the repository root. Without `{report}`
  it must end in a pytest command (the instrument appends `--junitxml=<file>` and a plugin that
  records markers). Any other runner writes JUnit XML or a pytest report log to `{report}`:
  Jest `JEST_JUNIT_OUTPUT_FILE={report} npx jest --reporters=jest-junit` (needs `jest-junit`
  installed), Vitest `npx vitest run --reporter=junit --outputFile={report}`, Go
  `go test -json ./... 2>&1 | go-junit-report -parser gojson > {report}` (needs
  `go-junit-report`). Use the environment the project uses: `uv run pytest` with a `uv.lock`,
  `poetry run pytest` with `poetry.lock`, `.venv/bin/pytest`, `hatch run test`, the `test` script
  in `package.json`, the test target of a `Makefile`; the CI workflow (`.github/workflows/*.yml`)
  shows the command the team trusts.
- **Kinds.** Defaults, tried after any `--kind`: `e2e=*e2e*`, `acceptance=*acceptance*`,
  `unit=*`, as globs over the test's path, so `tests/e2e/` and `tests/acceptance/` sort
  themselves. `--kind KIND=@marker` uses pytest markers (look in `pyproject.toml`
  `[tool.pytest.ini_options] markers`, `pytest.ini`, `conftest.py`); markers exist only in run
  mode with pytest or in a report log, never in a plain `--junitxml` file. `--kind ignore=...`
  drops tests.
- **Timeouts.** The run is killed at `--run-timeout`, by default the entry's `timeout` less a
  fifth (at most 5 s). Time the suite and set `timeout` well above it; `every` at least that.
- **Different schedules:** two entries (`tests-unit` every 5 m, `tests-e2e` every hour), each
  running its own subset; their series never collide.
- **`--history FILE`**, outside version control (`.git/...` works in a plain clone, not in a
  worktree, where `.git` is a file): needed for flakiness, confirmation and the
  `tests_added_total`/`tests_removed_total` counters that let discovery find the test count a
  stock. Use it.
- **Reports mode**, `--reports 'reports/**/*.xml' --max-age 2h`: when CI or a merge gate already
  writes reports; the instrument then runs nothing.
- **Absent is not zero.** A kind the current run lacks prints nothing (a gap), not zeros; a run
  that wrote no report prints no test series, only `test_run_result{result="no_report"}` and its
  log's last lines. A gap means "look at the log", never "no tests".
- Cost: every round runs the suite. A five-minute suite every five minutes keeps a core busy all
  day; ask the owner how often.

### `[[scrape]]`: a URL that serves measurements

```toml
[[scrape]]
name = "app"
url = "http://127.0.0.1:9100/metrics"
every = "30s"
timeout = "10s"            # bounds each wait for the server
```

For an app that already exposes Prometheus metrics: `prometheus_client`, Micrometer
(`/actuator/prometheus`), `prom-client`, an exporter. Only useful while the app is running; a
scrape of nothing records errors, not zeros.

### `[[sources]]` and `[[series]]`: another store, read in place

For metrics that already live in Prometheus, VictoriaMetrics, Thanos, Mimir or Chronosphere.
Orchestra reads them and never writes. What to read is inferred from the store's schema.

```toml
[[sources]]
name = "work"                       # lower-case letters, digits, _
url = "https://tenant.example/data/metrics"   # no user:pass@, no query string
auth = { bearer_env = "WORK_TOKEN" }          # the variable's name, never the token
machine = "service"                 # the label that names machines
match = ['{__name__=~"http_.*|queue_.*"}']    # narrow it: the default reads everything, capped
max_series = 200

[sources.labels]
service = ["service", "app", "k8s_app"]       # spellings that mean the same label
```

Narrow `match` to what bears on the owner's question; a broad match on a big store spends the
read deadline (`deadline`, 120 s) and the 200-series cap on noise. `settle = "30s"` for a
VictoriaMetrics with its default latency offset. A refused source counts as missing, and then
discovery saves no model version until it is fixed: check `GET /api/instruments` `errors`. A
`[[series]]` entry (`source`, `name`, `query` or `select`, `kind = "level" | "counter" | "rate"`)
pins one definition the inference would not rank.

## `[[machines]]`: commands kept running

```toml
[[machines]]
name = "app"
command = "uv run python -m app --port 9100"
restart = "always"         # always (default) | on-failure | never
stop_grace = 10            # seconds from SIGTERM to SIGKILL
```

Each runs in the repository root in its own process group, with `ORCHESTRA_REPO`,
`ORCHESTRA_EVENTS_ENDPOINT` and `ORCHESTRA_EVENTS_TOKEN` set, its output in its log. One that
exits is restarted after a pause that doubles (up to a minute); five quick failures in a row and
it is given up on (`orchestra.process.gave_up`; the Core page says so). One that exits 0 under
`always` runs again about once a minute: a sampler written as one reading is better a
`[[collect]]`. A name `<plugin>.<name>` is refused (plugins' processes are named so). Find what
to run from how the app is served: a `Procfile`, `docker-compose.yml` services, the `dev`/`start`
scripts in `package.json`, `[project.scripts]` in `pyproject.toml`, a `Makefile` `run` target,
the README. A container needs its runtime; prefer the command the developers use locally.

## The `python` rule

In every command Orchestra runs (`[[machines]]`, `[[collect]]`, a source's transform script),
`python` and `python3` are **Orchestra's own Python**, even inside `sh -c`: so
`python -m orchestra.instruments.test_reports` and plugins' modules import. For the project's
Python, write `uv run python` (uv picks the project's environment) or `.venv/bin/python`. Inside
the test-report instrument's `--run '...'` the same holds: write `uv run pytest`, not bare
`pytest`, unless Orchestra's Python is meant.

## Naming series

- Name a series for what it measures, with its unit: `queue_jobs`, `disk_free_bytes`,
  `orders_shipped_total`. Never for its role (`queue_stock`): stock or flow is discovery's answer.
- A counter (only goes up; a reset to zero is fine) ends in `_total`; only those can be flows.
  Anything else is a level.
- Never start a name with `orchestra_`: that prefix is Orchestra's, refused from instruments.
- Keep label values few; each is a series. `instance` for several of one thing.
- Write every series every round, even unchanged; instruments do.
- A `machine` label never makes a machine nor ties one to a flow: that is inferred from events.

## Pitfalls, in short

- `[[collect]]` timeout defaults to 10 s and is cut to `every`.
- Commands are not run by a shell; `--run '...'` is.
- Bare `python` is Orchestra's Python, not the project's.
- Absent test kinds and missing reports are gaps, not zeros.
- A refused `[[sources]]` entry stops model versions being saved.
- The model needs about an hour of data before it shows stocks.
- `[events]`, `[metrics]`, `[web]`, `[discovery]` need a restart; instruments and machines don't.
- A secret in either file is wrong; a private value goes to the overlay, a credential to the
  environment.
