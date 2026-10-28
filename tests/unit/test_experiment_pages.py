"""The Experiments pages (web/static/experiments.html, experiment.html): what the owner sees of what
machines did with the model. Real experiments on the predictions test system (a committed one,
judged; a forward and a replay run of an edited one, a refused batch among its edits; an inverse
run), read through the web app with the login, as the pages read them; the pages' renderers
(static/experiment-view.js) then draw them in Node, and the drawing is checked for what the owner
must see."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_experiments_api import judged_experiment  # pytest puts this folder on the path

from orchestra.sd.experiments.api import ExperimentError
from orchestra.sd.strategies import sd_installed

pytestmark = pytest.mark.skipif(not sd_installed(), reason="simulating needs orchestra[sd]")
RENDER = Path(__file__).parents[1] / "pages" / "experiments_render.mjs"


def double(e):
    c = next(f for f in e["draft"]["flows"] if f["id"] == "jobs_arrived_total")["params"]["c"]
    return [{"op": "set_params", "flow": "jobs_arrived_total", "params": {"c": 2 * c}}]


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """The committed experiment (judged ``passed``), and on the era after it: an edited one run
    forward and replayed, and an inverse run."""
    x, committed, _, verdict = judged_experiment(tmp_path, monkeypatch, double)
    assert verdict["verdict"] == "passed"
    monkeypatch.setattr("orchestra.web.core.metrics_for", lambda p: x.metrics)
    fwd = x.create("faster review", purpose="does reviewing faster drain the pile?")["experiment"]
    k = next(f for f in fwd["draft"]["flows"] if f["id"] == "jobs_reviewed_total")["params"]
    with pytest.raises(ExperimentError):
        x.edit(fwd["id"], [{"op": "set_params", "flow": "jobs_reviewed_total", "params": {p: v * 1.6 for p, v in k.items()}},
                           {"op": "replace_flow", "id": "jobs_done_total", "equation": "k * nope", "params": {"k": 1}}])
    x.edit(fwd["id"], [{"op": "replace_flow", "id": "jobs_done_total", "equation": "min(k * jobs_waiting, cap)", "params": {"k": 0.5, "cap": 3.0}}])
    h = x.history(x._draft(x.store.get(fwd["id"])), 0, 0)
    x.run(fwd["id"], "forward", horizon_s=1800, members=8, bounds={"jobs_reviewing": [2, 30]})
    x.run(fwd["id"], "replay", start=h["start"], end=h["at"])
    inv = x.create("halve the queue")["experiment"]
    x.run(inv["id"], "inverse", start=h["start"], end=h["at"], targets=[{"stock": "jobs_waiting", "scale": 0.5}], deadline_s=60)
    return x.project, {"committed": committed, "forward": fwd["id"], "inverse": inv["id"]}


def read_as_the_pages_do(web, ids) -> dict:
    out = {"experiments": {}, "predictions": web.get("/api/dynamics/predictions").json()["predictions"]}
    for name, eid in ids.items():
        x = web.get(f"/api/experiments/{eid}?base=true").json()["experiment"]
        row = {"experiment": x, "diff": web.get(f"/api/experiments/{eid}/diff").json()["diff"], "runs": []}
        if x["prediction"]:
            row["prediction"] = web.get(f"/api/experiments/{eid}/prediction").json()["prediction"]
        for r in x["runs"]:
            run = web.get(f"/api/experiments/{eid}/runs/{r['id']}").json()["run"]
            got = {"run": run}
            if run["mode"] == "forward":
                m = web.get(f"/api/experiments/{eid}/runs/{r['id']}/measured").json()
                assert m["ok"], m
                got["measured"] = m["stocks"]
            if run["mode"] == "inverse":
                got["solved"] = web.get(f"/api/experiments/{run['result']['experiment']}/diff").json()["diff"]
            row["runs"].append(got)
        out["experiments"][name] = row
    return out


def test_the_list_says_who_what_where_and_how_it_went(seeded):
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer

    project, ids = seeded
    web = TestClient(create_app(project), headers=bearer(project))
    rows = {r["id"]: r for r in web.get("/api/experiments").json()["experiments"]}
    c, f, i = rows[ids["committed"]], rows[ids["forward"]], rows[ids["inverse"]]
    assert c["verdict"] == {"status": "judged", "era": "e1", "verdict": "passed", "partial": None} and c["base"]["era"] is None
    assert f["purpose"] == "does reviewing faster drain the pile?" and f["last_run"]["mode"] == "replay" and f["runs"] == 2
    assert f["verdict"] is None and f["base"]["era"] == "e1"
    assert i["last_run"]["mode"] == "inverse"
    made = next(r for r in rows.values() if (r["origin"] or {}).get("experiment") == ids["inverse"])
    assert made["last_run"] is None and "UTC meets: jobs_waiting scale 0.5" in made["purpose"]
    # an era's: made on its model, or predicting the change that began it
    assert {r["id"] for r in web.get("/api/experiments?era=none").json()["experiments"]} == {ids["committed"]}
    assert ids["committed"] in {r["id"] for r in web.get("/api/experiments?era=e1").json()["experiments"]}
    assert ids["forward"] in {r["id"] for r in web.get("/api/experiments?era=e1&status=draft").json()["experiments"]}
    assert web.get("/api/experiments?era=e9").json()["experiments"] == []


def test_a_forward_runs_measured_levels_are_read_for_its_chart(seeded):
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer

    project, ids = seeded
    web = TestClient(create_app(project), headers=bearer(project))
    runs = web.get(f"/api/experiments/{ids['forward']}/runs").json()["runs"]
    fwd, rep = (next(r for r in runs if r["mode"] == m) for m in ("forward", "replay"))
    m = web.get(f"/api/experiments/{ids['forward']}/runs/{fwd['id']}/measured").json()
    assert m["ok"] and set(m["stocks"]) == {"jobs_waiting", "jobs_reviewing"} and m["start"] < m["now"] <= m["end"]
    assert all(m["start"] <= t <= m["end"] for pts in m["stocks"].values() for t, _ in pts) and len(m["stocks"]["jobs_waiting"]) > 10
    assert web.get(f"/api/experiments/{ids['forward']}/runs/{rep['id']}/measured").json() == {"ok": True, "mode": "replay", "stocks": {}}
    assert web.get(f"/api/experiments/{ids['forward']}/runs/r-000000000000/measured").status_code == 404
    assert web.post(f"/api/experiments/{ids['forward']}/runs/{fwd['id']}/measured").status_code == 405


def test_the_pages_are_served_behind_the_login_and_in_the_nav(seeded):
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer

    project, ids = seeded
    web = TestClient(create_app(project), headers=bearer(project))
    listing, one = web.get("/experiments"), web.get(f"/experiments/{ids['forward']}")
    assert listing.status_code == one.status_code == 200
    assert "/static/experiment-view.js" in listing.text and 'id="f-era"' in listing.text and 'class="themed"' in listing.text
    assert "/static/experiment-view.js" in one.text and 'id="runs"' in one.text and "/api/experiments/" in one.text
    assert '["/experiments", "Experiments"]' in web.get("/static/app.js").text, "in every page's nav"
    assert "/static/predictions.js" in web.get("/dynamics").text
    plain = TestClient(create_app(project), follow_redirects=False)
    assert plain.get("/experiments").status_code in (302, 303, 307, 401) and plain.get("/api/experiments").status_code == 401


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_the_pages_draw_what_the_owner_must_see(seeded, tmp_path):
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer

    project, ids = seeded
    web = TestClient(create_app(project), headers=bearer(project))
    (tmp_path / "answers.json").write_text(json.dumps(read_as_the_pages_do(web, ids)), encoding="utf-8")
    r = subprocess.run(["node", str(RENDER), str(tmp_path)], capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stderr
    page = json.loads(r.stdout)

    c = page["committed"]
    assert "✓ passed" in c["prediction"] and "jobs arrived.c ×2" in c["prediction"] and 'href="/dynamics?era=e1"' in c["prediction"]
    assert "cause" in c["prediction"] and "Evidence" in c["prediction"] and "<b>met</b>" in c["prediction"]
    assert "replaced: its numbers" in c["diff"] and 'class="before"' in c["diff"] and 'class="after"' in c["diff"]
    assert "Committed</b> as prediction" in c["log"]

    f = page["forward"]
    assert "min(k * jobs_waiting, cap)" in f["diff"] and "replaced: its equation" in f["diff"]
    assert "✗ refused: nothing changed" in f["log"] and "✗ replace jobs_done_total = k * nope" in f["log"] and "unknown name nope" in f["log"]
    fw = f["runs"]["forward"]
    assert "⚠ Not trusted here" in fw and "declared: an assumption, never fitted" in fw
    assert fw.count('<svg class="chart"') == 2 and 'class="band"' in fw and ">measured<" in fw and ">now<" in fw
    assert "[object Object]" not in fw
    rp = f["runs"]["replay"]
    assert "Against the base" in rp and rp.count('<svg class="chart"') == 2 and "experiment, simulated" in rp
    assert any(w in rp for w in ("▲ better", "= same", "▼ worse")) and "Each flow's fit" in rp

    inv = page["inverse"]["runs"]["inverse"]
    assert "Asked for" in inv and "jobs waiting: mean level ×0.5 the base replay's" in inv and ("✓ Reached" in inv or "Not reached" in inv)
    assert "The changes found" in inv and "Side effects" in inv and "Uniqueness check" in inv and 'class="diff"' in inv
    assert ("⚠ Ambiguous" in inv) == json.loads((tmp_path / "answers.json").read_text())["experiments"]["inverse"]["runs"][0]["run"]["result"]["ambiguous"]
    assert any("passed" in p for p in page["predictions"])
    assert "arrive = 2 * c" in page["equation"] and "<b>different</b>" in page["equation"] and "its law expects 10 events" in page["equation"]
