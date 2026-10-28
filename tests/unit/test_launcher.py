"""The launcher (orchestra/launcher.py): `orchestra run` keeps the declared commands running.

The commands are tiny Python programs; the pauses are shortened so a crash loop takes a second."""

import itertools
import json
import os
import subprocess
import sys
import threading
import time

import psutil
import pytest

from orchestra import runtime
from orchestra.config import init_project
from orchestra.launcher import Launcher, Process, check, from_toml

PY = sys.executable


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    return init_project(r)


def declare(project, *machines):
    """Write orchestra.toml with these [[machines]] (name, python code, restart)."""
    text = '[metrics]\nurl = "file"\n'
    for name, code, restart in machines:
        text += f'\n[[machines]]\nname = "{name}"\ncommand = {_toml_list([PY, "-c", code])}\nrestart = "{restart}"\n'
    path = project.repo_root / "orchestra.toml"
    path.write_text(text)
    t = time.time() + next(_later)
    os.utime(path, (t, t))                      # a new mtime, however fast the test rewrites it


_later = itertools.count(1)


def _toml_list(items):
    return "[" + ", ".join(json.dumps(i) for i in items) + "]"     # a JSON string is a TOML basic string


def launcher(project, **kw):
    events, lines = [], []
    la = Launcher(project, lambda t, d: events.append((t, d)), lines.append,
                  backoff=0.05, stable_s=kw.pop("stable_s", 5.0), give_up_after=kw.pop("give_up_after", 3), grace=2.0, **kw)
    return la, events, lines


def until(cond, la=None, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if la is not None:
            la.tick()
        if cond():
            return True
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


SLEEPER = "import time\nwhile True: time.sleep(0.1)"


def test_starts_a_declared_command_with_its_env_and_log(project):
    out = project.repo_root / "env.txt"
    code = (f"import os; open({str(out)!r}, 'w').write(os.environ['ORCHESTRA_REPO'] + '|' + "
            "os.environ['ORCHESTRA_MACHINE_LOG'] + '|' + os.getcwd()); print('hello'); import time; time.sleep(30)")
    declare(project, ("telemetry", code, "always"))
    la, events, _ = launcher(project)
    try:
        until(lambda: out.exists() and out.read_text(), la)
        repo, log, cwd = out.read_text().split("|")
        assert repo == str(project.repo_root)
        assert log == str(project.logs_dir / "machines" / "telemetry.log")
        assert os.path.realpath(cwd) == os.path.realpath(project.repo_root)
        until(lambda: "hello" in (project.logs_dir / "machines" / "telemetry.log").read_text())
        rec = runtime.read(project)["processes"]["telemetry"]
        assert rec["state"] == "running" and runtime.alive(rec["pid"]) and rec["owner"] == "project"
        assert events[0][0] == "orchestra.process.started" and events[0][1]["name"] == "telemetry"
    finally:
        la.stop_all()
    assert "processes" not in runtime.read(project)


def test_restarts_one_that_exits(project):
    declare(project, ("blip", "import time; time.sleep(0.05)", "always"))
    la, events, _ = launcher(project, give_up_after=100)
    try:
        until(lambda: la.runs["blip"].restarts >= 2, la)
        assert sum(t == "orchestra.process.started" for t, _ in events) >= 2
        assert any(t == "orchestra.process.exited" and d["code"] == 0 and d["restart_in"] for t, d in events)
    finally:
        la.stop_all()


def test_gives_up_after_a_crash_loop_and_says_so(project):
    declare(project, ("broken", "raise SystemExit(3)", "always"))
    la, events, lines = launcher(project, give_up_after=3)
    try:
        until(lambda: la.runs["broken"].state == "gave_up", la)
        starts = sum(t == "orchestra.process.started" for t, _ in events)
        for _ in range(20):                     # it stays given up
            la.tick()
            time.sleep(0.01)
        assert sum(t == "orchestra.process.started" for t, _ in events) == starts == 3
        assert ("orchestra.process.gave_up", {"name": "broken", "code": 3, "failures": 3}) in events
        assert any("gave up" in ln for ln in lines)
        assert "gave up" in (project.logs_dir / "machines" / "broken.log").read_text()
        assert runtime.read(project)["processes"]["broken"]["state"] == "gave_up"
        declare(project, ("broken", "import time; time.sleep(30)", "always"))     # fixed: tried again
        until(lambda: la.runs["broken"].state == "running", la)
    finally:
        la.stop_all()


def test_restart_policies(project):
    declare(project, ("once", "pass", "never"), ("fails", "raise SystemExit(1)", "on-failure"), ("ok", "pass", "on-failure"))
    la, events, _ = launcher(project, give_up_after=2)
    try:
        until(lambda: la.runs["once"].state == "exited" and la.runs["ok"].state == "exited"
              and la.runs["fails"].state == "gave_up", la)
        starts = [d["name"] for t, d in events if t == "orchestra.process.started"]
        assert starts.count("once") == 1 and starts.count("ok") == 1 and starts.count("fails") == 2
    finally:
        la.stop_all()


def test_follows_orchestra_toml_as_it_changes(project):
    declare(project, ("a", SLEEPER, "always"))
    la, _, _ = launcher(project)
    try:
        until(lambda: "a" in la.runs and la.runs["a"].state == "running", la)
        a_pid = la.runs["a"].popen.pid
        declare(project, ("a", SLEEPER, "always"), ("b", SLEEPER, "always"))      # added by a merge
        until(lambda: "b" in la.runs and la.runs["b"].state == "running", la)
        assert la.runs["a"].popen.pid == a_pid                                     # the other left alone
        declare(project, ("b", SLEEPER, "always"))                                 # removed
        until(lambda: "a" not in la.runs and not runtime.alive(a_pid), la)
        b_pid = la.runs["b"].popen.pid
        declare(project, ("b", SLEEPER + "  # changed", "always"))                 # its command changed
        until(lambda: la.runs["b"].popen is not None and la.runs["b"].popen.pid != b_pid, la)
        assert not runtime.alive(b_pid)
        assert set(runtime.read(project)["processes"]) == {"b"}
    finally:
        la.stop_all()


def test_stopping_stops_what_a_process_started(project):
    child = project.repo_root / "child.pid"
    code = ("import subprocess, sys, time; p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"open({str(child)!r}, 'w').write(str(p.pid)); time.sleep(60)")
    declare(project, ("parent", code, "always"))
    la, _, _ = launcher(project)
    until(lambda: child.exists() and child.read_text(), la)
    pid = int(child.read_text())
    assert runtime.alive(pid)
    la.stop_all()
    until(lambda: not runtime.alive(pid))


def test_bad_entries_are_reported_and_the_rest_run(project):
    (project.repo_root / "orchestra.toml").write_text(
        '[[machines]]\nname = "has space"\ncommand = "true"\n\n[[machines]]\nname = "nocmd"\n\n'
        '[[machines]]\nname = "x"\ncommand = "true"\nrestart = "sometimes"\n\n'
        f'[[machines]]\nname = "good"\ncommand = {_toml_list([PY, "-c", SLEEPER])}\n')
    la, _, lines = launcher(project, plugin_processes=[Process("good", [PY, "-c", SLEEPER], owner="tools"),
                                                       Process("missing", ["/no/such/program"], owner="tools")])
    try:
        until(lambda: "good" in la.runs and la.runs["good"].state == "running", la)
        text = "\n".join(lines)
        assert "bad name 'has space'" in text and "nocmd: empty command" in text and "restart must be one of" in text
        until(lambda: la.runs["tools.missing"].state == "gave_up", la)      # a command that cannot start is a failure
        assert "cannot start" in (project.logs_dir / "machines" / "tools.missing.log").read_text()
        assert sum("bad name" in ln for ln in lines) == 1                   # said once, not every tick
    finally:
        la.stop_all()


def test_a_toml_that_does_not_parse_keeps_what_runs(project):
    declare(project, ("a", SLEEPER, "always"))
    la, _, lines = launcher(project)
    try:
        until(lambda: "a" in la.runs and la.runs["a"].state == "running", la)
        (project.repo_root / "orchestra.toml").write_text("[[machines]\nbroken")
        la.tick()
        assert la.runs["a"].state == "running" and any("keeping what runs" in ln for ln in lines)
    finally:
        la.stop_all()


def test_python_is_the_python_orchestra_runs_in(project, monkeypatch):
    """A first word python or python3 runs with sys.executable, whatever is first on the PATH (here
    a `python` that only fails), so what Orchestra imports, the program imports."""
    fake = project.repo_root / "fakebin"
    fake.mkdir()
    for name in ("python", "python3"):
        (fake / name).write_text("#!/bin/sh\nexit 9\n")
        (fake / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    out = project.repo_root / "which.txt"
    code = f"import sys, orchestra; open({str(out)!r}, 'w').write(sys.executable)"
    path = project.repo_root / "orchestra.toml"
    path.write_text(f'[metrics]\nurl = "file"\n\n[[machines]]\nname = "py"\ncommand = {_toml_list(["python3", "-c", code])}\n'
                    'restart = "never"\n')
    la, _, _ = launcher(project)
    try:
        until(lambda: out.exists() and out.read_text(), la)
        assert out.read_text() == PY
    finally:
        la.stop_all()
    assert Process("a", "python3.11 x.py").argv() == ["python3.11", "x.py"]       # only python and python3
    assert Process("a", ["python", "-m", "x"]).argv() == [PY, "-m", "x"]


def test_check_and_from_toml():
    assert check(Process("ok", "uv run python x.py")) is None
    assert Process("ok", "python 'a b.py' --n 2").argv() == [PY, "a b.py", "--n", "2"]
    assert "unterminated" in check(Process("q", "python 'a")).lower() or "quotation" in check(Process("q", "python 'a")).lower()
    with pytest.raises(TypeError, match=r"\[\[machines\]\]"):
        from_toml({"machines": {"name": "x"}})
    assert from_toml({}) == []


def test_orphans_of_a_killed_host_are_stopped(project):
    p = subprocess.Popen([PY, "-c", SLEEPER], start_new_session=True)
    try:
        runtime.update(project, lambda d: d.__setitem__("processes", {"old": {"pid": p.pid, "since": psutil.Process(p.pid).create_time()}}))
        la, _, lines = launcher(project)
        la.reap_orphans()
        p.wait(timeout=5)
        assert any("left running by a previous orchestra run" in ln for ln in lines)
    finally:
        if p.poll() is None:
            p.kill()


def test_the_host_launches_the_project_and_plugin_processes_and_stops_them(project):
    from fastapi.testclient import TestClient

    from orchestra.host import Host
    from orchestra.plugins import Plugin
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer

    class EntryPoint:
        name = "tools"

        def load(self):
            return lambda project: Plugin("tools", processes=[Process("helper", [PY, "-c", SLEEPER])])

    declare(project, ("telemetry", SLEEPER, "always"))
    host = Host(project, interval=0.1, found=lambda: [EntryPoint()], launch_every=0.05)
    t = threading.Thread(target=host.run)
    t.start()
    try:
        until(lambda: set(runtime.read(project).get("processes") or {}) == {"telemetry", "tools.helper"}
              and all(r["state"] == "running" for r in runtime.read(project)["processes"].values()))
        procs = runtime.read(project)["processes"]
        assert procs["tools.helper"]["owner"] == "tools"
        pids = [r["pid"] for r in procs.values()]
        c = TestClient(create_app(project), headers=bearer(project))                         # the Core page shows them and their logs
        assert {p["name"]: p["alive"] for p in c.get("/api/core").json()["host"]["processes"]} == {"tools.helper": True, "telemetry": True}
        assert {"process:tools.helper", "process:telemetry"} <= {s["id"] for s in c.get("/api/core/logs/sources").json()["sources"]}
        assert any("started" in ln for ln in c.get("/api/core/logs", params={"source": "process:telemetry"}).json()["lines"])
    finally:
        host.stop()
        t.join(timeout=20)
    assert not t.is_alive()
    assert not any(runtime.alive(p) for p in pids)
    assert "processes" not in runtime.read(project)


STUBBORN = "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nwhile True: time.sleep(0.1)"


def test_an_orphan_that_ignores_sigterm_is_killed_before_reaping_returns(project):
    p = subprocess.Popen([PY, "-c", STUBBORN], start_new_session=True)
    try:
        time.sleep(0.3)                                             # its handler is in place
        runtime.update(project, lambda d: d.__setitem__("processes", {"old": {"pid": p.pid, "since": psutil.Process(p.pid).create_time(),
                                                                              "stop_grace_s": 0.5}}))
        la, _, lines = launcher(project)                            # grace 2 s; the record's own 0.5 s wins
        t0 = time.time()
        la.reap_orphans()
        assert 0.4 < time.time() - t0 < 1.9
        assert p.wait(timeout=1) == -9                              # dead when reaping returned, not later
        assert any("did not stop within 0.5 s; killed" in ln for ln in lines)
    finally:
        if p.poll() is None:
            p.kill()


def test_each_process_has_its_own_stop_grace(project):
    (project.repo_root / "orchestra.toml").write_text(
        f'[[machines]]\nname = "quick"\ncommand = {_toml_list([PY, "-c", STUBBORN])}\nstop_grace = 0.3\n\n'
        f'[[machines]]\nname = "slow"\ncommand = {_toml_list([PY, "-c", STUBBORN])}\n')
    la, _, _ = launcher(project)                                   # the launcher's own grace: 2 s
    until(lambda: all(n in la.runs and la.runs[n].state == "running" for n in ("quick", "slow")), la)
    time.sleep(0.3)
    quick, slow = la.runs["quick"].popen, la.runs["slow"].popen
    assert runtime.read(project)["processes"]["quick"]["stop_grace_s"] == 0.3
    t0 = time.time()
    threading.Thread(target=la.stop_all).start()
    quick.wait(timeout=1.5)
    assert time.time() - t0 < 1.5 and slow.poll() is None          # killed at its own grace, the other still waits
    slow.wait(timeout=5)
    assert time.time() - t0 >= 1.9
    assert check(Process("x", "true", stop_grace_s="soon")) and check(Process("x", "true", stop_grace_s=-1))
    assert from_toml({"machines": [{"name": "x", "command": "true", "stop_grace": 30}]})[0].stop_grace_s == 30


def test_a_project_machine_never_takes_a_plugin_process_s_place(project):
    declare(project, ("sampler", SLEEPER, "always"), ("tools.helper", SLEEPER, "always"))
    la, _, lines = launcher(project, plugin_processes=[Process("sampler", [PY, "-c", SLEEPER], owner="tools"),
                                                       Process("helper", [PY, "-c", SLEEPER], owner="tools")])
    try:
        until(lambda: len(la.runs) == 3 and all(r.state == "running" for r in la.runs.values()), la)
        assert {n: r.spec.owner for n, r in la.runs.items()} == {"sampler": "project", "tools.sampler": "tools", "tools.helper": "tools"}
        assert sum("'tools.helper' has the form tools.<name>, kept for the plugin tools's processes" in ln for ln in lines) == 1
        assert (project.logs_dir / "machines" / "tools.sampler.log").exists()
    finally:
        la.stop_all()


def test_a_plugin_s_processes_follow_its_section_in_orchestra_toml(project):
    from orchestra.host import Host
    from orchestra.plugins import Plugin

    def make(project):
        if "broken" in project.config.raw:
            raise RuntimeError("a mistake in the plugin")
        return Plugin("tools", processes=[Process("helper", [PY, "-c", SLEEPER])] if "tools" in project.config.raw else [])

    class EntryPoint:
        name = "tools"

        def load(self):
            return make

    def write(text):
        path = project.repo_root / "orchestra.toml"
        path.write_text('[metrics]\nurl = "file"\n' + text)
        t = time.time() + next(_later)
        os.utime(path, (t, t))

    def procs():
        return {n: r["state"] for n, r in (runtime.read(project).get("processes") or {}).items()}

    write("")
    host = Host(project, interval=0.1, found=lambda: [EntryPoint()], launch_every=0.05)
    t = threading.Thread(target=host.run)
    t.start()
    try:
        until(lambda: "launcher" in runtime.read(project))
        time.sleep(0.3)
        assert procs() == {}
        write("\n[tools]\n")                                        # the plugin's section added: its process starts
        until(lambda: procs() == {"tools.helper": "running"})
        pid = runtime.read(project)["processes"]["tools.helper"]["pid"]
        write("\n[tools]\nbroken = true\n")                         # the plugin fails to load: what it declared stands
        time.sleep(0.5)
        assert procs() == {"tools.helper": "running"} and runtime.read(project)["processes"]["tools.helper"]["pid"] == pid
        write("\n[tools\n")                                         # the file does not parse: likewise
        time.sleep(0.5)
        assert runtime.read(project)["processes"]["tools.helper"]["pid"] == pid
        write("")                                                   # the section removed: its process stops
        until(lambda: procs() == {})
        assert not runtime.alive(pid)
    finally:
        host.stop()
        t.join(timeout=20)


def test_a_process_is_restarted_when_the_settings_it_names_change(project):
    """A plugin's process that reads its settings once names them (``config_keys``): a change under
    them restarts it, a change elsewhere does not, and one given up on is tried again."""
    from orchestra.launcher import fingerprint

    out = project.repo_root / "starts.txt"
    code = (f"import tomllib; v = tomllib.load(open('orchestra.toml', 'rb')).get('tools', {{}}).get('every', 0)\n"
            f"open({str(out)!r}, 'a').write(f'{{v}}\\n')\nif v == 'bad': raise SystemExit(2)\n"
            "import time\nwhile True: time.sleep(0.1)")

    def write(text):
        path = project.repo_root / "orchestra.toml"
        path.write_text('[metrics]\nurl = "file"\n' + text)
        t = time.time() + next(_later)
        os.utime(path, (t, t))

    def starts():
        return out.read_text().split() if out.exists() else []

    write('[tools]\nevery = "1s"\n')
    la, _, _ = launcher(project, give_up_after=2,
                        plugin_processes=lambda: [Process("helper", [PY, "-c", code], owner="tools",
                                                          config_keys=["tools"])])
    try:
        until(lambda: starts() == ["1s"], la)
        write('[tools]\nevery = "1s"\n\n[other]\nx = 1\n')          # not its settings: left running
        for _ in range(20):
            la.tick()
            time.sleep(0.01)
        assert starts() == ["1s"]
        write('[tools]\nevery = "2s"\n')                              # its settings: restarted
        until(lambda: starts() == ["1s", "2s"] and la.runs["tools.helper"].state == "running", la)
        write('[tools]\nevery = "bad"\n')
        until(lambda: la.runs["tools.helper"].state == "gave_up", la)
        write('[tools]\nevery = "3s"\n')                              # fixed: tried again
        until(lambda: starts()[-1] == "3s" and la.runs["tools.helper"].state == "running", la)
    finally:
        la.stop_all()
    assert fingerprint({"a": {"b": 1}}, ["a.b"]) != fingerprint({"a": {"b": 2}}, ["a.b"])
    assert fingerprint({}, ["a.b"]) != fingerprint({"a": {"b": None, "c": 1}}, ["a"]) and fingerprint({}, []) == ""
    assert check(Process("x", "true", config_keys="tools")) is not None
