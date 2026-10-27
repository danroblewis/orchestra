"""The collectors on their intervals (orchestra/collect/runner.py): orchestra.toml read again on
each tick, rounds started when due, failures counted, and each instrument's health in the runtime
record: an instrument is not a machine, and nothing is announced for it."""

import itertools
import os
import subprocess
import time
from pathlib import Path

import pytest

from orchestra import runtime
from orchestra.collect.runner import FAILURES, Collecting
from orchestra.config import init_project
from orchestra.metrics import for_project
from orchestra.web.machine_logs import readable


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    (r / "machines").mkdir()
    for name, body in {"disk.sh": 'echo "disk_free_bytes 100"\necho "files_total 3"\n',
                       "broken.sh": "exit 1\n",
                       "plumbing.sh": 'echo "orchestra_disk_bytes 1"\necho "disk_bytes 1"\n'}.items():
        (r / "machines" / name).write_text("#!/bin/sh\n" + body)
        (r / "machines" / name).chmod(0o755)
    return init_project(r)


_later = itertools.count(1)


def declare(project, text):
    path = project.repo_root / "orchestra.toml"
    path.write_text('[metrics]\nurl = "file"\n' + text)
    t = time.time() + next(_later)
    os.utime(path, (t, t))                      # a new mtime, however fast the test rewrites it


def collecting(project):
    lines = []
    c = Collecting(project, lines.append)
    return c, runtime, lines


def series(project, name):
    return [labels for n, labels in for_project(project).series(name) if n == name]


def test_a_collector_added_runs_and_one_removed_stops(project):
    c, _, lines = collecting(project)
    declare(project, '\n[[collect]]\nname = "disk"\ncommand = "machines/disk.sh"\nevery = "60s"\n')
    c.tick(1000.0)
    assert c.idle(10)
    store = for_project(project)
    assert store.latest("disk_free_bytes", {"instrument": "disk", "project": project.key})[1] == 100.0
    assert store.latest("files_total", {"instrument": "disk"})[1] == 3.0
    c.tick(1001.0)                                         # records the round's health
    rec = runtime.read(project)["instruments"]["disk"]
    assert rec["kind"] == "script" and rec["target"] == "machines/disk.sh" and rec["every_s"] == 60.0
    assert rec["points"] == 2 and rec["failures"] == 0 and rec["last_write"] > 0
    assert readable(rec["log"], [project.repo_root, project.state_dir])[0] is not None   # the Instruments page can show it
    assert "/logs/instruments/" in rec["log"] and "wrote 2 points" in Path(rec["log"]).read_text()

    c.tick(1030.0)                                         # not due yet
    assert c.idle(10)
    assert len(store.raw("disk_free_bytes", {"instrument": "disk"})) == 1
    c.tick(1061.0)
    assert c.idle(10)
    assert len(store.raw("disk_free_bytes", {"instrument": "disk"})) == 2

    declare(project, '\n[[collect]]\nname = "disk"\ncommand = "machines/disk.sh"\nevery = "60s"\n'
                     '\n[[collect]]\nname = "more"\ncommand = "machines/plumbing.sh"\n')
    c.tick(1062.0)                                         # the new one runs at once; disk is not due
    assert c.idle(10)
    assert len(store.raw("disk_free_bytes", {"instrument": "disk"})) == 2
    assert store.latest("disk_bytes", {"instrument": "more"}) is not None
    assert sorted(runtime.read(project)["instruments"]) == ["disk", "more"]

    declare(project, "")
    c.tick(5000.0)
    assert c.idle(10)
    assert len(store.raw("disk_free_bytes", {"instrument": "disk"})) == 2
    assert c.wanted == {}
    assert any("disk: no longer declared" in ln for ln in lines)
    c.tick(5001.0)
    assert "instruments" not in runtime.read(project)


def test_a_changed_collector_starts_over(project):
    c, _, _ = collecting(project)
    declare(project, '\n[[collect]]\nname = "disk"\ncommand = "machines/disk.sh"\nevery = "60s"\n')
    c.tick(1000.0)
    assert c.idle(10)
    declare(project, '\n[[collect]]\nname = "disk"\ncommand = "machines/disk.sh"\nevery = "5m"\n')
    c.tick(1001.0)                                         # changed: due at once
    assert c.idle(10)
    assert len(for_project(project).raw("disk_free_bytes", {"instrument": "disk"})) == 2
    c.tick(1002.0)
    assert runtime.read(project)["instruments"]["disk"]["every_s"] == 300.0


def test_a_failing_collector_writes_nothing_and_is_counted(project):
    c, _, lines = collecting(project)
    declare(project, '\n[[collect]]\nname = "broken"\ncommand = "machines/broken.sh"\nevery = "1s"\n')
    for t in (1000.0, 1002.0):
        c.tick(t)
        assert c.idle(10)
    store = for_project(project)
    assert store.series("", {"instrument": "broken"}) == []          # nothing that would look like it is working
    assert [v for _, v in store.raw(FAILURES, {"collector": "broken", "machine": "orchestra-host"})] == [1.0, 2.0]
    assert sum("broken: exited with code 1; nothing written" in ln for ln in lines) == 2
    c.tick(1003.0)
    rec = runtime.read(project)["instruments"]["broken"]
    assert rec["failures"] == 2 and "exited with code 1" in rec["last_error"] and "last_write" not in rec


def test_orchestra_series_are_refused_with_a_line_saying_to_rename(project):
    c, _, lines = collecting(project)
    declare(project, '\n[[collect]]\nname = "p"\ncommand = "machines/plumbing.sh"\nevery = "1s"\n')
    for t in (1000.0, 1002.0):
        c.tick(t)
        assert c.idle(10)
    assert series(project, "orchestra_disk_bytes") == []
    assert len(for_project(project).raw("disk_bytes", {"instrument": "p"})) == 2
    refusals = [ln for ln in lines if "orchestra_disk_bytes refused" in ln]
    assert len(refusals) == 1 and "rename" in refusals[0]


def test_bad_entries_are_left_out_and_said(project):
    c, _, lines = collecting(project)
    declare(project, '\n[[collect]]\nname = "orchestra-host"\ncommand = "machines/disk.sh"\n'
                     '\n[[scrape]]\nname = "app"\nurl = "ftp://x"\n'
                     '\n[[scrape]]\nname = "ok"\nurl = "http://127.0.0.1:9/metrics"\nevery = "30s"\ntimeout = "1m"\n')
    c.tick(1000.0)
    c.stop()
    assert list(c.wanted) == ["ok"]
    assert c.wanted["ok"].timeout_s == 30.0 and c.wanted["ok"].what == "URL"
    assert any("the name is taken" in ln for ln in lines) and any("http://" in ln for ln in lines)


def test_an_instrument_may_share_a_programs_name(project):
    c, _, lines = collecting(project)
    declare(project, '\n[[machines]]\nname = "app"\ncommand = "sleep 1"\n'
                     '\n[[scrape]]\nname = "app"\nurl = "http://127.0.0.1:9/metrics"\n'
                     '\n[[scrape]]\nname = "app"\nurl = "http://127.0.0.1:10/metrics"\n'
                     '\n[[collect]]\nname = "app2"\ncommand = "machines/disk.sh"\n'
                     '\n[[machines]]\nname = "app2"\ncommand = "sleep 1"\n')
    c._read()
    assert list(c.wanted) == ["app2", "app"] and c.wanted["app"].target.endswith(":9/metrics")
    assert any("the name is taken" in ln for ln in lines)


def test_stop_kills_a_command_under_way(project):
    (project.repo_root / "machines" / "slow.sh").write_text("#!/bin/sh\nsleep 30\n")
    (project.repo_root / "machines" / "slow.sh").chmod(0o755)
    c, _, lines = collecting(project)
    declare(project, '\n[[collect]]\nname = "slow"\ncommand = "machines/slow.sh"\ntimeout = "50s"\n')
    c.tick(1000.0)
    time.sleep(0.3)
    t0 = time.time()
    c.stop()
    assert time.time() - t0 < 5
    assert c.idle(1) and not any("slow:" in ln and "nothing written" in ln for ln in lines)
