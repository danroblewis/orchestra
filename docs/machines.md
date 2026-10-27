# Writing a machine: emitting metrics and events

A machine is any program of yours that Orchestra observes. This page covers what a program in a
project needs to do so its measurements reach the project's metrics store, show up in the web UI
and are offered to discovery, how to test it and try it once, and how to have `orchestra run` keep
it running.

The program needs Orchestra importable. Either run it with the Python environment Orchestra is
installed in (see "Having Orchestra run it" below), or make the project depend on Orchestra:
`uv add "orchestra @ git+https://github.com/danroblewis/orchestra"`, or for a local checkout
`uv add --editable /path/to/orchestra`. (`uv add orchestra` alone installs an unrelated package
of that name from PyPI.)

## A whole machine

```python
"""Telemetry: free disk space and the files in the repository, every 30 s.

    python machines/telemetry.py           keeps measuring (how `orchestra run` runs it)
    python machines/telemetry.py --once    writes one round and exits (to try it)
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from orchestra.config import load_project
from orchestra.events import Events
from orchestra.metrics import Point, for_repo

MACHINE = "telemetry"          # the machine's id: its events' source, its series' label
EVERY_S = 30


def disk_free_bytes(root: Path) -> int:
    return shutil.disk_usage(root).free


def repo_files(root: Path) -> int:
    out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout
    return len(out.splitlines())


def measure(root: Path, now: float) -> list[Point]:
    """One round of measurements, as the points to write."""
    labels = {"machine": MACHINE}
    return [Point("disk_free_bytes", disk_free_bytes(root), now, labels),
            Point("repo_files", repo_files(root), now, labels)]


def main(once: bool = False) -> None:
    project = load_project()                  # ORCHESTRA_REPO (the launcher sets it), else the working directory
    store = for_repo(project.repo_root)       # the store orchestra.toml configures; adds the project label
    Events.for_project(project, source=MACHINE).publish("orchestra.machine.started", {
        "mode": "continuous", "kind": "program", "listens_for": [],
        "log": os.environ.get("ORCHESTRA_MACHINE_LOG")})          # where its output goes, for its dialog
    while True:
        store.write(measure(project.repo_root, time.time()))
        if once:
            return
        time.sleep(EVERY_S)


if __name__ == "__main__":
    main(once="--once" in sys.argv[1:])
```

Save it in the repository (say `machines/telemetry.py`), declare it (below), and commit both.

Keep the three parts apart, as above:
- **each measurement is a small function** that returns a value and writes nothing, so a test can
  call it;
- **`main()` opens the store, announces the machine and loops**, and runs only under
  `if __name__ == "__main__":`. Importing the module (as a test does) then starts nothing and
  writes nothing. A loop at module level would run on import, write to the project's real store,
  and never return, so a test suite that imports it hangs;
- **`--once` writes one round and exits.**

## Testing it and trying it once

A test imports the module and calls the measurements on a scratch repository:

```python
# tests/test_telemetry.py
import importlib.util
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location("telemetry", Path(__file__).parents[1] / "machines" / "telemetry.py")
telemetry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(telemetry)             # defines the functions; main() does not run


def test_repo_files(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("a")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    assert telemetry.repo_files(tmp_path) == 1
    assert [p.series for p in telemetry.measure(tmp_path, 0.0)] == ["disk_free_bytes", "repo_files"]
```

To try the whole program, run it once from the repository: `python machines/telemetry.py --once`.
It writes one round to the project's real store (the one `orchestra.toml` configures), so its
series appear in the Core page's catalogue, and exits. Don't try it by starting the loop and
leaving it running, or by putting it in the background: that is `orchestra run`'s job, and a copy
left running writes the same series twice.

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
`mode` (`continuous`, `scheduled` or `ad hoc`), `kind` (what kind of thing it is: `program` for a
program like this one), `listens_for` (the event types it reads from the bus) and `log` (its log file, shown
in its dialog when the file is inside the repository or the state directory). The Machines page
lists it from then on. Events it publishes go through `Events.publish` too, which writes the
CloudEvents envelope (SPEC §2).

## Having Orchestra run it

Declare it in `orchestra.toml`:

```toml
[[machines]]
name = "telemetry"                         # letters, digits, . _ -
command = "python machines/telemetry.py"   # split like a shell would, not run by one
restart = "always"                         # always (the default) | on-failure | never
stop_grace = 10                            # seconds from SIGTERM to SIGKILL (default 10)
```

**Which `python` runs it.** The launcher runs the command in the repository root with the `PATH`
that `orchestra run` was started with. Started from the environment Orchestra is installed in (an
activated virtual environment, or `uv run orchestra run` in a project that depends on Orchestra),
`python` is that environment's interpreter, which can import `orchestra`. Started otherwise (say
`orchestra` was installed with `uv tool install`, which keeps its environment off the `PATH`),
`python` is whatever else the `PATH` finds, the program fails with `ModuleNotFoundError`, and it is
given up on; give the interpreter's full path in `command` then. Write
`command = "uv run python machines/telemetry.py"` only when the project's own `pyproject.toml`
depends on Orchestra: `uv run` picks the project's environment, which otherwise lacks it.

`orchestra run` starts it with `ORCHESTRA_REPO` and `ORCHESTRA_MACHINE_LOG` set, sends its output
to `<state>/logs/machines/telemetry.log`, and starts it again when it exits, after a pause that
doubles with each quick exit (up to a minute). Only failing exits (a non-zero code) count towards
giving up: after five in a row, each within a minute of starting, it is given up on, which its log,
the host's log and the bus (`orchestra.process.gave_up`) say; it is tried again when its entry
changes or `orchestra run` restarts. A program that exits 0 is started again after the pause and
never given up, so a sampler that takes one reading and exits works like a cron job running about
once a minute.

It reads `orchestra.toml` again whenever the file changes: a machine added there (by a merge into
the checked-out branch, say) starts within seconds, one removed stops, and one whose entry changed
restarts. The program itself is read only when it starts, so a change to it alone takes effect at
its next restart. Stopping `orchestra run` stops it: SIGTERM, then SIGKILL after its `stop_grace`.
The Core page lists what the host runs, with each process's state, restarts and log.

A plugin's processes run under the name `<plugin>.<name>`, so a name of yours never replaces one
of theirs; a `[[machines]]` name of that form is refused. They follow `orchestra.toml` too: adding
or removing a plugin's section starts or stops what the plugin declares.

The command is not run by a shell: for a pipeline or `&&`, write `command = "sh -c '...'"`, or
better, a script. A program that should run on a clock rather than continuously can loop and sleep
itself, as above, or take one reading and exit.
