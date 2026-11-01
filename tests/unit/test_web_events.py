"""GET /api/events pages the bus in order: following ``next`` from 0 collects every event once,
none skipped and none repeated, a bounded page at a time, whatever the backlog, across a
malformed line."""

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


def test_paging_by_next_collects_every_event_once_in_bounded_pages(project):
    pub = Events.for_project(project, source="m")
    for i in range(30):
        pub.publish("x.counted", {"i": i})
    with project.events_file.open("a") as f:
        f.write("{torn\n")
    for i in range(30, 47):
        pub.publish("x.counted", {"i": i})
    web = TestClient(create_app(project), headers=bearer(project))
    got, since, pages = [], 0, 0
    for _ in range(50):
        page = web.get("/api/events", params={"since": since, "limit": 7}).json()
        if not page["events"]:
            break
        assert len(page["events"]) <= 7
        pages += 1
        got += [e["data"]["i"] for e in page["events"] if e.get("type") == "x.counted"]
        since = page["next"]
    assert got == list(range(47)) and pages >= 7
    pub.publish("x.counted", {"i": 47})
    assert [e["data"]["i"] for e in web.get("/api/events", params={"since": since, "limit": 7}).json()["events"]] == [47]


def test_the_page_size_is_capped_and_defaults_to_a_thousand(project):
    pub = Events.for_project(project, source="m")
    for i in range(1200):
        pub.publish("x.counted", {"i": i})
    web = TestClient(create_app(project), headers=bearer(project))
    page = web.get("/api/events").json()
    assert len(page["events"]) == 1000 and page["next"] == 1000
    assert len(web.get("/api/events", params={"limit": 10**9}).json()["events"]) == 1200
