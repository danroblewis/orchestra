"""The test-report instrument (orchestra/instruments/test_reports.py): JUnit as the common runners
write it, pytest's report log, kinds, flaky and confirmed tests across runs, history, and reports
that are missing or half-written. What it prints is read with the collector's own parser."""

import json
import os
import subprocess
import sys

from orchestra.collect.exposition import parse as parse_exposition
from orchestra.instruments import test_reports as tr

PYTEST_XUNIT2 = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="1" skipped="1" tests="5" time="1.5">
  <testcase classname="tests.unit.test_a" name="test_ok" time="0.10"/>
  <testcase classname="tests.unit.test_a" name="test_bad" time="0.20"><failure message="assert 1 == 2">trace</failure></testcase>
  <testcase classname="tests.e2e.test_flow" name="test_skip" time="0"><skipped type="pytest.skip" message="later"/></testcase>
  <testcase classname="tests.e2e.test_flow" name="test_err" time="0.3"><error message="fixture">boom</error></testcase>
  <testcase classname="tests.acceptance.test_api" name="test_get" time="0.9"/>
</testsuite></testsuites>"""

PYTEST_XUNIT1 = """<testsuite name="pytest" tests="1"><testcase classname="test_x" file="tests/e2e/test_x.py" line="3" name="test_y" time="1"/></testsuite>"""

JEST = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="jest tests" tests="2" failures="1" time="2.1">
  <testsuite name="Cart" tests="2" failures="1" time="2.1">
    <testcase classname="Cart adds an item" name="Cart adds an item" time="1.1" file="src/e2e/cart.test.js"/>
    <testcase classname="Cart removes an item" name="Cart removes an item" time="1,000.0" file="src/e2e/cart.test.js">
      <failure>Error: expected 0</failure>
    </testcase>
  </testsuite>
</testsuites>"""

SUREFIRE = """<testsuite xmlns="http://maven.apache.org/surefire" name="com.acme.ShopIT" tests="3">
  <testcase name="checkout" classname="com.acme.ShopIT" time="3.2"><flakyFailure message="timeout" type="java.lang.AssertionError"/></testcase>
  <testcase name="refund" classname="com.acme.ShopIT" time="1.0"><failure message="no"/><rerunFailure message="no"/></testcase>
  <testcase name="browse" classname="com.acme.ShopIT" time="0.5"/>
</testsuite>"""

APPENDED_RERUN = """<testsuite><testsuite name="nested">
  <testcase classname="t.e2e.a" name="once" time="1"><failure/></testcase>
  <testcase classname="t.e2e.a" name="once" time="2"/>
</testsuite></testsuite>"""


def write(path, text, at=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if at is not None:
        os.utime(path, (at, at))
    return path


def junit(cases: dict[str, str]) -> str:
    """A pytest-like report: {"tests.e2e.test_a::test_x": "passed"|"failed"|"skipped"}."""
    body = {"passed": "", "failed": "<failure/>", "skipped": "<skipped/>", "error": "<error/>"}
    rows = "".join(f'<testcase classname="{k.split("::")[0]}" name="{k.split("::")[1]}" time="0.5">{body[v]}</testcase>'
                   for k, v in cases.items())
    return f"<testsuites><testsuite>{rows}</testsuite></testsuites>"


def samples(text: str) -> dict[tuple, float]:
    p = parse_exposition(text)
    assert not p.bad, p.bad
    return {(s.name, *sorted(s.labels.items())): s.value for s in p.samples}


def run(argv) -> dict[tuple, float]:
    from io import StringIO
    from unittest import mock
    out = StringIO()
    with mock.patch.object(sys, "stdout", out):
        assert tr.main(argv) == 0
    return samples(out.getvalue())


def kinds(s: dict, name: str) -> dict[str, float]:
    return {dict(k[1:])["kind"]: v for k, v in s.items() if k[0] == name}


def outcomes(s: dict, kind: str) -> dict[str, float]:
    return {dict(k[1:])["outcome"]: v for k, v in s.items() if k[0] == "test_outcomes" and dict(k[1:])["kind"] == kind}


def test_pytest_junit_by_path_kind_and_outcome(tmp_path):
    write(tmp_path / "r" / "junit.xml", PYTEST_XUNIT2)
    s = run(["--reports", str(tmp_path / "r" / "*.xml")])
    assert kinds(s, "tests") == {"e2e": 2, "acceptance": 1, "unit": 2}
    assert outcomes(s, "unit") == {"passed": 1, "failed": 1, "error": 0, "skipped": 0}
    assert outcomes(s, "e2e") == {"passed": 0, "failed": 0, "error": 1, "skipped": 1}
    assert kinds(s, "tests_duration_seconds") == {"e2e": 0.3, "acceptance": 0.9, "unit": 0.3}
    assert s[("test_report_files", ("state", "read"))] == 1 and s[("test_report_files", ("state", "unreadable"))] == 0
    assert not any(k[0].startswith("orchestra_") for k in s)


def test_file_attribute_and_jest(tmp_path):
    write(tmp_path / "a.xml", PYTEST_XUNIT1)
    write(tmp_path / "jest.xml", JEST)
    s = run(["--reports", str(tmp_path / "*.xml")])
    assert kinds(s, "tests")["e2e"] == 3                       # by file: tests/e2e/…, src/e2e/…
    assert outcomes(s, "e2e")["failed"] == 1
    assert kinds(s, "tests_duration_seconds")["e2e"] == 1 + 1.1 + 1000      # "1,000.0" read as a thousand


def test_surefire_flaky_and_rerun_failures(tmp_path):
    write(tmp_path / "TEST-ShopIT.xml", SUREFIRE)
    s = run(["--reports", str(tmp_path / "*.xml"), "--kind", "e2e=com/acme/*IT"])
    assert kinds(s, "tests")["e2e"] == 3
    assert outcomes(s, "e2e") == {"passed": 2, "failed": 1, "error": 0, "skipped": 0}
    assert kinds(s, "tests_flaky")["e2e"] == 1                 # checkout passed on a rerun; refund failed every rerun


def test_a_case_reported_twice_counts_once_and_is_flaky(tmp_path):
    write(tmp_path / "r.xml", APPENDED_RERUN)
    s = run(["--reports", str(tmp_path / "r.xml")])
    assert kinds(s, "tests")["e2e"] == 1 and outcomes(s, "e2e")["passed"] == 1
    assert kinds(s, "tests_flaky")["e2e"] == 1 and kinds(s, "tests_duration_seconds")["e2e"] == 3


def test_pytest_report_log_with_markers_and_reruns(tmp_path):
    def rec(nodeid, when, outcome, **kw):
        return json.dumps({"$report_type": "TestReport", "nodeid": nodeid, "when": when, "outcome": outcome,
                           "keywords": kw.get("keywords", {}), "duration": 0.25})
    lines = [json.dumps({"$report_type": "SessionStart", "pytest_version": "8"})]
    for when in ("setup", "call", "teardown"):
        lines.append(rec("tests/test_shop.py::test_buy", when, "passed", keywords={"test_buy": 1, "e2e": 1}))
    lines += [rec("tests/test_shop.py::test_sell", "setup", "passed", keywords={"e2e": 1}),
              rec("tests/test_shop.py::test_sell", "call", "rerun", keywords={"e2e": 1}),
              rec("tests/test_shop.py::test_sell", "setup", "passed", keywords={"e2e": 1}),
              rec("tests/test_shop.py::test_sell", "call", "passed", keywords={"e2e": 1}),
              rec("tests/test_shop.py::test_sell", "teardown", "passed", keywords={"e2e": 1}),
              rec("tests/test_math.py::test_add", "setup", "passed"),
              rec("tests/test_math.py::test_add", "call", "passed"),
              rec("tests/test_math.py::test_add", "teardown", "failed"),
              rec("tests/test_math.py::test_sub", "setup", "skipped")]
    write(tmp_path / "log.jsonl", "\n".join(lines) + "\n")
    s = run(["--reports", str(tmp_path / "log.jsonl"), "--kind", "e2e=@e2e"])
    assert kinds(s, "tests") == {"e2e": 2, "unit": 2}                     # no acceptance test: no acceptance row
    assert outcomes(s, "e2e")["passed"] == 2 and kinds(s, "tests_flaky")["e2e"] == 1
    assert outcomes(s, "unit") == {"passed": 0, "failed": 0, "error": 1, "skipped": 1}     # a teardown failure is an error


def test_kind_rules_in_order_with_names_and_ignore(tmp_path):
    write(tmp_path / "r.xml", junit({"tests.unit.test_a::test_x": "passed", "tests.unit.test_a::test_slow_e2e_path": "passed",
                                     "tests.helpers.test_h::test_h": "passed"}))
    s = run(["--reports", str(tmp_path / "r.xml"), "--kind", "e2e=*::*_e2e_*", "--kind", "ignore=tests/helpers/*",
             "--kind", "smoke=nothing/*"])
    assert kinds(s, "tests") == {"e2e": 1, "unit": 1}                     # smoke is named but absent: not 0


def test_runs_make_tests_flaky_and_confirmed(tmp_path):
    """Five runs of one stream, one directory each (as the merge gate keeps them): a test that
    failed once is flaky while that run is in the window and confirmed once it has passed three
    times since; a new test is unconfirmed until it has passed three runs."""
    history = [{"t.e2e.a::steady": "passed", "t.e2e.a::wobbly": "passed"},
               {"t.e2e.a::steady": "passed", "t.e2e.a::wobbly": "failed"},
               {"t.e2e.a::steady": "passed", "t.e2e.a::wobbly": "passed"},
               {"t.e2e.a::steady": "passed", "t.e2e.a::wobbly": "passed", "t.e2e.a::new": "passed"},
               {"t.e2e.a::steady": "passed", "t.e2e.a::wobbly": "passed", "t.e2e.a::new": "passed"}]
    for i, cases in enumerate(history):
        write(tmp_path / f"run{i}" / "tests.xml", junit(cases), at=1_000_000 + i)
    glob = str(tmp_path / "*" / "tests.xml")
    s = run(["--reports", glob])
    assert kinds(s, "tests")["e2e"] == 3 and kinds(s, "tests_flaky")["e2e"] == 1
    assert kinds(s, "tests_confirmed")["e2e"] == 2           # steady, and wobbly (passed its last 3); new has 2
    s = run(["--reports", glob, "--window", "3"])            # the failure is out of the window
    assert kinds(s, "tests_flaky")["e2e"] == 0
    s = run(["--reports", glob, "--confirm", "2"])
    assert kinds(s, "tests_confirmed")["e2e"] == 3


def test_a_regression_shows_in_the_current_run(tmp_path):
    write(tmp_path / "1" / "tests.xml", junit({"t.e2e.a::x": "passed", "t.e2e.a::y": "passed"}), at=1_000_000)
    write(tmp_path / "2" / "tests.xml", junit({"t.e2e.a::x": "passed", "t.e2e.a::y": "failed"}), at=1_000_100)
    s = run(["--reports", str(tmp_path / "*" / "tests.xml")])
    assert outcomes(s, "e2e")["failed"] == 1 and kinds(s, "tests_confirmed")["e2e"] == 0


def test_streams_are_file_names_without_digits(tmp_path):
    write(tmp_path / "unit-1.xml", junit({"t.unit.a::x": "failed"}), at=1_000_000)
    write(tmp_path / "unit-2.xml", junit({"t.unit.a::x": "passed"}), at=1_000_100)
    write(tmp_path / "e2e.xml", junit({"t.e2e.a::y": "passed"}), at=1_000_000)
    s = run(["--reports", str(tmp_path / "*.xml")])
    assert kinds(s, "tests") == {"e2e": 1, "unit": 1}          # unit-2 is unit-1's next run
    assert outcomes(s, "unit")["passed"] == 1 and kinds(s, "tests_flaky")["unit"] == 1


def test_missing_and_half_written_reports(tmp_path):
    s = run(["--reports", str(tmp_path / "nothing" / "*.xml")])
    assert s == {("test_report_files", ("state", "read")): 0, ("test_report_files", ("state", "unreadable")): 0}
    write(tmp_path / "1" / "tests.xml", junit({"t.e2e.a::x": "passed"}), at=1_000_000)
    write(tmp_path / "2" / "tests.xml", junit({"t.e2e.a::x": "passed", "t.e2e.a::y": "passed"})[:60], at=1_000_100)
    write(tmp_path / "3" / "tests.xml", "", at=1_000_200)
    s = run(["--reports", str(tmp_path / "*" / "tests.xml")])
    assert kinds(s, "tests")["e2e"] == 1                     # the half-written run is skipped; the previous stands
    assert s[("test_report_files", ("state", "unreadable"))] == 2


def test_history_keeps_runs_of_a_report_overwritten_in_place(tmp_path):
    report, hist = tmp_path / "junit.xml", tmp_path / "hist.json"
    argv = ["--reports", str(report), "--history", str(hist)]
    for i, outcome in enumerate(["passed", "failed", "passed", "passed", "passed"]):
        write(report, junit({"t.e2e.a::x": outcome}), at=1_000_000 + i)
        s = run(argv)
    assert kinds(s, "tests_confirmed")["e2e"] == 1 and kinds(s, "tests_flaky")["e2e"] == 1
    report.unlink()
    s = run(argv)                                             # the last run seen still stands
    assert kinds(s, "tests")["e2e"] == 1
    hist.write_text("{not json")
    s = run(argv)                                             # a broken history starts again
    assert ("tests", ("kind", "e2e")) not in s


def test_history_counts_tests_added_and_removed(tmp_path):
    """The counters balance the level: tests(now) - tests(first) = added - removed after the
    first run, kind by kind, across runs in directories and a run that arrives late."""
    hist = tmp_path / "hist.json"
    glob = str(tmp_path / "r" / "*" / "tests.xml")
    argv = ["--reports", glob, "--history", str(hist)]
    s = run(argv)
    assert kinds(s, "tests_added_total") == {}                              # nothing counted yet
    write(tmp_path / "r" / "1" / "tests.xml", junit({"t.unit.a::x": "passed", "t.e2e.a::y": "passed"}), at=1_000_000)
    s = run(argv)
    assert kinds(s, "tests_added_total") == {"e2e": 1, "unit": 1}
    write(tmp_path / "r" / "2" / "tests.xml", junit({"t.unit.a::x": "passed", "t.e2e.a::y": "passed", "t.e2e.a::z": "passed",
                                                     "t.e2e.b::w": "failed"}), at=1_000_100)
    write(tmp_path / "r" / "3" / "tests.xml", junit({"t.e2e.a::y": "passed", "t.e2e.a::z": "passed", "t.e2e.b::w": "passed"}),
          at=1_000_200)
    s = run(argv)                                           # two runs since the last round, tallied in order
    assert kinds(s, "tests_added_total") == {"e2e": 3, "unit": 1}
    assert kinds(s, "tests_removed_total") == {"e2e": 0, "unit": 1}
    assert kinds(s, "tests") == {"e2e": 3}                                # every unit test removed: unit is absent
    write(tmp_path / "r" / "0" / "tests.xml", junit({"t.e2e.old::q": "passed"}), at=999_000)   # an older run found late
    s = run(argv)
    assert kinds(s, "tests_added_total")["e2e"] == 3 and kinds(s, "tests")["e2e"] == 3
    assert run(argv) == s                                   # nothing new: nothing counted again


def test_without_history_no_counters(tmp_path):
    write(tmp_path / "r.xml", junit({"t.unit.a::x": "passed"}))
    assert not [k for k in run(["--reports", str(tmp_path / "r.xml")]) if k[0].endswith("_total")]


def test_bad_arguments_exit_2(tmp_path):
    for argv in (["--reports", "x", "--kind", "e2e"], ["--reports", "x", "--confirm", "5", "--window", "3"], []):
        p = subprocess.run([sys.executable, "-m", "orchestra.instruments.test_reports", *argv], capture_output=True, check=False)
        assert p.returncode == 2


def test_runs_as_a_script_with_no_orchestra_import(tmp_path):
    """A repository may copy the file and run it with any Python: it imports only the standard library."""
    src = tr.__file__
    from pathlib import Path
    assert "orchestra" not in "".join(line for line in Path(src).read_text().splitlines() if line.startswith(("import ", "from ")))
    write(tmp_path / "r.xml", junit({"t.unit.a::x": "passed"}))
    p = subprocess.run([sys.executable, "-I", src, "--reports", str(tmp_path / "r.xml")], capture_output=True, text=True, check=True,
                       cwd=tmp_path)
    assert samples(p.stdout)[("tests", ("kind", "unit"))] == 1
