"""Control metrics (sdlab/ladder/control.py) against the analytic answers of the simplest loops."""

import math

import numpy as np
import pytest

from sdlab.ladder import cases as casemod
from sdlab.ladder import control


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def lin(c, *terms):
    return {"form": "linear", "c": c, "terms": [{"stock": s, "k": k} for s, k in terms]}


def test_p_control_of_a_first_order_lag():
    # T' = 0.3 (r - T) - 0.05 T: pole 0.65, steady-state error 1 - 0.3 / 0.35, L = 0.3 / (z - 0.95)
    flows = [{"id": "heater", "from": None, "to": "T", "rate": lin(0, ("r", 0.3), ("T", -0.3))},
             {"id": "t_out", "from": "T", "to": None, "rate": {"form": "proportional", "stock": "T", "k": 0.05}}]
    m = control.metrics(flows, ["T"], np.array([100.0]), {"r": 200.0}, {"y": "T", "step": "r", "size": 20}, 200)
    assert m["settles"] and m["overshoot"] == 0
    assert m["sse"] == pytest.approx(1 - 0.3 / 0.35, abs=1e-6)
    assert m["rho"] == pytest.approx(0.65, abs=1e-6)
    assert m["gm"] == pytest.approx(1.95 / 0.3, rel=1e-3)          # |L(-1)| = 0.3 / 1.95
    w = math.acos((0.95 ** 2 + 1 - 0.09) / (2 * 0.95))              # |e^{iw} - 0.95| = 0.3
    pm = 180 - math.degrees(math.atan2(math.sin(w), math.cos(w) - 0.95))
    assert m["pm"] == pytest.approx(pm, abs=0.5)


def test_pi_control_has_no_steady_state_error_and_a_model_without_the_setpoint_has_no_margins():
    s = control.setup(casemod.load("201-control-pi-room-heater"), "none-short")
    t = control.true_metrics(s)
    assert t["settles"] and abs(t["sse"]) < 1e-4 and t["overshoot"] > 0
    blind = [f for f in s["truth"] if "setpoint" not in str(f.get("rate"))]
    f = control.found_metrics(s, blind)
    assert not f.get("reads_setpoint", True) or not f["settles"]


def test_on_off_control_is_a_limit_cycle():
    s = control.setup(casemod.load("210-control-on-off-heater"), "none-short")
    t = control.true_metrics(s)
    assert not t["settles"] and t["cycle"] > 1
