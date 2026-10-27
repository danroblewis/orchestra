"""Real `orchestra run` processes on one project: only one launches, and the others leave its
record and its processes alone."""

import os
import random
import signal
import subprocess
import sys
import time

import psutil
import pytest

from orchestra import runtime
from orchestra.config import init_project


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    return init_project(r)


@pytest.fixture
def hosts(project, tmp_path):
    """Start `orchestra run` processes for the project; every one, and every `sleep` they leave,
    is killed at the end."""
    started: list[subprocess.Popen] = []
    n = random.randint(100_000, 999_999)                  # the `sleep <n>` this test's machine runs
    (project.repo_root / "orchestra.toml").write_text(
        f'[discovery]\nevery = "1h"\n\n[[machines]]\nname = "nap"\ncommand = "sleep {n}"\n')

    def start(name: str) -> subprocess.Popen:
        out = (tmp_path / f"{name}.out").open("w")
        p = subprocess.Popen([sys.executable, "-m", "orchestra", "--repo", str(project.repo_root), "run"],
                             stdout=out, stderr=subprocess.STDOUT, env={**os.environ})
        p.out = tmp_path / f"{name}.out"
        started.append(p)
        return p

    start.n = n
    yield start
    for p in started:
        if p.poll() is None:
            p.kill()
            p.wait()
    for s in sleeps(n):
        s.kill()


def sleeps(n: int) -> list[psutil.Process]:
    out = []
    for p in psutil.process_iter(["cmdline"]):
        try:
            if p.info["cmdline"] == ["sleep", str(n)]:
                out.append(p)
        except psutil.Error:
            pass
    return out


def until(cond, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.1)
    raise AssertionError("condition not met in time")


def said(p, text: str) -> bool:
    return text in p.out.read_text()


def test_a_host_that_does_not_launch_leaves_the_launch_alone(project, hosts):
    a = hosts("a")
    until(lambda: (runtime.read(project).get("processes") or {}).get("nap", {}).get("state") == "running")
    record = runtime.read(project)
    assert record["launcher"]["pid"] == a.pid
    child = record["processes"]["nap"]["pid"]

    b = hosts("b")
    until(lambda: said(b, "this one starts none"))
    assert runtime.read(project)["launcher"]["pid"] == a.pid
    b.send_signal(signal.SIGTERM)
    b.wait(timeout=30)
    assert runtime.read(project)["launcher"]["pid"] == a.pid      # b did not clear a's claim

    c = hosts("c")
    until(lambda: said(c, "this one starts none"))
    time.sleep(1.5)                                                # a tick or two, had c launched
    assert [s.pid for s in sleeps(hosts.n)] == [child]             # one copy, and a's child was not killed
    record = runtime.read(project)
    assert record["launcher"]["pid"] == a.pid and record["processes"]["nap"]["pid"] == child
    assert {int(k) for k in record["hosts"]} == {a.pid, c.pid}

    a.send_signal(signal.SIGTERM)
    a.wait(timeout=30)
    until(lambda: not sleeps(hosts.n))
    assert "launcher" not in runtime.read(project) and "processes" not in runtime.read(project)


def test_a_host_takes_the_launch_from_a_dead_one_and_stops_its_orphans(project, hosts):
    a = hosts("a")
    until(lambda: (runtime.read(project).get("processes") or {}).get("nap", {}).get("state") == "running")
    orphan = runtime.read(project)["processes"]["nap"]["pid"]
    a.kill()                                                       # no chance to stop its processes
    a.wait()
    assert psutil.pid_exists(orphan)
    b = hosts("b")
    until(lambda: (runtime.read(project).get("launcher") or {}).get("pid") == b.pid
          and (runtime.read(project).get("processes") or {}).get("nap", {}).get("pid") not in (None, orphan))
    until(lambda: not psutil.pid_exists(orphan) or psutil.Process(orphan).status() == psutil.STATUS_ZOMBIE)
    assert len(sleeps(hosts.n)) == 1


def test_a_reused_pid_is_not_a_live_holder():
    me = runtime.me()
    assert runtime.holds(me)
    assert not runtime.holds({**me, "since": me["since"] - 3600})  # the same pid, another process
    assert not runtime.holds({"pid": me["pid"]}) and not runtime.holds({})
    assert runtime.launcher({"launcher": {**me, "since": 1.0}}) is None


def test_sighup_stops_the_host_and_its_processes(project, hosts):
    a = hosts("a")
    until(lambda: (runtime.read(project).get("processes") or {}).get("nap", {}).get("state") == "running")
    a.send_signal(signal.SIGHUP)                                   # the terminal it ran in was closed
    a.wait(timeout=30)
    until(lambda: not sleeps(hosts.n), timeout=5)
    assert said(a, "host stopped")
