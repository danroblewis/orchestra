# Writing a machine: measurements and events

A machine is any program of yours that Orchestra observes. This page covers how a program's
measurements reach the project's metrics store, so they show up in the web UI and are offered to
discovery, and how to have `orchestra run` keep the program running. Nothing here needs Orchestra's
library: a script that prints two lines is enough.

There are three ways, simplest first:

1. **A script collector** (`[[collect]]`): `orchestra run` runs your script on an interval and
   stores what it prints.
2. **A scrape** (`[[scrape]]`): `orchestra run` reads a URL that serves Prometheus metrics, such
   as a program's `/metrics` or an exporter's.
3. **A long-running program** (`[[machines]]`): `orchestra run` keeps it running; it serves its
   measurements for a scrape, or writes them with the Python helper.

All three are declared in `orchestra.toml`, committed with the repository, and take effect within
seconds of the file changing, without restarting `orchestra run`.

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
name = "disk"                    # the machine's id: letters, digits, . _ -
command = "machines/disk.sh"     # split like a shell would, not run by one
every = "60s"                    # how often (default 60 s)
timeout = "20s"                  # how long one run may take (default 10 s, never more than every)
```

Every `every`, `orchestra run` runs the command in the repository root, with `ORCHESTRA_REPO` (the
root) and `ORCHESTRA_MACHINE_LOG` (its log) set, reads its standard output (below), and writes each
series to the project's store with two labels added: `project` and `machine = "disk"`. Its standard
error goes to its log, `<state>/logs/machines/disk.log`, with a line per run saying how many points
it wrote. The command is not run by a shell: a file in the repository is named with a slash
(`machines/disk.sh` or `./disk.sh`), and a pipeline goes in the script.

A run that exits non-zero, takes longer than `timeout` (it is killed, with what it started) or
cannot start writes nothing that round; the host's log and the collector's log say why, and
`orchestra_collect_failures_total{collector="disk"}` counts it. The next round runs on time.

The collector appears on the Machines page as the machine `disk`, run on a schedule, with its
series and its log: `orchestra run` announces it on the collector's behalf when it starts
collecting. A test of it is a test of a script: run it and check what it prints.

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
- `machine` and `project` labels in the output are replaced with the collector's own.
- **A series whose name starts with `orchestra_` is refused**, with a line in the host's log
  saying to rename it: the prefix is Orchestra's own.

## Scraping a program that serves metrics

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
failures (anything but a 200, or no answer within the timeout). The machine `app` appears on the
Machines page as running continuously. Orchestra reads Prometheus's text format only; it does not
take pushes. A remote Prometheus-compatible store can also be read in place, without copying,
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

Serve its measurements on a port and add a `[[scrape]]` of the same name, as above: the launcher
keeps it running and the scrape reads it, and the two are one machine. (Only a `[[scrape]]` may
share a `[[machines]]` entry's name; a `[[collect]]` with one is refused.)

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

**Which `python` runs it.** The command runs with the `PATH` that `orchestra run` was started with.
Give an interpreter's full path, or `uv run python ...` when the project's own `pyproject.toml`
lists what the program needs.

## Naming

- Name a series for what it measures, in plain words with its unit: `disk_free_bytes`,
  `repo_files`, `weather_temperature_celsius`, `bitcoin_price_usd`. Whether it is a stock, a flow
  or neither is the model's business, not the name's.
- **Never start a name with `orchestra_`.** The prefix is Orchestra's own: a collector's is
  refused, and discovery leaves such series out (its "left out" list says so).
- A **counter** (a running count that only goes up: things done, bytes sent) ends in `_total`:
  `files_written_total`. Starting again from zero after a restart is fine (a reset, as in
  Prometheus). Discovery reads counters as flows.
- Anything else is a **level** (a gauge: how much there is now). Discovery may find a level is a
  stock when counters explain its changes.

## Labels

- `machine=<id>`: the machine that wrote it. A collector's and a scrape's points get their name;
  discovery attributes flows to machines by it, and the machine's dialog lists its series.
- `instance=<n>` when several instances of one machine run.
- Other labels split one measurement into several series (`disk="/"`, `city="Denver"`). Keep their
  values few: each value is a series of its own.

## How often

Write every series on a schedule (every few seconds to a minute), even when the value has not
changed; a collector and a scrape do. A machine is taken to be alive while its writes keep coming;
a level written only when it changes looks, between writes, like a machine that stopped. The
`[discovery] step` (30 s by default) is the finest grain discovery sees.

## Events, and the Python helper (optional)

Measurements are all most machines need. A machine that also takes part in the event bus (it
publishes what it did, or listens for what others did) publishes CloudEvents through Orchestra's
Python helper, `orchestra.events.Events` (`SPEC.md` §2), and announces itself when it starts with
`orchestra.machine.started`: `mode` (`continuous`, `scheduled` or `ad hoc`), `kind` (`program`),
`listens_for` (the event types it reads) and `log` (its log file, shown in its dialog when it is
inside the repository or the state directory). Collectors and scrapes are announced for you.

A Python program may also write its measurements with the helper instead of serving them, in the
environment Orchestra is installed in (or with Orchestra as a dependency:
`uv add "orchestra @ git+https://github.com/danroblewis/orchestra"`):

```python
import os, shutil, time
from orchestra.config import load_project
from orchestra.events import Events
from orchestra.metrics import Point, for_repo

project = load_project()                      # ORCHESTRA_REPO (the launcher sets it), else the working directory
store = for_repo(project.repo_root)           # the store orchestra.toml configures; adds the project label
Events.for_project(project, source="telemetry").publish("orchestra.machine.started", {
    "mode": "continuous", "kind": "program", "listens_for": [], "log": os.environ.get("ORCHESTRA_MACHINE_LOG")})
while True:
    store.write([Point("disk_free_bytes", shutil.disk_usage(project.repo_root).free, time.time(), {"machine": "telemetry"})])
    time.sleep(30)
```

Keep each measurement a small function a test can call, and the loop under
`if __name__ == "__main__":`, so importing the module (as a test does) writes nothing and never
hangs. `Point(series, value, ts, labels)` takes unix seconds; `store.write([...])` takes the series
of one moment together. Don't write to a store URL of your own choosing, or to the file yourself:
`for_repo` writes where the web UI and discovery read.
