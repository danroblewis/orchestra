# Writing machines and measurements

Orchestra keeps two things apart:

- A **machine** does actual work: a program, an AI agent, a person. It is known by its
  **events**: it shows up on the event bus under its CloudEvents `source`, publishing what it did
  and listening for what others did ([Events](#events)). A machine does not produce metrics.
- An **instrument** measures the running system and never acts on it. Its measurements go to the
  project's metrics store, where the web UI shows them and discovery builds the model from them.
  Measurements are kept apart from the machines so they can test what we believe about them.

There are three kinds of instrument, simplest first:

1. **A script collector** (`[[collect]]`): `orchestra run` runs your script on an interval and
   stores what it prints.
2. **A scrape** (`[[scrape]]`): `orchestra run` reads a URL that serves Prometheus metrics, such
   as a program's `/metrics` or an exporter's.
3. **A source** (`[[sources]]`): another time-series store, read in place at each discovery
   (`USING_ORCHESTRA.md`, SPEC §4.4).

A plugin may add instruments too (`Plugin.collectors`, `PLUGINS.md`). Instruments are shown on
the Instruments page (`/instruments`): what each is, its target, how often it runs, its last
write, its failures and its log. They are not machines and are not on the Machines page.

A program you want kept running goes under `[[machines]]` ([below](#a-long-running-program)): it
is a machine by the events it publishes. Nothing here needs Orchestra's library: a script that
prints two lines is enough, and events go over HTTP. Everything is declared in `orchestra.toml`,
committed with the repository, and takes effect within seconds of the file changing, without
restarting `orchestra run`.

## A script collector

```sh
#!/bin/sh
# machines/disk.sh: free disk space and the files in the repository.
set -eu
echo "disk_free_bytes $(df -Pk . | awk 'NR == 2 { print $4 * 1024 }')"
echo "repo_files $(git ls-files | wc -l)"
```

Make it executable (`chmod +x machines/disk.sh`), try it (`./machines/disk.sh` prints the two
lines), and declare it:

```toml
[[collect]]
name = "disk"                    # the instrument's name: letters, digits, . _ -
command = "machines/disk.sh"     # split like a shell would, not run by one
every = "60s"                    # how often (default 60 s)
timeout = "20s"                  # how long one run may take (default 10 s, never more than every)
```

Every `every`, `orchestra run` runs the command in the repository root, with `ORCHESTRA_REPO` (the
root) and `ORCHESTRA_MACHINE_LOG` (its log) set, reads its standard output (below), and writes each
series to the project's store with two labels added: `project` and `instrument = "disk"` (which
instrument measured it). Its standard error goes to its log, `<state>/logs/instruments/disk.log`,
with a line per run saying how many points it wrote. The command is not run by a shell: a file in the repository is named with a slash
(`machines/disk.sh` or `./disk.sh`), and a pipeline goes in the script.

A run that exits non-zero, takes longer than `timeout` (it is killed, with what it started) or
cannot start writes nothing that round; the host's log and the collector's log say why, the
Instruments page shows the failure and the last error, and
`orchestra_collect_failures_total{collector="disk"}` counts it. The next round runs on time.

The collector appears on the Instruments page as `disk`, a script, with its target, its interval,
its last write and its log. Nothing is announced on the bus for it, and it is not a machine. A
test of it is a test of a script: run it and check what it prints.

**A ready-made one: your tests.** `python -m orchestra.instruments.test_reports --reports
'reports/*/*.xml'` reads the JUnit XML (or pytest report log) your test runner writes and prints
the tests by kind and outcome, the flaky and the confirmed ones, and with `--history` counters of
tests added and removed, so the test count can be a stock. One `[[collect]]` entry adopts it
(`USING_ORCHESTRA.md` section 3.4).

## What a collector prints

The Prometheus text format, one sample per line:

```
# HELP disk_free_bytes Free space on the volume.   (optional)
# TYPE disk_free_bytes gauge                        (optional)
disk_free_bytes{volume="/"} 201491873792
files_written_total 42 1761500000000
```

- `name{label="value",...} value`, labels optional. A label value escapes `\\`, `\"` and `\n`.
- An optional timestamp after the value, in **milliseconds** since 1970. Without one, the point
  takes the time the run began; that is usually what you want.
- `#` lines are comments; `# TYPE` says what a series is. Counters, gauges and untyped series are
  stored as they are. Of a histogram or a summary only its `_count` and `_sum` are kept; its
  buckets and quantiles are left out (a distribution's shape is not a stock or a flow).
- A value that is not a number (`NaN`, `+Inf`) is left out. A line that cannot be read is skipped,
  and the host's log says so once; the rest of the output is still written.
- Every label in the output is kept as it is, `machine` included: it is the measured system's own
  dimension (which baker, say), and says nothing to Orchestra about which machine does the work.
  Orchestra adds `project` and `instrument`; a label of the output with either name is kept as
  `exported_project` or `exported_instrument`, as Prometheus does.
- **A series whose name starts with `orchestra_` is refused**, with a line in the host's log
  saying to rename it: the prefix is Orchestra's own.

## Scraping a URL that serves metrics

A program that already serves the Prometheus format (a web service with `/metrics`, an exporter
such as `node_exporter`) needs no script:

```toml
[[scrape]]
name = "app"
url = "http://127.0.0.1:9100/metrics"
every = "30s"                    # default 60 s
timeout = "10s"                  # default 10 s
```

The body is read like a collector's output, with the same labels and the same handling of
failures (anything but a 200, or no answer within the timeout). The scrape `app` appears on the
Instruments page as a URL. Orchestra reads Prometheus's text format only; it does not take
pushes. A remote Prometheus-compatible store can also be read in place, without copying,
under `[[sources]]` (`USING_ORCHESTRA.md`, SPEC §4.4).

## A long-running program

A program that should run all the time (a service, a program that follows the bus) goes under
`[[machines]]`:

```toml
[[machines]]
name = "app"                     # letters, digits, . _ -
command = "bin/app --port 9100"  # split like a shell would, not run by one
restart = "always"               # always (the default) | on-failure | never
stop_grace = 10                  # seconds from SIGTERM to SIGKILL (default 10)
```

It is a machine by the events it publishes ([Events](#events)), not by being launched. A program
may also serve `/metrics` for a `[[scrape]]` to read: that makes the scrape an instrument, not
the program a machine. Instrument names are their own namespace, so a `[[scrape]]` or a
`[[collect]]` may share a `[[machines]]` entry's name; they are still two things, a process and
an instrument.

`orchestra run` starts it in the repository root with `ORCHESTRA_REPO` and `ORCHESTRA_MACHINE_LOG`
set, sends its output to `<state>/logs/machines/app.log`, and starts it again when it exits, after
a pause that doubles with each quick exit (up to a minute). Only failing exits (a non-zero code)
count towards giving up: after five in a row, each within a minute of starting, it is given up on,
which its log, the host's log and the bus (`orchestra.process.gave_up`) say; it is tried again when
its entry changes or `orchestra run` restarts. A program that exits 0 is started again after the
pause and never given up. For a measurement on a clock, a `[[collect]]` script is simpler.

`orchestra.toml` is read again whenever it changes: an entry added (by a merge into the
checked-out branch, say) starts within seconds, one removed stops, and one whose entry changed
restarts. The program itself is read only when it starts, so a change to it alone takes effect at
its next restart. Stopping `orchestra run` stops it: SIGTERM, then SIGKILL after its `stop_grace`.
The Core page lists what the host runs, with each process's state, restarts and log.

A plugin's processes run under the name `<plugin>.<name>`, so a name of yours never replaces one
of theirs; a `[[machines]]` name of that form is refused.

**Which `python` runs it.** Inside commands Orchestra runs, `python` is Orchestra's Python, even
inside `sh -c`. Use `uv run python` or `.venv/bin/python` for your project's. Orchestra's Python is
the one it runs in, whatever is first on the `PATH` `orchestra run` was started with, so Orchestra
and its plugins are importable; the `PATH` each command gets begins with a directory where
`python` and `python3` are it. A `[[collect]]` command follows the same rule.

## Naming

- Name a series for what it measures, in plain words with its unit: `disk_free_bytes`,
  `repo_files`, `weather_temperature_celsius`, `bitcoin_price_usd`. Whether it is a stock, a flow
  or neither is the model's business, not the name's.
- **Never start a name with `orchestra_`.** The prefix is Orchestra's own: a collector's is
  refused, and discovery leaves such series out (its "left out" list says so). The one such series
  discovery reads is `orchestra_events_total{type, source}`, Orchestra's count of the bus: the only
  series derived from the event log, and secondary to what the instruments measure.
- A **counter** (a running count that only goes up: things done, bytes sent) ends in `_total`:
  `files_written_total`. Starting again from zero after a restart is fine (a reset, as in
  Prometheus). Discovery reads counters as flows.
- Anything else is a **level** (a gauge: how much there is now). Discovery may find a level is a
  stock when counters explain its changes.

## Labels

- `instrument=<name>`: the instrument that measured it, added by Orchestra. It is provenance:
  discovery groups an instrument's series to tell when it was writing, and never reads it to say
  which machine does a flow's work.
- Labels split one measurement into several series (`disk="/"`, `city="Denver"`, `instance="2"`).
  Keep their values few: each value is a series of its own.
- A `machine` label is kept like any other. A series labelled `machine=X` never makes a machine
  X (nor an instance of it), never keeps X active, is not listed on X's card, and never
  associates X with a flow: a card lists the flows its
  events are hypothesised to be associated with.

## How often

Write every series on a schedule (every few seconds to a minute), even when the value has not
changed; a collector and a scrape do. An instrument is taken to be alive while its writes keep
coming; a level written only when it changes looks, between writes, like an instrument that
stopped. The
`[discovery] step` (30 s by default) is the finest grain discovery sees.

## Events

A machine takes part in the event bus (it publishes what it did, or listens for what others did)
over HTTP, through the events
endpoint `orchestra run` serves (`SPEC.md` §3.1, `USING_ORCHESTRA.md` §5.2). What it launches gets
the address in `ORCHESTRA_EVENTS_ENDPOINT` and the token in `ORCHESTRA_EVENTS_TOKEN`; a program it
did not launch runs `eval "$(orchestra events endpoint --env)"` for both.

```bash
# announce yourself once, at start: a plain event, from your own source
curl -sf -X POST "$ORCHESTRA_EVENTS_ENDPOINT/events" \
  -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN" -H "Content-Type: application/json" \
  -d '{"type": "orchestra.machine.started", "source": "telemetry",
       "data": {"mode": "continuous", "kind": "program", "listens_for": ["disk.full"]}}'

# publish what happened; an id of your own makes a retry write it once
curl -sf -X POST "$ORCHESTRA_EVENTS_ENDPOINT/events" \
  -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN" -H "Content-Type: application/json" \
  -d '{"type": "disk.cleaned", "source": "telemetry", "id": "clean-2026-10-27", "data": {"freed_bytes": 1200000}}'

# read what others published after an offset, waiting up to 30 s for one
curl -sf "$ORCHESTRA_EVENTS_ENDPOINT/events?after=0&types=disk.full&wait=30" \
  -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN"
# -> {"ok": true, "events": [...], "next": 42}: read again with after=42
```

`orchestra.machine.started` takes `mode` (`continuous`, `scheduled` or `ad hoc`), `kind`
(`program`, `agent`, `person` or `service`), `listens_for` (the event types it reads) and `log`
(its log file, `$ORCHESTRA_MACHINE_LOG` for a launched process, shown in its dialog when it is
inside the repository or the state directory). Instruments are not announced: they are not
machines.

### Being seen

A machine is seen, and active, by its own events alone: its announcements, what it publishes and
any heartbeat it sends (a plain event of its own type). Writing series does not count. It is
active while its last event is within two and a half beats of its own cadence, and at least two
minutes. The cadence is observed, never announced: the median gap between its recent beats, where
events less than 48 s apart are one beat (a restart's announcements, one run's events). So a job
that runs every hour and publishes once a run is active between runs and quiet after a few missed
ones (a cadence over a day counts as a day). A continuous machine that has nothing to publish for
long stretches should send a heartbeat now and then, or it shows as quiet.

## How a machine is associated with flows

The model has stocks and flows, and no machines: how a machine's work relates to the flows is not
known. It may touch no flow, one or several, and several machines may contribute to one flow.
Orchestra infers it, at each discovery, as hypotheses with their evidence and a confidence from 0
to 1, from the machines' events alone:

- **its own events**: the flow's counter is itself one machine's event count;
- **events on the bus**: a machine's events of one type (its instances summed) match the counter's
  increments step by step, at the same step or one step either way: equal in at least 90% of the
  steps either moved, or correlated at least 0.9 with totals within a factor 2.

Nothing declares an association: not `orchestra.toml`, not a plugin, and not a label (a series'
`machine` or `instrument` label, or a counted-traffic counter's producer or consumer, is never
read for it). An association never changes a flow's equation or the stocks and flows. The
Dynamics page lists each flow's hypotheses with why; a flow with none reads "no machine associated
yet". Orchestra's own `orchestra.*` events are never candidates.

**Tip.** If a machine publishes one event per unit of the work it does (`order.baked` for each
loaf), discovery can match it to the counter that measures that work (`loaves_baked_total`). An
event per batch, or a summary event now and then, is much harder to match.

The limits: a match is a correlation in time, not a cause; two machines reacting to the same
events both match; and discovery may not tell apart two similar flows between the same stocks, so
a hypothesis may belong to a flow's twin.

## The Python helper (optional)

A Python program may use Orchestra's library instead of HTTP, in the environment Orchestra is
installed in (or with Orchestra as a dependency:
`uv add "orchestra @ git+https://github.com/danroblewis/orchestra"`).

A machine publishes and reads the same events with `orchestra.events.Events`
(`USING_ORCHESTRA.md` §5.2):

```python
import os
from orchestra.config import load_project
from orchestra.events import Events

project = load_project()                      # ORCHESTRA_REPO (the launcher sets it), else the working directory
events = Events.for_project(project, source="baker")
events.publish("orchestra.machine.started", {
    "mode": "continuous", "kind": "program", "listens_for": ["order.placed"], "log": os.environ.get("ORCHESTRA_MACHINE_LOG")})
events.publish("order.baked", {"loaves": 1}, subject="order-17")   # one event per loaf baked
```

An instrument written in Python may write its measurements with `orchestra.metrics.for_repo`
instead of printing them for a `[[collect]]`:

```python
import shutil, time
from orchestra.config import load_project
from orchestra.metrics import Point, for_repo

project = load_project()
store = for_repo(project.repo_root)           # the store orchestra.toml configures; adds the project label
while True:
    store.write([Point("disk_free_bytes", shutil.disk_usage(project.repo_root).free, time.time(), {"instrument": "disk"})])
    time.sleep(30)
```

Keep each measurement a small function a test can call, and the loop under
`if __name__ == "__main__":`, so importing the module (as a test does) writes nothing and never
hangs. `Point(series, value, ts, labels)` takes unix seconds; `store.write([...])` takes the series
of one moment together. Don't write to a store URL of your own choosing, or to the file yourself:
`for_repo` writes where the web UI and discovery read.
