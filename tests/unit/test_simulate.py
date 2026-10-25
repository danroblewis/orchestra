"""Running the model's equations forward (sd/simulate.py) to known steady states."""

import pytest

from orchestra.sd.model import Equation, Flow, Model, Stock
from orchestra.sd.simulate import simulate
from orchestra.sd.strategies import sd_installed

pytestmark = pytest.mark.skipif(not sd_installed(), reason="simulating needs orchestra[sd]")


def queue(outflow: Equation, inflow: Equation | None = None) -> Model:
    inflow = inflow or Equation("constant", {"c": 2.0}, "fitted")
    return Model("m", "m", time_unit="minute", stocks=[Stock("q", "queue")],
                 flows=[Flow("in", "in", None, "q", equations=[inflow]), Flow("out", "out", "q", None, equations=[outflow])])


def history(level: float, start: float = 0.0, now: float = 600.0) -> dict:
    return {"stocks": {"q": [[start, level], [now, level]]}, "flows": {}, "inputs": {}}


def test_constant_in_proportional_out_settles_at_in_over_k():
    # 2/min in, 0.1/min of the queue out: steady at 20, from either side
    m = queue(Equation("proportional", {"k": 0.1}, "fitted", inputs=["q"]))
    for start_level in (0.0, 60.0):
        r = simulate(m, history(start_level), now=600, start=0, horizon_s=3 * 3600, step_s=15)
        assert r["era"]["q"][0][1] == start_level
        assert r["projection"]["q"][-1][1] == pytest.approx(20.0, abs=0.2)
        assert r["replayed"] == []


def test_an_sdlab_spec_is_stepped_per_step_not_per_minute():
    # the same system written as SD Lab's spec: the rates are per minute and stepped every 15 s
    m = queue(Equation("proportional", {"k": 0.1}, "discovered", spec={"form": "proportional", "stock": "q", "k": 0.1}),
              Equation("constant", {"value": 2.0}, "discovered", spec={"form": "constant", "value": 2.0}))
    r = simulate(m, history(0.0), now=600, start=0, horizon_s=60, step_s=15)
    # the first minute adds about 2 (less what drains as it fills)
    assert r["era"]["q"][4][1] == pytest.approx(2 * (1 - 0.1 / 2), rel=0.05)


def test_nothing_leaves_a_stock_that_is_not_there():
    m = queue(Equation("constant", {"c": 50.0}, "fitted"), Equation("constant", {"c": 0.0}, "fitted"))
    r = simulate(m, history(3.0), now=600, start=0, horizon_s=600, step_s=15)
    assert min(v for _, v in r["projection"]["q"]) == 0.0


def test_a_flow_with_no_form_to_step_is_replayed_then_held():
    m = queue(Equation("expr", {}, "discovered", spec={"form": "expr", "expr": "q / 10"}))
    h = history(10.0)
    h["flows"]["out"] = [[0, 1.0], [300, 1.0], [600, 1.0]]
    r = simulate(m, h, now=600, start=0, horizon_s=1200, step_s=15)
    assert r["replayed"] == ["out"]
    # 2 in, 1 out (replayed and then held): +1/min
    assert r["projection"]["q"][-1][1] == pytest.approx(10.0 + 20.0, abs=0.5)
