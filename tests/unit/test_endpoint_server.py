"""The events endpoint over real HTTP, on a file bus: publishing, reading, the token, idempotency."""

import json
import os
import socket
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.request

import pytest

from orchestra import endpoint, runtime
from orchestra.config import init_project
from orchestra.endpoint.server import EventsEndpoint
from orchestra.events import Events


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ORCHESTRA_EVENTS_URL", raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    return init_project(r)


@pytest.fixture
def ep(project):
    e = EventsEndpoint(project, Events.for_project(project), ("127.0.0.1", 0), endpoint.token(project), log=lambda _: None)
    e.start()
    yield e
    e.stop()


def call(ep, method, path, body=None, token=True):
    data = json.dumps(body).encode() if body is not None and not isinstance(body, bytes) else body
    req = urllib.request.Request(ep.url + path, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {ep.token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_the_token_is_made_once_and_readable_by_its_owner_only(project):
    t = endpoint.token(project)
    assert len(t) >= 32 and endpoint.token(project) == t
    assert stat.S_IMODE(os.stat(endpoint.token_file(project)).st_mode) == 0o600


def test_without_the_token_nothing_is_published_or_read(ep, project):
    assert call(ep, "POST", "/events", {"type": "a", "source": "m"}, token=False)[0] == 401
    assert call(ep, "GET", "/events", token=False)[0] == 401
    req = urllib.request.Request(ep.url + "/events", method="GET", headers={"Authorization": "Bearer wrong"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 401
    assert call(ep, "GET", "/health", token=False) == (200, {"ok": True})
    assert Events.for_project(project).end() == 0


def test_a_published_event_lands_on_the_bus_with_the_envelope(ep, project):
    status, out = call(ep, "POST", "/events", {"type": "bread.baked", "source": "baker/2", "data": {"loaves": 3},
                                               "subject": "batch-9"})
    assert status == 201 and out["ok"] and not out["duplicate"]
    (ev,), _ = Events.for_project(project).read(0)
    assert ev["id"] == out["id"] and ev == out["event"]
    assert ev["specversion"] == "1.0" and ev["type"] == "bread.baked" and ev["source"] == "baker/2"
    assert ev["subject"] == "batch-9" and ev["data"] == {"loaves": 3} and ev["datacontenttype"] == "application/json"
    assert ev["time"].endswith("+00:00")


def test_a_repeated_id_is_written_once(ep, project):
    body = {"type": "a.b", "source": "m", "id": "only-once"}
    assert call(ep, "POST", "/events", body)[0] == 201
    assert call(ep, "POST", "/events", body) == (200, {"ok": True, "id": "only-once", "duplicate": True})
    assert Events.for_project(project).end() == 1


def test_an_id_already_on_the_bus_when_it_starts_is_a_duplicate(project):
    Events.for_project(project).publish("a.b", source="m", id="from-before")
    e = EventsEndpoint(project, Events.for_project(project), ("127.0.0.1", 0), endpoint.token(project), log=lambda _: None)
    e.start()
    try:
        assert call(e, "POST", "/events", {"type": "a.b", "source": "m", "id": "from-before"})[1]["duplicate"]
    finally:
        e.stop()


def test_refusals_say_why_and_write_nothing(ep, project):
    assert call(ep, "POST", "/events", {"type": "orchestra.host.started", "source": "m"})[0] == 403
    status, out = call(ep, "POST", "/events", {"type": "a", "source": "m", "colour": "red"})
    assert status == 400 and "colour" in out["error"]
    assert call(ep, "POST", "/events", b"nope")[0] == 400
    assert call(ep, "POST", "/events", b"x" * 1_000_001)[0] == 413
    assert call(ep, "POST", "/elsewhere", {"type": "a", "source": "m"})[0] == 404
    assert call(ep, "GET", "/events?after=-1")[0] == 400
    assert call(ep, "GET", "/events?since=0")[0] == 400
    assert Events.for_project(project).end() == 0


def test_reading_from_an_offset_by_type_and_in_pages(ep):
    for i in range(5):
        call(ep, "POST", "/events", {"type": "even" if i % 2 == 0 else "odd", "source": "m", "data": i})
    status, out = call(ep, "GET", "/events?after=0")
    assert status == 200 and [e["data"] for e in out["events"]] == [0, 1, 2, 3, 4] and out["next"] == 5
    assert [e["data"] for e in call(ep, "GET", "/events?after=2")[1]["events"]] == [2, 3, 4]
    out = call(ep, "GET", "/events?after=0&types=odd")[1]
    assert [e["data"] for e in out["events"]] == [1, 3] and out["next"] == 5
    page = call(ep, "GET", "/events?after=0&limit=2")[1]
    assert [e["data"] for e in page["events"]] == [0, 1] and page["next"] == 2
    assert [e["data"] for e in call(ep, "GET", f"/events?after={page['next']}&limit=2")[1]["events"]] == [2, 3]
    assert call(ep, "GET", "/events?after=end")[1] == {"ok": True, "events": [], "next": 5}


def test_a_long_poll_returns_when_a_matching_event_arrives(ep):
    later = threading.Timer(0.6, lambda: [call(ep, "POST", "/events", {"type": "noise", "source": "m"}),
                                          call(ep, "POST", "/events", {"type": "wanted", "source": "m"})])
    later.start()
    t0 = time.monotonic()
    out = call(ep, "GET", "/events?after=0&types=wanted&wait=20")[1]
    assert 0.5 < time.monotonic() - t0 < 10
    assert [e["type"] for e in out["events"]] == ["wanted"] and out["next"] == 2
    t0 = time.monotonic()
    assert call(ep, "GET", "/events?after=end&wait=0.5")[1]["events"] == []
    assert time.monotonic() - t0 >= 0.45


def test_the_address_is_recorded_while_it_serves(project):
    e = EventsEndpoint(project, Events.for_project(project), ("127.0.0.1", 0), endpoint.token(project), log=lambda _: None)
    e.start()
    assert endpoint.recorded(project)["url"] == e.url and e.url.startswith("http://127.0.0.1:")
    e.stop()
    assert endpoint.recorded(project) is None and endpoint.RECORD_KEY not in runtime.read(project)


def test_the_host_runs_on_without_an_endpoint_it_cannot_serve(project):
    from orchestra.host import Host
    said = []
    host = Host(project)
    host.log = said.append
    project.config.events_listen = "off"
    assert host._serve_events() is None and said[-1] == "events endpoint: off ([events] listen)"
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        project.config.events_listen = f"127.0.0.1:{taken.getsockname()[1]}"
        assert host._serve_events() is None and said[-1].startswith("events endpoint: not started: OSError")
    project.config.events_listen = "nonsense"
    assert host._serve_events() is None and "ConfigError" in said[-1]
    assert endpoint.recorded(project) is None
