"""Demo 4, capacity projection (docs/demos/capacity.md): traffic scaled through a stored found model and the true model
of 311; the limits it has, the data reached, and the headroom, checked against the truth."""

import numpy as np
import pytest

from sdlab.demos import capacity as C


def test_binds_reads_each_limit():
    L = {"queue": np.array([100.0, 1000.0]), "ready": np.array([12.0, 12.0]), "pending": np.array([0.0, 3.0]),
         "nodes": np.array([3.0, 3.0]), "cpu": np.array([1000.0, 4000.0]), "desired": np.array([9.0, 15.0])}
    b = C._binds(L)
    assert b["serving"].tolist() == [False, True]          # 0.6 x 1000 > 40 x 12
    assert b["room"].tolist() == [False, True]             # 3 pending, no room on 3 full nodes
    assert b["hpa"].tolist() == [False, True]              # ceil(4000 / 192.5) = 21 > 16


def test_headroom_is_the_last_scale_under_the_tolerance():
    rows = [{"binds": {"serving": x, "room": 0.0, "hpa": 0.5}} for x in [0.0] * 5 + [0.2] * 16]
    hd = C._headroom(rows)
    assert hd == {"serving": C.SCALES[4], "room": C.SCALES[-1], "hpa": None}


def _have():
    try:
        C.found("milp")
        C.setup()
        return True
    except Exception:                                                  # noqa: BLE001  (no stored passing result here)
        return False


def test_case_failures_repeat_weekly():
    if not _have():
        pytest.skip("no 311 case data")
    f = C.case_failures(2 * C.WEEK)
    assert len(f) == 2 * len(C.setup()["truth"]["injections"])
    assert {j["t"] for j in f if j["stock"] == "nodes" and j["amount"] < 0} == {130, 706, 1282, 2146, 2722, 3298}


needs = pytest.mark.skipif(not _have(), reason="no stored passing result of milp on 311 none-long in this store")


@needs
def test_found_model_reproduces_the_truth_on_the_case_week():
    base = np.asarray(C.base_traffic(2000))
    tr = C.run_true(base, 3, C.case_failures(2000))
    d = C.setup()["data"]["all_levels"]
    assert np.allclose(tr["queue"], d["queue"])                  # the copy with explicit traffic is the case's run
    fo = C.run_found(C.found("milp")["found"], base, 3, C.case_failures(2000))
    assert np.max(np.abs(fo["ready"] - tr["ready"])) < 2.5


@needs
def test_caps_found_and_missing():
    c = {x["flow"]: x for x in C.caps("milp")}
    assert c["dispatched"]["has_min"] and c["dispatched"]["reached"] > 0.1
    assert c["started"]["has_min"] and c["started"]["reached"] > 0.1
    assert not c["hpa_up"]["has_min"] and c["hpa_up"]["reached"] == 0            # never reached: fits, not proven


@needs
def test_projection_agrees_with_3_nodes_and_not_past_the_autoscaler_maximum():
    p = C.projection("milp", 3, True)
    assert p["headroom"]["found"] == p["headroom"]["truth"]
    for a, b in zip(p["truth"], p["found"]):
        assert abs(a["queue_peak"] - b["queue_peak"]) / a["queue_peak"] < 0.06
    p6 = C.projection("milp", 6, True)
    i = p6["scales"].index(2.0)
    assert p6["truth"][i]["desired_peak"] <= 16 < p6["found"][i]["desired_peak"]   # the truth stops at 16 pods
    assert p6["found"][i]["queue_peak"] < 0.7 * p6["truth"][i]["queue_peak"]        # so the found model is too hopeful


@needs
def test_routes():
    from fastapi.testclient import TestClient

    from sdlab.server import create_app
    c = TestClient(create_app())
    m = c.get("/api/demos/manifest").json()
    assert "/static/demos-capacity.js" in m["scripts"]
    r = c.get("/api/demos/capacity/week?strategy=milp&scale=1.5&nodes=3")
    assert r.status_code == 200 and len(r.json()["stocks"]["queue"]["found"]) == len(r.json()["t"])
    assert c.get("/api/demos/capacity/projection?strategy=nope").status_code == 404
    assert c.get("/api/demos/capacity/week?nodes=9").status_code == 404
