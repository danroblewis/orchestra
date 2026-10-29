"""A launched process's log on the Core page (orchestra/web/process_logs.py, web/core.py): found by
name, read from the end within a bound, only inside the project, a missing one a note."""

import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from orchestra import plugins, runtime
from orchestra.config import init_project
from orchestra.web import process_logs
from orchestra.web.app import create_app
from orchestra.web.auth import bearer


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(plugins, "entry_points", lambda group: [])
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    return init_project(r)


def write_log(project, name, text):
    d = project.logs_dir / "machines"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.log").write_text(text)
    return d / f"{name}.log"


def roots(project):
    return [project.state_dir, project.repo_root]


def test_the_tail_is_the_last_lines_oldest_first_with_more_before(project):
    write_log(project, "tasks.scheduler", "".join(f"line {i}\n" for i in range(1000)))
    got = process_logs.read("tasks.scheduler", project.logs_dir, roots(project), 200)
    assert got["lines"][0] == "line 800" and got["lines"][-1] == "line 999" and len(got["lines"]) == 200
    assert got["more"] and got["note"] is None and got["size"] > 0
    assert process_logs.read("tasks.scheduler", project.logs_dir, roots(project), 5000)["lines"][0] == "line 0"
    assert not process_logs.read("tasks.scheduler", project.logs_dir, roots(project), 2000)["more"]


def test_a_read_is_bounded_from_the_end(project):
    write_log(project, "big", "x" * 5000 + "\n" + "".join(f"line {i}\n" for i in range(100)))
    got = process_logs.read("big", project.logs_dir, roots(project), 2000, max_bytes=400)
    assert got["more"] and got["lines"][-1] == "line 99" and all(ln.startswith("line ") for ln in got["lines"])


def test_an_error_in_the_last_lines_is_marked(project):
    write_log(project, "tasks.scheduler", "ok\nticket 7: git-spice is not on PATH\nstill polling\n")
    assert "git-spice" in process_logs.hint("tasks.scheduler", project.logs_dir, roots(project))
    write_log(project, "tasks.scheduler", "Traceback (most recent call last):\n  File x\nValueError: bad\n")
    assert process_logs.hint("tasks.scheduler", project.logs_dir, roots(project)) == "ValueError: bad"
    write_log(project, "calm", "started\nserving\n")
    assert process_logs.hint("calm", project.logs_dir, roots(project)) is None


def test_missing_odd_names_and_links_out_of_the_project_are_notes(project, tmp_path):
    assert process_logs.read("nope", project.logs_dir, roots(project))["note"].startswith("no log yet")
    for bad in ("../secret", "a/b", ".hidden", ""):
        assert process_logs.read(bad, project.logs_dir, roots(project))["note"] == "not a process name"
    (tmp_path / "secret").write_text("key")
    (project.logs_dir / "machines").mkdir(parents=True, exist_ok=True)
    os.symlink(tmp_path / "secret", project.logs_dir / "machines" / "sneaky.log")
    got = process_logs.read("sneaky", project.logs_dir, roots(project))
    assert got["lines"] == [] and "outside the project" in got["note"]


def test_the_core_page_lists_and_reads_a_process_log_even_when_the_host_is_not_running(project):
    write_log(project, "tasks.scheduler", "2026-10-28 09:00:00 [orchestra] started `x`\nticket 3 failed: git-spice is not on PATH\n")
    c = TestClient(create_app(project), headers=bearer(project))
    sources = {s["id"]: s for s in c.get("/api/core/logs/sources").json()["sources"]}
    assert sources["process:tasks.scheduler"]["running"] is False and "git-spice" in sources["process:tasks.scheduler"]["error"]
    got = c.get("/api/core/processes/tasks.scheduler/log", params={"lines": 50}).json()
    assert got["lines"][-1].endswith("not on PATH") and "git-spice" in got["error"]
    assert c.get("/api/core/logs", params={"source": "process:tasks.scheduler"}).json()["lines"] == got["lines"]
    assert c.get("/api/core/processes/ghost/log").json()["note"].startswith("no log yet")


def test_a_recorded_process_carries_its_log_error_into_the_host_card(project):
    write_log(project, "tasks.scheduler", "FATAL: cannot reach the bus\n")
    runtime.update(project, lambda d: d.update(processes={"tasks.scheduler": {"pid": None, "state": "exited", "code": 1,
                                                                           "restarts": 4, "owner": "tasks"}}))
    from orchestra.web.core import CoreProbe
    probe = CoreProbe.__new__(CoreProbe)
    probe.project = project
    row = probe._processes(runtime.read(project))[0]
    assert row["code"] == 1 and row["restarts"] == 4 and row["log_error"] == "FATAL: cannot reach the bus"
