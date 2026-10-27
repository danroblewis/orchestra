"""A real `orchestra run` runs a project's [[collect]] script and writes what it prints to the
project's store, announcing it as a machine; stopping the host stops the collecting."""

import signal
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from orchestra.config import init_project
from orchestra.events import Events
from orchestra.metrics import for_project
from orchestra.web.app import create_app
from orchestra.web.machines import machines_view


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    (r / "machines").mkdir()
    (r / "machines" / "disk.sh").write_text('#!/bin/sh\necho "# TYPE disk_free_bytes gauge"\n'
                                            'echo "disk_free_bytes 100"\necho "files_written_total 7"\n')
    (r / "machines" / "disk.sh").chmod(0o755)
    p = init_project(r)
    (r / "orchestra.toml").write_text('[discovery]\nevery = "1h"\n\n[[collect]]\nname = "disk"\n'
                                      'command = "machines/disk.sh"\nevery = "1s"\n')
    return p


def test_orchestra_run_collects(project, tmp_path):
    out = (tmp_path / "host.out").open("w")
    host = subprocess.Popen([sys.executable, "-m", "orchestra", "--repo", str(project.repo_root), "run"],
                            stdout=out, stderr=subprocess.STDOUT)
    try:
        store = for_project(project)
        end = time.time() + 30
        while time.time() < end and len(store.raw("disk_free_bytes", {"machine": "disk"})) < 2:
            time.sleep(0.2)
        assert len(store.raw("disk_free_bytes", {"machine": "disk"})) >= 2, (tmp_path / "host.out").read_text()
        assert store.latest("files_written_total", {"machine": "disk", "project": project.key})[1] == 7.0
    finally:
        host.send_signal(signal.SIGTERM)
        host.wait(timeout=30)
    evs, _ = Events.for_project(project).read(0, limit=10_000)
    view = machines_view(evs, store.series(""))
    (disk,) = [m for m in view["machines"] if m["id"] == "disk"]
    assert disk["mode"] == "scheduled" and disk["kind"] == "program" and disk["logs"] == ["disk"]
    assert "disk_free_bytes" in disk["metrics"]

    web = TestClient(create_app(project))                     # the web app shows its log and its series
    log = web.get("/api/machines/disk/log").json()
    assert log["ok"] and any("wrote 2 points" in ln for ln in log["lines"])
    cat = web.get("/api/core/metrics/catalog").json()
    assert {"disk_free_bytes", "files_written_total"} <= {m["name"] for m in cat["metrics"]}
