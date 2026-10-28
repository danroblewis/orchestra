"""The test-report instrument: a repository's tests counted from the reports its test runner
writes, printed in the Prometheus text format for a ``[[collect]]`` entry. Standard library only.

    python -m orchestra.instruments.test_reports --reports 'reports/*.xml' [--kind e2e=tests/e2e/*]...
        [--window 10] [--confirm 3] [--history .test-history.json]

**What it reads.** Every file the ``--reports`` globs match (relative to the working directory, the
repository root under ``orchestra run``; ``~`` and ``$VARS`` are expanded, ``**`` recurses):

- JUnit XML, as pytest (``--junitxml``), Jest (``jest-junit``), Maven Surefire, Go's
  ``go-junit-report`` and most runners write it: every ``<testcase>``, under ``<testsuites>`` or
  ``<testsuite>``, at any depth. A case with ``<failure>`` failed, with ``<error>`` erred, with
  ``<skipped>`` was skipped; otherwise it passed. Surefire's ``<flakyFailure>``/``<flakyError>``
  (failed, then passed on a rerun) mark it flaky; its ``<rerunFailure>`` beside a ``<failure>`` is a
  failure that every rerun repeated. A case reported more than once in one file (a runner that
  reruns by appending) counts once, as its last result, flaky if an earlier one failed.
- pytest's report log (``pytest --report-log=FILE``, the ``pytest-reportlog`` plugin): JSON lines,
  one per phase of each test. Its ``keywords`` carry the test's markers, so kinds can be told by
  marker. pytest-rerunfailures' ``rerun`` phases count as failed attempts.

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
(``--kind e2e=@e2e``; the report log only). The kind ``ignore`` drops what it matches.

**What it prints**, for each kind (every kind the rules name, zero when there is none), from the
current run of every stream:

- ``tests{kind}``: the tests. Their growth is the stock of tests written;
- ``test_outcomes{kind, outcome}``: by outcome, ``passed``, ``failed``, ``error``, ``skipped``;
- ``tests_flaky{kind}``: current tests that are flaky: within the stream's last ``--window`` runs
  the test both failed (or erred) and passed, or a report marks it as passing on a rerun;
- ``tests_confirmed{kind}``: current tests that passed in each of their last ``--confirm`` runs
  (default 3), consecutively, not flaky in any of them, and so ran at least that often. A new
  test is unconfirmed until it has passed that many runs; one failure unconfirms it until it has;
- ``tests_duration_seconds{kind}``: the time the tests of the kind took in their current runs;
- ``test_report_files{state}``: the report files read and ``unreadable`` this round;
- with ``--history`` only, the counters ``tests_added_total{kind}`` and
  ``tests_removed_total{kind}``: the tests that appeared in, or disappeared from, a stream's run
  since its previous run (a stream's first run adds all its tests). They need memory, so they are
  kept in the history file, and between them they balance ``tests``: what lets discovery find the
  test count a stock, with writing tests and deleting them as its flows.

With no readable report at all it prints only ``test_report_files``: a repository that has not
run its tests yet has no count, not a count of zero. It never prints a series starting with
``orchestra_``, and always exits 0 once its arguments are understood (2 when they are not)."""

from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
import re
import sys
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
        "test_report_files": "report files read and unreadable this round"}


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
        seen.setdefault(f"{cls}::{name}", []).append(Case(path, name, outcome, flaky, _seconds(tc.get("time"))))
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
    """The per-kind numbers: {series: {kind or kind|outcome: value}}."""
    kinds = list(dict.fromkeys(k for k, _ in rules if k != IGNORE))
    m: dict[str, dict[str, float]] = {name: dict.fromkeys(kinds, 0) for name in ("tests", "tests_flaky", "tests_confirmed", "tests_duration_seconds")}
    m["test_outcomes"] = {f"{k}|{o}": 0 for k in kinds for o in OUTCOMES}
    for rs in streams.values():
        if not rs:
            continue
        for tid, case in rs[0].cases.items():
            kind = kind_of(case, rules)
            if kind == IGNORE:
                continue
            history = [r.cases[tid] for r in rs if tid in r.cases]
            m["tests"][kind] += 1
            m["test_outcomes"][f"{kind}|{case.outcome}"] += 1
            m["tests_flaky"][kind] += flaky(history)
            m["tests_confirmed"][kind] += confirmed(history, confirm)
            m["tests_duration_seconds"][kind] += case.seconds
    return m


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def exposition(m: dict[str, dict[str, float]] | None, counts: dict[str, int] | None, kinds: list[str], read: int, bad: int) -> str:
    """The text: the levels from ``m`` (None: no readable report), the counters from ``counts``
    (None: no history), the files read."""
    lines: list[str] = []

    def series(name: str, rows: list[tuple[dict[str, str], float]], kind: str = "gauge") -> None:
        lines.extend([f"# HELP {name} {HELP[name]}", f"# TYPE {name} {kind}"])
        for labels, v in rows:
            inner = ",".join(f'{k}="{_esc(x)}"' for k, x in labels.items())
            lines.append(f"{name}{{{inner}}} {round(v, 3):g}")

    if m is not None:
        for name in ("tests", "test_outcomes", "tests_flaky", "tests_confirmed", "tests_duration_seconds"):
            if name == "test_outcomes":
                series(name, [({"kind": k.split("|")[0], "outcome": k.split("|")[1]}, v) for k, v in m[name].items()])
            else:
                series(name, [({"kind": k}, v) for k, v in m[name].items()])
    if counts is not None:
        for change in ("added", "removed"):
            series(f"tests_{change}_total", [({"kind": k}, counts.get(f"{change}|{k}", 0)) for k in kinds], "counter")
    series("test_report_files", [({"state": "read"}, read), ({"state": "unreadable"}, bad)])
    return "\n".join(lines) + "\n"


def _rule(s: str) -> tuple[str, str]:
    kind, eq, pat = s.partition("=")
    if not eq or not re.fullmatch(r"[A-Za-z0-9_.-]+", kind) or not pat:
        raise argparse.ArgumentTypeError(f"{s!r}: expected KIND=PATTERN (KIND: letters, digits, _ . -)")
    return kind, pat


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m orchestra.instruments.test_reports", description=__doc__.split("\n\n")[0])
    ap.add_argument("--reports", action="append", required=True, metavar="GLOB", help="report files (repeatable)")
    ap.add_argument("--kind", action="append", type=_rule, default=[], metavar="KIND=PATTERN",
                    help="a kind rule, before the defaults (repeatable)")
    ap.add_argument("--window", type=int, default=10, help="runs per stream judged for flakiness (default 10)")
    ap.add_argument("--confirm", type=int, default=3, help="consecutive passing runs that confirm a test (default 3)")
    ap.add_argument("--history", help="a file to keep the runs seen in, and the tests added and removed")
    a = ap.parse_args(argv)
    if a.window < 1 or a.confirm < 1 or a.confirm > a.window:
        ap.error("need 1 <= --confirm <= --window")
    rules = [*a.kind, *DEFAULT_KINDS]
    kinds = list(dict.fromkeys(k for k, _ in rules if k != IGNORE))
    seen, read, bad = runs(a.reports, a.window, a.history, rules)
    m = measure(seen.streams, rules, a.confirm) if any(seen.streams.values()) else None
    sys.stdout.write(exposition(m, seen.counts if a.history else None, kinds, read, bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
