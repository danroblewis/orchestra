"""A program in a project writes its own series (docs/machines.md), and the web app shows them.

``orchestra.metrics.for_repo`` opens the store the project's orchestra.toml configures and labels
what is written with the project, which is what the catalogue and discovery select by."""

import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from orchestra.config import init_project
from orchestra.metrics import Point, for_project, for_repo


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ORCHESTRA_METRICS_URL", raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    return init_project(r)


def test_for_repo_writes_to_the_projects_store_with_its_label(project, monkeypatch):
    now = time.time()
    (project.repo_root / "machines").mkdir()
    monkeypatch.setenv("ORCHESTRA_REPO", str(project.repo_root / "machines"))      # as the launcher sets it; any subdirectory resolves
    store = for_repo()
    store.write([Point("disk_free_bytes", 5e9, now, {"machine": "telemetry"}),
                 Point("weather_temperature_celsius", 12.5, now, {"machine": "telemetry", "project": "elsewhere"})])
    assert store.project == project.key and store.name == "file"
    plain = for_project(project)                                    # the store the host and the web app open
    assert plain.latest("disk_free_bytes", {"project": project.key, "machine": "telemetry"}) == (now, 5e9)
    assert plain.latest("weather_temperature_celsius", {"project": "elsewhere"}) == (now, 12.5), "a label it names is kept"


def test_the_catalogue_and_core_page_show_a_programs_series(project):
    from orchestra.web.app import create_app

    for_repo(project.repo_root).write([Point("disk_free_bytes", 5e9 - i, time.time() - 60 * i, {"machine": "telemetry"}) for i in range(5)])
    for_project(project).write([Point("bitcoin_price_usd", 1.0, time.time(), {"machine": "telemetry"})])    # no project label
    c = TestClient(create_app(project))
    cat = c.get("/api/core/metrics/catalog").json()
    assert cat["ok"] and [m["name"] for m in cat["metrics"]] == ["disk_free_bytes"]
    assert cat["metrics"][0]["points"] == 5 and cat["metrics"][0]["labels"]["machine"]["values"] == ["telemetry"]
    assert cat["unlabelled"] == ["bitcoin_price_usd"], "written without the project's label: said, not hidden silently"
    q = c.get("/api/core/metrics/query", params={"q": "disk_free_bytes", "hours": 1}).json()
    assert q["ok"] and q["lines"]
    assert c.get("/api/core").json()["metrics"]["series"] >= 1 + 3      # the program's, and the probe's own three
