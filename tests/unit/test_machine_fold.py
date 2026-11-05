"""Folding machines away on the Machines page and the Event Map (SPEC §10, AGENTS.md rules 2 and 9
as amended on 2026-11-04): a machine that only announced itself, the first time more than ten
minutes ago, is ``announced_only`` and returns the moment it acts; the owner's ``ignore`` mark on a
machine (``hidden``), one or several in one change, undone by ``unignore``. Display only: the bus,
discovery and the flows' hypotheses are unchanged."""

import time

import pytest
from fastapi.testclient import TestClient
from intended_seed import project_at, seed

from orchestra.events import ANNOUNCEMENT, HOST, Events, utc_time
from orchestra.sd.intended import IntentError
from orchestra.sd.intended.controls import page_control
from orchestra.sd.store import ModelStore
from orchestra.web.machines import ANNOUNCED_ONLY_S, machines_view

T0 = 1_790_000_000.0
OWNER = {"author": "owner", "quote": "hide it"}


def ev(src, t, type=ANNOUNCEMENT, **kw):
    return {"type": type, "source": src, "time": utc_time(t), "data": {"mode": "continuous"} if type == ANNOUNCEMENT else {}, **kw}


def by_id(evs, now):
    return {m["id"]: m for m in machines_view(evs, now=now)["machines"]}


def test_a_machine_that_only_announced_itself_long_enough_ago_is_announced_only():
    evs = [ev("person.tracker.u1", T0), ev("person.tracker.u1", T0 + 30), ev("worker", T0), ev("worker", T0 + 5, "order.placed"),
           ev("fresh", T0 + ANNOUNCED_ONLY_S), ev(HOST, T0)]
    ms = by_id(evs, T0 + ANNOUNCED_ONLY_S + 60)
    assert ms["person.tracker.u1"]["announced_only"] is True and ms["person.tracker.u1"]["announced"] == 2
    assert ms["worker"]["announced_only"] is False, "it published something else"
    assert ms["fresh"]["announced_only"] is False, "announced less than ten minutes ago"
    assert ms[HOST]["announced_only"] is False, "Orchestra's host is never folded"
    # under ten minutes since the first announcement, it is not yet folded
    assert by_id(evs, T0 + ANNOUNCED_ONLY_S - 1)["person.tracker.u1"]["announced_only"] is False


def test_an_announced_only_machine_returns_the_moment_it_publishes_anything_else():
    evs = [ev("person.tracker.u1", T0)]
    assert by_id(evs, T0 + 3600)["person.tracker.u1"]["announced_only"] is True
    back = by_id([*evs, ev("person.tracker.u1", T0 + 3500, "issue.updated", subject="X-1")], T0 + 3600)["person.tracker.u1"]
    assert back["announced_only"] is False and back["publishes"][0]["type"] == "issue.updated"


def test_counted_traffic_is_acting():
    from orchestra.web.traffic import merge
    view = {"machines": list(by_id([ev("pipe.a", T0)], T0 + 3600).values())}
    pipe = next(m for m in view["machines"] if m["id"] == "pipe.a")
    assert pipe["announced_only"] is True
    merge(view, {"machines": {"pipe.a": {"traffic": [{"channel": "c", "direction": "out", "per_min": 1.0, "window": 60}], "last": T0}},
                 "edges": [], "channels": []}, T0 + 3600)
    assert pipe["announced_only"] is False


def test_a_page_control_is_one_observation_or_several_machines_hidden_at_once():
    page_control([{"op": "ignore", "part": "machine", "key": "a"}])
    page_control([{"op": "unignore", "part": "machine", "key": "a"}])
    page_control([{"op": "ignore", "part": "machine", "key": "a"}, {"op": "ignore", "part": "machine", "key": "b"}])
    for bad in ([{"op": "ignore", "part": "machine", "key": "a"}, {"op": "unignore", "part": "machine", "key": "b"}],
                [{"op": "ignore", "part": "stock", "key": "a"}, {"op": "ignore", "part": "stock", "key": "b"}],
                [{"op": "ignore", "part": "machine", "key": "a"}, {"op": "ignore", "part": "stock", "key": "b"}],
                [{"op": "expect", "part": "machine", "key": "a"}],
                [{"op": "unignore", "part": "stock", "key": "a"}], []):
        with pytest.raises(IntentError):
            page_control(bad)


def test_ignore_on_a_machine_is_kept_apart_from_a_stock_of_the_same_name(tmp_path):
    from orchestra.sd.intended.view import dynamics_block
    from orchestra.sd.model import Model, SeriesRef, Stock
    ms = ModelStore.for_state(tmp_path)
    m = Model("m", "m", stocks=[Stock("baker", "baker", series=SeriesRef("baker", {"instrument": "i"}))])
    ms.save(m)
    it = ms.intended()
    it.apply([{"op": "ignore", "part": "machine", "key": "baker"}], OWNER)
    marks = it.read()["layer"]["marks"]["ignored"]
    assert list(marks) == ["machine:baker"] and marks["machine:baker"]["part"] == "machine"
    b = dynamics_block(it, ms.load(), None, version=1, live=False, hold=3)
    assert b["ignored"] == [], "a hidden machine is not an ignored part on Dynamics"
    it.apply([{"op": "ignore", "part": "stock", "key": "baker"}], OWNER)
    assert sorted(it.read()["layer"]["marks"]["ignored"]) == ["baker", "machine:baker"]
    b = dynamics_block(it, ms.load(), None, version=1, live=False, hold=3)
    assert [(x["part"], x["key"]) for x in b["ignored"]] == [("stock", "baker")]
    it.apply([{"op": "unignore", "part": "stock", "key": "baker"}], OWNER)
    with pytest.raises(IntentError, match="never expected"):
        it.apply([{"op": "expect", "part": "machine", "key": "baker"}], OWNER)
    it.apply([{"op": "unignore", "part": "machine", "key": "baker"}], OWNER)
    assert it.read()["layer"]["marks"]["ignored"] == {}


def client(project):
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer
    return TestClient(create_app(project), headers=bearer(project))


def machines(c, want=lambda got: True):
    deadline, got = time.time() + 15, None
    while time.time() < deadline:
        got = c.get("/api/machines").json()
        if got.get("ok") and want(got):
            return {m["id"]: m for m in got["machines"]}
        time.sleep(0.2)
    raise AssertionError(got)


def test_hide_show_and_hide_all_on_the_machines_page(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    long_ago = time.time() - 1200
    bus = Events(project.events_file, source="worker")
    for who in ("person.tracker.u1", "person.tracker.u2", "worker"):
        bus.publish(ANNOUNCEMENT, {"mode": "ad hoc", "kind": "person", "listens_for": []}, source=who, time=long_ago)
    bus.publish("order.placed", {}, subject="o-1")
    toml = project.config_file.read_text()
    saved = sorted(p.name for p in ModelStore.for_state(project.state_dir).dir.glob("v*.json"))
    c = client(project)
    ms = machines(c, lambda g: any(m["id"] == "worker" and m["publishes"] for m in g["machines"]))
    assert ms["person.tracker.u1"]["announced_only"] and ms["person.tracker.u2"]["announced_only"]
    assert not ms["worker"]["announced_only"] and all(m["hidden"] is None for m in ms.values())

    # "Hide all of these": one change, one dN, a mark per machine
    n = project.intended.current_version()
    got = c.post("/api/intended/control", json={"control": "ignore", "part": "machine", "keys": ["person.tracker.u1", "person.tracker.u2"],
                                                "page": "machines", "from": "announced only, never acted"}).json()
    assert got["ok"] and got["version"] == n + 1
    line = project.intended.journal(after=n)
    assert len(line) == 1 and [(x["op"], x["part"], x["id"]) for x in line[0]["changes"]] == [
        ("ignore", "machine", "person.tracker.u1"), ("ignore", "machine", "person.tracker.u2")]
    assert line[0]["provenance"]["via"] == "page" and line[0]["provenance"]["page"] == "machines"
    ms = machines(c)
    assert ms["person.tracker.u1"]["hidden"]["provenance"]["author"] == "owner" and ms["person.tracker.u2"]["hidden"]
    assert ms["worker"]["hidden"] is None

    # "Hide this machine" on a card, then "Show"
    assert c.post("/api/intended/control", json={"control": "ignore", "part": "machine", "id": "worker"}).json()["ok"]
    assert machines(c)["worker"]["hidden"]
    assert c.post("/api/intended/control", json={"control": "unignore", "part": "machine", "id": "worker"}).json()["ok"]
    assert machines(c)["worker"]["hidden"] is None
    assert c.post("/api/intended/control", json={"control": "unignore", "part": "machine", "id": "worker"}).status_code == 422

    n = project.intended.current_version()
    for bad in ({"control": "ignore", "part": "machine", "id": "nobody.at.all"},          # not on the page: no lasting typo
                {"control": "expect", "part": "machine", "id": "worker"},
                {"control": "confirm", "part": "machine", "id": "worker"},
                {"control": "ignore", "part": "machine"},
                {"control": "ignore", "part": "machine", "keys": []},
                {"control": "ignore", "part": "machine", "keys": "worker"},
                {"control": "ignore", "part": "stock", "keys": ["a", "b"]},
                {"control": "unignore", "part": "stock", "key": "acceptance_tests_passing"},
                {"control": "ignore", "part": "machine", "id": "worker", "value": 1}):
        assert c.post("/api/intended/control", json=bad).status_code == 400, bad
    assert project.intended.current_version() == n

    # Dynamics' ignored group is of stocks and flows only
    ign = c.get("/api/dynamics/model").json()["model"]["intended"]["ignored"]
    assert all(x["part"] in ("stock", "flow") for x in ign)

    # hidden is display only: the bus, the configuration and the saved versions are unchanged
    types = [e["type"] for e in Events(project.events_file).read(0, 10_000)[0] if e.get("source") == "person.tracker.u1"]
    assert types == [ANNOUNCEMENT]
    assert project.config_file.read_text() == toml
    assert sorted(p.name for p in ModelStore.for_state(project.state_dir).dir.glob("v*.json")) == saved

    # an announced-only machine that acts is back by itself; a hidden one stays hidden until shown
    bus.publish("issue.updated", {}, source="person.tracker.u2", subject="X-1")
    ms = machines(c, lambda g: any(m["id"] == "person.tracker.u2" and m["publishes"] for m in g["machines"]))
    assert not ms["person.tracker.u2"]["announced_only"] and ms["person.tracker.u2"]["hidden"]
    assert ms["person.tracker.u1"]["announced_only"]


def test_discovery_and_attribution_are_the_same_with_a_machine_hidden(tmp_path, monkeypatch):
    import random

    from orchestra.metrics import Point
    from orchestra.metrics import for_project as metrics_for
    from orchestra.sd.rediscover import rediscover

    project = project_at(tmp_path, monkeypatch)
    rng, now, lv, inn, out, pts = random.Random(2), time.time(), 0, 0, 0, []
    bus = Events(project.events_file, source="q_worker")
    bus.publish(ANNOUNCEMENT, {"mode": "continuous", "listens_for": []}, time=now - 3600)
    for i in range(700):
        t = now - 3500 + 5 * i
        a = rng.random() < 0.3
        d = lv > 0 and rng.random() < 0.05 * lv
        inn, out, lv = inn + a, out + d, lv + a - d
        if a:
            bus.publish("q.added", {}, time=t)
        pts += [Point(n, float(v), t, {"project": project.key}) for n, v in (("q_level", lv), ("q_in_total", inn), ("q_out_total", out))]
        # Orchestra's count of the bus, which attribution reads (sd/attribute.py)
        pts.append(Point("orchestra_events_total", float(inn), t, {"project": project.key, "source": "q_worker", "type": "q.added"}))
    metrics_for(project).write(pts)

    def body():
        m = rediscover(project, metrics_for(project), now=now).model.to_json()
        m.pop("saved_at", None)
        m["discovery"].pop("compute_ms", None)
        return m
    without = body()
    hyps = [h["machine"] for f in without["flows"] for h in (((f.get("evidence") or {}).get("machines") or {}).get("hypotheses") or [])]
    assert "q_worker" in hyps, "the worker is hypothesised on a flow before it is hidden"
    project.intended.apply([{"op": "ignore", "part": "machine", "key": "q_worker"},
                            {"op": "ignore", "part": "machine", "key": "q_level"}], OWNER)
    assert without["stocks"] and body() == without
