"""The test-report instrument: a repository's tests counted from the reports its test runner
writes, printed in the Prometheus text format for a ``[[collect]]`` entry. Standard library only.

    python -m orchestra.instruments.test_reports --run 'uv run pytest -q' [--kind e2e=@e2e]...
        [--run-timeout 4m] [--window 10] [--confirm 3] [--history .git/test-history.json]
    python -m orchestra.instruments.test_reports --reports 'reports/*.xml' [--max-age 1h] [...]

**Run mode, ``--run CMD``** (the usual one). The instrument runs the tests itself and reads the
report that run wrote, so what it prints is always this round's run, never an older report left
behind by a run that failed to start. CMD is run by the shell (``/bin/sh -c``) in the working
directory (the repository root under ``orchestra run``), so ``uv run pytest -q`` runs pytest in
the project's own environment. The report goes to a fresh temporary file:

- if CMD contains ``{report}``, that is replaced by the file's path (shell-quoted) and CMD is run
  as it is, for any runner that writes JUnit XML or a pytest report log:
  ``--run 'JEST_JUNIT_OUTPUT_FILE={report} npx jest --reporters=jest-junit'``;
- otherwise CMD is taken to end in a pytest command, and ``--junitxml=<file> -p
  _orchestra_test_markers`` is appended: the second is a ten-line pytest plugin the instrument
  writes beside the report (found through ``PYTHONPATH``) that records each test's markers in the
  report as ``<property name="marker" value="...">``, so ``--kind e2e=@e2e`` works.

CMD's output (standard output and error) is captured, never mixed into what the instrument
prints; when the run writes no report, its last lines go to standard error (the instrument's log).
A run that outlasts ``--run-timeout`` is killed (its process group). The timeout must be under the
``[[collect]]`` entry's own ``timeout`` (10 s unless the entry sets one, and never more than its
``every``), which is passed in ``ORCHESTRA_COLLECT_TIMEOUT``: by default it is that less a fifth
(at most 5 s), 8 s when run by hand. A suite that takes a minute needs ``timeout = "3m"`` in the
entry. Each round prints, whatever happened:

- ``test_run_result{result}``: 1 for this round's result, 0 for the others: ``reported`` (a
  report was written and read; tests that failed are in it), ``no_report`` (CMD exited without
  writing one: a broken environment, a collection error, the wrong command), ``unreadable`` (the
  report could not be read) or ``timed_out``;
- ``test_run_exit_code``: CMD's exit status (pytest: 0 all passed, 1 some failed, 2 interrupted,
  3 internal error, 4 usage error, 5 no tests); not printed when it timed out;
- ``test_run_duration_seconds``: how long CMD ran;

and the test series below only when the report was read: a run that wrote none has no count, not a
count of zero. With ``--history``, each run's report is one run of the stream ``run.xml``, so
flakiness and confirmation are judged across rounds.

**Reports mode, ``--reports GLOB``**: reads every file the globs match (relative to the working
directory; ``~`` and ``$VARS`` are expanded, ``**`` recurses), as another step or CI wrote them.
A report older than ``--max-age`` (``90s``, ``30m``, ``2h``, ``1d``; none by default) is not
current: its stream prints nothing, and is counted as ``test_report_files{state="stale"}``.

**What it reads.**

- JUnit XML, as pytest (``--junitxml``), Jest (``jest-junit``), Maven Surefire, Go's
  ``go-junit-report`` and most runners write it: every ``<testcase>``, under ``<testsuites>`` or
  ``<testsuite>``, at any depth. A case with ``<failure>`` failed, with ``<error>`` erred, with
  ``<skipped>`` was skipped; otherwise it passed. Surefire's ``<flakyFailure>``/``<flakyError>``
  (failed, then passed on a rerun) mark it flaky; its ``<rerunFailure>`` beside a ``<failure>`` is a
  failure that every rerun repeated. A case reported more than once in one file (a runner that
  reruns by appending) counts once, as its last result, flaky if an earlier one failed. A
  ``<property name="marker">`` under a case is one of its markers.
- pytest's report log (``pytest --report-log=FILE``, the ``pytest-reportlog`` plugin): JSON lines,
  one per phase of each test. Its ``keywords`` carry the test's markers. pytest-rerunfailures'
  ``rerun`` phases count as failed attempts.

**Streams and runs.** A report's *stream* is its file name with its digits ignored
(``reports/<run>/unit.xml`` and ``reports/unit-1712.xml`` are both in a stream of their name). Each
file is one run of its stream, ordered by modification time; the newest readable file is the
stream's current run. Only the newest ``--window`` files of a stream are read. A report that
cannot be read (missing, being written, not XML or JSON, over 50 MB) is skipped and counted, and
the stream's previous run stands. A repository whose runner overwrites one file per run has one
run per stream unless ``--history`` names a file where the instrument keeps the runs it has seen
(the newest ``--window`` per stream): then flakiness and confirmation are judged across runs.

**Kinds.** ``--kind KIND=PATTERN``, in order, first match wins, then the defaults
``e2e=*e2e*``, ``acceptance=*acceptance*``, ``unit=*``. A pattern is a glob over the test's path
(JUnit: its ``file`` attribute, else its ``classname`` with dots as slashes; pytest: the node id's
file), over ``path::name`` when it contains ``::``, or a marker when it starts with ``@``
(``--kind e2e=@e2e``). Markers are in pytest's report log and in run mode's reports, never in a
plain ``pytest --junitxml`` report: a marker rule over reports that carry no markers matches
nothing, and the instrument says so on standard error. The kind ``ignore`` drops what it matches.

**Absent is not zero.** A kind is printed only when the current run of some stream has tests of
that kind; a kind no current run has is not measured this round and prints nothing (a gap), not a
row of zeros. Otherwise a kind would read 0 whenever a run skipped it (a quick run without e2e)
and its real count when one included it, and the model would see tests vanish and return. Within a
kind that is printed, zeros are real (``test_outcomes{kind="unit",outcome="failed"} 0``). To
measure kinds on different schedules (unit every 5 minutes, e2e every hour), use two ``[[collect]]``
entries: each point carries its entry's ``instrument=<name>``, so their series never collide.

**What it prints**, for each kind present, from the current run of every stream:

- ``tests{kind}``: the tests. Their growth is the stock of tests written;
- ``test_outcomes{kind, outcome}``: by outcome, ``passed``, ``failed``, ``error``, ``skipped``;
- ``tests_flaky{kind}``: current tests that are flaky: within the stream's last ``--window`` runs
  the test both failed (or erred) and passed, or a report marks it as passing on a rerun;
- ``tests_confirmed{kind}``: current tests that passed in each of their last ``--confirm`` runs
  (default 3), consecutively, not flaky in any of them, and so ran at least that often. A new
  test is unconfirmed until it has passed that many runs; one failure unconfirms it until it has;
- ``tests_duration_seconds{kind}``: the time the tests of the kind took in their current runs;
- ``test_report_files{state}``: the report files ``read`` and ``unreadable`` this round (and
  ``stale``, with ``--max-age``);
- with ``--history`` only, the counters ``tests_added_total{kind}`` and
  ``tests_removed_total{kind}``, for every kind they have counted: the tests that appeared in, or
  disappeared from, a stream's run since its previous run (a stream's first run adds all its
  tests). They need memory, so they are kept in the history file, and between them they balance
  ``tests``: what lets discovery find the test count a stock, with writing tests and deleting them
  as its flows.

With no current report it prints none of the test series. It never prints a series starting with
``orchestra_``, and always exits 0 once its arguments are understood (2 when they are not)."""

from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

OUTCOMES = ("passed", "failed", "error", "skipped")
DEFAULT_KINDS = [("e2e", "*e2e*"), ("acceptance", "*acceptance*"), ("unit", "*")]
IGNORE = "ignore"
MAX_BYTES = 50 * 1024 * 1024
HELP = {"tests": "tests in the current run of every report stream, by kind",
        "test_outcomes": "tests in the current runs, by kind and outcome",
        "tests_flaky": "current tests that both failed and passed within the recent runs, or passed on a rerun",
        "tests_confirmed": "current tests that passed in each of their last N runs",
        "tests_duration_seconds": "time the tests of each kind took in their current runs",
        "tests_added_total": "tests that appeared from one run of a report stream to the next, by kind",
        "tests_removed_total": "tests that disappeared from one run of a report stream to the next, by kind",
        "test_report_files": "report files read, unreadable and stale (older than --max-age) this round",
        "test_run_result": "this round's run of --run: 1 for its result, 0 for the others",
        "test_run_exit_code": "the exit status of this round's run of --run",
        "test_run_duration_seconds": "how long this round's run of --run took"}


@dataclass
class Case:
    """One test's result in one report."""
    path: str                          # what a kind's path pattern matches
    name: str
    outcome: str                       # passed | failed | error | skipped
    flaky: bool = False                # passed after a failed attempt within the same report
    seconds: float = 0.0
    markers: list[str] = field(default_factory=list)

    def failed(self) -> bool:
        return self.outcome in ("failed", "error")


@dataclass
class Run:
    """One report file: one run of its stream."""
    key: str                           # path, modification time and size: the same file unchanged
    at: float
    cases: dict[str, Case]



def _tag(el: ET.Element) -> str:
    return el.tag.rpartition("}")[2]


def _seconds(v: str | None) -> float:
    try:
        return max(0.0, float((v or "0").replace(",", "")))
    except ValueError:
        return 0.0


def _combine(attempts: list[Case]) -> Case:
    """One test reported several times in a report: its last result, flaky when it passed last
    after an earlier attempt failed, its time the sum."""
    last = attempts[-1]
    last.flaky = last.flaky or (last.outcome == "passed" and any(a.failed() for a in attempts[:-1]))
    last.seconds = sum(a.seconds for a in attempts)
    return last


def parse_junit(text: str) -> dict[str, Case]:
    root = ET.fromstring(text)
    seen: dict[str, list[Case]] = {}
    for tc in root.iter():
        if _tag(tc) != "testcase":
            continue
        name, cls = tc.get("name") or "", tc.get("classname") or ""
        tags = {_tag(c) for c in tc}
        outcome = ("failed" if "failure" in tags else "error" if "error" in tags
                   else "skipped" if "skipped" in tags else "passed")
        flaky = outcome == "passed" and bool(tags & {"flakyFailure", "flakyError"})
        path = tc.get("file") or cls.replace(".", "/")
        markers = sorted({p.get("value") or "" for c in tc if _tag(c) == "properties" for p in c
                          if _tag(p) == "property" and p.get("name") == "marker"} - {""})
        seen.setdefault(f"{cls}::{name}", []).append(Case(path, name, outcome, flaky, _seconds(tc.get("time")), markers))
    return {k: _combine(v) for k, v in seen.items()}


def _attempt(phases: list[dict]) -> str:
    """One attempt's outcome from its phases (setup, call, teardown)."""
    for p in phases:
        if p.get("outcome") == "failed":
            return "failed" if p.get("when") == "call" else "error"
        if p.get("outcome") == "rerun":
            return "failed"
    if any(p.get("outcome") == "skipped" for p in phases):
        return "skipped"
    return "passed"


def parse_reportlog(text: str) -> dict[str, Case]:
    phases: dict[str, list[list[dict]]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("$report_type") != "TestReport" or not r.get("nodeid"):
            continue
        attempts = phases.setdefault(r["nodeid"], [])
        if not attempts or r.get("when") == "setup" or attempts[-1][-1].get("outcome") == "rerun":
            attempts.append([])
        attempts[-1].append(r)
    out: dict[str, Case] = {}
    for nodeid, attempts in phases.items():
        path, _, name = nodeid.partition("::")
        markers = sorted({k for a in attempts for p in a for k in (p.get("keywords") or {})})
        cases = [Case(path, name, _attempt(a), seconds=sum(_seconds(str(p.get("duration") or 0)) for p in a), markers=markers)
                 for a in attempts]
        out[nodeid] = _combine(cases)
    return out


def parse(path: Path) -> dict[str, Case]:
    """A report's cases. Raises when the file cannot be read as either format."""
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f"over {MAX_BYTES // 2**20} MB")
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith("<"):
        return parse_junit(text)
    if text.lstrip().startswith("{"):
        return parse_reportlog(text)
    raise ValueError("neither JUnit XML nor a pytest report log")



def stream_of(path: str) -> str:
    return re.sub(r"\d+", "#", os.path.basename(path))


def find(patterns: list[str]) -> dict[str, list[tuple[str, float, str]]]:
    """The matched files by stream, newest first: (path, mtime, key)."""
    streams: dict[str, list[tuple[str, float, str]]] = {}
    seen: set[str] = set()
    for pat in patterns:
        for p in glob.glob(os.path.expandvars(os.path.expanduser(pat)), recursive=True):
            if p in seen or not os.path.isfile(p):
                continue
            seen.add(p)
            try:
                st = os.stat(p)
            except OSError:
                continue
            streams.setdefault(stream_of(p), []).append((p, st.st_mtime, f"{p}|{st.st_mtime_ns}|{st.st_size}"))
    for files in streams.values():
        files.sort(key=lambda f: (f[1], f[0]), reverse=True)
    return streams


def _to_json(run: Run) -> dict:
    return {"key": run.key, "at": run.at, "cases": {k: [c.path, c.name, c.outcome, c.flaky, c.seconds, c.markers]
                                                    for k, c in run.cases.items()}}


def _from_json(d: dict) -> Run:
    return Run(d["key"], float(d["at"]), {k: Case(p, n, o, bool(f), float(s), list(m)) for k, (p, n, o, f, s, m) in d["cases"].items()})


@dataclass
class Seen:
    """What a history file keeps: each stream's recent runs, and the counts of tests added and
    removed between consecutive runs (``added|<kind>``, ``removed|<kind>``)."""
    streams: dict[str, list[Run]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)


def load_history(path: str | None) -> Seen:
    if not path or not os.path.exists(path):
        return Seen()
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return Seen({s: [_from_json(r) for r in rs] for s, rs in d["streams"].items()}, {k: int(v) for k, v in d["counts"].items()})
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"test_reports: history {path} unreadable ({e}); starting it again", file=sys.stderr)
        return Seen()


def save_history(path: str, seen: Seen) -> None:
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "counts": seen.counts,
                       "streams": {s: [_to_json(r) for r in rs] for s, rs in seen.streams.items()}}, fh)
        os.replace(tmp, path)
    except OSError as e:
        print(f"test_reports: cannot write history {path}: {e}", file=sys.stderr)


def kind_of(case: Case, rules: list[tuple[str, str]]) -> str:
    for kind, pat in rules:
        if pat.startswith("@"):
            if pat[1:] in case.markers:
                return kind
        elif fnmatch.fnmatchcase(f"{case.path}::{case.name}" if "::" in pat else case.path, pat):
            return kind
    return IGNORE


def tally(before: Run | None, after: Run, rules: list[tuple[str, str]], counts: dict[str, int]) -> None:
    """The tests added and removed from one run of a stream to the next, by kind. A stream's first
    run adds all its tests."""
    old = before.cases if before else {}
    for change, ids, cases in (("added", after.cases.keys() - old.keys(), after.cases), ("removed", old.keys() - after.cases.keys(), old)):
        for tid in ids:
            kind = kind_of(cases[tid], rules)
            if kind != IGNORE:
                counts[f"{change}|{kind}"] = counts.get(f"{change}|{kind}", 0) + 1


def runs(patterns: list[str], window: int, history: str | None, rules: list[tuple[str, str]]) -> tuple[Seen, int, int]:
    """Each stream's newest ``window`` readable runs, newest first, with the files read and
    unreadable. With ``history``, the runs seen before are kept, each run newer than its stream's
    last is tallied against the one before it, and the file is updated."""
    seen = load_history(history)
    known = {r.key for rs in seen.streams.values() for r in rs}
    last = {s: rs[0] for s, rs in seen.streams.items() if rs}
    read = bad = 0
    fresh: dict[str, list[Run]] = {}
    for stream, files in find(patterns).items():
        for path, at, key in files[:window]:
            if key in known:
                read += 1
                continue
            try:
                cases = parse(Path(path))
            except (OSError, ValueError, ET.ParseError) as e:
                bad += 1
                print(f"test_reports: {path}: unreadable ({e}); skipped", file=sys.stderr)
                continue
            read += 1
            fresh.setdefault(stream, []).append(Run(key, at, cases))
    for stream, new in fresh.items():
        prev = last.get(stream)
        for r in sorted(new, key=lambda r: (r.at, r.key)):
            if prev is None or (r.at, r.key) > (prev.at, prev.key):
                tally(prev, r, rules, seen.counts)
                prev = r
        seen.streams[stream] = sorted([*seen.streams.get(stream, []), *new], key=lambda r: (r.at, r.key), reverse=True)[:window]
    if history:
        save_history(history, seen)
    return seen, read, bad


def flaky(history: list[Case]) -> bool:
    """Within the recent runs (newest first): marked flaky, or both failed and passed."""
    return any(c.flaky for c in history) or (any(c.failed() for c in history) and any(c.outcome == "passed" for c in history))


def confirmed(history: list[Case], n: int) -> bool:
    """Passed in each of its last ``n`` runs, none of them flaky."""
    last = history[:n]
    return len(last) >= n and all(c.outcome == "passed" and not c.flaky for c in last)


def measure(streams: dict[str, list[Run]], rules: list[tuple[str, str]], confirm: int) -> dict[str, dict[str, float]]:
    """The per-kind numbers, {series: {kind or kind|outcome: value}}, for the kinds the current runs
    have tests of, and only those: a kind no current run has is not measured (absent is not zero)."""
    m: dict[str, dict[str, float]] = {name: {} for name in ("tests", "test_outcomes", "tests_flaky", "tests_confirmed", "tests_duration_seconds")}
    order = [k for k, _ in rules]
    for rs in streams.values():
        if not rs:
            continue
        for tid, case in rs[0].cases.items():
            kind = kind_of(case, rules)
            if kind == IGNORE:
                continue
            if kind not in m["tests"]:
                for name in ("tests", "tests_flaky", "tests_confirmed", "tests_duration_seconds"):
                    m[name][kind] = 0
                m["test_outcomes"].update({f"{kind}|{o}": 0 for o in OUTCOMES})
            history = [r.cases[tid] for r in rs if tid in r.cases]
            m["tests"][kind] += 1
            m["test_outcomes"][f"{kind}|{case.outcome}"] += 1
            m["tests_flaky"][kind] += flaky(history)
            m["tests_confirmed"][kind] += confirmed(history, confirm)
            m["tests_duration_seconds"][kind] += case.seconds
    rank = {k: i for i, k in enumerate(order)}
    return {name: dict(sorted(v.items(), key=lambda kv: (rank.get(kv[0].split("|")[0], len(rank)), kv[0].split("|")[0])))
            for name, v in m.items()}


def warn_markers(streams: dict[str, list[Run]], rules: list[tuple[str, str]]) -> None:
    """Say on standard error when a marker rule cannot match: the current runs carry no markers
    (a plain ``pytest --junitxml`` report never does)."""
    marker_rules = [f"{k}={p}" for k, p in rules if p.startswith("@")]
    current = [c for rs in streams.values() if rs for c in rs[0].cases.values()]
    if marker_rules and current and not any(c.markers for c in current):
        print(f"test_reports: {', '.join(marker_rules)} matches nothing: the reports carry no markers "
              "(pytest --junitxml writes none; use --run, which records them, or pytest --report-log)", file=sys.stderr)


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class Text:
    """The Prometheus text being printed."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def series(self, name: str, rows: list[tuple[dict[str, str], float]], kind: str = "gauge") -> None:
        if not rows:
            return
        self.lines.extend([f"# HELP {name} {HELP[name]}", f"# TYPE {name} {kind}"])
        for labels, v in rows:
            inner = ",".join(f'{k}="{_esc(x)}"' for k, x in labels.items())
            self.lines.append(f"{name}{{{inner}}} {round(v, 3):g}" if inner else f"{name} {round(v, 3):g}")

    def __str__(self) -> str:
        return "\n".join(self.lines) + "\n"


def exposition(m: dict[str, dict[str, float]] | None, counts: dict[str, int] | None, files: dict[str, int],
               ran: Ran | None = None) -> str:
    """The text: this round's run (``ran``, run mode), the levels from ``m`` (None: no current
    report), the counters from ``counts`` (None: no history) and the report files."""
    t = Text()
    if ran is not None:
        t.series("test_run_result", [({"result": r}, float(r == ran.result)) for r in RESULTS])
        if ran.code is not None:
            t.series("test_run_exit_code", [({}, ran.code)])
        t.series("test_run_duration_seconds", [({}, ran.seconds)])
    if m is not None:
        for name in ("tests", "test_outcomes", "tests_flaky", "tests_confirmed", "tests_duration_seconds"):
            if name == "test_outcomes":
                t.series(name, [({"kind": k.split("|")[0], "outcome": k.split("|")[1]}, v) for k, v in m[name].items()])
            else:
                t.series(name, [({"kind": k}, v) for k, v in m[name].items()])
    if counts is not None:
        kinds = list(dict.fromkeys(k.split("|", 1)[1] for k in sorted(counts)))
        for change in ("added", "removed"):
            t.series(f"tests_{change}_total", [({"kind": k}, counts.get(f"{change}|{k}", 0)) for k in kinds], "counter")
    t.series("test_report_files", [({"state": s}, n) for s, n in files.items()])
    return str(t)


@dataclass
class Ran:
    """One run of ``--run``'s command."""
    result: str                        # one of RESULTS
    code: int | None                   # its exit status; None when it timed out or could not start
    seconds: float
    tail: str = ""                     # the end of what it printed


RESULTS = ("reported", "no_report", "unreadable", "timed_out")
RUN_FILE = "run.xml"                   # the run's report: one stream, run.xml, across rounds
PLUGIN = "_orchestra_test_markers"
PLUGIN_SOURCE = '''"""Written by Orchestra's test-report instrument for one run: records each test's markers in
pytest's JUnit XML report as <property name="marker" value="..."/>."""


def pytest_collection_modifyitems(items):
    for item in items:
        for name in dict.fromkeys(m.name for m in item.iter_markers()):
            item.user_properties.append(("marker", name))
'''


def command(cmd: str, report: Path) -> str:
    """CMD as it is run: ``{report}`` replaced by the report's path, or pytest's options appended."""
    if "{report}" in cmd:
        return cmd.replace("{report}", shlex.quote(str(report)))
    return f"{cmd} {shlex.quote('--junitxml=' + str(report))} -p {PLUGIN}"


def _tail(path: Path, lines: int = 15, chars: int = 2000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.rstrip().splitlines()[-lines:])[-chars:]


def _stop(p: subprocess.Popen) -> None:
    """Kill the run's process group: politely, then not."""
    for sig, grace in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 5.0)):
        try:
            os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            p.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


def run_tests(cmd: str, timeout: float, tmp: Path) -> tuple[Ran, Path]:
    """Run CMD by the shell in the working directory, its output captured in ``tmp``, and kill its
    process group when it outlasts ``timeout``. The report it was asked to write, and how it went."""
    report, out = tmp / RUN_FILE, tmp / "output.txt"
    (tmp / f"{PLUGIN}.py").write_text(PLUGIN_SOURCE, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in (str(tmp), os.environ.get("PYTHONPATH")) if p)}
    start = time.monotonic()
    with out.open("wb") as fh:
        try:
            p = subprocess.Popen(command(cmd, report), shell=True, stdin=subprocess.DEVNULL, stdout=fh,
                                 stderr=subprocess.STDOUT, env=env, process_group=0)
        except OSError as e:
            return Ran("no_report", None, 0.0, f"cannot start: {e}"), report
        try:
            code: int | None = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = None
            _stop(p)
    seconds = time.monotonic() - start
    if code is None:
        return Ran("timed_out", None, seconds, _tail(out)), report
    return Ran("reported" if report.exists() else "no_report", code, seconds, _tail(out)), report


DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(s|m|h|d|w)?")
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, None: 1}


def _duration(s: str) -> float:
    d = DURATION.fullmatch(s.strip())
    if not d or float(d[1]) <= 0:
        raise argparse.ArgumentTypeError(f"{s!r}: expected a duration such as 90s, 5m, 2h, 1d")
    return float(d[1]) * UNITS[d[2]]


def default_run_timeout() -> float:
    """Under the ``[[collect]]`` entry's own timeout, which ``orchestra run`` passes in
    ``ORCHESTRA_COLLECT_TIMEOUT``: that less a fifth, at most 5 s; 8 s without one."""
    try:
        t = float(os.environ["ORCHESTRA_COLLECT_TIMEOUT"])
    except (KeyError, ValueError):
        return 8.0
    return max(0.5, t - min(5.0, t / 5))


def _rule(s: str) -> tuple[str, str]:
    kind, eq, pat = s.partition("=")
    if not eq or not re.fullmatch(r"[A-Za-z0-9_.-]+", kind) or not pat:
        raise argparse.ArgumentTypeError(f"{s!r}: expected KIND=PATTERN (KIND: letters, digits, _ . -)")
    return kind, pat


def arguments(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m orchestra.instruments.test_reports", description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--run", metavar="CMD", help="run the tests by the shell and read the report they write")
    src.add_argument("--reports", action="append", metavar="GLOB", help="report files written by something else (repeatable)")
    ap.add_argument("--run-timeout", type=_duration, metavar="DURATION",
                    help="kill the run after this long (default: under the [[collect]] entry's timeout)")
    ap.add_argument("--max-age", type=_duration, metavar="DURATION", help="with --reports: a report older than this is not current")
    ap.add_argument("--kind", action="append", type=_rule, default=[], metavar="KIND=PATTERN",
                    help="a kind rule, before the defaults (repeatable)")
    ap.add_argument("--window", type=int, default=10, help="runs per stream judged for flakiness (default 10)")
    ap.add_argument("--confirm", type=int, default=3, help="consecutive passing runs that confirm a test (default 3)")
    ap.add_argument("--history", help="a file to keep the runs seen in, and the tests added and removed")
    a = ap.parse_args(argv)
    if a.window < 1 or a.confirm < 1 or a.confirm > a.window:
        ap.error("need 1 <= --confirm <= --window")
    if a.run is not None and not a.run.strip():
        ap.error("--run needs a command")
    if a.run is None and a.run_timeout is not None:
        ap.error("--run-timeout goes with --run")
    if a.run is not None and a.max_age is not None:
        ap.error("--max-age goes with --reports (a --run report is always this round's)")
    return a


def run_round(a: argparse.Namespace, rules: list[tuple[str, str]]) -> tuple[Ran, Seen, dict[str, list[Run]], dict[str, int]]:
    """Run mode: run the tests, read the fresh report (one more run of the stream ``run.xml``)."""
    timeout = a.run_timeout or default_run_timeout()
    with tempfile.TemporaryDirectory(prefix="orchestra-tests-") as tmp:
        ran, report = run_tests(a.run, timeout, Path(tmp))
        if ran.result == "reported":
            seen, read, bad = runs([glob.escape(str(report))], a.window, a.history, rules)
        else:
            seen, read, bad = load_history(a.history), 0, 0
    if ran.result == "reported" and not read:
        ran.result = "unreadable"
    if ran.result != "reported":
        what = {"no_report": f"exited with {ran.code} and wrote no report", "unreadable": "wrote a report that cannot be read",
                "timed_out": f"took longer than {timeout:g} s (--run-timeout); killed"}[ran.result]
        print(f"test_reports: `{a.run}` {what}; no tests counted this round. Its output ended:\n{ran.tail}", file=sys.stderr)
    current = {RUN_FILE: seen.streams.get(RUN_FILE, [])} if ran.result == "reported" else {}
    return ran, seen, current, {"read": read, "unreadable": bad}


def reports_round(a: argparse.Namespace, rules: list[tuple[str, str]]) -> tuple[Seen, dict[str, list[Run]], dict[str, int]]:
    """Reports mode: the matched files' current runs, less those older than ``--max-age``."""
    seen, read, bad = runs(a.reports, a.window, a.history, rules)
    current = {s: rs for s, rs in seen.streams.items() if rs}
    files = {"read": read, "unreadable": bad}
    if a.max_age is not None:
        stale = {s for s, rs in current.items() if rs[0].at < time.time() - a.max_age}
        current = {s: rs for s, rs in current.items() if s not in stale}
        files["stale"] = len(stale)
    return seen, current, files


def main(argv: list[str] | None = None) -> int:
    a = arguments(argv)
    rules = [*a.kind, *DEFAULT_KINDS]
    ran = None
    if a.run is not None:
        ran, seen, current, files = run_round(a, rules)
    else:
        seen, current, files = reports_round(a, rules)
    warn_markers(current, rules)
    m = measure(current, rules, a.confirm) if current else None
    sys.stdout.write(exposition(m, seen.counts if a.history else None, files, ran))
    return 0


if __name__ == "__main__":
    sys.exit(main())
