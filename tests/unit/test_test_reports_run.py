"""The test-report instrument's run mode (``--run CMD``) and what it prints when a kind is absent:
a fake test runner that writes a report, writes none, fails with one, prints noise or hangs; the
markers it records; reports older than ``--max-age``. What it prints is read with the collector's
own parser, so CMD's own output never gets into it."""

import shlex
import subprocess
import sys
import time
from io import StringIO
from unittest import mock

import pytest

from orchestra.collect.exposition import parse as parse_exposition
from orchestra.instruments import test_reports as tr

FAKE = '''
import sys, time
args = sys.argv[1:]
report = next((a.split("=", 1)[1] for a in args if a.startswith("--junitxml=")), None) or args[args.index("--out") + 1]
mode, cases, code = args[0], args[1], int(args[2])
print("collected some items: noise on stdout 1 2 3")
print("warning: noise on stderr", file=sys.stderr)
if mode == "hang":
    time.sleep(60)
rows = ""
for case in filter(None, cases.split(",")):      # module..name=outcome@marker@marker
    test, _, rest = case.partition("=")
    outcome, *markers = rest.split("@")
    cls, _, name = test.partition("..")
    props = "".join(f'<property name="marker" value="{m}"/>' for m in markers)
    rows += (f'<testcase classname="{cls}" name="{name}" time="0.5">' + ("<failure/>" if outcome == "failed" else "")
             + (f"<properties>{props}</properties>" if props else "") + "</testcase>")
if mode != "none":
    with open(report, "w") as fh:
        fh.write(f"<testsuites><testsuite>{rows}</testsuite></testsuites>")
sys.exit(code)
'''


@pytest.fixture
def fake(tmp_path):
    """A runner: ``fake(mode, "pkg.mod..name=passed@marker,...", code)`` as a --run command."""
    path = tmp_path / "fake_runner.py"
    path.write_text(FAKE)

    def cmd(mode: str, cases: str, code: int = 0, report_arg: bool = False) -> str:
        base = f"{shlex.quote(sys.executable)} {shlex.quote(str(path))} {mode} {shlex.quote(cases)} {code}"
        return f"{base} --out {{report}}" if report_arg else base
    return cmd


def samples(text: str) -> dict[tuple, float]:
    p = parse_exposition(text)
    assert not p.bad, p.bad                                    # nothing but Prometheus text
    return {(s.name, *sorted(s.labels.items())): s.value for s in p.samples}


def run(argv) -> dict[tuple, float]:
    out = StringIO()
    with mock.patch.object(sys, "stdout", out):
        assert tr.main(argv) == 0
    return samples(out.getvalue())


def kinds(s, name):
    return {dict(k[1:])["kind"]: v for k, v in s.items() if k[0] == name}


def result(s):
    return next(dict(k[1:])["result"] for k, v in s.items() if k[0] == "test_run_result" and v == 1)


TEST_SERIES = {"tests", "test_outcomes", "tests_flaky", "tests_confirmed", "tests_duration_seconds"}


def test_a_run_that_writes_a_report(tmp_path, fake, capsys):
    s = run(["--run", fake("ok", "tests.unit.t..a=passed,tests.unit.t..b=passed,tests.api.t..c=passed@acceptance"),
             "--kind", "acceptance=@acceptance", "--kind", "e2e=@e2e"])
    assert result(s) == "reported" and s[("test_run_exit_code",)] == 0 and s[("test_run_duration_seconds",)] >= 0
    assert kinds(s, "tests") == {"acceptance": 1, "unit": 2}          # e2e is named but absent: no row, not 0
    assert {k[0] for k in s if dict(k[1:]).get("kind") == "e2e"} == set()
    assert s[("test_outcomes", ("kind", "unit"), ("outcome", "failed"))] == 0      # a zero within a present kind is real
    assert s[("test_report_files", ("state", "read"))] == 1
    assert "noise" not in capsys.readouterr().err                     # a run that reported says nothing


def test_a_run_whose_tests_fail_still_reports(fake):
    s = run(["--run", fake("ok", "tests.unit.t..a=passed,tests.unit.t..b=failed", 1)])
    assert result(s) == "reported" and s[("test_run_exit_code",)] == 1
    assert s[("test_outcomes", ("kind", "unit"), ("outcome", "failed"))] == 1


def test_a_run_that_writes_no_report_prints_no_tests(tmp_path, fake, capsys):
    hist = tmp_path / "h.json"
    run(["--run", fake("ok", "tests.unit.t..a=passed"), "--history", str(hist)])
    s = run(["--run", fake("none", "", 2), "--history", str(hist)])
    assert result(s) == "no_report" and s[("test_run_exit_code",)] == 2
    assert not {k[0] for k in s} & TEST_SERIES                        # a gap, not zeros, not the last run again
    assert s[("tests_added_total", ("kind", "unit"))] == 1            # the counters stand
    err = capsys.readouterr().err
    assert "wrote no report" in err and "noise on stderr" in err       # the run's last lines, on standard error


def test_a_run_that_hangs_is_killed(fake, capsys):
    t0 = time.monotonic()
    s = run(["--run", fake("hang", "tests.unit.t..a=passed"), "--run-timeout", "0.5"])
    assert time.monotonic() - t0 < 10
    assert result(s) == "timed_out" and ("test_run_exit_code",) not in s
    assert not {k[0] for k in s} & TEST_SERIES
    assert "killed" in capsys.readouterr().err


def test_an_unreadable_report(tmp_path):
    cmd = "echo '<testsuites><testcase' > {report}"
    s = run(["--run", cmd])
    assert result(s) == "unreadable" and s[("test_report_files", ("state", "unreadable"))] == 1
    assert not {k[0] for k in s} & TEST_SERIES


def test_report_placeholder_runs_the_command_as_it_is(fake):
    s = run(["--run", fake("ok", "tests.e2e.t..a=passed", report_arg=True)])
    assert kinds(s, "tests") == {"e2e": 1}
    assert tr.command("jest --out {report}", tr.Path("/t m/r.xml")) == "jest --out '/t m/r.xml'"
    assert tr.command("uv run pytest -q", tr.Path("/t/r.xml")) == "uv run pytest -q --junitxml=/t/r.xml -p _orchestra_test_markers"


def test_runs_with_history_judge_flakiness(tmp_path, fake):
    hist = str(tmp_path / "h.json")
    for outcome in ("passed", "failed", "passed"):
        s = run(["--run", fake("ok", f"tests.unit.t..a={outcome},tests.unit.t..b=passed"), "--history", hist])
    assert kinds(s, "tests_flaky") == {"unit": 1}
    s = run(["--run", fake("ok", "tests.unit.t..a=passed,tests.unit.t..b=passed"), "--history", hist])
    assert kinds(s, "tests_confirmed") == {"unit": 1}                 # b passed four times; a twice since it failed


def test_a_kind_a_run_skips_is_absent_not_zero(tmp_path, fake):
    """A quick run without e2e, then a full one, then a quick one: e2e is printed only when it ran."""
    hist = str(tmp_path / "h.json")
    full, quick = "tests.unit.t..a=passed,tests.e2e.t..b=passed", "tests.unit.t..a=passed"
    seen = [kinds(run(["--run", fake("ok", c), "--history", hist]), "tests") for c in (quick, full, quick)]
    assert seen == [{"unit": 1}, {"unit": 1, "e2e": 1}, {"unit": 1}]


def test_markers_are_read_from_junit_properties(tmp_path):
    (tmp_path / "r.xml").write_text('<testsuite><testcase classname="tests.test_api" name="t"><properties>'
                                    '<property name="marker" value="acceptance"/></properties></testcase></testsuite>')
    s = run(["--reports", str(tmp_path / "r.xml"), "--kind", "acceptance=@acceptance"])
    assert kinds(s, "tests") == {"acceptance": 1}


def test_a_marker_rule_over_reports_without_markers_says_so(tmp_path, capsys):
    (tmp_path / "r.xml").write_text('<testsuite><testcase classname="tests.test_api" name="t"/></testsuite>')
    s = run(["--reports", str(tmp_path / "r.xml"), "--kind", "acceptance=@acceptance"])
    assert kinds(s, "tests") == {"unit": 1}
    assert "acceptance=@acceptance matches nothing" in capsys.readouterr().err


def test_kinds_come_only_from_streams_that_have_them(tmp_path):
    (tmp_path / "unit.xml").write_text('<testsuite><testcase classname="tests.unit.t" name="a"/></testsuite>')
    (tmp_path / "e2e.xml").write_text('<testsuite></testsuite>')
    s = run(["--reports", str(tmp_path / "*.xml")])
    assert kinds(s, "tests") == {"unit": 1}


def test_max_age_leaves_out_an_old_report(tmp_path):
    import os
    r = tmp_path / "r.xml"
    r.write_text('<testsuite><testcase classname="tests.unit.t" name="a"/></testsuite>')
    assert kinds(run(["--reports", str(r), "--max-age", "1h"]), "tests") == {"unit": 1}
    old = time.time() - 7200
    os.utime(r, (old, old))
    s = run(["--reports", str(r), "--max-age", "1h"])
    assert not {k[0] for k in s} & TEST_SERIES and s[("test_report_files", ("state", "stale"))] == 1


def test_the_run_timeout_stays_under_the_collect_timeout(monkeypatch):
    monkeypatch.delenv("ORCHESTRA_COLLECT_TIMEOUT", raising=False)
    assert tr.default_run_timeout() == 8
    for collect, run_s in (("10", 8), ("300", 295), ("4", 3.2)):
        monkeypatch.setenv("ORCHESTRA_COLLECT_TIMEOUT", collect)
        assert tr.default_run_timeout() == pytest.approx(run_s)


@pytest.mark.parametrize("argv", [["--run", "x", "--reports", "y"], ["--run", "x", "--max-age", "1h"],
                                  ["--reports", "y", "--run-timeout", "5s"], ["--run", " "], ["--run", "x", "--run-timeout", "soon"]])
def test_bad_run_arguments_exit_2(argv):
    p = subprocess.run([sys.executable, "-m", "orchestra.instruments.test_reports", *argv], capture_output=True, check=False)
    assert p.returncode == 2
