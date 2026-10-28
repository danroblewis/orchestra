"""The model's own events (goal G12): a structure change announced once it holds, and a system
pushed off its prediction announced as diverged, then returned."""

import pytest

from orchestra.sd.announce import announce
from orchestra.sd.loops import loops
from orchestra.sd.model import Equation, Flow, Model, Stock
from orchestra.sd.store import ModelStore
from orchestra.sd.strategies import sd_installed

T = 1_800_000_000.0


def eq(form="constant", params=None, inputs=None):
    return Equation(form, params or {"c": 1.0}, "fitted", "poisson-mle", quality={"events": 2000.0, "dispersion": 1.0},
                    inputs=inputs or [])


def model(extra: bool = False) -> Model:
    stocks = [Stock("q", "q", evidence={"balance": []})]
    flows = [Flow("in", "in", None, "q", None, [eq()])]
    if extra:
        stocks.append(Stock("r", "r", evidence={"balance": []}))
        flows.append(Flow("move", "move", "q", "r", None, [eq("proportional", {"k": 0.1}, ["q"])]))
    return Model("system", "s", time_unit="minute", stocks=stocks, flows=flows)


def run(tmp_path, seq, **kw):
    store, said = ModelStore.for_state(tmp_path), []
    opts = {"hold": 3, "gap_s": 0.0, "after_s": 600.0, "every_s": 300.0, **kw}
    for i, m in enumerate(seq):
        announce(store, lambda ty, data: said.append((ty, data)), m, T + 300 * i, None, **opts)
    return said


def test_a_structure_change_is_announced_once_after_it_holds(tmp_path):
    said = run(tmp_path, [model(), model(True), model(True), model(True), model(True), model(True)])
    assert [ty for ty, _ in said] == ["orchestra.model.changed"]
    data = said[0][1]
    assert data["added"] == {"stocks": ["r"], "flows": ["move"], "loops": []} and data["removed"] == {"stocks": [], "flows": [], "loops": []}
    assert data["held"] == 3 and data["first_seen"] == T + 300


def test_churn_within_the_hold_announces_nothing(tmp_path):
    assert run(tmp_path, [model(), model(True), model(True), model(), model(True), model(), model(True), model(True)]) == []


def test_announcements_keep_their_gap(tmp_path):
    seq = [model(), model(True), model(True), *[model()] * 6]
    said = run(tmp_path, seq, hold=2, gap_s=1500.0)
    assert [d["added"]["stocks"] or d["removed"]["stocks"] for _, d in said] == [["r"], ["r"]]
    assert said[1][1]["removed"]["stocks"] == ["r"] and said[1][1]["held"] == 5, "the removal waited for the gap, still held, then was announced"


def test_loops_are_cycles_of_influence():
    m = model(True)
    m.flows.append(Flow("back", "back", "r", "q", None, [eq("proportional", {"k": 0.2}, ["r"])]))
    assert [x["id"] for x in loops(m)] == ["loop:q+r"]
    assert loops(model(True)) == []


def history(levels: list[tuple[float, float]], rate: float) -> dict:
    return {"at": levels[-1][0], "start": levels[0][0], "stocks": {"q": [[t, v] for t, v in levels]},
            "flows": {"in": [[t, rate] for t, _ in levels]}, "inputs": {}}


@pytest.mark.skipif(not sd_installed(), reason="the prediction steps SD Lab's simulator (orchestra[sd])")
def test_a_system_pushed_off_its_prediction_diverges_then_returns(tmp_path):
    # the model says one job a minute arrives; from T five a minute do, for 15 minutes; then one a minute again
    store, said = ModelStore.for_state(tmp_path), []
    level = lambda t: 100 + (t - T) / 60 * (5 if t <= T + 900 else 1) + (4 * 15 if t > T + 900 else 0)
    for k in range(9):
        now = T + 300 * k
        pts = [(t, level(t)) for t in range(int(T) - 600, int(now) + 1, 15)]
        rate = 5.0 if T < now <= T + 900 else 1.0
        announce(store, lambda ty, data, now=now: said.append((now, ty, data)), model(), now, history(pts, rate),
                 hold=3, gap_s=0.0, after_s=600.0, every_s=300.0, era_start=None)
    kinds = [(t - T, ty) for t, ty, _ in said]
    assert kinds[0] == (900.0, "orchestra.model.diverged"), kinds
    [d] = said[0][2]["stocks"]
    assert d["stock"] == "q" and d["gap"] > 2 and d["level"] > d["hi"] and said[0][2]["diverged"] == ["q"]
    assert [ty for _, ty in kinds] == ["orchestra.model.diverged", "orchestra.model.returned"], kinds
    back = said[1][2]
    assert back["stocks"][0]["stock"] == "q" and abs(back["stocks"][0]["gap"]) <= 1 and back["diverged"] == []


@pytest.mark.skipif(not sd_installed(), reason="the prediction steps SD Lab's simulator (orchestra[sd])")
def test_a_system_that_follows_its_prediction_says_nothing(tmp_path):
    store, said = ModelStore.for_state(tmp_path), []
    for k in range(8):
        now = T + 300 * k
        pts = [(t, 100 + (t - T) / 60) for t in range(int(T) - 600, int(now) + 1, 15)]
        announce(store, lambda ty, data: said.append(ty), model(), now, history(pts, 1.0),
                 hold=3, gap_s=0.0, after_s=600.0, every_s=300.0)
    assert said == []
