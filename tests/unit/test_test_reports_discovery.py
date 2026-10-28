"""The test-report instrument replayed over an hour of a repository's runs, as `orchestra run`
would run it under ``[[collect]]`` (every step, its output labelled with the project and the
instrument), and discovery read over what it wrote: the test counts are levels, and with the
history's counters the e2e count is a stock whose inflow is tests written and outflow tests
deleted."""

import os
import random
import sys
from io import StringIO
from unittest import mock

from orchestra.collect.exposition import parse
from orchestra.instruments import test_reports as tr
from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.discover import discover

T0 = 1_800_000_000.0
STEP = 30.0


def report(cases: dict[str, str]) -> str:
    rows = "".join(f'<testcase classname="{c.split("::")[0]}" name="{c.split("::")[1]}" time="0.2">'
                   f'{"<failure/>" if o == "failed" else ""}</testcase>' for c, o in cases.items())
    return f"<testsuites><testsuite>{rows}</testsuite></testsuites>"


def replay(tmp_path, minutes=60, seed=3):
    """A run every 2 minutes, each adding e2e tests (0 to 3) and sometimes deleting one, some
    with an e2e test failing, with a unit suite that grows slowly; the instrument every step."""
    rng = random.Random(seed)
    tests = {f"tests.unit.test_core::t{i}": "passed" for i in range(20)} | {f"tests.e2e.test_flow::t{i}": "passed" for i in range(4)}
    store = FileMetrics(tmp_path / "metrics.jsonl")
    hist, n = tmp_path / "history.json", 0
    argv = ["--reports", str(tmp_path / "reports" / "*" / "tests.xml"), "--history", str(hist)]
    for i in range(int(minutes * 60 / STEP)):
        t = T0 + i * STEP
        if i % 4 == 0:
            for _ in range(rng.choice([0, 1, 1, 2, 3])):
                n += 1
                tests[f"tests.e2e.test_new::t{n}"] = "passed"
            if rng.random() < 0.3:
                tests.pop(rng.choice(sorted(k for k in tests if "e2e" in k)))
            if rng.random() < 0.2:
                tests[f"tests.unit.test_core::u{i}"] = "passed"
            outcomes = dict(tests)
            if rng.random() < 0.4:                    # a run where one e2e test fails (flaky, or broken and fixed)
                outcomes[rng.choice(sorted(k for k in tests if "e2e" in k))] = "failed"
            f = tmp_path / "reports" / f"run{i}" / "tests.xml"
            f.parent.mkdir(parents=True)
            f.write_text(report(outcomes))
            os.utime(f, (t, t))
        out = StringIO()
        with mock.patch.object(sys, "stdout", out):
            tr.main(argv)
        store.write([Point(s.name, s.value, t, {**s.labels, "project": "p", "instrument": "tests"}) for s in parse(out.getvalue()).samples])
    return store, T0, T0 + minutes * 60


def test_the_e2e_count_is_a_stock_of_tests_written_and_deleted(tmp_path):
    store, start, end = replay(tmp_path)
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=STEP)
    found = [(s.series.name, s.series.labels.get("kind")) for s in m.stocks if s.series]
    e2e = next((s for s in m.stocks if s.series and s.series.name == "tests" and s.series.labels.get("kind") == "e2e"), None)
    assert e2e is not None, f"stocks: {found}; left out: {m.discovery.get('left_out')}"
    balance = {(b["series"].split("{")[0], b["sign"]) for b in e2e.evidence["balance"]}
    assert balance == {("tests_added_total", 1), ("tests_removed_total", -1)}
    assert e2e.evidence["balance_r2"] > 0.99
    # every other count is seen as a level: a stock, or left out as one, with the reason
    seen = {k.split("{")[0] for k in m.discovery["left_out"]} | {s.series.name for s in m.stocks}
    assert {"tests", "test_outcomes", "tests_flaky", "tests_confirmed", "tests_duration_seconds"} <= seen
