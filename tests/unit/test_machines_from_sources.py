"""A series read from another store (``[[sources]]``) whose labels name a machine makes no machine
on the Machines page: a machine exists by its events (AGENTS.md rules 2 and 7). A model saved
before 2026-10-27 that lists one is not read for it either."""

import subprocess
import time

from fastapi.testclient import TestClient

from orchestra.config import init_project
from orchestra.sd.model import Flow, Machine, Model, SeriesRef, Stock
from orchestra.sd.store import ModelStore


def test_a_discovered_remote_series_with_a_machine_label_makes_no_machine(tmp_path, monkeypatch):
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer

    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    (tmp_path / "repo").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path / "repo", check=True)
    project = init_project(tmp_path / "repo")
    pods = SeriesRef("rig:app_latency_seconds_pods", {"service": "search", "machine": "rig.search"}, source="rig")
    started = SeriesRef("rig:app_latency_seconds_pods_started_total", {"service": "search", "machine": "rig.search"}, source="rig")
    model = Model("m", "m", stocks=[Stock("pods", "pods", series=pods)],
                  flows=[Flow("started", "started", None, "pods", counter=started)],
                  machines=[Machine("rig.search", "rig.search", "machine", attributed=["started"], observed_by=[pods, started])])
    ModelStore.for_state(project.state_dir).write_discovery(model)
    c = TestClient(create_app(project), headers=bearer(project))
    deadline = time.time() + 15
    while time.time() < deadline:
        got = c.get("/api/machines").json()
        if got.get("ok"):
            break
        time.sleep(0.2)
    assert got["ok"] and not any(m["id"] == "rig.search" for m in got["machines"])
