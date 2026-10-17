"""The server's discovery jobs (POST, wait, supersede, cancel) and the research view's read-only
endpoints (topics and the bench's saved runs)."""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sdlab.server import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    bench = tmp_path_factory.mktemp("bench")
    mp = pytest.MonkeyPatch()
    mp.setenv("SDLAB_HOME", str(home))
    mp.setenv("SDLAB_BENCH_CACHE", str(bench))
    with TestClient(create_app()) as c:
        c.bench = bench / "runs"
        yield c
    mp.undo()


def socks_request():
    run = json.loads((ROOT / "tests" / "fixtures" / "socks-eras-run.json").read_text())
    stocks = json.loads((ROOT / "sdlab" / "examples" / "socks.json").read_text())["stocks"]
    return {"stocks": stocks, "run": {"t": run["t"], "levels": run["levels"]}, "eras": run["eras"]}


def wait(client, model, job):
    for _ in range(10):
        st = client.get(f"/api/models/{model}/discovery", params={"job": job, "wait": 20}).json()
        if st["state"] != "running":
            return st
    raise AssertionError("discovery never finished")


def test_a_discovery_job_runs_in_the_background_and_returns_the_pages_shape(client):
    assert client.get("/api/models/socks/discovery").json() == {"job": None, "state": "idle"}
    began = time.time()
    j = client.post("/api/models/socks/discovery", json=socks_request()).json()
    assert time.time() - began < 2 and j["state"] == "running"     # the request does not wait for discovery
    st = wait(client, "socks", j["job"])
    assert st["state"] == "done", st
    r = st["result"]
    assert r["flows"] and r["strategy"] == "matrix" and set(r["unexplained"]) == {"basket", "loose", "pairs", "dress", "sport", "lost"}
    assert {"from", "to", "rate", "rates", "perStep", "nearly", "bothWays", "ratio"} <= r["flows"][0].keys()


def test_a_newer_request_supersedes_an_older_one_and_the_last_result_is_kept(client):
    first = client.post("/api/models/socks/discovery", json=socks_request()).json()["job"]
    second = client.post("/api/models/socks/discovery", json=socks_request()).json()["job"]
    assert client.get("/api/models/socks/discovery", params={"job": first}).json()["state"] == "superseded"
    now = client.get("/api/models/socks/discovery").json()
    assert now["job"] == second and now["state"] == "running"
    assert now["last"]["state"] == "done" and now["last"]["result"]["flows"]   # shown while the new one runs
    assert wait(client, "socks", second)["state"] == "done"


def test_a_job_can_be_cancelled(client):
    job = client.post("/api/models/socks/discovery", json=socks_request()).json()["job"]
    assert client.delete("/api/models/socks/discovery").json()["state"] == "cancelled"
    assert client.get("/api/models/socks/discovery", params={"job": job, "wait": 1}).json()["state"] == "cancelled"


def test_discovery_requests_are_checked(client):
    good = socks_request()
    assert client.post("/api/models/no-such-model/discovery", json=good).status_code == 404
    assert client.post("/api/models/socks/discovery", json={**good, "stocks": []}).status_code == 422
    assert client.post("/api/models/socks/discovery", json={**good, "strategy": "nope"}).status_code == 422
    short = {**good, "run": {"t": good["run"]["t"], "levels": {"basket": [1, 2, 3]}}}
    assert client.post("/api/models/socks/discovery", json=short).status_code == 422
    assert client.post("/api/models/socks/discovery", json={**good, "known": {"basket": [0]}}).status_code == 422
    assert client.get("/api/discovery/strategies").json()["default"] == "matrix"


def run_file(at, label, results, branch="sdlab"):
    return {"at": at, "label": label, "engine": "matrix", "branch": branch, "commit": "abc", "results": results}


def row(example, length, s20, s100, fresh=True):
    x = {"example": example, "length": length, "steps": 100, "parts": 1, "of": 2, "skill": {"5": s20, "20": s20, "100": s100},
         "moved": {"20": 1.0}, "ms": 5, "flows": 3, "chosen": "forward", "error": None}
    if fresh:
        x["fresh"] = {"20": s20, "100": s100}
    return x


def test_the_bench_runs_are_listed_summarised_and_fetched_by_name(client):
    d = client.bench
    d.mkdir(parents=True, exist_ok=True)
    (d / "2026-10-17T01-00-00-000Z-a.json").write_text(json.dumps(run_file("2026-10-17T01:00:00.000Z", "a", [row("sd-x", "default", 0.95, 0.9), row("sd-y", "default", -5, 0.1)])))
    (d / "baseline-good.json").write_text(json.dumps(run_file("2026-10-17T02:00:00.000Z", "b", [row("sd-x", "default", 0.5, 0.5, fresh=False)])))
    (d / "broken.json").write_text("{not json")
    (d / "notes.txt").write_text("not a run")
    r = client.get("/api/research/runs").json()
    by = {x["file"]: x for x in r["runs"]}
    assert set(by) == {"2026-10-17T01-00-00-000Z-a.json", "baseline-good.json", "broken.json"}
    a = by["2026-10-17T01-00-00-000Z-a.json"]
    assert a["skill20"] == pytest.approx((0.95 - 1) / 2) and a["meets"] == 1 and a["fresh20"] == pytest.approx((0.95 - 1) / 2) and a["freshMeets"] == 1
    assert by["baseline-good.json"]["baseline"] == "good" and by["baseline-good.json"]["fresh20"] is None
    assert by["broken.json"]["broken"]
    assert r["goal"] == {"skill20": 0.9, "skill100": 0.8}
    one = client.get("/api/research/runs/2026-10-17T01-00-00-000Z-a.json").json()
    assert one["results"][0]["example"] == "sd-x" and one["summary"]["n"] == 2
    for bad in ("..%2Fruns%2Fbaseline-good.json", "%2Fetc%2Fpasswd", "..%2F..%2Fsecret.json", "notes.txt", "missing.json", ".hidden.json"):
        assert client.get(f"/api/research/runs/{bad}").status_code == 404, bad


def test_a_runs_candidates_and_failure_classes_are_summarised_and_two_runs_are_tested_paired(client):
    d = client.bench
    d.mkdir(parents=True, exist_ok=True)
    before = [row(f"sd-{i}", "default", 0.5, 0.5) for i in range(10)]
    after = [row(f"sd-{i}", "default", 0.6, 0.5) for i in range(10)]
    after[0].update(best={"name": "f", "skill": {"20": 0.95, "100": 0.9}, "rank": 3, "of": 8, "meets": True}, failure="not chosen")
    after[1].update(best={"name": "f", "skill": {"20": 0.6, "100": 0.5}, "rank": 1, "of": 8, "meets": False}, failure="not representable")
    (d / "2026-10-17T03-00-00-000Z-before.json").write_text(json.dumps(run_file("2026-10-17T03:00:00.000Z", "before", before)))
    (d / "2026-10-17T04-00-00-000Z-after.json").write_text(json.dumps(run_file("2026-10-17T04:00:00.000Z", "after", after)))
    s = client.get("/api/research/runs/2026-10-17T04-00-00-000Z-after.json").json()["summary"]
    assert (s["graded"], s["picked"], s["bestMeets"]) == (2, 1, 1) and s["best20"] == pytest.approx(0.775)
    assert s["failures"] == {"not representable": 1, "not chosen": 1, "not supported": 0, "error": 0}
    assert client.get("/api/research/runs/2026-10-17T03-00-00-000Z-before.json").json()["summary"]["failures"] is None
    t = client.get("/api/research/compare/2026-10-17T03-00-00-000Z-before.json/2026-10-17T04-00-00-000Z-after.json").json()["tests"]
    s20 = next(x for x in t if x["key"] == "skill" and x["horizon"] == 20)
    assert (s20["n"], s20["better"], s20["worse"]) == (10, 10, 0) and s20["sign_p"] == pytest.approx(2 / 1024)
    assert next(x for x in t if x["key"] == "skill" and x["horizon"] == 100)["sign_p"] is None
    assert client.get("/api/research/compare/missing.json/2026-10-17T04-00-00-000Z-after.json").status_code == 404


def test_the_research_topics_come_from_the_index_and_render_from_their_documents(client):
    r = client.get("/api/research/topics").json()
    assert len(r["topics"]) >= 30
    kinds = {t["kind"] for t in r["topics"]}
    assert {"done", "running", "idea"} <= kinds
    frols = next(t for t in r["topics"] if t["file"] == "frols.md")
    assert frols["kind"] == "idea"
    assert client.get("/api/research/topics/frols.md").json()["markdown"].startswith("# FROLS")
    assert "literature/system-identification.md" in r["documents"]
    assert client.get("/api/research/topics/literature/system-identification.md").status_code == 200
    for bad in ("../SPEC.md", "..%2FSPEC.md", "nope.md", "README"):
        assert client.get(f"/api/research/topics/{bad}").status_code == 404, bad


def test_the_research_page_is_served(client):
    html = client.get("/research").text
    assert "/static/research.js?v=" in html
    assert 'href="/research"' in client.get("/").text
