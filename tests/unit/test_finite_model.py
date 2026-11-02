"""A model never holds a non-finite number, and one that does still reads: a form that cannot
produce the data (an event where its rate is zero) is "not fitted" with its reason, never an
infinite AIC; the store writes strict JSON; the web API and the endpoint send a stray infinity
as null rather than answering 500."""

from __future__ import annotations

import json
import logging
import math
import subprocess

import pytest

from orchestra.config import init_project
from orchestra.finite import finite
from orchestra.sd.discover import discover
from orchestra.sd.series import Declared, series_key
from orchestra.sd.store import ModelStore

T0 = 1_800_000_000.0
LAB = {"machine": "supervisor"}
STARTS = [300, 700, 1300, 1900, 2500, 3000, 3300]
LASTS = [5, 400, 3, 200, 8, 100, 4]          # most turns end within the counters' 15 s sample


def turns_model():
    """The T2b run's shape: an agent's turns started and finished, counted every 15 s, and the
    number working, read every 53 s. A turn that starts and ends between two reads of the level
    finishes while the level reads zero: a rate proportional to it cannot produce that event."""
    ends = [s + d for s, d in zip(STARTS, LASTS, strict=True)]
    count = lambda times: [(T0 + 15 * i, float(sum(1 for t in times if t <= 15 * i))) for i in range(241)]
    working = [(T0 + 53 * i, float(sum(1 for a, b in zip(STARTS, ends, strict=True) if a <= 53 * i < b))) for i in range(68)]
    dump = [("agents_working", LAB, working), ("agent_turns_started_total", LAB, count(STARTS)),
            ("agent_turns_finished_total", LAB, count(ends))]
    kinds = {series_key(n, lab): Declared("level", resolution_s=53.0) if n == "agents_working" else Declared("counter", resolution_s=15.0)
             for n, lab, _ in dump}
    return discover(dump, start=T0, end=T0 + 3600, step=15, time_unit="minute", kinds=kinds)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    (tmp_path / "repo").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path / "repo", check=True)
    return init_project(tmp_path / "repo")


def test_a_form_with_an_event_at_a_zero_rate_is_not_fitted_and_the_model_is_finite():
    m = turns_model()
    assert [s.id for s in m.stocks] == ["agents_working"]
    body = m.to_json()
    json.dumps(body, allow_nan=False)                          # strict JSON: no infinity anywhere
    q = next(f for f in body["flows"] if f["id"] == "agent_turns_finished_total")["equations"][0]["quality"]
    assert "aic_proportional" not in q and "proportional_k" not in q
    assert q["rejected"]["proportional_agents_working"].startswith("not fitted: an event came while its rate in agents_working was zero")


def test_finite_replaces_non_finite_numbers_with_null_and_logs_each_path_once(caplog):
    caplog.set_level(logging.WARNING, logger="orchestra.finite")
    d = {"a": [1.0, math.inf], "b": {"c": math.nan}, "ok": 2.5}
    assert finite(d, "x") == {"a": [1.0, None], "b": {"c": None}, "ok": 2.5}
    finite(d, "x")
    said = [r.getMessage() for r in caplog.records]
    assert len(said) == 2 and any("x.a[1]" in s for s in said) and any("x.b.c" in s for s in said)
    same = {"a": [1.0], "b": "s"}
    assert finite(same) is same


def _with_inf(m):
    eq = m.flows[0].equations[0]
    eq.params["c"] = math.inf
    eq.quality["aic_proportional"] = math.inf
    return m


def test_a_model_with_an_infinite_coefficient_round_trips_the_store_and_the_api(project):
    from fastapi.testclient import TestClient

    from orchestra.web import auth
    from orchestra.web.app import create_app

    store = ModelStore.for_state(project.state_dir)
    n = store.save(_with_inf(turns_model()), "with an infinity")
    raw = store._path(n).read_text(encoding="utf-8")
    assert "Infinity" not in raw and "NaN" not in raw
    json.loads(raw, parse_constant=lambda c: pytest.fail(f"{c} in the saved version"))
    assert store.load(n).flows[0].equations[0].params["c"] is None
    store.write_discovery(_with_inf(turns_model()))
    assert "Infinity" not in (store.dir / "discovered.json").read_text(encoding="utf-8")

    # a version written before the store refused them still reads on the page: null, not a 500
    p = store._path(n)
    p.write_text(raw.replace('"c": null', '"c": Infinity', 1), encoding="utf-8")
    c = TestClient(create_app(project), headers={"Authorization": f"Bearer {auth.token(project)}"})
    r = c.get(f"/api/dynamics/model?version={n}")
    assert r.status_code == 200, r.text
    flow = r.json()["model"]["flows"][0]
    assert flow["equations"][0]["params"]["c"] is None


def test_the_endpoint_sends_a_non_finite_number_as_null():
    from orchestra.endpoint import server

    sent = {}

    class Fake:
        def send_response(self, s): sent["status"] = s
        def send_header(self, k, v): pass
        def end_headers(self): pass
        class wfile:
            @staticmethod
            def write(raw): sent["raw"] = raw

    handler = server._handler(None)
    handler._send(Fake(), 200, {"x": math.inf})
    assert json.loads(sent["raw"]) == {"x": None}
