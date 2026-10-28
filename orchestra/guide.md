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
  the repository (`[[sources]]` `auth = { bearer_file = "~/..." }` or `{ bearer_env = "..." }`). A literal secret in a
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
  `[[sources]]` read of a store that bills per query, instruments that hit paid APIs. (Reading a
  store the owner asked you to connect is not one: it is observation; see "Two stores, and a busy one".)
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
changes for a few seconds at a time is invisible on a 30 s grid. Its balance must also hold on
evidence, not on R² alone: chosen again on each half of the window, reproducing the level over
time, beating the same search on the level shifted in time, on enough points; and every stock
carries a trust score from 0 to 1 (`evidence.trust`: its weakest measurement), shown beside it on
the Dynamics page. Read the score before acting on a stock: a net flow at 0.2 is a correlation
the data happen to show, not a finding. A demo wants a short window and
a fine step (`window = "10m"`, `step = "5s"`); a slow system (tickets, deploys) a longer window.
`every` below a minute costs CPU for little: discovery's deadline is 80% of it. Discoveries never
overlap: the host starts one every `every`, or a fifth of `every` after the last one ended when it
took longer, and logs how long each took and whether the strategy was stopped at its deadline
(`discovery (kalman_lna): …; took 312 s; kalman_lna stopped at its deadline of 240 s`). A run that
is always stopped there is reading too much: narrow `[[sources]] match` or lower `max_series`.
Change these only for a reason you can name.

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
read deadline (`deadline`, 120 s) and the 200-series cap on noise. The cap is spent on every
family's total first (up to 60% of it), then on the splits whose groups move apart (three
queues, consumer groups, pod phases), and each definition says what it merges (`merges queue
(3 values)` in `infer_source`): a total you need split is one to pin or a reason to narrow. `settle = "30s"` for a
VictoriaMetrics with its default latency offset. A refused source counts as missing, and then
discovery saves no model version until it is fixed: check `GET /api/instruments` `errors`. A
`[[series]]` entry (`source`, `name`, `query` or `select`, `kind = "level" | "counter" | "rate"`)
pins one definition the inference would not rank.

### Reading another store's schema

A company's store is rarely organised for this: thousands of names, several spellings of one
label, per-pod series, recording rules beside their bases. Look before declaring anything
(`orchestra sources check|infer|preview`, or the Supervisor's `check_sources`, `source_schema`,
`preview_query` and `infer_source`, which take a `url` and `auth` before a source exists):

1. **Start from the owner's question, not the store.** Name the few things whose amount or flow
   the question is about (requests waiting, jobs queued, orders shipped) and search the names for
   them (`match = ['{__name__=~".*queue.*|.*backlog.*"}']`). A store read whole fills the 200-series
   cap with whatever ranks first.
2. **Tell counters from gauges by behaviour, not only by name.** Inference does most of this
   and says so in each family's `retyped`: a summary's or histogram's `_count` is a counter even
   when the store types only the base name; a gauge that never falls but at a rare reset, and
   whose name counts events rather than an amount held (`…_offset`, `…_processed_messages`, not
   `…_used_bytes` or `…_lag`), is read as a counter (kafka_exporter types its offsets gauges); a
   "counter" that falls by halves is read as a gauge; Unix timestamps (`…_created`,
   `…_start_time_seconds`), clocks (`…_uptime_seconds`), info metrics (always 1) and Prometheus'
   own `up` and `scrape_*` are read as neither. A recording rule's name is a hint too: one named
   a rate of a utilisation is a gauge, and a rule is read on its own evaluation interval. Check
   `retyped` against what you know of the exporter; where it is wrong, pin the series. A counter
   is a flow (read as increments or a rate); a gauge may be a stock.
3. **Find the stock candidates.** A good stock is a gauge of an amount that accumulates and
   drains (a queue's depth, items in progress, open tickets, a balance), with counters beside it
   that fill and drain it (`enqueued_total`, `processed_total`). Discovery makes a stock of a level
   whose changes the counters explain; a level with no counter that moves with it is a measured
   input at best. Rates and ratios (latency, utilisation, `_p95`, percent) are never stocks:
   they are intensive (the views take their max or average, never a sum).
4. **Mind the labels.** `source_schema` shows each label's number of values. A label with many
   values (pod, instance, request id, path, user) multiplies series: sum it away (it is an
   `identity` label by default for pod, instance and container, and for any label that names one
   object: a `…_id`, `uid`, an IP address, an image or version, or values that look like ids; name
   others in `identity`), unless it names the thing the model is about (`service`, `queue`). Several spellings of one label
   (`service`, `app`, `k8s_app`) are one `[sources.labels]` entry.
5. **Watch for duplicates.** One quantity is often stored several ways: a base metric and its
   recording rules (`job:http_requests:rate5m`), a histogram's `_count` and a separate
   `requests_total`, the same gauge from two exporters. Inference reads a family once when two
   scrape jobs (or Prometheus replicas) hold the same series (`notes`: `job=… only repeats
   job=…`), and keeps one of two families equal at every point and one count of the same pods;
   what it cannot see (two exporters that disagree a little) is yours. Read one of each quantity:
   two flows that count the same events make discovery see twice the flow, and a stock balanced
   by one while the other is read too will not balance.
6. **Check units and windows.** A gauge reported every 5 minutes cannot show a change inside one
   discovery step; a counter that resets every deploy is fine (increments are reset-safe), one that
   is a cumulative from another system's start is fine too. A stock and its flows must count the
   same things: `queue_depth{queue="orders"}` with `processed_total{service="payments"}` is a
   mismatched stock, and the model's fit will say so with a large error. Narrow both to one label
   value, or group both by the same label. Discovery never adds counters in another unit to a
   level (seconds to a queue, bytes to a count, KiB to bytes): it reads the unit from a `unit`
   label, the store's metadata, or the name's suffix (`_seconds`, `_bytes`; `_count` counts), so
   name pinned series with their unit, and never sum a gauge over a label that holds units
   (`resource="cpu"` beside `resource="memory"`).
7. **Pin what inference does not rank.** `infer_source` lists what it keeps and what it left out
   with why. When it left out the series the question needs, or kept a view you would not use,
   pin it with `[[series]]` and a plain name for what it measures:

```toml
[[sources]]
name = "work"
url = "https://tenant.example/data/metrics"
auth = { bearer_env = "WORK_TOKEN" }
match = ['{__name__=~"queue_depth|orders_processed_total"}']

[[series]]
source = "work"
name = "orders_queue"                         # the name discovery sees: <prefix>:orders_queue
query = 'sum(queue_depth{queue="orders"})'
kind = "level"

[[series]]
source = "work"
name = "orders_processed_total"
select = 'orders_processed_total{service="payments"}'   # raw samples, read as increments
by = []
kind = "counter"
```

Preview each pinned query first (`preview_query`): a query that returns many series, or none, is
wrong before discovery ever reads it. A pin is read **beside** what inference keeps, not instead of
it: once you have translated a store into pinned series, set `infer = false` on its `[[sources]]`
entry, so only the pinned series are read (otherwise the raw family is read too, a duplicate of
each pin), or narrow `match` to the families you did not pin.

8. **Translate into quantities of the system.** Discovery wants levels that are amounts held
   (backlogs, queues, inventories, connections, sessions) and counters of what fills and drains
   them, each counting the same things. A pinned query is how a store's naming becomes that:
   - a consumer's backlog: its lag gauge summed over partitions, or the offsets produced less the
     offsets consumed (offsets are counters even when typed gauges: their rates are the flows);
   - a pool or a set of connections: the active gauge, with the opened and closed counters as its
     flows (a counter need not end in `_total`: `…_destroy` is one);
   - a stock with an outflow nobody measures: pin the level and the inflow, and say the outflow is
     the residual. Never invent the missing series;
   - a gauge that only rises between resets someone makes (a "since reset" or "today" count) is a
     counter: read it as increments (`select`), never as a stock whose outflow is the reset;
   - a delta written as a gauge (OpenTelemetry's delta temporality: each sample is the count in its
     interval) is a flow: `sum_over_time(x[5m]) / 300` with `kind = "rate"`, never a level and
     never `rate()` of it;
   - a metric renamed during the history: both names in one selector (`{__name__=~"old|new"}`),
     one flow; a label whose values changed case: a case-insensitive matcher
     (`outcome=~"(?i)success"`), not two families;
   - one environment: select production explicitly (`env="prod"`). A staging or test twin is never
     summed in and never a stock of its own. Exporters spell the environment label differently
     (`env`, `environment`, `deployment_environment`) and its values too (`prod`, `production`,
     `prd`): read the values, not only the name;
   - units: two exporters of one quantity may disagree (bytes and KiB, messages and orders, a
     help text that names the wrong unit); compare them with `preview_query` over one window, and
     read one, in the unit you name it in (`…_bytes`);
   - latencies, quantiles, histogram buckets (including VictoriaMetrics' `vmrange` ones), ratios,
     flags, timestamps and an exporter's own scrape or query timings are not quantities of the
     system: never stocks;
   - labels that change with every request or sample (trace or request ids) are identity: sum
     them away, or leave the metric out.

9. **Declare a stock you know.** When you know which level a set of counters fills and drains,
   say so: give the level and its flows one `stock` name and each its `role` (`"level"`,
   `"inflow"` or `"outflow"`; a flow is `kind = "counter"`). Discovery tries that balance first,
   before any search, and judges it by the same evidence as any other (enough stretches, a fit
   that holds on each half of the window, the level reproduced over the hour, the shift null). A
   declaration is a hypothesis, not a binding: one that does not fit is searched like any level,
   and the reason the level is left out (if it is) says how well the declared balance fitted. A
   stock found this way records `declared` (its origin) in its evidence; its flows are still
   fitted. The level and its flows may be in different stores:

```toml
[[sources]]
name = "shop"
url = "https://shop.example/metrics"
infer = false

[[sources]]
name = "biz"
url = "https://biz.example/metrics"
settle = "90s"                                # it writes its samples a minute late
infer = false

[[series]]
source = "shop"
name = "email_queue_backlog"
query = 'sum(rabbitmq_queue_messages{queue="email.notifications"})'
kind = "level"
stock = "email_queue"
role = "level"

[[series]]
source = "shop"
name = "email_queue_published"
query = 'sum(rabbitmq_queue_messages_published_total{queue="email.notifications"})'
kind = "counter"
stock = "email_queue"
role = "inflow"

[[series]]
source = "biz"                                # another store, once a minute, a minute late
name = "emails_sent"
query = 'sum(fulfilment_emails_sent_total{env="prod"})'
kind = "counter"
stock = "email_queue"
role = "outflow"
```

### Two stores, and a busy one

- **One store, one entry.** One store is often reachable at several addresses (direct, behind a
  gateway with a token, a regional front). Configure one: two would read every series twice.
  The same names, label values and latest values (`preview_query` of a few) mean one store.
- **Two stores of one system** are two `[[sources]]` entries, each named for what it is. They
  often hold one quantity under different names (the platform's exporter and a team's own).
  Read each quantity once: pin the better copy (finer resolution, fewer gaps, production
  explicit) and leave the other out, or keep it only as a check you look at. Two copies of a
  stock become two stocks; two copies of a flow double it. A label may mean different things in
  different stores (`cluster` the Kubernetes cluster in one, the Kafka cluster in another): alias
  labels per source, never across stores.
- **Late and coarse stores.** A store that writes its samples late needs `settle` above that
  delay (one written a minute late, on VictoriaMetrics: `settle = "90s"`); one sampled once a
  minute cannot show a change inside a minute. Discovery handles both: a series' steps after its
  last sample, a little before the window's end, are missing rather than zero, and a level whose
  flows include a counter counted once a minute is balanced on the stretches between that
  counter's samples (the stock's evidence says `balance_on`), where every series is read at the
  same two instants. Two stores never scrape at the same instant, so such a balance misses by a
  few seconds' worth either way, made up in the next minute; it is judged on whether those misses
  cancel and the level is reproduced over the window, not on R² alone.
- **A busy store** answers 429 or 503 when rate-limited or overloaded, 422 when a query touches too
  many series, 400 when a range asks for too many points. Never lower the cap or raise a limit to
  fit: narrow the read. A `match` per family you need, with label matchers on a metric that is too
  big alone; on a slow store (a second a request) every family costs a few requests to infer and
  the probes have the source's `deadline` (120 s), so narrow first and raise `deadline` or
  `concurrency` only then, never past what the store's rate limit allows. What could not be read
  is in `infer_source`'s notes.
- **Credentials by reference.** A token the owner keeps in a file is
  `auth = { bearer_file = "~/path/to/token" }` (or `header = { name = "API-Token", value_file = "…" }`
  for a store that wants its own header); one in the environment is `bearer_env`. Never read the
  file, copy the token or put it in a command: the tools read it when they ask the store.

Connecting a store the owner asked for is observation: Orchestra reads it and never writes, and it
needs no further go-ahead. Choose a narrow selection from the owner's question, declare it, check
it, and say what you chose. Ask only what you cannot find out: where the credential is, when the
store refuses without one and nobody said; which environment is production, when the data cannot
tell. A store that bills per query is the owner's choice before it is read at all.

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
- Two series of one quantity (a metric and its recording rule) double a flow; read one.
- A stock and its flows must count the same things, grouped by the same labels.
- The model needs about an hour of data before it shows stocks.
- A stock's R² is not its credibility; its trust score is. A count of pods balanced by its own
  started and stopped counts is exact by construction and scores 0; a hidden state has no R².
- `[events]`, `[metrics]`, `[web]`, `[discovery]` need a restart; instruments and machines don't.
- A secret in either file is wrong; a private value goes to the overlay, a credential to the
  environment.
