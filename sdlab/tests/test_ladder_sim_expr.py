"""skill@H runs a found expression rate (sdlab/ladder/sim.py found_model, _ExprRate): simulate.Model (pinned)
reads an 'expr' rate as 0, so a found MIN, the truth itself, used to score skill@20 below 0 on rung 306."""

import numpy as np

from sdlab.discovery.simulate import Model
from sdlab.ladder.sim import _quiet, found_model, says_expr
from sdlab.skill import same_behaviour

MIN = {"from": "q", "to": "w", "rate": {"form": "expr", "expr": "min(0.6 * q, 40 * cap)"}}


def test_expr_rate_is_evaluated_per_state():
    m = found_model([MIN], ["q", "w", "cap"])
    L = np.array([[100.0, 1000.0], [0.0, 0.0], [10.0, 10.0]])
    a = m._amounts(L, np.array([1.0, 1.0]))[0]
    assert np.allclose(a, [60.0, 400.0])                          # the demand, then the cap
    assert np.allclose(Model([MIN], ["q", "w", "cap"])._amounts(L, np.array([1.0, 1.0]))[0], 0)   # the pinned simulator: 0


def test_expr_reads_inputs_floors_and_byTime_segments():
    inputs = {"t": [0, 1, 2], "values": {"u": [5.0, -50.0, 5.0]}}
    f = {"from": None, "to": "q", "byTime": [{"from": 0, "to": 1, "rate": {"form": "expr", "expr": "2 * u"}},
                                              {"from": 2, "to": 9, "rate": {"form": "constant", "value": 3}}]}
    m = found_model([f], ["q"], inputs=inputs)
    L = np.zeros((1, 3))
    assert np.allclose(m._amounts(L, np.array([0.0, 1.0, 2.0]))[0], [10.0, 0.0, 3.0])   # floored at 0; the linear segment as before


def test_no_expr_unchanged():
    flows = [{"from": "q", "to": "w", "rate": {"form": "proportional", "stock": "q", "k": 0.5}}]
    assert not says_expr(flows) and type(found_model(flows, ["q", "w"])) is Model


def test_found_min_equal_to_truth_has_skill_one():
    truth = {"stocks": [{"id": "q", "initial": 10}, {"id": "w", "initial": 0}, {"id": "cap", "initial": 0.6}],
             "flows": [{"id": "in", "from": None, "to": "q", "rate": {"form": "constant", "value": 30}}, {**MIN, "id": "out"}],
             "steps": 80}
    run = _quiet(truth).run(steps=80)       # the cap (24 a step) binds once q passes 40
    data = {"t": list(range(len(run["levels"]["q"]))), "levels": run["levels"]}
    found = {"flows": [{"from": None, "to": "q", "rate": {"form": "constant", "value": 30}}, MIN]}
    assert min(run["levels"]["q"][-1], 0.6 * run["levels"]["q"][-1]) > 24
    assert same_behaviour(found, truth, data, horizon=20, starts=30)["skill"] > 0.999
