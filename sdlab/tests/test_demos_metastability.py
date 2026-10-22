"""Demo 6, metastability scan (docs/demos/metastability.md): the spike, the recovery test and the found models'
free runs are checked against the true model they are built on; the scan's findings are pinned where stored
passing results exist (skipped otherwise)."""

import copy

import numpy as np
import pytest

from sdlab.demos import engine as E
from sdlab.demos import metastability as M


def test_recovery_and_bands():
    base = np.full(100, 100.0)
    q = base.copy()
    q[10:30] = 500.0                                                      # off for 20 steps after index 10
    assert M.recovery(q, base, 10) == 20 and M.band(20) == "within 6 h"
    assert M.recovery(base, base, 10) == 0 and M.band(0) == "within 1 h"
    q2 = base.copy()
    q2[10:] = np.linspace(200, 2000, 90)                                  # never back: stuck
    assert M.recovery(q2, base, 10) is None and M.band(None) == "stuck"
    q3 = base.copy()
    q3[10:90] = 300.0                                                     # back with fewer than HOLD steps left: not back
    assert M.recovery(q3, base, 10) is None


def test_dispatch_cap_and_loop():
    capped = [{"from": "queue", "to": "inflight", "rate": {"form": "expr", "expr": "min(0.6 * queue, 40 * ready)"}}]
    plain = [{"from": "queue", "to": "inflight", "rate": {"form": "proportional", "stock": "queue", "k": 0.6}}]
    assert M.dispatch_cap(capped) and M.dispatch_cap(plain) is None
    assert M.dispatch_text(plain) == "0.6 × queue"
    g = M.loop_gain()
    assert abs(g["loss_at_cap"] - 0.032) < 1e-12 and g["tips_when_k_above"] == 0.4
    assert M.MECHANISMS["amplify-1.05"]["k"] > g["tips_when_k_above"] > M.MECHANISMS["amplify-0.9"]["k"]


def test_spike_series_is_the_engines_pulse():
    c, tr = E.case_and_truth("310-k8s-memory-oom", M.VARIANT)
    m = copy.deepcopy(tr)
    m["steps"] = 40
    m["inputs"]["traffic"]["terms"].append({"fn": "pulse", "height": 300.0, "start": 10, "width": 5})
    got = np.asarray(E.run_truth(m)["inputs"]["traffic"])
    base = np.asarray(E.run_truth({**tr, "steps": 40})["inputs"]["traffic"])
    want = M.spike_series(base, list(range(1, 41)), 10, 300, 5)
    assert np.allclose(got, want) and np.isclose((got - base).sum(), 1500)


def _have(case, strategy="milp"):
    try:
        return M._found(case, strategy) is not None
    except Exception:                                                     # noqa: BLE001  (no store here)
        return False


@pytest.mark.skipif(not _have("310-k8s-memory-oom"), reason="no stored passing result on 310")
def test_found_free_run_reproduces_the_truth_on_310():
    s = M._setup("310-k8s-memory-oom")
    f = M._found("310-k8s-memory-oom", "milp")
    steps = 600
    fr = M.found_runs(f["flows"], "310-k8s-memory-oom", "as-built", s["traffic"][None, :steps], steps)
    tq = M.truth_run("310-k8s-memory-oom", "as-built", 0, 0, 0, steps)["queue"]
    assert np.abs(fr["queue"][:, 0] - tq).max() < 1e-3                   # the cap never binds: the same dynamics


@pytest.mark.skipif(not _have("310-k8s-memory-oom"), reason="no stored passing result on 310")
def test_310_no_metastability_and_no_cap_in_found_models():
    r = M.scan("310-k8s-memory-oom", "as-built", "ramp")
    cells = sum(r["truth"]["grid"], [])
    assert all(c["recovery"] is not None for c in cells)                 # the true system always recovers ...
    assert max(c["recovery"] for c in cells) >= 60                       # ... but can take hours
    assert r["coverage"]["bound_steps"] == 0 and r["coverage"]["max_ratio"] < 1
    for f in r["found"]:
        if f.get("missing"):
            continue
        assert f["cap"] is None                                           # fitted where the cap never bound
        assert max(c["recovery"] for c in sum(f["grid"], [])) <= 12      # so it says every spike is over in an hour
    amp = M.scan("310-k8s-memory-oom", "amplify-1.05", "ramp")
    assert any(c["growing"] for c in sum(amp["truth"]["grid"], []))      # with amplification above 1: a tipping point
    assert all(f["agreement"]["missed_stuck"] > 0 for f in amp["found"] if not f.get("missing"))


@pytest.mark.skipif(not _have("311-k8s-node-pool"), reason="no stored passing result on 311")
def test_311_found_models_have_the_cap_and_the_tipping_point():
    r = M.scan("311-k8s-node-pool", "amplify-1.05", "ramp")
    assert not r["truth"]["base_stuck"]
    assert sum(c["growing"] for c in sum(r["truth"]["grid"], [])) >= 5
    for f in r["found"]:
        if f.get("missing"):
            continue
        assert f["cap"] and f["agreement"]["same_band"] >= 33 and f["agreement"]["missed_stuck"] == 0


@pytest.mark.skipif(not _have("310-k8s-memory-oom"), reason="no stored passing result on 310")
def test_routes():
    from fastapi.testclient import TestClient

    from sdlab.server import create_app
    c = TestClient(create_app())
    assert c.get("/api/demos/metastability/options").json()["strategies"][0] == "milp"
    r = c.get("/api/demos/metastability/example", params={"case": "310-k8s-memory-oom", "height": 800, "width": 48}).json()
    assert r["found"]["cap"] is None and r["truth"]["recovery"] > r["found"]["recovery"]
    assert c.get("/api/demos/metastability/scan", params={"case": "nope"}).status_code == 404
    assert "/static/demos-metastability.js" in c.get("/api/demos/manifest").json()["scripts"]
