"""A machine the model knows from another store's series (``[[sources]]``) is on the Machines page,
marked with its source, read from the latest discovery and never by querying the source."""

import subprocess
import time

from fastapi.testclient import TestClient

from orchestra.config import init_project
from orchestra.sd.model import Flow, Machine, Model, SeriesRef, Stock
from orchestra.sd.store import ModelStore


def test_a_discovered_remote_series_with_a_machine_label_lists_that_machine(tmp_path, monkeypatch):
    from orchestra.web.app import create_app

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
    c = TestClient(create_app(project))
    deadline = time.time() + 15
    while time.time() < deadline:
        got = c.get("/api/machines").json()
        if got.get("ok") and any(m["id"] == "rig.search" for m in got["machines"]):
            break
        time.sleep(0.2)
    m = next(m for m in got["machines"] if m["id"] == "rig.search")
    assert m["from_source"] == "rig"
    assert 'rig:app_latency_seconds_pods{service="search"}' in m["metrics"]
