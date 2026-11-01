"""GET /api/events pages the bus in order: following ``next`` from 0 collects every event once,
none skipped, whatever the backlog."""

import subprocess

import pytest
from fastapi.testclient import TestClient

from orchestra import plugins
from orchestra.config import init_project
from orchestra.events import Events
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


def test_paging_by_next_collects_every_event_in_order(project):
    pub = Events.for_project(project, source="m")
    for i in range(1200):
        pub.publish("x.counted", {"i": i})
    web = TestClient(create_app(project), headers=bearer(project))
    got, since = [], 0
    for _ in range(20):
        page = web.get("/api/events", params={"since": since}).json()
        if not page["events"]:
            break
        got += [e["data"]["i"] for e in page["events"] if e.get("type") == "x.counted"]
        since = page["next"]
    assert got == list(range(1200))
    pub.publish("x.counted", {"i": 1200})
    assert [e["data"]["i"] for e in web.get("/api/events", params={"since": since}).json()["events"]] == [1200]
