# Configuring Orchestra: the operator's guide

For an AI operator (a plugin's machine) setting up Orchestra in the owner's repository. It says what
each setting is for, when to choose each value, how they interact, the pitfalls, how to check a
setting took, and which choices are the owner's. Each installed plugin has a guide of its own
(`GET /api/guides` lists them all). The design in full: `SPEC.md` in Orchestra's repository.

Orchestra is an event bus, a metrics store and a system dynamics model discovered from the
metrics. It runs no AI and knows no domain: plugins add one. What you configure here is
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
  `[overlay] secret = ["desk.owner"]` hides those values from pages (private, not a credential).
- **Credentials never go in either file.** They come from environment variables or files outside
  the repository (`[[sources]]` `auth = { bearer_file = "~/..." }` or `{ bearer_env = "..." }`). A literal secret in a
  `[[sources]]` entry refuses the source.
- Sections Orchestra does not know are ignored: each plugin keeps its own section here.
- **A clean repository** (`orchestra init --clean`): the owner keeps Orchestra's files out of the
  repository. There is no `orchestra.toml`; the private overlay is the whole configuration, and a
  change made with `target="repo"` is written to the overlay (its `note` says so). Put machines,
  workflows and resource kinds in the state directory, never under the repository's `.orchestra/`.

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
- Anything a plugin's guide marks as the human's (letting a plugin change code, outbound messages).

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
stall_after = "15m"        # a stock rising with its outflows stopped this long: orchestra.model.stalled
stall_share = 0.1          # an outflow below this share of its usual rate counts as stopped
```

`orchestra.model.stalled` (subject `stock:<id>` or `flow:<id>`) and `orchestra.machine.quiet`
(subject the machine) are what a flow keeper wakes on. Lengthen `stall_after` for a slow system
(items move in hours: `"2h"`), or stalls fire on ordinary pauses; never shorten it below a few
`step`s. A stall needs the history on both sides of the window: a new stock is not judged for
`stall_after` plus a little after it first appears.

**Eras.** An era begins only for a change of how the system behaves, and discovery reads only the
current era, so an era begun by setup throws away the history. Publish `config.changed` with a
`subject` naming what changed: `machine:<name>` (a machine's spec, its model or its duties),
`definition:<name>` (a definition machines work by), and it begins an era; `instrument:`,
`collector:`, `source:`, `series:` or `setting:<section>` (a plugin's settings) never do, nor does a
`config.changed` with no subject, one that left the configuration as it was, or one about a
measurement. A change a prediction is about always does. A change within half the window of the
current era's start is kept in that era instead (an era is never shorter than discovery needs), so
an `eras_from` that fires every few minutes (every merge) gives one era per half hour; prefer
marking releases with a prediction to judge them, over an era per release.

The defaults suit a system that runs all day. A level becomes a stock only after it has been
written for half the window, changed in at least 5 steps, with counters that counted at least 5
events each: so the first model appears about an hour after instruments start, and a series that
changes for a few seconds at a time is invisible on a 30 s grid. Its balance must also hold on
evidence, not on R² alone: chosen again on each half of the window, reproducing the level over
time, beating the same search on the level shifted in time, on enough points; and every stock
carries a trust score from 0 to 1 (`evidence.trust`: its weakest measurement), shown beside it on
the Dynamics page. Read the score before acting on a stock: a net flow at 0.2 is a correlation
the data happen to show, not a finding. A demo wants a short window and
a fine step (`window = "10m"`, `step = "5s"`); a slow system (orders, deploys) a longer window.
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
command = "python -m orchestra.instruments.test_reports --run 'uv run pytest -q' --kind e2e=@e2e"
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
  in `package.json`, the test target of a `Makefile`; the CI configuration (`.github/workflows/*.yml`, `.gitlab-ci.yml`)
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
- **`--history FILE`**, at an absolute path outside the repository (under the owner's home, say),
  so no instrument writes inside it: needed for flakiness, confirmation and the
  `tests_added_total`/`tests_removed_total` counters that let discovery find the test count a
  stock. Add it once you have chosen where it lives.
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
Orchestra reads them and never writes. What to read is inferred from the store's schema. The setup,
step by step, with every lever and what it costs, is "A Prometheus-API store: the entry and every
lever" below; this subsection and the next two are what inference and the reads do underneath.

```toml
[[sources]]
name = "work"                       # lower-case letters, digits, _
url = "https://tenant.example/data/metrics"   # no user:pass@, no query string
auth = { bearer_env = "WORK_TOKEN" }          # the variable's name, never the token
machine = "service"                 # the label that names machines
match = ['{namespace="shop", __name__=~"http_.*|queue_.*"}']    # required: the owner's scope (ask them), never one family alone
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
source most of whose reads arrived is **partial**, not missing: when at most a tenth of its
definitions could not be read, the rest are used, the failed ones are named in the source's
status (`failed`), and the version is saved.

How hard a store is leaned on, per source (defaults shown; none of these changes what is
inferred, so changing one keeps the cached definitions):

```toml
[[sources]]
name = "work"
url = "https://tenant.example/data/metrics"
match = ['{namespace="shop"}']
auth = { bearer_env = "WORK_TOKEN" }
rate = 5                  # requests a second to this store, from everything on this machine
burst = 10
max_requests_per_day = 20000   # per store per UTC day, every project and process counted; then reads stop until 00:00 UTC
web_share = 0.2           # of the rate and the daily cap, at most, for the web server's reads
max_requests = 1000       # per discovery's reads, retries included
infer_requests = 1500     # per inference round, retries included
infer_deadline = "300s"   # per inference round, the schema's reads included
series_per_query = 2000   # the most series one batched read touches; below the store's limit
max_names = 2000          # metric names match may select for inference to list them
```

The rate and the daily cap are **per store**: its URL and any tenant header, shared by every
project, process, `[[sources]]` entry and trial read on this machine that points at it (a bucket
under Orchestra's home, `stores/`). Two entries for one store do not get twice the rate.

Only the host's discovery and `orchestra sources infer` infer; the web server and the judge read
the cached definitions (an hour old by default, `infer_every`; six hours for a source that declares
`[[series]]` and does not set it). A round that fails, or could not read everything, is tried again
after 5 minutes, then 20, 80, never at once; the definitions before it stand meanwhile. After three
rounds that failed for what they cost (their budget or deadline spent), or one refused because the
store is too big to list, **no round runs until the `[[sources]]` entry changes** (or
`orchestra sources infer` asks for one): narrow it rather than paying for the same failure every
hour. A round over a shorter window than the cached one's never replaces it.

**What a store is asked, and how often.** Discovery reads its window once, then only the steps
since its last read (and five minutes before, further for a series whose newest samples are late), reading the whole window
again hourly; the web server reads other stores only while a page shows their levels, history or
counted traffic, starting from what the host's discovery read, and slows down when the store
throttles it. A read the store refused for its size is not asked again for an hour.

**A large tenant (millions of series, tens of thousands of names).** Inference never lists a
whole big store: when `match` selects more than `max_names` metric names (one cheap request
says how many), inference is refused with what to narrow, and not tried again until the entry
changes. Never answer that by raising a budget or a limit: narrow `match` to the families the
model is about, with a label matcher where the store is shared, or declare the series and set
`infer = false`. Safe settings for a tenant of about 5M series:

```toml
[[sources]]
name = "prod"
url = "https://<tenant>.chronosphere.io/data/metrics"
auth = { header = { name = "API-Token", value_file = "~/.config/chronosphere/token" } }
settle = "60s"
match = ['{__name__=~"rabbitmq_queue_messages(_ready|_unacked)?|kafka_consumergroup_lag_sum|checkout_orders_total", env="prod"}']
infer = false            # once the declared [[series]] cover the stocks; infer only while setting up
rate = 1.0               # requests a second to this store from this machine
burst = 5
concurrency = 2
max_requests_per_day = 10000
max_requests = 200       # per discovery round
infer_requests = 300     # per inference round: fail fast, then narrow
infer_every = "6h"       # the schema does not change hourly; a burst must not flip the model
series_per_query = 1000  # well under the tenant's per-query limit: a burst doubles cardinality
max_series = 60          # definitions discovery reads
history = "6h"

[discovery]
window = "60m"
step = "60s"             # half the points and samples of 30 s
every = "15m"
```

With these, check a store before inferring from it (`check_sources` asks no series), look at
names before series (`source_schema` with a `match`), preview only aggregated queries with a label
matcher, and infer at most once per change of `match`. Every query Orchestra sends carries the label matchers
every `match` selector has (`{namespace="hackriff"}`), so a shared store is read within the
project's part. `history` (default `"7d"`) is how far back a new source's first read reaches, in
pages of a day, within `max_requests`: discovery's window is then the longer of `[discovery] window`
and what the store holds, so a source with a week of data gives a model at once; a family's type is
judged over at most a day of it (below). A
`[[series]]` entry (`source`, `name`, `query` or `select`, `kind = "level" | "counter" | "rate"`)
pins one definition the inference would not rank.

### Reading another store's schema

A company's store is rarely organised for this: thousands of names, several spellings of one
label, per-pod series, recording rules beside their bases. Look before declaring anything
(`orchestra sources check|infer|preview`, or a plugin's tools, which may take a `url` and `auth`
before a source exists):

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
   a rate of a utilisation is a gauge, and a rule is read on its own evaluation interval. A family
   that only rose in the hour is judged over the last day too (`history`): a counter that resets
   once a day is a counter, a queue named for events (`sidekiq_retries`) that drains outside the
   incident is a gauge. Once judged, a type changes only when the samples decide it (a fall by
   part says gauge, a reset says counter), never on a name. A gauge whose samples are each a count
   of their own (OpenTelemetry's delta temporality: never negative, not carried from sample to
   sample) is read as counts; a native histogram is read by its count. Check `retyped` against
   what you know of the exporter; where it is wrong, pin the series. A counter is a flow (read as
   its increase each step); a gauge may be a stock.
3. **Find the stock candidates.** A good stock is a gauge of an amount that accumulates and
   drains (a queue's depth, items in progress, open items, a balance), with counters beside it
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
   scrape jobs (or Prometheus replicas) scrape the same targets (`notes`: `job=… only repeats
   job=…`: the same instances, an `ip-10-0-1-1` host name matching `10.0.1.1:9100`, and the same
   counts each quarter of the window), reads a counter rather than a rule over it (the rule is left
   out naming the counter), and keeps one of two families equal at every point and one count of the same pods;
   what it cannot see (two exporters that disagree a little) is yours. Read one of each quantity:
   two flows that count the same events make discovery see twice the flow, and a stock balanced
   by one while the other is read too will not balance.
6. **Check units and windows.** A label that names a unit (`unit`, `resource`, or values like
   `cpu`/`memory`) is kept in every view, so cores are never added to bytes; each definition
   carries its unit (the store's metadata, else the name's suffix). A level is read with a
   lookback of two and a half reporting intervals (at least one plus 30 s), so a missed scrape is
   no dip. A gauge reported every 5 minutes cannot show a change inside one
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

9. **Name a balance you know.** When you know which level a set of counters fills and drains,
   say so: give the level and its flows one `stock` name and each its `role` (`"level"`,
   `"inflow"` or `"outflow"`; a flow is `kind = "counter"`). Discovery tries that balance first,
   before any search, and judges it by the same evidence as any other (enough stretches, a fit
   that holds on each half of the window, the level reproduced over the hour, the shift null). A
   declaration is a hypothesis, not a binding: one that does not fit is searched like any level,
   and the reason the level is left out (if it is) says how well the declared balance fitted. A
   stock found this way records `declared` (its origin) in its evidence; its flows are still
   fitted. This is not the intended model's declared stock (a stock the owner expects, made with
   `POST /intended`): that one is drawn as a ghost, never handed to discovery, and matched to
   what discovery finds only by `link`. The level and its flows may be in different stores:

```toml
[[sources]]
name = "shop"
url = "https://shop.example/metrics"
match = ['{namespace="shop"}']
infer = false

[[sources]]
name = "biz"
url = "https://biz.example/metrics"
match = ['{job="biz"}']
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
  many series, 400 when a range asks for too many points. Orchestra waits out a 429 or 503 for
  its `Retry-After` (every reader of the source pauses with it), splits a batch the store refuses
  for its size and remembers the limit the store named, and reads at `rate` requests a second.
  A metric over the limit across an HA pair's replicas (`prometheus_replica`, `replica`) is read
  at one replica, and a recording rule over the pair is read at one replica too: a rule summed
  across replicas counts everything twice, so its base is read instead.
  Inference batches its reads across families: a tenant of a few hundred metric names costs one
  or two hundred requests to infer and a handful a discovery. Never lower the cap or raise a
  limit to fit: narrow the read. A metric too big for one query alone is named in
  `infer_source`'s notes (narrow `match` with label matchers, or pin it); a family that could not
  be read in a round keeps what the last round found of it, or is `unknown` and left out, never
  guessed. Lower `rate` when the store's owner gives Orchestra less than 5 requests a second.
- **Credentials by reference.** A token the owner keeps in a file is
  `auth = { bearer_file = "~/path/to/token" }` (or `header = { name = "API-Token", value_file = "…" }`
  for a store that wants its own header), or the short form `token_file = "~/path/to/token"` with
  `auth = "bearer"`, `"header:API-Token"` or `"basic"` (and `user`); one in the environment is
  `bearer_env`. A `url` may carry a path (Chronosphere's `https://<tenant>.chronosphere.io/data/metrics`):
  the API is joined under it. Never read the
  file, copy the token or put it in a command: the tools read it when they ask the store.

Connecting a store the owner asked for is observation: Orchestra reads it and never writes, and it
needs no further go-ahead. Choose a narrow selection from the owner's question, declare it, check
it, and say what you chose. Ask only what you cannot find out: where the credential is, when the
store refuses without one and nobody said; which environment is production, when the data cannot
tell. A store that bills per query is the owner's choice before it is read at all.

## A Prometheus-API store: the entry and every lever

This section and the three after it are the whole setup of a Prometheus-API store (Prometheus,
VictoriaMetrics, Thanos, Mimir, Chronosphere), read in place and never written. The subsections of
"Instruments and machines" above say how inference reads a schema and how a busy store is spared;
read them when a reason sends you there. Work in this order: one entry with a narrow `match`,
`sources check`, `sources infer`, then only the levers its reasons call for, one change at a time,
each said to the owner (what and why) before you make it.

```toml
[[sources]]
name = "chronosphere"                           # lower-case letters, digits, _
url = "https://tenant.chronosphere.io/data/metrics"   # Chronosphere's Prometheus API is under /data/metrics
auth = { bearer_env = "CHRONOSPHERE_TOKEN" }    # or auth = "bearer" with token_file = "~/.config/..."
prefix = "chrono"                               # its series are chrono:<name>
match = ['{service_name=~"checkout|payments"}'] # required: the owner's scope
split = ["service_name", "method", "status"]
kinds = { "*:count" = "flow", "legacy_queue_size" = "level", "debug_*" = "ignore" }
max_series = 100
rate = 2.0
max_requests_per_day = 5000
infer_every = "6h"

[sources.names]
"*_num_undelivered_messages" = "{subscription_id} messages waiting"
"grpc_client_callMillis:count" = "{method} calls completed"
"grpc_client_callMillis:sum" = "{method} calls in progress"

[sources.labels]
service = ["service", "service_name", "app"]
```

Add it with `project.config_edit.add_entry("sources", {...}, target="overlay")` (the overlay when
the store is the owner's own, as at work); the same call with the entry's `name` and only the
fields you change edits it later. `config_edit` does not check sources: the Instruments page's
`errors` does.

**`match` (required).** A list of PromQL selectors, the shape of Prometheus' `match[]`, saying the
owner's scope: a label their team's series carry (`namespace`, `service`, `service_name`, `job`,
`team`, `cluster`, `env`), narrowed by a name pattern if the scope is large. Orchestra conjoins it
into every query it sends (the label matchers every selector has), so nothing outside it is asked.
**Never one family alone** (`{__name__=~"grpc_client_callMillis.*"}`): one counter family holds
no level and nothing for its counts to balance, so no stock can come of it ("no counters
balance"). Match a service's levels and counters together (its queue depths, in-flight calls,
replicas, and its request and error counts). `{}` and `{__name__=~".+"}` refuse the source; more
than `max_names` (2,000) metric names refuses inference until the entry changes. To see the labels
and values inside a match: `source_schema`, or the Core page's External stores row (its **labels**
button). Ask the owner which part of the store is theirs when nobody said; widening past it, to
families or services they did not name, is theirs to say yes to. What you may survey beyond it is the
owner's `explore` ("Exploring beyond the match").

**`split`: the labels a family is split by.** The store's spellings; every family is split by those
it has and summed by the store over every other label. Use it when inference splits by a label
nobody wants apart (a `edge_service` with a value per caller: a series per value, crowding out the
ones that matter), or to pin the grouping the owner thinks in. Leave it out to let inference
choose: it ranks labels across the store and proposes finer splits of a split that became a stock.
A label left out of `split` is summed away everywhere, the replica label (`pod`) included: then no
attachment can count replicas by it ("Machines from a workload label"). Rows and drawers say
"summed over <labels>".

**`kinds`: only for the exceptions.** Names and metadata already say most, so most entries need none:

| Says | Read as |
|---|---|
| metadata `type=counter` | a counter: its increments are a flow |
| a gauge or untyped whose help says per interval (`delta`, `in the sampling period`) | a flow, each sample its interval's count |
| a gauge or untyped `…_count` / `…_total` (GCP's per-minute DELTA counts: `ack_message_count`, `send_request_count`) | a flow (not things held: `pod_count`, `…_pending_total`) |
| `num_…`, `oldest_…_age`, `…undelivered…`, `…outstanding…`, `…unacked…`, `…backlog…`, `…retained…` | a level |
| `:count` beside a `:sum` | a flow (a `:rate` a rate) |

Anything else is judged by how its samples behave. When one is read wrongly (its row says the
kind and why), say what it is: `"<metric or glob>" = "flow" | "level" | "ignore"`; an exact name
wins over a pattern, a longer pattern over a shorter; `ignore` is never read. The row then says
"kind: flow (declared by *:count)". A change re-infers at the next round, or at once with
`sources infer`.

**`names`: what the owner's stocks are called, by rule.** A series is called by its metric's words
and the labels that tell it from its siblings ("gcp pubsub subscription num undelivered messages
(orders)"). Once stocks and flows appear, read the metric names and label conventions of what was
found and derive **a few general rules**, each a glob with a template over the labels (`{label}`
any label, canonical or the store's spelling; `{metric}` the metric; a label a series lacks is
dropped with its brackets), so one rule names a whole family. Show the owner the rules and, beside
each current stock and flow, the name it would get:

```
"*_num_undelivered_messages" = "{subscription_id} messages waiting"
    gcp pubsub subscription num undelivered messages (orders-worker)  ->  orders-worker messages waiting
    gcp pubsub subscription num undelivered messages (billing)        ->  billing messages waiting
```

Write `[sources.names]` only on the owner's yes, and quote it when you say what you wrote. An exact
name per stock is only for an exception a rule cannot reach. A name reads nothing differently and
needs no inference: it shows at the next discovery; a name the owner gives a stock on the Dynamics
page still wins.

**The rest of the entry.** `prefix`: the series are `<prefix>:<name>`. `[sources.labels]` is an
alias map (which spellings stand for one label), never a selection: only `match` selects.
`machine = "<label>"` tags each series `machine=<prefix>.<value>`, which names a machine only for
counted traffic a `[[series]]` declares (`traffic`); on any other series it is a label, and never
makes a machine or ties one to a flow (rules 2 and 7).

**Caps, and what each costs the store.** None changes what is inferred.

| Lever | Default | Bounds | Costs the store |
|---|---|---|---|
| `rate`, `burst` | 5 a s, 10 | requests a second to this store, every project and process on this machine together | slower reads, not fewer; lower it to what the store's owner allows |
| `max_requests_per_day` | 20,000 | requests per store per UTC day; past it nothing is asked until 00:00 UTC | when spent, the source is missing: no model version is saved and the job's health is red |
| `max_series` | 200 | definitions discovery reads (12 a family at most) | each is a range read per discovery; more series, more points |
| `infer_every` | 1 h (6 h with `[[series]]`) | how often inference reads the schema again | a round costs up to `infer_requests` (1,500), typically one or two hundred for a few hundred names |
| `[discovery] every` | 5 m | how often the host rediscovers | each discovery reads the new steps only, the whole window hourly; tens of requests each |

Do the sum before you settle: discoveries a day (1,440 ÷ `every` in minutes) × one discovery's
requests, plus rounds a day (24 ÷ `infer_every` in hours) × one round's, must sit well under
`max_requests_per_day` less the web server's share (`web_share`, a fifth). At 35 requests a
discovery, every 5 minutes is about 10,000 a day: twice a 5,000 cap, so `every = "15m"` (a project
setting: `[discovery]`, read at start). Read the real costs from the run record (next section),
never guess them. `history` (7 d) is how far a new source's first read reaches, in pages of a day,
within `max_requests` (1,000 a discovery). Raising a cap is the owner's; narrowing is yours.

## Reading what Orchestra sees of a store

Each of these reads what Orchestra already has, or asks the store a bounded question; none writes.

- **`orchestra sources check`** (a plugin's `check_sources`): per source, the auth and where its
  credential comes from (`bearer from file …: present`, never the value), whether the store
  `answers`, which endpoints it serves (`metadata no` is normal for some), and the last five
  requests. It asks no series: run it first, and after every change of `url` or `auth`.
- **`orchestra sources infer --source <name>`** (`infer_source`): runs an inference round now (it
  costs one) and lists each family found, the definitions kept, and every one left out with why;
  `retyped` (a type judged from samples), what each merges (`merges queue (3 values)`), notes, and
  why it re-inferred (`re-inferred: the source's kinds changed`). The left-out reasons are what you
  act on and what you report.
- **`orchestra sources preview '<query>' --source <name>`** (`preview_query`): a query's fan-out and
  values, within `match`. Preview only aggregated queries with a label matcher.
- **The request log**, `~/.orchestrator/<key>/sources/<name>.requests.jsonl` (the last 10,000):
  every request any part of Orchestra sent the store: time, endpoint, query or `match[]`, window
  and step, series, points, bytes, milliseconds, who asked (`host`, `infer`, `page`, `web`, `cli`, `explore`),
  the run's id, the error, and `sent: false` for one refused before sending (budget, daily cap). It
  never holds a header. The Core page's row of the store shows the last twenty and today's count
  beside the cap.
- **The explorer drawer**, the Dynamics page: each left-out row, each changed-but-not-in-the-model
  name and each stock opens a drawer saying what discovery read and tried for that series: the kind
  taken and its evidence (never falls, resets, range, reporting interval), the exact query, window
  and step, what came back (points, span, a sparkline), every role tried (the counters offered to
  its balance with their R², each net-flow form and why it lost), the verdict, "summed over …" and
  "named … by …". The same is `GET /api/dynamics/explain?key=<series key>` (with the web token),
  the keys as the discovery record names them (`~/.orchestrator/<key>/model/discovered.json`,
  `left_out`). An R² of 0.00 against nothing means there was nothing to compare with: read the
  drawer, not the number.
- **The run record**, `~/.orchestrator/<key>/model/runs.jsonl` (`GET /api/dynamics/runs`; the
  Dynamics page's discovery line and its drawer): one line per discovery and per inference round:
  trigger, phases (reads, inference, fit, saving), outcome (`saved vN`, `unchanged`, `no model`,
  `failed: …`, `timed out`), `partial`, the strategy, window and step, and per source its cost:
  requests, whole and incremental reads, series, points, bytes, waiting, refused, errors, and the
  store's count today against its cap. **Health** (`GET /api/dynamics/runs/health`, the Core page's
  discovery row) is red when the last two runs failed or a store spent its daily cap; amber when a
  run is overdue, slow, partial, failed once or stopped at its deadline; each reason said.
- **`orchestra sd discover`** runs one discovery now and prints the stocks, flows and what was left
  out: after a change you want to see without waiting for `every` (it costs a discovery's reads).

From a reason to a lever: "no counters balance" or "no counter moved" → the match holds a level
without what fills it, or counts without a level (next section); "summed over <label>" where the
owner wants that label apart → `split`; a kind read wrongly → `kinds`; "too many names" or a budget
or deadline spent → narrow `match`, never raise a cap; a selector that returns nothing →
`preview_query` it; a source missing → `sources check`, then the Instruments page's `errors`.

## What makes a stock, in the owner's terms

Say it to the owner this way. A **stock** is an amount you could count at one instant: messages
waiting, calls in progress, pods running, tickets open. A **flow** is how fast something moves into
or out of one: messages published a minute, acks a minute, calls completed a second. A stock changes
only by its flows, and discovery finds a stock where a level moves as some counters say it should.
So it needs a **level** (a gauge holding a quantity) and, to balance it, **counters** that fill and
drain it, counting the same things grouped by the same labels.

- **A per-interval count is a flow**, never a stock by itself: a `:count` recording rule, a GCP
  per-minute DELTA count (`ack_message_count`), an OpenTelemetry delta. Each sample is the interval's
  count. A "since reset" or "today" total is a counter too.
- **"In progress", by Little's law.** A latency family with both a sum and a count (`_sum`/`_count`,
  or `:sum`/`:count`) gives a level of its own: calls in progress = busy time over the interval
  (arrival rate × mean latency), named "<family> in progress", by each grouping it is split by. It
  is a stock **by construction**: its completions (the count) are its outflow and its arrivals are
  derived as the completions plus its change, so its balance is exact by definition and proves
  nothing; what it adds is the arrivals' rate and a level the owner can reason about. Tell the
  owner so when it is the only stock. A latency family with a count and no sum gives no such stock.
- **GCP Pub/Sub, one subscription.** Two stocks: the **backlog**, `…_num_undelivered_messages`
  (published to its topic and not yet acked), filled by the topic's publishes
  (`…topic…_send_message_count`, or `send_request_count` for requests) and drained by acks
  (`…_ack_message_count`); and the **outstanding**, `…_num_outstanding_messages` (delivered and not
  yet acked), filled by deliveries (`…_sent_message_count`) and drained by acks and by expired ack
  deadlines (`…_expired_ack_deadlines_count`, messages handed out again). `oldest_unacked_message_age`
  is a level but not an amount: a symptom, never a stock. Match one subscription and its topic
  (`['{subscription_id="orders-worker"}', '{topic_id="orders"}']`): every subscription of a topic
  gets every publish, so a topic's publishes fill each of its subscriptions, never their sum.
- **Only flows under the match.** Counts alone give flows and no stock. Never invent the missing
  level. Ask the owner one sentence for what would close it: "Is there a gauge of what waits or is
  in flight for checkout (a queue depth, in-flight calls, replicas) I can read too?", "Does
  `grpc_client_callMillis` have a sum beside its count?" (then "in progress" follows), or, for a
  level with one side counted, "What counts what leaves it?" A level with an unmeasured outflow can
  still be pinned with its inflow, the outflow the residual (step 8 of "Reading another store's
  schema").

## Machines from a workload label

When a store's series carry a label naming the workloads (`container_name`, `service_name`,
`subscription_id`, `job`, `app`), its values are the owner's existing machines: they do the work and
will never publish on Orchestra's bus. Put the ones the owner cares about on the map as **declared
machines**, each with the instruments that measure it attached
(docs/proposals/instruments-on-machines.md):

1. List the label's values within `match` (`source_schema`, or the Core page's labels button), and
   for each the instruments whose series carry it: the source, a `[[scrape]]` of the same service.
2. Find the label counting its replicas, where one is kept: `pod` or `instance`, with several stable
   values (never one that grows without bound: a build number, a request id; never over 50). If
   `split` sums it away, the attachment takes no `instance_label` (one would be refused); say so.
3. Show the owner a list, one line per value: the machine's id (`^[a-z][a-z0-9_]{1,40}$`:
   `hk-checkout` is `hk_checkout`), its title, each attachment (instrument and match), and its
   replica label or "replicas not counted". Ask which they want declared. Never declare every value
   on your own: the label's values are a list to choose from; the owner names the machines.
4. On the owner's yes, one `POST /intended` on the events endpoint (`ORCHESTRA_EVENTS_ENDPOINT`,
   `ORCHESTRA_EVENTS_TOKEN`), quoting it; in-process, `project.intended.apply(ops, provenance)`:

```json
{"source": "supervisor", "author": "owner", "quote": "yes, checkout and payments",
 "reason": "workloads named by container_name in chronosphere",
 "ops": [
  {"op": "propose_machine", "id": "checkout", "title": "checkout", "kind": "programmatic",
   "managed": "external", "engagement": {"mode": "continuous"}},
  {"op": "propose_attachment", "machine": "checkout", "instrument": "chronosphere",
   "match": {"labels": {"container_name": "checkout"}}, "instance_label": "pod"},
  {"op": "confirm", "part": "machine", "id": "checkout"},
  {"op": "confirm", "part": "attachment", "id": "checkout_chronosphere"}]}
```

An attachment's id is `<machine>_<instrument>` (`_2` for a second of the pair), as the answer's
`changes` say. Its match labels are the source's canonical ones, after `[sources.labels]`. Without
the owner's quoted yes, stop at `propose_…`: proposals are drawn dashed, "unconfirmed", for the owner
to confirm on the Machines page (a request you then act on).

The rules that bind it (rules 2 and 7): **a series never makes a machine**, and **a label never
associates a machine with a flow**. The owner's declaration makes each machine; the label only told
you what to offer. A declared machine is shown as declared; it is **heard** only once its id (or an
`alias` of it) publishes on the bus, never because it is measured; it is **measured** by its
attachments ("never heard · last measured 2 min ago", its replicas counted per attachment, never
summed); and discovery's hypotheses of which machine drives a flow still come from events only
(`sd/attribute.py` never reads attachments), so a machine that is only measured says "none
hypothesised yet". Its route into the model is an expected effect, a prediction judged when the
flow appears (`set_expected_effect`). Discovery reads the same series with or without the
declaration: nothing is relabelled, no stock or flow is marked as the machine's.

## Exploring beyond the match

**Two scopes.** `match` is what the model reads: narrow and deliberate. `explore` is what you may
look at to choose what the model should read next: wider, and the owner's alone.

```toml
[[sources]]
name = "chronosphere"
url = "https://tenant.chronosphere.io/data/metrics"
auth = { bearer_env = "CHRONOSPHERE_TOKEN" }
match = ['{namespace="payments", service_name=~"checkout|ledger"}']
explore = ['{namespace="payments"}', '{__name__=~"gcp_pubsub_.*", project_id="payments-prod"}']
```

Without `explore`, it is `match`: nothing beyond the match may be surveyed. A selector that
selects everything refuses the source, as in `match`, and so does a `match` selector that lies
within none of `explore`'s (judged by the matchers as written: `{service_name="checkout",
namespace="payments"}` lies within `{namespace="payments"}`; two regexes are never proved, so
write `explore` plainer). **Never write or widen `explore` yourself**, through `config_edit` or
otherwise: nothing in code stops you, and that is why the rule is yours to keep. Ask the owner in
one sentence when a candidate lies outside it.

**The command.** `orchestra sources explore --source <name> [--family '<glob>'] [--limit N]
[--minutes M] [--json]` surveys `explore` beyond `match`, bounded: the metric names under each
`explore` selector, grouped into families, those outside the match first; for at most N families
(10, at most 50) their labels and each label's value count (`50+` past fifty), their metadata, and
their kind as inference would read it from a few sampled series. Columns: **family**, **in
match** (whether the model reads it already), **kind**, **reads as** (flow, level, neither),
**type** (the store's metadata), **labels (values)**, **why** (the kind's reason). The families past
N are named in a line; narrow with `--family 'gcp_pubsub_*'`. Every request is within `explore`,
counted against the store's rate and daily cap and logged `by: explore`; a survey whose worst case
(about 14 requests a family) would pass the daily cap is refused before anything is sent, with
when the cap resets: ask for fewer families. It reads only.

**The experiment discipline.** The explorer reads; discovery concludes.

1. **One change at a time**: a change to `match`, `split`, `kinds` or `names`, or an expected flow
   in the declared layer. Two at once cannot be told apart in discovery's verdict.
2. **Expected effect first**, recorded before the change is made:
   `orchestra explorer log add --change '{"source": "chronosphere", "match": [...]}' --expect "the
   undelivered-messages level gets the ack count as its outflow"`. It records the last discovery
   run as `before`.
3. **Apply it** on the owner's standing rule (narrowing and naming without asking, widening `match`
   only on their yes), or ask in one sentence.
4. **Judged by discovery's next rounds**, never by the survey: after one or more discovery runs,
   `orchestra explorer log judge <id> --verdict kept|reverted|inconclusive --why "<what the runs
   showed>"` records the runs since, the latest one's stocks, flows, mean trust, fitted flows and
   their mean R², the store's requests, and the effect (after less before).
5. **Reverted when worse**: fewer stocks kept, lower trust, worse fits or a higher store cost for
   no gain: undo the change, then judge it `reverted`. Inconclusive when the runs cannot say.

`orchestra explorer log list [--json]` reads the log (`~/.orchestrator/<key>/model/explorer.jsonl`)
first each round, so nothing that failed is retried until the data changes. The Dynamics page's
run drawer shows each experiment among the runs: what changed, what it expected, its verdict and
effect.

## `[[machines]]`: commands kept running

```toml
[[machines]]
name = "app"
command = "uv run python -m app --port 9100"
restart = "always"         # always (default) | on-failure | never
stop_grace = 10            # seconds from SIGTERM to SIGKILL
```

Each runs in the repository root in its own process group, with `ORCHESTRA_REPO`,
`ORCHESTRA_PROCESS` (the entry's name, which its announcement passes on as `process`),
`ORCHESTRA_EVENTS_ENDPOINT` and `ORCHESTRA_EVENTS_TOKEN` set, its output in its log. One that
exits is restarted after a pause that doubles (up to a minute); five quick failures in a row and
it backs off, tried again after one minute, five, fifteen, then hourly (`orchestra.process.gave_up`
once, with `next_try`; the Core page says `stopped after N crashes; next try at <time>`). One that exits 0 under
`always` runs again about once a minute: a sampler written as one reading is better a
`[[collect]]`. A name `<plugin>.<name>` is refused (plugins' processes are named so). Find what
to run from how the app is served: a `Procfile`, `docker-compose.yml` services, the `dev`/`start`
scripts in `package.json`, `[project.scripts]` in `pyproject.toml`, a `Makefile` `run` target,
the README. A container needs its runtime; prefer the command the developers use locally.

## Connecting another system: the strategies

Orchestra never calls an outside system. A machine or an instrument does, and Orchestra sees only
what they give it (`AGENTS.md` rules 1, 2 and 7): **series** (a measurement: "2 incidents open",
shown on Instruments, then Dynamics), **events** (something happened to one item, as who did it:
the Machines page, the actor a machine and the `subject` the item), or **a declared machine** (the
owner's expectation, dashed on the Machines page until heard and confirmed). Orchestra counts every
event by type and source itself (`orchestra_events_total`), so an event stream is also a flow:
never write a counter of your own events.

Take the first strategy that fits; most systems take two, one for series and one for events.

- **(a) `[[sources]]`**, a store with a Prometheus API (Prometheus, Mimir, Thanos, VictoriaMetrics,
  Chronosphere): read in place, no code. The sections above.
- **(b) `[[collect]]` or `[[scrape]]`**, one number the store lacks that one cheap call gets (open
  incidents now, issues per status). An instrument: it measures and never acts.
- **(c) A poller** that reads an API's changes since its cursor every N minutes (5 by default) and
  publishes one CloudEvent per change, as who acted. The same file run with `measure` is its
  `[[collect]]`. It runs as a `[[machines]]` entry, never as a Workflows item or role: it is a
  relay, not a machine. A workflow waits on what it relays (`jira.issue.assigned`) and declares the
  system, managed elsewhere, as `bot.<system>`.

| System | Series | Events |
|---|---|---|
| A Prometheus-API store | (a) | none: a metrics store has no item events |
| An alerting service (PagerDuty) | (c)'s `measure`: open incidents | (c): each incident's status changes |
| An issue tracker (Jira) | (c)'s `measure`: issues by status | (c): transitions and assignments |
| A chat (Slack) | (c)'s `measure`: messages and threads per channel | (c): threads started, replied, checked |

The bridges plugin is a library, not a reader: kits, fakes, templates and a scaffold
(`orchestra bridges scaffold <jira|slack|pagerduty|promql|http> <name>`); every collector is a
script in the owner's repository. Its own guide covers the kits, the fakes, credentials, clearance
and the entries; its tools are `integrate_system` and `approve_integration`. Its older direct
readers (`[bridges.jira]`, `[bridges.slack]`, `[bridges.github]`) are retired: never configure them.

To declare what the owner expects (a stock, an effect, a flow, a machine), call `POST /intended` on
the events endpoint (`ORCHESTRA_EVENTS_ENDPOINT`, with `ORCHESTRA_EVENTS_TOKEN`), with the owner's
words quoted in the provenance; read the layer with `GET /intended` and `GET /intended/design`. A
declaration runs nothing and binds no series (SPEC §4.6). A declared external machine names
itself (`^[a-z][a-z0-9_]{1,40}$`), says `managed: "external"`, joins the observed source (`alias`
→ `bot.pagerduty`) and predicts its effect ("a flow into open incidents appears"); it changes no
flow, and the owner's confirm is a request that stays proposed until answered.

## Rules for every collector

1. **Where files go.** The program in the owner's repository, `.orchestra/machines/<name>/`
   (`--root repo`), landing by a pull request like any code; the state directory
   (`--root state`) only when the owner keeps the repository clean, or for a throwaway trial. What
   changes as it runs stays in the state directory (`kits/pollers/<name>/`, `kits/cache/`). Its
   `[[machines]]` and `[[collect]]` entries go in the private overlay
   (`project.config_edit.add_entry(..., target="overlay")`), and only **after** the owner's
   approval: an entry added early does no harm to the poller (it logs `waiting for approval`), but
   its measurement fails every round.
2. **Credentials by reference only**: `token_env` (the variable must be in `orchestra run`'s
   environment, and every launched process inherits it) or `token_file` (`chmod 600`, outside every
   repository). Never a `token` key, never in a chat, never printed, logged or committed.
3. **Rates.** The kits' client limits each host for every process on the machine, retries 429 and
   5xx honouring `Retry-After`, and caches only what `keep` returns; change reads use `ttl_s=0`.
   Stay under the system's documented budget; unsure, poll less often.
4. **Compliance before the first read.** A scaffolded `poller.toml` says
   `clearance = "needs approval"`; until the owner's written yes (naming the system, the token's
   scope and "metadata only") it reads only a fake on this machine. Never change it yourself.
   **Never text**: events, series, logs and cache hold ids, keys, accounts, states, numbers and
   times; titles, descriptions and messages are dropped by `keep`. **Your session is a model too**:
   never paste a real API answer into it; use `--dry-run` and print counts.
5. **Idempotent emission.** Each id is `<name>:<type>:<key>@<stamp>` (the item's id; its change
   stamp), skipped once emitted, across restarts; the cursor is saved only after a good poll.
6. **The envelope** (SPEC §2). `type` is `<system>.<item>.<what>` (`jira.issue.transitioned`);
   `source` is who acted (`person.<system>.<account>`, `bot.<system>.<account>`, `bot.<system>`;
   the `[bridges] people` map wins, so one person is one machine); `subject` is the item, the same
   in every event about it; `time` is the system's own, RFC 3339 with a zone. **Never stamp the
   future**: an event more than 60 s ahead of this clock is published but its count is refused, so
   the flow never sees it (said only in `orchestra run`'s output).
7. **The poller is not a machine** (decision D19). It never publishes as itself, never announces
   itself, never writes a metric; it announces each actor once (`mode: "ad hoc"`, `kind`
   `person` or `program`).
8. **Ratios and flows.** A ratio is a level, never a flow. For a failure rate, publish one event
   type per outcome (`<system>.build.succeeded`, `.failed`: the outcome in the type, which is what
   is counted); print the ratio, if wanted, as a gauge over a stated window beside its counts.
9. **A fake before any real call**, then a trial on a scratch project, then the real system.
10. **Behind a corporate proxy.** Orchestra's HTTP takes `HTTPS_PROXY`, `HTTP_PROXY` and
    `NO_PROXY` from `orchestra run`'s and `orchestra web`'s environment; put `127.0.0.1,localhost`
    in `NO_PROXY`. A proxy that re-signs TLS needs its CA: for one store `[[sources]] auth =
    { ca_file = "…" }`; for the process `SSL_CERT_FILE=<a bundle with the public CAs too>`; `uv`
    reads `SSL_CERT_FILE`, or `UV_NATIVE_TLS=1`. Hosts to allow: `github.com`, `pypi.org`,
    `files.pythonhosted.org`, the model provider's API (only where an agent runs), and each system
    integrated.

## The systems

**Auth formats** (the kits' `auth_format`): Bearer for Jira Data Center, Slack, Chronosphere and
most APIs; `"Token token={token}"` with a read-only REST key for PagerDuty; `"Basic {token}"` (the
base64 of `user:apitoken`) for Jira Cloud, Jenkins and anything on HTTP Basic.

**PagerDuty** (`scaffold pagerduty`). Each poll lists the open incidents and reads by id each that
was open last poll and is not now; it emits `pagerduty.incident.<status>` with the incident id as
subject, the user in `last_status_change_by` (or `bot.pagerduty`) as source,
`last_status_change_at` as stamp. `measure` prints `pagerduty_incidents_open{service, urgency}`,
with no total beside it (a gauge is never `_total`, and a sum of its parts is the level twice).

**Jira** (`scaffold jira jira_ops`: not `jira`, which is the system's name). `[settings]`:
`base_url` (no `/rest/...`), `jql` (no `ORDER BY`; the board's saved filter), `every = "5m"`,
`per_minute = 20`, `lookback`, `overlap`, `since = "1d"` for a catch-up. `flavour`/`edition`:
`datacenter` (REST v2, a personal access token as Bearer) or `cloud` (REST v3 `/search/jql`, email
in `user_file`/`user_env` plus an API token, Basic); `auto` picks `cloud` on `*.atlassian.net`. It
emits `jira.issue.transitioned` per status change (changelog id as stamp) and
`jira.issue.assigned` per change of assignee; `measure` prints `jira_issues{status, category}`.
A changelog cut short (`changelog.total > maxResults`) needs `/rest/api/2/issue/<key>?expand=changelog`.

**Slack** (`scaffold slack <name>`). `channels` are ids, not names; `per_minute = 20`
(`conversations.history` is Tier 3). A bot token (`xoxb-`, the bot added to each channel) with
`channels:history` and `channels:read` (plus `groups:history`, `groups:read` for a private one);
posting (`chat:write`) is an Outbox draft, never the kit. The owner's own pings need a user token
with `search:read`. It emits `slack.thread.started`, `.replied`, `.checked`, `.unchecked` and
`slack.message.posted`, subject `<channel>/<thread ts>`, ids and timestamps only; `measure` prints
`slack_channel_messages_last_hour`, `slack_threads_awaiting_reply` and `slack_threads_unchecked`
by channel. How soon a thread is answered is the workflow's setting, never the poller's.

**Chronosphere** (strategy (a)). Its Prometheus API is under `https://<tenant>.chronosphere.io/data/metrics`,
authenticated by `Authorization: Bearer <a service account's token>`; the `API-Token` header is its
config API's (`auth = "header:API-Token"` if a tenant takes it on `/data/metrics`); Grafana's way is
`auth = "basic"`, `user = "chronosphere"`. The token file is read on every request, so a rotated one
needs no restart. Only where `[[sources]]` cannot serve (an auth kind not built, or a series that
must be computed and stored here), the `promql` kit (`scaffold promql <name>`: a `[[collect]]` only,
every 60 s) copies a few gauges into Orchestra's store.

**A system with no kit.** `scaffold http <name>`, or the closest template renamed: `pagerduty` for
items each with a status and who last changed it (builds, alerts, deployments; the usual one),
`jira` for a search by update time with a history, `slack` for append-only streams, `promql` for
numbers only. Write its fake on `FakeServer` (`route(method, path, query, body)` returning
`(status, json)` in the real shape, `CANARY` in every text field).

## Without the kits: `minikit.py` and a one-file poller

Where the bridges plugin is not installed, save this as `minikit.py` beside the program: the kits'
names for what the program below uses, the standard library and Orchestra only. It has no scaffold
or fakes; keep the clearance as a constant in the program.

```python
"""minikit.py: a stand-in for orchestra_bridges.kits with the same names, standard library and Orchestra only."""
import hashlib, json, os, re, signal, sys, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

def state_root():
    from orchestra.config import load_project
    return load_project().state_dir

def actor_source(system, account=None, *, bot=False):
    safe = lambda s: re.sub(r"[^a-z0-9._-]", "-", str(s).lower())
    return f"bot.{safe(system)}" if not account else f"{'bot' if bot else 'person'}.{safe(system)}.{safe(account)}"

def read_token(token_env, token_file):
    if token_env and os.environ.get(token_env, "").strip():
        return os.environ[token_env].strip()
    p = Path(token_file).expanduser() if token_file else None
    if not p or not p.is_file():
        sys.exit(f"no token: set {token_env} or put it in {token_file} (chmod 600)")
    if p.stat().st_mode & 0o077:
        sys.exit(f"{p} is readable by others: chmod 600 it")
    return p.read_text().strip()

class CachedClient:
    def __init__(self, base_url, token_env=None, token_file=None, per_minute=60, cache_dir=None, ttl_s=300, *,
                 auth_format="Bearer {token}", headers=None, retries=3):
        self.base, self.ttl, self.retries, self.gap = base_url.rstrip("/"), ttl_s, retries, 60.0 / per_minute
        self.hdr = {"Accept": "application/json", **(headers or {})}
        if token_env or token_file:
            self.hdr["Authorization"] = auth_format.format(token=read_token(token_env, token_file))
        self.cache_dir = Path(cache_dir) if cache_dir else state_root() / "kits" / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last = 0.0

    def get(self, path, params=None, *, keep=None, ttl_s=None, cache=True):
        items = [(k, x) for k, v in (params or {}).items() if v is not None
                 for x in (v if isinstance(v, (list, tuple)) else [v])]
        url = self.base + "/" + path.lstrip("/") + ("?" + urllib.parse.urlencode(items) if items else "")
        ttl = self.ttl if ttl_s is None else ttl_s
        f = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        cache = cache and keep is not None and ttl > 0        # only what keep returns reaches the disk
        if cache and f.exists() and time.time() - f.stat().st_mtime < ttl:
            return json.loads(f.read_text())
        for attempt in range(self.retries + 1):
            time.sleep(max(0.0, self.last + self.gap - time.time()))
            self.last = time.time()
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=self.hdr), timeout=30) as r:
                    body = json.load(r)
                break
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise RuntimeError(f"HTTP {e.code} from {self.base}{path}") from None
                time.sleep(min(float(e.headers.get("Retry-After") or 2 ** attempt), 300))
        body = keep(body) if keep else body
        if cache:
            f.write_text(json.dumps(body))
        return body

class Poller:
    def __init__(self, name, every_s=300, state_dir=None, *, events=None, project=None, package=None):
        from orchestra.config import load_project
        from orchestra.events import Events
        self.name, self.every_s, self.package = name, every_s, package or name
        self.dir = Path(state_dir) if state_dir else state_root() / "kits" / "pollers" / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events = events or Events.for_project(project or load_project())
        cur, ids = self.dir / "cursor.json", self.dir / "emitted.log"
        self.cursor = json.loads(cur.read_text()) if cur.exists() else None
        self.emitted = set(ids.read_text().split()) if ids.exists() else set()
        self.stopped = threading.Event()

    def _publish(self, eid, type, data, source, **ext):
        ev = self.events.publish(type, data, source=source, id=eid, **ext)
        with open(self.dir / "emitted.log", "a") as fh:
            fh.write(eid + "\n")
        self.emitted.add(eid)
        return ev

    def announce(self, source, time=None):
        eid = f"{self.name}:announce:{source}"
        if eid not in self.emitted:
            data = {"mode": "ad hoc", "kind": "program" if source.startswith("bot.") else "person",
                    "listens_for": [], "package": self.package}
            self._publish(eid, "orchestra.machine.started", data, source, **({"time": time} if time else {}))

    def emit(self, type, subject, data=None, source=None, *, key=None, stamp=None, time=None):
        if not str(source).startswith(("person.", "bot.")):
            raise ValueError(f"{type}: publish only as who acted (person.…, bot.…), never {source!r}")
        stamp = stamp or hashlib.sha1(json.dumps([type, data], sort_keys=True).encode()).hexdigest()[:16]
        eid = f"{self.name}:{type}:{key or subject}@{stamp}"
        if eid in self.emitted:
            return None
        self.announce(source, time)
        return self._publish(eid, type, data, source, subject=subject, **({"time": time} if time else {}))

    def run(self, poll, *, once=False, rounds=None):
        signal.signal(signal.SIGTERM, lambda *_: self.stopped.set())
        n, ok = 0, True
        while not self.stopped.is_set():
            before = self.cursor
            try:
                poll(self)
                tmp = self.dir / "cursor.tmp"
                tmp.write_text(json.dumps(self.cursor))
                tmp.replace(self.dir / "cursor.json")     # saved only after a good poll
                ok = True
            except Exception as e:                        # say what failed; never a body or a header
                self.cursor, ok = before, False
                print(f"{self.name}: poll failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
            n += 1
            if once or (rounds and n >= rounds):
                break
            self.stopped.wait(self.every_s)
        return 0 if ok else 1
```

The program, `pagerduty_alerts.py`: one file with its own `__main__` and its settings as constants.
It runs unchanged on the kits too (the import falls back to `minikit` only when they are missing);
a scaffolded program keeps the scaffold's shape instead.

```python
"""PagerDuty -> pagerduty.incident.<status>, as who changed it (poll); open incidents as series (measure)."""
import os, sys, urllib.parse
try:
    from orchestra_bridges.kits import CachedClient, Poller
    from orchestra_bridges.kits.poller import actor_source
except ImportError:
    from minikit import CachedClient, Poller, actor_source

CLEARANCE = "needs approval"     # the owner's word turns it to "approved"; until then only a fake is read

def client(**kw):
    url = os.environ.get("PAGERDUTY_API", "https://api.pagerduty.com")
    if CLEARANCE != "approved" and urllib.parse.urlsplit(url).hostname not in ("127.0.0.1", "localhost"):
        sys.exit(f"reading {url} is not cleared: CLEARANCE = {CLEARANCE!r}")
    kw = {"per_minute": 30, "ttl_s": 240, **kw}
    return CachedClient(url, token_env="PAGERDUTY_TOKEN", token_file="~/.config/orchestra-bridges/pagerduty-token",
                        auth_format="Token token={token}", headers={"Accept": "application/vnd.pagerduty+json;version=2"}, **kw)

def meta(i):                     # what is kept of an incident: never its title or a name
    by = i.get("last_status_change_by") or {}
    return {"id": i["id"], "status": i["status"], "urgency": i.get("urgency"),
            "service": (i.get("service") or {}).get("id"), "changed_at": i.get("last_status_change_at"),
            "by": by.get("id") if by.get("type") == "user_reference" else None}

def open_incidents(api):
    out, offset = [], 0
    while True:
        page = api.get("/incidents", {"statuses[]": ["triggered", "acknowledged"], "offset": offset, "limit": 100},
                       keep=lambda b: {"incidents": [meta(i) for i in b.get("incidents") or []], "more": bool(b.get("more"))})
        out += page["incidents"]
        if not page["more"]:
            return out
        offset += 100

def make_poll(api):
    def poll(p):
        now_open = open_incidents(api)
        gone = [iid for iid in (p.cursor or {"open": []})["open"] if iid not in {i["id"] for i in now_open}]
        closed = [api.get(f"/incidents/{iid}", keep=lambda b: meta(b["incident"]), ttl_s=0) for iid in gone]
        for i in now_open + closed:
            p.emit(f"pagerduty.incident.{i['status']}", i["id"], {"urgency": i["urgency"], "service": i["service"]},
                   source=actor_source("pagerduty", i["by"]), stamp=i["changed_at"], time=i["changed_at"])
        p.cursor = {"open": sorted(i["id"] for i in now_open)}
    return poll

def measure(api):
    n = {}
    for i in open_incidents(api):
        n[(i["service"], i["urgency"])] = n.get((i["service"], i["urgency"]), 0) + 1
    for (service, urgency), count in sorted(n.items()):
        print(f'pagerduty_incidents_open{{service="{service}",urgency="{urgency}"}} {count}')

if __name__ == "__main__":
    if sys.argv[1:2] == ["measure"]:
        measure(client())
    else:
        sys.exit(Poller("pagerduty_alerts", every_s=300).run(make_poll(client()), once="--once" in sys.argv))
```

Its test, `test_pagerduty_alerts.py` (`python test_pagerduty_alerts.py` prints `ok`):

```python
"""python test_pagerduty_alerts.py: the test, against a fake of /incidents with a canary in every title."""
import contextlib, io, json, os, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from orchestra.events import Events

CANARY = "CANARY-7f3a"
SERVICE = {"type": "service_reference", "id": "PSVC1"}
WORLD = {"PINC1": {"status": "triggered", "by": SERVICE, "at": "2026-11-02T10:00:00Z"},
         "PINC2": {"status": "acknowledged", "by": {"type": "user_reference", "id": "PUSER1"}, "at": "2026-11-02T10:03:00Z"}}

def shape(iid, w):
    return {"id": iid, "title": CANARY, "status": w["status"], "urgency": "high", "service": SERVICE,
            "last_status_change_at": w["at"], "last_status_change_by": {**w["by"], "summary": CANARY}}

class Fake(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Authorization") != "Token token=test-token":
            return self.send_error(401)
        path = self.path.split("?")[0]
        if path == "/incidents":
            body = {"incidents": [shape(k, w) for k, w in WORLD.items() if w["status"] != "resolved"], "more": False}
        elif path.startswith("/incidents/") and path[11:] in WORLD:
            body = {"incident": shape(path[11:], WORLD[path[11:]])}
        else:
            return self.send_error(404)
        raw = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(raw)
    def log_message(self, *a):
        pass

def test():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tmp = Path(tempfile.mkdtemp())
    os.environ.update(PAGERDUTY_API=f"http://127.0.0.1:{srv.server_port}", PAGERDUTY_TOKEN="test-token")
    import pagerduty_alerts as pd
    def poll_once():
        api = pd.client(cache_dir=tmp / "cache", ttl_s=0)
        pd.Poller("pagerduty_alerts", state_dir=tmp / "state", events=Events(tmp / "events.jsonl")).run(pd.make_poll(api), once=True)
        return [json.loads(x) for x in (tmp / "events.jsonl").read_text().splitlines()]
    changes = lambda evs: [(e["type"], e["subject"], e["source"]) for e in evs if e["type"] != "orchestra.machine.started"]
    assert changes(poll_once()) == [("pagerduty.incident.triggered", "PINC1", "bot.pagerduty"),
                                    ("pagerduty.incident.acknowledged", "PINC2", "person.pagerduty.puser1")]
    WORLD["PINC1"] = {"status": "resolved", "by": {"type": "user_reference", "id": "PUSER2"}, "at": "2026-11-02T10:20:00Z"}
    evs = poll_once()                                           # a restart: cursor and emitted ids read back
    assert changes(evs)[2:] == [("pagerduty.incident.resolved", "PINC1", "person.pagerduty.puser2")], changes(evs)
    assert sum(e["type"] == "orchestra.machine.started" for e in evs) == 3     # each actor announced once
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        pd.measure(pd.client(cache_dir=tmp / "cache"))
    assert 'pagerduty_incidents_open{service="PSVC1",urgency="high"} 1' in out.getvalue()
    files = [p.read_text() for p in tmp.rglob("*") if p.is_file()]
    assert not any(CANARY in s or "test-token" in s for s in [out.getvalue(), *files]), "text or token leaked"
    print("ok")

if __name__ == "__main__":
    test()
```

The entries, after the owner's approval, with Orchestra's Python from the repository:

```python
import sys
from orchestra.config import load_project
p = load_project(); d = p.repo_root / ".orchestra" / "machines" / "pagerduty_alerts"   # or p.state_dir / "machines" / ...
for array, entry in [("machines", {"name": "pagerduty_alerts", "command": f"{sys.executable} {d}/pagerduty_alerts.py",
                                  "restart": "always"}),
                     ("collect", {"name": "pagerduty_alerts", "command": f"{sys.executable} {d}/pagerduty_alerts.py measure",
                                  "every": "5m", "timeout": "60s"})]:
    print(p.config_edit.add_entry(array, entry, target="overlay").what)
```

`[[machines]]` is the poll loop (restarted whenever it exits); `[[collect]]` the instrument of the
same name, on the same rhythm. A trial against the fake should publish
`pagerduty.incident.triggered` on `PINC001` as `bot.pagerduty` and
`pagerduty.incident.acknowledged` on `PINC002` as `person.pagerduty.puser01`, each actor announced
once, and two points of `pagerduty_incidents_open`.

## Confirming an integration, and what goes wrong

| Check | What you should see |
|---|---|
| the program's test | passes against the fake, with the canary and token check |
| `orchestra bridges integrations` | the poller `approved`, its token's variable name or file, scheduled, `[[collect]]` `yes`, no guesses left |
| `<state>/logs/machines/<name>.log` | `poll N: K events`; no `poll failed` |
| `<state>/logs/instruments/<name>.log` | `wrote N points` |
| `orchestra metrics series` | the measured series, labelled `instrument=<name>` |
| `orchestra sources check` / `infer` | the source answers; its definitions kept (strategy (a)) |
| Instruments page | the entry, its interval, last write, no failures |
| Machines page | `bot.<system>` and `person.<system>.<id>`, edges by event type, hand-offs; **no node named after the poller** |
| Dynamics page | after an hour of data, the series as a stock or flow, its flows' hypotheses naming the actors |

A hand-off is drawn only when two different actors act on one subject; one actor per subject gives
none, and that is correct. Grep for a token's value by its shape, never the word:
`grep -rEn '(xox[bpa]-|Bearer [A-Za-z0-9._-]{12,}|[A-Za-z0-9+/=_-]{32,})' <overlay> <the program's directory>`.

- **"the environment variable X is not set" / "no token file at …"**: the owner sets it, never in
  the chat; "readable by others" means `chmod 600`. A variable in your shell but not in
  `orchestra run`'s environment is invisible to what it launches.
- **"… is not cleared"** or **`waiting for approval`**: the compliance check working. Use the fake
  (`--base-url http://127.0.0.1:…`) until the owner approves; then it polls on its own.
- **HTTP 401 or 403**: the wrong token or a missing scope (above). Look at the status code only,
  never the body.
- **HTTP 429**: raise `every` or `ttl`, lower `per_minute`, narrow the query; for a source, lower
  `rate` (its daily cap shows in `orchestra sources check`).
- **Nothing on the Machines page**: is the process running (Core page, its log)? `poll N: 0
  events` on a first run means nothing changed within `lookback`; already-emitted ids are in
  `kits/pollers/<name>/`.
- **Nothing on the Instruments page**: the `[[collect]]` entry is missing (`/api/project`), the
  command fails (`logs/instruments/`), or it prints a series named `orchestra_*` (refused).
- **No hand-offs**: the subject must be the item (the key, the incident id, the thread), never a
  channel alone, a timestamp or the poller's name.
- **"a poller publishes only as the person or bot who acted"**: use `actor_source` (rule 7).
- **The same change twice under different ids**: the stamp moved without a change (a hash over a
  timestamp), or two collectors read the same items.

## Patching an installed plugin: `.orchestra/overrides/` and `.orchestra/plugins/`

Orchestra's environment is not an editable install. To fix a bug in an installed plugin now, write
`.orchestra/overrides/<name>.py` in the repository:

```python
TARGET = "tasking.gate:run_specs"            # module:attribute
PACKAGE = "orchestra-tasking==0.9.2"         # the version installed now (pip show / importlib.metadata)
KIND = "wrap"                                # wrap: override(original) returns the replacement; replace: override is it
ISSUE = "danroblewis/orchestra-tasking#41"   # the upstream issue asking for the real fix
def override(original):
    def run_specs(*a, **kw):
        ...
    return run_specs
```

It is applied on the next plugin load (a change to `orchestra.toml`, or a restart of `orchestra
run` and `orchestra web`) and before every plugin command, so a plugin process picks it up when it
restarts. Check the Core page (or `GET /api/plugins`, `local`): `applied`, `stale` (another version
is installed: the upstream fix may have landed; remove the override), or `failed` with the error.
It patches the attribute on its module only: code that already took a copy (`from x import y`)
keeps the original, so prefer a target that is looked up when called. A project's own plugin goes
in `.orchestra/plugins/<name>/__init__.py` with `def plugin(project): return Plugin(...)`. Both are
code: they land as the project's work mode says, and every override names its upstream issue.

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
- A workload label's values are a list for the owner to choose from, never machines you declare
  on your own; a declared machine is measured by its attachments, heard only by its events.
- A secret in either file is wrong; a private value goes to the overlay, a credential to the
  environment.
