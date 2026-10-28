"""The intended-effect test (goal G13): a change states its effect before it is made, and once
the change has begun an era and the horizon has passed, Orchestra judges it against the boundary's
comparison and the stocks' simulated runs (docs/rationale/lifted-models.md §3.1, §3.2).

The acceptance cases run on a synthetic pipeline with known rates: jobs arrive, wait, are done
into review (per waiting job) and reviewed (per job in review); a change at ``CHANGE`` alters
some of those rates."""

import random

import pytest
from test_eras import CHANGE, T0, at, poisson, project  # pytest puts this folder on the path

from orchestra.events import Events, envelope
from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd import predictions as P
from orchestra.sd.judge import judge_due
from orchestra.sd.rediscover import rediscover
from orchestra.sd.store import ModelStore
from orchestra.sd.verdict import edit, law_holds, level, outcome, stock_rows, unpredicted

HORIZON = 2400.0


def pipeline(store, minutes, arrive, done_k, review_k, *, seed=5, key="p"):
    """Jobs arrive at ``arrive(t)`` a minute, each waiting job is done at ``done_k(t)`` a minute
    into review, and each job in review is reviewed at ``review_k(t)`` a minute; a point every 5 s."""
    rng = random.Random(seed)
    q = r = 4
    a_t = d_t = v_t = 0
    lab = {"project": key, "machine": "worker"}
    pts = []
    for i in range(minutes * 12):
        t = T0 + i * 5
        a = poisson(rng, arrive(t) / 12)
        d = min(q, poisson(rng, done_k(t) * q / 12))
        v = min(r, poisson(rng, review_k(t) * r / 12))
        q, r = q + a - d, r + d - v
        a_t, d_t, v_t = a_t + a, d_t + d, v_t + v
        pts += [Point("jobs_waiting", q, t, lab), Point("jobs_reviewing", r, t, lab), Point("jobs_arrived_total", a_t, t, lab),
                Point("jobs_done_total", d_t, t, lab), Point("jobs_reviewed_total", v_t, t, lab)]
    store.write(pts)


def step(before, after):
    return lambda t: before if t < CHANGE else after


def made(expect, *, id="pred", change="cause", horizon_s=HORIZON, t=CHANGE - 30, source="ops", **data):
    return envelope(P.MADE, source, {"change": change, "expect": expect, "horizon_s": horizon_s, **data}, time=at(t), id=id)


ARRIVE, DONE, REVIEW = step(2.0, 2.0), step(0.5, 0.5), step(0.4, 0.4)      # the rates when the change changes nothing


def judged(tmp_path, expect, arrive=ARRIVE, done_k=DONE, review_k=REVIEW, *, extra=(), at_s=HORIZON, measure_false=False, **cfg):
    """Run the pipeline, predict, change at CHANGE, discover the era ``at_s`` after it and judge."""
    store = FileMetrics(tmp_path / "m.jsonl")
    pipeline(store, 120, arrive, done_k, review_k)
    events = Events(tmp_path / "events.jsonl")
    for ev in (made(expect), envelope("config.changed", "supervisor", subject="orchestra.toml", time=at(CHANGE), id="cause"), *extra):
        events.bus.append(ev)
    p = project(tmp_path, **cfg)
    rediscover(p, store, now=CHANGE - 1)
    rediscover(p, store, now=CHANGE + at_s, events=events)
    said = []
    vs = judge_due(p, store, CHANGE + at_s, lambda ty, data, **ext: said.append((ty, data, ext)), events=events,
                   measure_false=measure_false)
    return vs, said, p


DOUBLE_ARRIVALS = [{"flow": "jobs_arrived_total", "factor": 2}]


# --- acceptance: the outcomes of lifted-models §3.1 on a system with known rates

def test_a_change_predicted_to_double_a_rate_that_does_is_passed(tmp_path):
    [v], said, _ = judged(tmp_path, DOUBLE_ARRIVALS, arrive=step(2.0, 4.0))
    assert v["verdict"] == "passed", v
    [e] = v["expectations"]
    [c] = e["params"]
    assert e["status"] == "met" and c["z"] >= 2 and abs(c["z_predicted"]) < 2 and 1.6 < c["ratio"] < 2.6
    assert v["unpredicted"] == [] and v["stocks"]["from"] == "simulated"
    assert {r["stock"] for r in v["stocks"]["rows"]} == {"jobs_waiting", "jobs_reviewing"} and not any(r["out"] for r in v["stocks"]["rows"])
    [(ty, data, ext)] = said
    assert ty == "orchestra.prediction.judged" and data == v
    assert ext == {"subject": "pred", "causationid": "pred", "correlationid": "cause"}


def test_predicted_to_double_but_nothing_changes_is_no_effect(tmp_path):
    [v], _, _ = judged(tmp_path, DOUBLE_ARRIVALS)
    assert v["verdict"] == "no effect", v
    assert v["expectations"][0]["status"] == "absent" and v["unpredicted"] == []


def test_predicted_to_change_x_but_y_changes_is_a_side_effect_naming_y(tmp_path):
    [v], _, _ = judged(tmp_path, DOUBLE_ARRIVALS, done_k=step(0.5, 0.25))
    assert v["verdict"] == "side effect", v
    assert v["expectations"][0]["status"] == "absent"
    [y] = v["unpredicted"]
    assert y["part"] == "flow" and y["id"] == "jobs_done_total" and y["status"] == "changed" and y["z"] <= -2


def test_the_edit_appears_but_a_downstream_stock_does_not_move_as_simulated_is_model_wrong_elsewhere(tmp_path):
    # the reviewer stops at the change: the era has not found the review flow since, so it is
    # carried from the prior (not yet a change the comparison can see), but review piles up
    [v], _, _ = judged(tmp_path, DOUBLE_ARRIVALS, arrive=step(2.0, 4.0), review_k=step(0.4, 0.0), prior_for=10800.0)
    assert v["verdict"] == "model wrong elsewhere", v
    assert v["expectations"][0]["status"] == "met" and v["unpredicted"] == []
    rows = {r["stock"]: r for r in v["stocks"]["rows"]}
    assert rows["jobs_reviewing"]["out"] and rows["jobs_reviewing"]["level"] > 5 * rows["jobs_reviewing"]["central"]
    assert not rows["jobs_waiting"]["out"], "upstream of the predicted edit, the stock moved as simulated"


def test_a_null_test_on_a_change_that_changes_nothing_passes_and_reports_its_false_change_rate(tmp_path):
    [v], _, _ = judged(tmp_path, [], measure_false=True)
    assert v["verdict"] == "passed", v
    assert v["expectations"] == [] and v["unpredicted"] == []
    fc = v["false_change"]
    assert fc["z"] == 2.0 and fc["nominal"] == pytest.approx(0.0455, abs=1e-4)
    assert fc["measured"] is not None and fc["flows"] >= 2 and 0 <= fc["measured"] <= 1
    assert fc["window"] == [T0 + 3600 - 3600, T0 + 1800, CHANGE], "the previous era's two halves, within the window"


def test_a_null_test_on_a_change_that_does_change_something_is_a_side_effect(tmp_path):
    [v], _, _ = judged(tmp_path, [], arrive=step(2.0, 4.0))
    assert v["verdict"] == "side effect" and [u["id"] for u in v["unpredicted"]] == ["jobs_arrived_total"]


def test_a_second_change_before_the_horizon_interrupts_with_what_could_be_judged(tmp_path):
    second = envelope("system.changed", "ops", time=at(CHANGE + 1500), id="second")
    store = FileMetrics(tmp_path / "m.jsonl")
    pipeline(store, 120, step(2.0, 4.0), step(0.5, 0.5), step(0.4, 0.4))
    events = Events(tmp_path / "events.jsonl")
    for ev in (made(DOUBLE_ARRIVALS), envelope("config.changed", "supervisor", time=at(CHANGE), id="cause"), second):
        events.bus.append(ev)
    p = project(tmp_path)
    rediscover(p, store, now=CHANGE - 1)
    rediscover(p, store, now=CHANGE + 1400, events=events)
    assert judge_due(p, store, CHANGE + 1400, events=events, measure_false=False) == [], "before the horizon, before the second change"
    rediscover(p, store, now=CHANGE + 1600, events=events)                  # era e2 began: e1's last model is saved
    [v] = judge_due(p, store, CHANGE + 1600, events=events, measure_false=False)
    assert v["verdict"] == "interrupted" and v["interrupted_by"] == "e2" and v["until"] == CHANGE + 1500
    assert v["partial"] == "passed", v
    assert v["expectations"][0]["status"] == "met"


# --- when it is judged

def test_nothing_is_judged_before_the_horizon_and_a_prediction_waits_for_its_change(tmp_path):
    vs, _, p = judged(tmp_path, DOUBLE_ARRIVALS, arrive=step(2.0, 4.0), at_s=HORIZON - 300)
    assert vs == []
    [rec] = P.recorded(ModelStore.for_state(p.state_dir))
    assert rec["status"] == "waiting" and rec["era"] == "e1"
    events = Events(tmp_path / "events.jsonl")
    events.bus.append(made([], id="later", change="not-yet"))
    store = FileMetrics(tmp_path / "m.jsonl")
    assert judge_due(p, store, CHANGE + HORIZON, events=events, measure_false=False) == [], "the host has not discovered the era since"
    rediscover(p, store, now=CHANGE + HORIZON, events=events)
    assert [v["prediction"] for v in judge_due(p, store, CHANGE + HORIZON, events=events, measure_false=False)] == ["pred"]
    later = next(x for x in P.recorded(ModelStore.for_state(p.state_dir)) if x["id"] == "later")
    assert later["status"] == "waiting" and "era" not in later


def test_a_prediction_made_after_its_change_is_judged_and_marked_late(tmp_path):
    late = made([], id="late", t=CHANGE + 60)
    vs, _, _ = judged(tmp_path, DOUBLE_ARRIVALS, arrive=step(2.0, 4.0), extra=[late])
    by = {v["prediction"]: v for v in vs}
    assert not by["pred"]["late"] and by["late"]["late"]


def test_with_its_own_trajectories_the_stocks_are_judged_against_the_predictors_run(tmp_path):
    traj = {"t": [0, HORIZON], "stocks": {"jobs_waiting": {"central": [4, 30], "lo": [3, 29], "hi": [5, 31]}}}
    store = FileMetrics(tmp_path / "m.jsonl")
    pipeline(store, 120, step(2.0, 4.0), step(0.5, 0.5), step(0.4, 0.4))
    events = Events(tmp_path / "events.jsonl")
    for ev in (made(DOUBLE_ARRIVALS, trajectories=traj), envelope("config.changed", "supervisor", time=at(CHANGE), id="cause")):
        events.bus.append(ev)
    p = project(tmp_path)
    rediscover(p, store, now=CHANGE - 1)
    rediscover(p, store, now=CHANGE + HORIZON, events=events)
    [v] = judge_due(p, store, CHANGE + HORIZON, events=events, measure_false=False)
    assert v["stocks"]["from"] == "prediction" and [r["stock"] for r in v["stocks"]["rows"]] == ["jobs_waiting"]
    assert v["verdict"] == "model wrong elsewhere", "the predictor's run had the queue pile up to 30; it settled near 8"


# --- the record

def test_predictions_are_checked_into_one_shape():
    assert P.expectation({"flow": "f", "factor": 1.5}) == {"kind": "factor", "flow": "f", "factor": 1.5}
    assert P.expectation({"flow": "f", "factor": 0}) == {"kind": "disappears", "part": "flow", "id": "f"}
    assert P.expectation({"from": "a", "to": None, "appears": True}) == {"kind": "appears", "part": "flow", "from": "a", "to": None}
    assert P.expectation({"stock": "s", "below": 6}) == {"kind": "level", "stock": "s", "below": 6.0}
    assert P.check({"change": "c", "expect": [], "horizon": "30m"})["horizon_s"] == 1800.0
    for bad, why in [({"flow": "f"}, "say what"), ({"stock": "s", "factor": 2}, "flow's"), ({"flow": "f", "factor": -1}, "at least 0"),
                     ({"flow": "f", "factor": 2, "colour": "red"}, "unknown field")]:
        with pytest.raises(P.PredictionError, match=why):
            P.expectation(bad)
    with pytest.raises(P.PredictionError, match="horizon_s"):
        P.check({"change": "c", "expect": []})
    with pytest.raises(P.PredictionError, match="change"):
        P.check({"expect": [], "horizon_s": 60})


def test_an_equation_is_an_expectation_checked_for_syntax():
    assert P.expectation({"flow": "f", "equation": "k * min(q, 2 * r)", "params": {"k": 0.4}}) == {
        "kind": "equation", "flow": "f", "equation": "k * min(q, 2 * r)", "params": {"k": 0.4}}
    new = P.expectation({"from": "a", "to": None, "appears": True, "equation": "c", "params": {"c": 1}})
    assert new == {"kind": "appears", "part": "flow", "from": "a", "to": None, "equation": "c", "params": {"c": 1.0}}
    assert P.plain(new) == {"from": "a", "to": None, "appears": True, "equation": "c", "params": {"c": 1.0}}
    for bad, why in [({"flow": "f", "equation": "__import__('os')"}, "equation"), ({"flow": "f", "equation": "k * q", "params": {"z": 1}}, "not read by the equation"),
                     ({"flow": "f", "params": {"k": 1}}, "params go with an equation"),
                     ({"flow": "f", "appears": True, "equation": "c", "params": {"c": 1}}, "its ends")]:
        with pytest.raises(P.PredictionError, match=why):
            P.expectation(bad)


def test_sync_records_each_prediction_once_keeps_invalid_ones_and_survives_a_replaced_bus(tmp_path):
    store = ModelStore.for_state(tmp_path)
    events = Events(tmp_path / "events.jsonl")
    events.bus.append(made([], id="a"))
    events.bus.append(envelope(P.MADE, "ops", {"change": "c", "expect": [{"flow": "f"}], "horizon_s": 60}, id="b"))
    events.bus.append(envelope("job.done", "worker", {"change": "c", "expect": [], "horizon_s": 60}))
    all_, new = P.sync(store, events)
    assert [(p["id"], p["status"]) for p in new] == [("a", "waiting"), ("b", "invalid")]
    assert "say what is expected" in new[1]["why"] and new[0]["source"] == "ops" and new[0]["made_at"] == CHANGE - 30
    assert P.sync(store, events)[1] == []
    P.update(store, "a", lambda x: x.update(status="judged", verdict={"verdict": "passed"}))
    fresh = Events(tmp_path / "other.jsonl")
    fresh.bus.append(made([], id="a"))
    all_, new = P.sync(store, fresh)
    assert new == [] and all_[0]["verdict"] == {"verdict": "passed"}, "a bus read again keeps the verdicts"


def test_the_python_api_publishes_records_and_reads_back(tmp_path):
    from types import SimpleNamespace
    proj = SimpleNamespace(state_dir=tmp_path / "state")
    events = Events(tmp_path / "events.jsonl", source="curator")
    api = P.Predictions(proj, source="curator", events=events)
    rec = api.record([{"flow": "f", "factor": 1.3}], horizon="2h", subject="playbook")
    assert rec["status"] == "waiting" and rec["horizon_s"] == 7200 and rec["source"] == "curator" and len(rec["change"]) == 32
    [ev] = [e for e in events.read(0, 10)[0] if e["type"] == P.MADE]
    assert ev["id"] == rec["id"] and ev["source"] == "curator" and ev["subject"] == "playbook" and ev["data"]["change"] == rec["change"]
    assert api.about(rec["change"]) == [rec] and api.verdict(rec["id"]) is None
    with pytest.raises(P.PredictionError):
        api.record([{"flow": "f"}], horizon=60)


def test_a_machine_may_publish_a_prediction_over_the_endpoint_but_not_a_verdict():
    from orchestra.endpoint.validate import Invalid, check
    assert check({"type": P.MADE, "source": "curator", "data": {"change": "c", "expect": [], "horizon_s": 60}})["type"] == P.MADE
    with pytest.raises(Invalid, match="Orchestra's own type"):
        check({"type": P.JUDGED, "source": "curator"})


# --- the rules, on comparisons made by hand

def _cmp(*flows, stocks=None, loops=None):
    return {"from": None, "to": "e1", "flows": list(flows), "stocks": {"appeared": [], "disappeared": [], "carried": [], **(stocks or {})},
            "loops": {"appeared": [], "disappeared": [], **(loops or {})}}


def _num(before, after, se=0.1, z=None):
    return {"param": "c", "before": before, "after": after, "se_before": se, "se_after": se, "ratio": after / before,
            "z": z if z is not None else round((after - before) / (se * 2 ** 0.5), 2)}


def test_a_factor_is_met_when_the_number_moved_to_where_predicted_and_different_when_it_moved_elsewhere():
    e = {"kind": "factor", "flow": "f", "factor": 2.0}
    assert edit(e, _cmp({"id": "f", "status": "changed", "params": [_num(1.0, 2.05)]}))["status"] == "met"
    assert edit(e, _cmp({"id": "f", "status": "changed", "params": [_num(1.0, 1.4)]}))["status"] == "different"
    assert edit(e, _cmp({"id": "f", "status": "unchanged", "params": [_num(1.0, 1.05)]}))["status"] == "absent"
    assert edit(e, _cmp({"id": "f", "status": "carried"}))["status"] == "waiting"
    assert edit(e, _cmp())["status"] == "absent"


def test_a_form_change_is_judged_by_whether_the_old_law_still_predicts_the_count():
    e = {"kind": "factor", "flow": "f", "factor": 2.0}
    c = _cmp({"id": "f", "status": "form changed", "before": {"form": "constant", "inputs": []}, "after": {"form": "linear", "inputs": ["s"]}})
    same = {"f": {"expected": 100.0, "events": 104.0, "dispersion": 1.0, "rel": 0.05}}
    double = {"f": {"expected": 100.0, "events": 196.0, "dispersion": 1.0, "rel": 0.05}}
    assert edit(e, c, laws=same)["status"] == "absent" and edit(e, c, laws=double)["status"] == "met"
    assert unpredicted([], c, [], laws=same) == [], "discovery chose another form; the old law still holds"
    assert [u["id"] for u in unpredicted([], c, [], laws=double)] == ["f"] and law_holds(None) is None


def test_appearing_and_disappearing_parts_and_what_was_not_predicted():
    from orchestra.sd.model import Flow, Model, Stock
    m = Model("system", "s", stocks=[Stock("a", "a"), Stock("b", "b")], flows=[Flow("new", "new", "a", "b")])
    c = _cmp({"id": "new", "status": "appeared"}, {"id": "gone", "status": "carried"}, {"id": "g", "status": "changed", "params": [_num(1, 3)]},
             stocks={"appeared": ["b"]}, loops={"appeared": ["L1"]})
    taken: set = set()
    by_ends = {"kind": "appears", "part": "flow", "from": "a", "to": "b"}
    assert edit(by_ends, c, m, taken) == {"status": "met", "flow": "new"}
    assert edit({"kind": "disappears", "part": "flow", "id": "gone"}, c)["status"] == "met"
    statuses = [{**by_ends, "status": "met", "flow": "new"}]
    extra = unpredicted([by_ends], c, statuses, m, {"L1": ["a", "b"]})
    assert [(u["part"], u["id"]) for u in extra] == [("flow", "g")], "the new flow's stocks and loop were predicted with it"


def test_levels_stocks_and_the_verdict_table():
    measured = {"s": [[t, 10.0 + (t % 2)] for t in range(0, 101, 5)]}
    assert level({"kind": "level", "stock": "s", "below": 12}, measured, 100)["status"] == "met"
    assert level({"kind": "level", "stock": "s", "above": 12}, measured, 100)["status"] == "missed"
    assert level({"kind": "level", "stock": "x", "above": 1}, measured, 100)["status"] == "waiting"
    traj = {"t": [0, 100], "stocks": {"s": {"central": [10, 10], "lo": [9, 9], "hi": [11, 11]}}}
    [row] = stock_rows(traj, measured, 100)
    assert not row["out"] and row["readings"] == 11
    [row] = stock_rows({"t": [0, 100], "stocks": {"s": {"central": [30, 30], "lo": [29, 29], "hi": [31, 31]}}}, measured, 100)
    assert row["out"] and row["z"] < -2
    met, absent, diff, wait = ({"status": s} for s in ("met", "absent", "different", "waiting"))
    assert outcome([met], [], [], []) == "passed" and outcome([], [], [], None) == "passed"
    assert outcome([met], [], [{"id": "y"}], []) == "side effect" and outcome([diff], [], [], []) == "side effect"
    assert outcome([absent], [], [], []) == "no effect" and outcome([met, wait], [], [], []) is None
    assert outcome([met], [{"status": "missed"}], [], []) == "model wrong elsewhere"
    assert outcome([met], [], [], [{"out": True}]) == "model wrong elsewhere"


# --- the command line, the host and the Dynamics page

def test_a_prediction_judged_by_the_host_shown_by_the_cli_and_the_dynamics_api(tmp_path, monkeypatch, capsys):
    import json
    import subprocess

    from fastapi.testclient import TestClient

    from orchestra.cli import main
    from orchestra.config import init_project, load_project
    from orchestra.host import Host
    from orchestra.web.app import create_app
    from orchestra.web.dynamics import model_view

    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    for k in ("ORCHESTRA_METRICS_URL", "ORCHESTRA_EVENTS_URL"):
        monkeypatch.delenv(k, raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    init_project(repo)
    (repo / "orchestra.toml").write_text('[discovery]\nstrategy = "conservation"\n', encoding="utf-8")
    p = load_project(repo)
    store = FileMetrics(tmp_path / "m.jsonl")              # the project's own store refuses points from the future
    pipeline(store, 120, step(2.0, 4.0), step(0.5, 0.5), step(0.4, 0.4), key=p.key)
    monkeypatch.setattr("orchestra.host.metrics_for", lambda project: store)
    monkeypatch.chdir(repo)

    def cli(*args) -> str:
        monkeypatch.setattr("sys.argv", ["orchestra", "sd", *args])
        assert main() == 0
        return capsys.readouterr().out

    made = P.Predictions(p, source="ops").record([{"flow": "jobs_arrived_total", "factor": 2}, {"flow": "jobs_done_total", "unchanged": True}],
                                                 horizon="40m", change="cause")
    assert made["status"] == "waiting" and made["change"] == "cause"
    monkeypatch.setattr("sys.argv", ["orchestra", "sd", "predict", "--source", "ops", "--horizon", "40m"])
    with pytest.raises(SystemExit):
        main()
    assert "invalid choice: 'predict'" in capsys.readouterr().err, "the command is gone: machines predict through the APIs"

    host = Host(p)
    events = Events.for_project(p)
    events.bus.append(envelope("config.changed", "supervisor", time=at(CHANGE), id="cause"))
    host._eras()
    rediscover(p, store, now=CHANGE - 1)
    rediscover(p, store, now=CHANGE + HORIZON, events=events)
    host._judge(CHANGE + HORIZON)
    [ev] = [e for e in events.read(0, 1000)[0] if e["type"] == P.JUDGED]
    pid = ev["subject"]
    assert ev["source"] == "orchestra-host" and ev["causationid"] == pid and ev["correlationid"] == "cause"
    assert ev["data"]["verdict"] == "passed" and ev["data"]["era"] == "e1"
    log = (p.logs_dir / "orchestra-host.log").read_text()
    assert f"prediction {pid} judged: passed (era e1)" in log
    other = events.publish(P.MADE, {"change": "next", "expect": [], "horizon": "1h"}, source="curator")
    host._eras()
    assert f"prediction {other['id']} from curator about change next: waiting" in (p.logs_dir / "orchestra-host.log").read_text()

    out = cli("predictions")
    assert "era e1" in out and "jobs_arrived_total ×2, jobs_done_total unchanged" in out and "    passed" in out
    assert "jobs_arrived_total ×2: met; c " in out and "stocks against the simulated run" in out
    data = json.loads(cli("predictions", "--json"))
    assert data["predictions"][0]["era"] == "e1" and data["predictions"][0]["verdict"]["verdict"] == "passed"

    m = model_view(p)["model"]
    assert [x["id"] for x in m["predictions"]] == [pid, other["id"]], "the era's, and those still waiting for their change"
    assert m["predictions"][0]["verdict"]["verdict"] == "passed" and m["predictions"][1]["era"] is None
    assert model_view(p, era="none")["model"]["predictions"] == [], "not the era before"
    from orchestra.web.auth import bearer

    web = TestClient(create_app(p), headers=bearer(p))
    assert [x["id"] for x in web.get("/api/dynamics/predictions?era=e1").json()["predictions"]] == [pid]
    assert [x["id"] for x in web.get("/api/dynamics/predictions?era=none").json()["predictions"]] == [other["id"]], "not yet matched"
