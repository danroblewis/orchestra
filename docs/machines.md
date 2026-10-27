# Writing a machine: emitting metrics and events

A machine is any program of yours that Orchestra observes. This page covers what a program in a
project needs to do so its measurements reach the project's metrics store, show up in the web UI
and are offered to discovery, and how to have `orchestra run` keep it running. You need Orchestra
installed in the program's environment (`uv add orchestra`, or run it with the environment
`orchestra` is installed in); nothing else.

## A whole machine

```python
"""Telemetry: free disk space and the files in the repository, every 30 s."""

import os
import shutil
import subprocess
import time

from orchestra.config import load_project
from orchestra.events import Events
from orchestra.metrics import Point, for_repo

MACHINE = "telemetry"                          # the machine's id: its events' source, its series' label
project = load_project()                       # ORCHESTRA_REPO (the launcher sets it), else the working directory
store = for_repo(project.repo_root)            # the store orchestra.toml configures; adds the project label
Events.for_project(project, source=MACHINE).publish("orchestra.machine.started", {
    "mode": "continuous", "kind": "program", "listens_for": [],
    "log": os.environ.get("ORCHESTRA_MACHINE_LOG")})          # where its output goes, for its dialog

while True:
    now, labels = time.time(), {"machine": MACHINE}
    files = subprocess.run(["git", "ls-files"], cwd=project.repo_root, capture_output=True, text=True).stdout
    store.write([Point("disk_free_bytes", shutil.disk_usage(project.repo_root).free, now, labels),
                 Point("repo_files", files.count("\n"), now, labels)])
    time.sleep(30)
```

Save it in the repository (say `machines/telemetry.py`), declare it (below), and commit both.

## Writing series

- **Open the project's store with `orchestra.metrics.for_repo()`.** It reads `orchestra.toml`
  (`[metrics] url`: the file store, `<state>/metrics.jsonl`, by default, or VictoriaMetrics), so
  points land where the web UI and discovery read. Don't write to a store URL of your own
  choosing, and don't write the file yourself.
- **Every point carries the `project` label**; `for_repo` adds it. A series without it is shown
  nowhere (the Core page's catalogue says how many such series the file store holds).
- **`Point(series, value, ts, labels)`**: `ts` is unix seconds; `store.write([...])` takes a list,
  so write the series of one moment together.

## Naming

- Name a series for what it measures, in plain words with its unit: `disk_free_bytes`,
  `repo_files`, `weather_temperature_celsius`, `bitcoin_price_usd`. Whether it is a stock, a flow
  or neither is the model's business, not the name's.
- **Never start a name with `orchestra_`.** The prefix is Orchestra's own; discovery leaves those
  series out (its "left out" list says so and asks you to rename them).
- A **counter** (a running count that only goes up: things done, bytes sent) ends in `_total`:
  `files_written_total`. Starting again from zero after a restart is fine (a reset, as in
  Prometheus). Discovery reads counters as flows.
- Anything else is a **level** (a gauge: how much there is now). Discovery may find a level is a
  stock when counters explain its changes.

## Labels

- `machine=<id>`: the machine that wrote it, the same id its events' `source` uses. Discovery
  attributes flows to machines by it, and the machine's dialog lists its series.
- `instance=<n>` when several instances of one machine run (`source` `<machine>/<n>`).
- Other labels split one measurement into several series (`disk="/"`, `city="Denver"`). Keep their
  values few: each value is a series of its own.

## How often

Write every series on a schedule (every few seconds to a minute), even when the value has not
changed. A machine is taken to be alive while its writes keep coming; a level written only when it
changes looks, between writes, like a machine that stopped. The `[discovery] step` (30 s by
default) is the finest grain discovery sees.

## Announcing the machine

When it starts, a machine publishes `orchestra.machine.started` with its `source` and:
`mode` (`continuous`, `scheduled` or `ad hoc`), `kind` (`program`, `agent`, `person` or
`service`), `listens_for` (the event types it reads from the bus) and `log` (its log file, shown
in its dialog when the file is inside the repository or the state directory). The Machines page
lists it from then on. Events it publishes go through `Events.publish` too, which writes the
CloudEvents envelope (SPEC §2).

## Having Orchestra run it

Declare it in `orchestra.toml`:

```toml
[[machines]]
name = "telemetry"                                  # letters, digits, . _ -
command = "uv run python machines/telemetry.py"     # split like a shell would, not run by one
restart = "always"                                  # always (the default) | on-failure | never
stop_grace = 10                                     # seconds from SIGTERM to SIGKILL (default 10)
```

`orchestra run` starts it in the repository root with `ORCHESTRA_REPO` and
`ORCHESTRA_MACHINE_LOG` set, sends its output to `<state>/logs/machines/telemetry.log`, starts it
again when it exits (after a pause that doubles with each quick exit, up to a minute), and gives up
after five failures in a row within a minute of starting, saying so in its log, the host's log and
on the bus (`orchestra.process.gave_up`). It reads `orchestra.toml` again whenever the file
changes: a machine added there (by a merge into the checked-out branch, say) starts within
seconds, one removed stops, and one whose entry changed restarts. The program itself is read only
when it starts, so a change to it alone takes effect at its next restart. The Core page lists what
the host runs, with each process's state, restarts and log.

The command is not run by a shell: for a pipeline or `&&`, write `command = "sh -c '...'"`, or
better, a script. A program that should run on a clock rather than continuously can loop and sleep
itself, as above.
