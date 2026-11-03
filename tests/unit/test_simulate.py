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


def test_a_flow_fitted_from_too_few_events_is_replayed_not_stepped():
    m = queue(Equation("constant", {"c": 9.0}, "fitted", quality={"events": 2}))
    h = history(10.0)
    h["flows"]["out"] = [[0, 1.0], [600, 1.0]]
    r = simulate(m, h, now=600, start=0, horizon_s=600, step_s=15)
    assert r["replayed"] == ["out"] and r["too_few"] == ["out"]
    assert r["projection"]["q"][-1][1] == pytest.approx(10.0 + 10.0, abs=0.5)     # 2 in, 1 out as observed: never the fitted 9


def behaviour(**kw) -> dict:
    return {"trust": {"score": 0.8, "kind": "balance", "behaviour": {"score": 0.7, "level": "medium", "beats_hold": True,
                                                                     "growth": 0.5, "z": 2.0, "horizon": 10.0, **kw}}}


def test_each_flow_says_what_it_moves_over_the_projection():
    # 2/min in for 10 minutes; the outflow asks for 50/min of a queue that holds 3: it gets what is there
    m = queue(Equation("constant", {"c": 50.0}, "fitted"))
    r = simulate(m, history(3.0), now=600, start=0, horizon_s=600, step_s=15)
    assert r["flows"]["in"] == {"count": pytest.approx(20.0, abs=0.01), "replayed": False}
    assert r["flows"]["out"]["count"] == pytest.approx(22.5, abs=0.01), "never more than was there: the last step's 0.5 stays"
    assert r["horizon"] == 600


def test_a_stock_that_drains_says_when_it_empties_and_its_band_widens_past_what_was_tested():
    m = queue(Equation("constant", {"c": 3.0}, "fitted"), Equation("constant", {"c": 1.0}, "fitted"))   # net −2/min
    m.stocks[0].evidence = behaviour()
    r = simulate(m, history(10.0), now=600, start=0, horizon_s=30 * 60, step_s=15)
    s = r["stocks"]["q"]
    assert s["no_projection"] is None and s["start"] == 10.0 and s["end"] == pytest.approx(0.25)
    assert s["empties_at"] == pytest.approx(600 + 5 * 60, abs=15), "10 at −2/min: empty in five minutes"
    assert s["trust"]["trusted_s"] == 600.0 and s["tested_until"] == 1200
    by_t = {t: (lo, hi) for t, lo, hi in s["band"]}
    assert by_t[600 + 120] == (pytest.approx(6 - 2.0 * 0.5 * 2), pytest.approx(6 + 2.0 * 0.5 * 2)), "within the tested horizon: ± z × growth × h"
    assert by_t[600 + 1800][1] == pytest.approx(0.25 + 2.0 * 0.5 * 30 * 3), "beyond it: × h / T, so it widens faster"
    assert min(lo for _, lo, _ in s["band"]) == 0.0, "never below zero"


def test_no_projection_is_said_with_its_reason():
    m = queue(Equation("constant", {"c": 1.0}, "fitted"))
    m.stocks[0].evidence = behaviour(beats_hold=False)
    r = simulate(m, history(5.0), now=600, start=0, horizon_s=600, step_s=15)
    assert r["stocks"]["q"]["no_projection"] == "worse than holding" and "band" not in r["stocks"]["q"]
    m.stocks[0].evidence = {"hidden": True}
    assert simulate(m, history(5.0), now=600, start=0, horizon_s=600, step_s=15)["stocks"]["q"]["no_projection"] == "no level measured"
    m.stocks[0].evidence = {}
    r = simulate(m, history(5.0), now=600, start=0, horizon_s=600, step_s=15)
    assert r["stocks"]["q"]["no_projection"] is None and r["stocks"]["q"]["trust"] is None and r["stocks"]["q"]["band"] == [], "trust not measured: no band"
