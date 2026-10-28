"""Experiments for any machine: the Python API (sd/experiments/api.py), the HTTP API beside the
events endpoint (endpoint/api.py, behind its token, answering what the Python API answers), the web
UI's read-only routes, and a committed experiment judged as a prediction (goal G13) on the
predictions test system (``test_predictions.pipeline``: a known change to a pipeline's rates)."""

import json
import subprocess
import urllib.error
import urllib.request

import pytest
from experiment_systems import chain, history_of
from test_eras import CHANGE, at  # pytest puts this folder on the path
from test_predictions import HORIZON, pipeline, step

from orchestra import endpoint
from orchestra.events import Events, envelope
from orchestra.metrics.file import FileMetrics
from orchestra.sd.experiments.api import ExperimentError, Experiments
from orchestra.sd.judge import judge_due
from orchestra.sd.rediscover import rediscover
from orchestra.sd.store import ModelStore
from orchestra.sd.strategies import sd_installed

pytestmark = pytest.mark.skipif(not sd_installed(), reason="simulating needs orchestra[sd]")


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


def api(project, h, source="curator"):
    return Experiments(project, source, history=lambda model, start, end: h)


def test_a_machine_makes_edits_runs_and_discards_an_experiment(project, h):
    x = api(project, h)
    e = x.create("slower drain", purpose="does a capped drain explain the hour?")["experiment"]
    assert e["owner"] == "curator" and e["status"] == "draft" and e["base"]["label"]["version"] == 1 and e["changes"] == 0
    drain = next(f for f in e["draft"]["flows"] if f["id"] == "drain")
    assert drain["equation"] == "k * ready" and drain["params"] == {"k": 0.3} and drain["origin"] == "fitted"
    got = x.edit(e["id"], [{"op": "replace_flow", "id": "drain", "equation": "min(k * ready, cap)", "params": {"k": 0.3, "cap": 9.0}}])
    assert got["diff"]["flows"]["changed"][0]["after"]["equation"] == "min(k * ready, cap)"
    with pytest.raises(ExperimentError, match="unknown name nope") as err:
        x.edit(e["id"], [{"op": "set_params", "flow": "arrive", "params": {"c": 4.0}},
                         {"op": "replace_flow", "id": "move", "equation": "k * nope", "params": {"k": 1}}])
    assert err.value.status == 422 and err.value.extra == {"index": 1}
    rec = x.get(e["id"])["experiment"]
    assert [entry["ok"] for entry in rec["log"]] == [True, False] and rec["changes"] == 1, "the refused batch changed nothing"
    with pytest.raises(ExperimentError, match="only its owner changes it") as err:
        api(project, h, "intruder").edit(e["id"], [{"op": "remove_flow", "id": "side"}])
    assert err.value.status == 403
    fwd = x.run(e["id"], "forward", horizon_s=1800, members=8)["run"]
    assert fwd["mode"] == "forward" and fwd["by"] == "curator" and fwd["result"]["changed"] == ["drain"]
    rep = x.run(e["id"], "replay", start=h["start"], end=h["at"])["run"]
    assert rep["result"]["flows"]["drain"]["versus_base"] == "worse", "capped at 9 a minute, it cannot drain the 60 it started with"
    assert [r["mode"] for r in x.runs(e["id"])["runs"]] == ["forward", "replay"]
    assert x.run_result(e["id"], rep["id"])["run"]["result"] == rep["result"]
    with pytest.raises(ExperimentError, match="forward takes"):
        x.run(e["id"], "forward", colour="red")
    assert x.discard(e["id"])["experiment"]["status"] == "discarded"
    with pytest.raises(ExperimentError, match="is discarded: only a draft changes") as err:
        x.edit(e["id"], [{"op": "remove_flow", "id": "side"}])
    assert err.value.status == 409
    assert [r["id"] for r in x.list(owner="curator")["experiments"]] == [e["id"]] and x.list(status="draft")["experiments"] == []


def test_an_inverse_run_answers_with_a_new_draft_of_the_callers(project):
    h = history_of(chain())
    x = api(project, h, "planner")
    e = x.create("what makes ready half as large again?")["experiment"]
    run = x.run(e["id"], "inverse", start=h["start"], end=h["at"], targets=[{"stock": "ready", "scale": 1.5}],
                hold=[{"flow": "side"}, {"flow": "drain"}])["run"]["result"]
    assert run["reached"] and run["changes"][0]["flow"] == "arrive" and not run["ambiguous"] and run["uniqueness"]["consistent"]
    made = x.get(run["experiment"])["experiment"]
    assert made["owner"] == "planner" and made["origin"] == {"experiment": e["id"], "mode": "inverse"} and made["changes"] == 1
    arrive = next(f for f in made["draft"]["flows"] if f["id"] == "arrive")
    assert arrive["origin"] == "declared" and arrive["method"] == f"experiment {made['id']} by the inverse solver for planner"
    assert 5.4 < arrive["params"]["c"] < 6.9
    loose = x.run(e["id"], "inverse", start=h["start"], end=h["at"], targets=[{"stock": "ready", "scale": 1.5}])["run"]["result"]
    assert loose["ambiguous"], "doubling the side supply, or draining slower, would do as well"


def test_the_reads_a_machine_needs_in_shapes_an_llm_can_use(project, h):
    x = api(project, h)
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


def test_the_http_api_needs_the_token_and_answers_what_the_python_api_answers(project, h, monkeypatch):
    from orchestra.endpoint.server import EventsEndpoint

    metrics = FileMetrics(project.state_dir / "m.jsonl")
    monkeypatch.setattr("orchestra.metrics.for_project", lambda p: metrics)
    token = endpoint.token(project)
    ep = EventsEndpoint(project, Events.for_project(project), ("127.0.0.1", 0), token, log=lambda s: None)
    url = ep.start()
    try:
        for path in ("/model", "/experiments", "/language"):
            status, body = call(url, None, "GET", path)
            assert status == 401 and "Bearer" in body["error"]
        assert call(url, "wrong", "GET", "/model")[0] == 401
        status, made = call(url, token, "POST", "/experiments", {"source": "curator", "title": "over http"})
        assert status == 201
        eid = made["experiment"]["id"]
        py = Experiments(project)
        assert made["experiment"] == py.get(eid)["experiment"]
        status, out = call(url, token, "POST", f"/experiments/{eid}/edits",
                           {"source": "curator", "edits": [{"op": "set_params", "flow": "arrive", "params": {"c": 6.0}}]})
        assert status == 200 and out["diff"] == py.diff(eid)["diff"]
        status, bad = call(url, token, "POST", f"/experiments/{eid}/edits", {"source": "curator", "edits": [{"op": "remove_stock", "id": "x"}]})
        assert status == 422 and bad["index"] == 0 and "no stock x" in bad["error"]
        assert call(url, token, "POST", f"/experiments/{eid}/edits", {"source": "other", "edits": [{"op": "remove_flow", "id": "side"}]})[0] == 403
        assert call(url, token, "POST", f"/experiments/{eid}/edits", {"edits": []})[0] == 400, "a write names its machine"
        status, ran = call(url, token, "POST", f"/experiments/{eid}/runs", {"source": "curator", "mode": "forward", "horizon_s": 600, "members": 4})
        assert status == 200
        again = api(project, h).run(eid, "forward", horizon_s=600, members=4)["run"]["result"]
        assert ran["run"]["result"].keys() == again.keys() and ran["run"]["result"]["changed"] == again["changed"] == ["arrive"]
        assert call(url, token, "GET", f"/experiments/{eid}/runs/{ran['run']['id']}")[1]["run"] == py.run_result(eid, ran["run"]["id"])["run"]
        for path, want in ((f"/experiments/{eid}", py.get(eid)), (f"/experiments/{eid}/diff", py.diff(eid)), ("/model", py.model()),
                           ("/eras", py.eras()), ("/model/versions", py.versions()), ("/language", py.language()),
                           ("/experiments?owner=curator", py.list(owner="curator"))):
            status, got = call(url, token, "GET", path)
            assert status == 200 and got == json.loads(json.dumps(want)), path
        assert call(url, token, "POST", "/equations/check", {"equation": "k * queue", "params": {"k": 1}})[1]["ok"]
        assert call(url, token, "GET", "/experiments/x-000000000000")[0] == 404
        assert call(url, token, "DELETE", f"/experiments/{eid}")[0] == 405
        status, done = call(url, token, "POST", f"/experiments/{eid}/discard", {"source": "curator"})
        assert status == 200 and done["experiment"]["status"] == "discarded"
        assert call(url, token, "GET", "/events?after=0")[0] == 200, "the events endpoint itself is as it was"
    finally:
        ep.stop()


def test_the_web_ui_reads_experiments_and_cannot_change_them(project, h):
    from fastapi.testclient import TestClient

    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer

    x = api(project, h)
    eid = x.create("seen on the web")["experiment"]["id"]
    x.edit(eid, [{"op": "remove_flow", "id": "side"}])
    rid = x.run(eid, "replay", start=h["start"], end=h["at"])["run"]["id"]
    web = TestClient(create_app(project), headers=bearer(project))
    assert [e["id"] for e in web.get("/api/experiments").json()["experiments"]] == [eid]
    assert web.get(f"/api/experiments/{eid}").json()["experiment"]["changes"] == 1
    assert web.get(f"/api/experiments/{eid}/diff").json()["diff"]["flows"]["removed"][0]["id"] == "side"
    assert web.get(f"/api/experiments/{eid}/runs").json()["runs"][0]["id"] == rid
    assert web.get(f"/api/experiments/{eid}/runs/{rid}").json()["run"]["mode"] == "replay"
    assert web.get(f"/api/experiments/{eid}/prediction").status_code == 404
    assert web.get("/api/experiments/x-000000000000").status_code == 404
    for method, path in (("post", "/api/experiments"), ("post", f"/api/experiments/{eid}/edits"), ("post", f"/api/experiments/{eid}/runs"),
                         ("post", f"/api/experiments/{eid}/commit"), ("post", "/api/dynamics/whatif")):
        assert getattr(web, method)(path, json={}).status_code in (404, 405), f"{path}: humans only read (AGENTS.md rule 9)"
    assert web.get("/api/dynamics/eras").json()["ok"]
    assert TestClient(create_app(project)).get("/api/experiments").status_code == 401


# --- committed, and judged (G13)

def judged_experiment(tmp_path, monkeypatch, edits):
    """The predictions test system: a pipeline whose arrivals double at CHANGE. An experiment of
    the model before the change, committed before it; the change; the era discovered after the
    horizon; the verdict."""
    from orchestra.config import init_project

    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    p = init_project(repo)
    (repo / "orchestra.toml").write_text('[discovery]\nstrategy = "conservation"\n', encoding="utf-8")
    from orchestra.config import load_project
    p = load_project(repo)
    store = FileMetrics(tmp_path / "m.jsonl")
    pipeline(store, 120, step(2.0, 4.0), step(0.5, 0.5), step(0.4, 0.4), key=p.key)
    events = Events(tmp_path / "events.jsonl")
    rediscover(p, store, now=CHANGE - 1)
    from orchestra.sd.judge import reader
    from orchestra.web.background import history
    x = Experiments(p, "ops", metrics=store, events=events,
                    history=lambda model, start, end: history(model, reader(p, store), CHANGE - 30, 15.0))
    e = x.create("double the arrivals")["experiment"]
    eid = e["id"]
    x.edit(eid, edits(e) if callable(edits) else edits)
    made = x.commit(eid, horizon=HORIZON, change="cause")
    assert made["experiment"]["status"] == "committed" and made["change"] == "cause"
    events.bus.append(envelope("config.changed", "supervisor", time=at(CHANGE), id="cause"))
    rediscover(p, store, now=CHANGE + HORIZON, events=events)
    [v] = judge_due(p, store, CHANGE + HORIZON, events=events, measure_false=False)
    return x, eid, made, v


def test_a_committed_experiment_is_a_prediction_and_the_verdict_judges_it(tmp_path, monkeypatch):
    def double(e):
        c = next(f for f in e["draft"]["flows"] if f["id"] == "jobs_arrived_total")["params"]["c"]
        return [{"op": "set_params", "flow": "jobs_arrived_total", "params": {"c": 2 * c}}]
    x, eid, made, v = judged_experiment(tmp_path, monkeypatch, double)
    pred = made["prediction"]
    assert pred["source"] == "ops" and pred["subject"] == eid and pred["horizon_s"] == HORIZON
    assert pred["expect"] == [{"kind": "factor", "flow": "jobs_arrived_total", "factor": 2.0, "param": "c"}]
    assert set(pred["trajectories"]["stocks"]) == {"jobs_waiting", "jobs_reviewing"}, "the forward run's band is the prediction's"
    assert v["verdict"] == "passed", json.dumps(v, indent=1)
    got = x.prediction(eid)["prediction"]
    assert got["status"] == "judged" and got["verdict"]["verdict"] == "passed" and got["era"] == "e1"


def test_an_equation_replaced_is_judged_by_its_law(tmp_path, monkeypatch):
    right = [{"op": "replace_flow", "id": "jobs_arrived_total", "equation": "2 * c", "params": {"c": 1.85}}]
    _, _, made, v = judged_experiment(tmp_path, monkeypatch, right)
    [e] = made["prediction"]["expect"]
    assert e["kind"] == "equation" and e["equation"] == "2 * c"
    assert v["verdict"] == "passed", json.dumps(v, indent=1)
    [s] = v["expectations"]
    assert s["status"] == "met" and abs(s["law"]["z"]) < 2 and abs(s["old_law"]["z"]) >= 2


def test_an_equation_that_misses_the_change_is_a_side_effect(tmp_path, monkeypatch):
    # predicted: the arrivals follow the waiting queue; they doubled instead
    wrong = [{"op": "replace_flow", "id": "jobs_arrived_total", "equation": "k * jobs_waiting", "params": {"k": 0.05}}]
    *_, v = judged_experiment(tmp_path, monkeypatch, wrong)
    [s] = v["expectations"]
    assert s["status"] == "different" and abs(s["law"]["z"]) >= 2 and v["verdict"] == "side effect", json.dumps(v, indent=1)
