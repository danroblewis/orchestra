"""The model as a machine reads it (sd/reads.py), from Python and over the events endpoint's HTTP
API (endpoint/api.py), alike; and the experiments' routes, removed on 2026-11-01, are gone."""

import json
import subprocess
import urllib.error
import urllib.request

import pytest
from equation_systems import chain, history_of

from orchestra import endpoint
from orchestra.events import Events
from orchestra.metrics.file import FileMetrics
from orchestra.sd.reads import ModelReads
from orchestra.sd.store import ModelStore
from orchestra.sd.strategies import sd_installed

pytestmark = pytest.mark.skipif(not sd_installed(), reason="the test system is made by simulating, orchestra[sd]")


@pytest.fixture
def project(tmp_path, monkeypatch):
    from orchestra.config import init_project

    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    for k in ("ORCHESTRA_METRICS_URL", "ORCHESTRA_EVENTS_URL"):
        monkeypatch.delenv(k, raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    p = init_project(repo)
    ModelStore.for_state(p.state_dir).save(chain(), note="the chain")
    return p


@pytest.fixture
def h():
    return history_of(chain(), minutes=60, start_levels={"queue": 0.0, "ready": 60.0}, seed=3)


def test_the_reads_a_machine_needs_in_shapes_an_llm_can_use(project, h):
    x = ModelReads(project, history=lambda model, start, end: h)
    m = x.model()["model"]
    assert [f["equation"] for f in m["flows"]] == ["c", "k * queue", "c", "k * ready"] and m["time_unit"] == "minute"
    assert x.check_equation("k * min(queue, ready)", {"k": 1}) == {
        "ok": True, "equation": "k * min(queue, ready)", "params": {"k": 1.0},
        "reads": {"stocks": ["queue", "ready"], "inputs": [], "params": ["k"], "functions": ["min"]}}
    assert not x.check_equation("k * nope", {"k": 1})["ok"]
    s = x.series(["ready", "drain"], start=h["start"], end=h["at"], points=True, limit=100)
    ready = s["series"]["ready"]
    assert ready["kind"] == "stock" and ready["summary"]["first"] == 60.0 and len(ready["points"]) == 100 and "next" in ready
    page2 = x.series(["ready"], start=h["start"], end=h["at"], points=True, limit=100, after=ready["next"])["series"]["ready"]
    assert page2["points"][0][0] > ready["points"][-1][0]
    assert s["series"]["drain"]["unit"] == "per minute" and s["series"]["drain"]["summary"]["mean"] > 0
    assert x.versions()["current"] == 1 and x.language()["language"]["units"] == "not checked"


def call(url, token, method, path, body=None):
    req = urllib.request.Request(url + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_the_http_api_needs_the_token_answers_what_the_python_api_answers_and_has_no_experiments(project, monkeypatch):
    from orchestra.endpoint.server import EventsEndpoint

    metrics = FileMetrics(project.state_dir / "m.jsonl")
    monkeypatch.setattr("orchestra.metrics.for_project", lambda p: metrics)
    token = endpoint.token(project)
    ep = EventsEndpoint(project, Events.for_project(project), ("127.0.0.1", 0), token, log=lambda s: None)
    url = ep.start()
    try:
        for path in ("/model", "/language"):
            status, body = call(url, None, "GET", path)
            assert status == 401 and "Bearer" in body["error"]
        assert call(url, "wrong", "GET", "/model")[0] == 401
        py = ModelReads(project)
        for path, want in (("/model", py.model()), ("/eras", py.eras()), ("/model/versions", py.versions()),
                           ("/language", py.language()), ("/predictions", py.predictions())):
            status, got = call(url, token, "GET", path)
            assert status == 200 and got == json.loads(json.dumps(want)), path
        assert call(url, token, "POST", "/equations/check", {"equation": "k * queue", "params": {"k": 1}})[1]["ok"]
        assert call(url, token, "GET", "/predictions/nope")[0] == 404
        for method, path in (("GET", "/experiments"), ("POST", "/experiments"), ("GET", "/experiments/x-000000000000")):
            assert call(url, token, method, path, {} if method == "POST" else None)[0] == 404, path
        assert call(url, token, "GET", "/events?after=0")[0] == 200, "the events endpoint itself is as it was"
    finally:
        ep.stop()


def test_the_web_ui_has_no_experiments_and_still_shows_the_eras(project):
    from fastapi.testclient import TestClient

    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer

    web = TestClient(create_app(project), headers=bearer(project))
    for path in ("/experiments", "/api/experiments"):
        assert web.get(path).status_code == 404, path
    for path in ("/api/experiments", "/api/dynamics/whatif"):
        assert web.post(path, json={}).status_code in (404, 405), f"{path}: humans only read (AGENTS.md rule 9)"
    assert web.get("/api/dynamics/eras").json()["ok"]
    assert "/experiments" not in web.get("/static/app.js").text
