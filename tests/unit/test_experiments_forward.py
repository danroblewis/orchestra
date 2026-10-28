"""The forward run (sd/experiments/forward.py): an experiment's draft and its base from the
measured levels now, with a band, the limits they meet and where not to trust them.

- on models with known solutions, an equation replaced by another form, a flow added that reads
  two stocks, a flow removed, a hidden stock added with an inflow and an outflow, and the delay
  and smooth functions follow the analytic solution (or an independent integration);
- on the bakery's model (``fixtures/sd/bakery-whatif.json.gz``: the conservation discovery of the
  bakery's export, round 6, over the hour before 1793046690, and the web server's history at its
  end), the base run is the model's own simulation (``sd.simulate``), and a faster bottleneck
  moves its stocks the way a reader expects;
- weak, declared, hidden and replayed parts are not trusted, and the band is the recorded error."""

import copy
import gzip
import json
import math
from pathlib import Path

import pytest
from experiment_systems import chain

from orchestra.sd.experiments.edits import apply
from orchestra.sd.experiments.forward import forward
from orchestra.sd.model import Equation, Flow, Model, Stock
from orchestra.sd.strategies import sd_installed

pytestmark = pytest.mark.skipif(not sd_installed(), reason="simulating needs orchestra[sd]")

BAKERY = Path(__file__).parent.parent / "fixtures" / "sd" / "bakery-whatif.json.gz"
C, K, L0 = 2.0, 0.1, 5.0           # per minute: in at C, out at K × the level


def queue(**quality) -> Model:
    q = {"events": 400.0, "dispersion": 1.0, **quality}
    return Model("m", "m", time_unit="minute", stocks=[Stock("q", "queue")],
                 flows=[Flow("in", "in", None, "q", equations=[Equation("constant", {"c": C}, "fitted", "poisson-mle", quality=dict(q))]),
                        Flow("out", "out", "q", None, equations=[Equation("proportional", {"k": K}, "fitted", "poisson-mle",
                                                                          inputs=["q"], quality=dict(q))])])


def history(level: float = L0, now: float = 3600.0, lo: float | None = None, hi: float | None = None, **extra) -> dict:
    pts = [[0.0, lo if lo is not None else level], [now / 2, hi if hi is not None else level], [now, level]]
    return {"at": now, "start": 0.0, "stocks": {"q": pts}, "flows": {}, "inputs": {}, **extra}


def edited(m: Model, *edits, scenario=None):
    d = apply(m, scenario or {}, m, list(edits), "x-000000000000", "tester")
    return d.model, d.scenario


def run(m: Model, h: dict, *edits, **kw) -> dict:
    draft, scenario = edited(m, *edits)
    return forward(m, draft, h, scenario, **{"members": 0, **kw})


def analytic(c: float, k: float, l0: float, t_s: float) -> float:
    return c / k + (l0 - c / k) * math.exp(-k * t_s / 60)


@pytest.mark.parametrize(("edit", "c", "k", "l0"), [
    ({"op": "set_params", "flow": "in", "params": {"c": 3.0}}, 3.0, K, L0),
    ({"op": "replace_flow", "id": "out", "equation": "k * q", "params": {"k": 0.2}}, C, 0.2, L0),
    ({"op": "replace_flow", "id": "in", "equation": "c + 1", "params": {"c": C}}, C + 1, K, L0),
    ({"op": "set_level", "stock": "q", "level": 40.0}, C, K, 40.0),
])
def test_one_stock_with_an_inflow_and_a_proportional_outflow_follows_its_analytic_solution(edit, c, k, l0):
    r = run(queue(), history(), edit, horizon_s=3600, step_s=1)
    s = r["stocks"]["q"]
    for t, base, changed in zip(r["t"], s["base"]["central"], s["experiment"]["central"]):
        assert base == pytest.approx(analytic(C, K, L0, t), rel=2e-3, abs=1e-3)
        assert changed == pytest.approx(analytic(c, k, l0, t), rel=2e-3, abs=1e-3)
    assert s["difference"]["central"][-1] == pytest.approx(analytic(c, k, l0, 3600) - analytic(C, K, L0, 3600), abs=0.05)


def test_an_equation_replaced_by_another_form_follows_its_analytic_solution():
    # the outflow k q replaced by a quadratic one, k q²: dq/dt = C − k q², whose solution is
    # q = a tanh(√(C k) t + atanh(q0 / a)) with a = √(C / k)
    k = 0.01
    r = run(queue(), history(), {"op": "replace_flow", "id": "out", "equation": "k * q ** 2", "params": {"k": k}}, horizon_s=3600, step_s=1)
    a = math.sqrt(C / k)
    for t, v in zip(r["t"], r["stocks"]["q"]["experiment"]["central"]):
        assert v == pytest.approx(a * math.tanh(math.sqrt(C * k) * t / 60 + math.atanh(L0 / a)), rel=2e-3, abs=1e-3)
    # and a capped one, min(k q, cap): it drains at the cap, 1 a minute, until k q falls under it
    r = run(queue(), history(level=30.0), {"op": "replace_flow", "id": "out", "equation": "min(k * q, cap)",
                                         "params": {"k": K, "cap": 1.0}}, horizon_s=600, step_s=1)
    for t, v in zip(r["t"], r["stocks"]["q"]["experiment"]["central"]):
        assert v == pytest.approx(30.0 + (C - 1.0) * t / 60, abs=1e-3), "above 10, k q is over the cap: C − 1 a minute"


def euler(rates, levels: dict, minutes: float, step_min: float) -> dict:
    """An independent integration: every rate from the levels at the start of the step, floored at 0."""
    L = dict(levels)
    for _ in range(round(minutes / step_min)):
        moves = [(src, dst, max(0.0, f(L)) * step_min) for src, dst, f in rates]
        for src, dst, a in moves:
            if src:
                L[src] -= a
            if dst:
                L[dst] += a
    return L


def chain_history(levels=None) -> dict:
    lv = levels or {"queue": 6.0, "ready": 20.0}
    return {"at": 3600.0, "start": 0.0, "stocks": {s: [[0.0, v], [3600.0, v]] for s, v in lv.items()}, "flows": {}, "inputs": {}}


def test_a_flow_added_that_reads_two_stocks_simulates_as_integrated():
    m = chain()
    r = run(m, chain_history(), {"op": "add_flow", "id": "back", "from": "ready", "to": "queue",
                                 "equation": "k * min(queue, ready / 4)", "params": {"k": 0.2}}, horizon_s=1800, step_s=5)
    want = euler([(None, "queue", lambda L: 3.0), ("queue", "ready", lambda L: 0.5 * L["queue"]), (None, "ready", lambda L: 3.0),
                  ("ready", None, lambda L: 0.3 * L["ready"]), ("ready", "queue", lambda L: 0.2 * min(L["queue"], L["ready"] / 4))],
                 {"queue": 6.0, "ready": 20.0}, 30, 5 / 60)
    for sid in ("queue", "ready"):
        assert r["stocks"][sid]["experiment"]["central"][-1] == pytest.approx(want[sid], abs=1e-3)
    assert r["stocks"]["queue"]["experiment"]["central"][-1] > 6.2, "the new flow carries work back"
    assert r["changed"] == ["back"] and r["flows"]["back"]["base"] is None and r["flows"]["back"]["experiment"]["central"][0] > 0


def test_a_flow_removed_simulates_as_its_analytic_solution():
    r = run(chain(), chain_history(), {"op": "remove_flow", "id": "side"}, horizon_s=1800, step_s=1)
    # without the side supply, ready drains toward 3 / 0.3 = 10: ready = 10 + 10 e^(−0.3 t)
    for t, v in zip(r["t"], r["stocks"]["ready"]["experiment"]["central"]):
        assert v == pytest.approx(10 + 10 * math.exp(-0.3 * t / 60), rel=2e-3, abs=2e-3)
    assert r["stocks"]["queue"]["experiment"]["central"][-1] == pytest.approx(6.0, abs=1e-6)
    assert r["flows"]["side"]["experiment"] is None


def test_a_hidden_stock_added_with_an_inflow_and_an_outflow_simulates_and_is_not_trusted():
    r = run(chain(), chain_history(), {"op": "add_stock", "id": "buffer", "initial": 5.0},
            {"op": "add_flow", "id": "fill", "from": None, "to": "buffer", "equation": "c", "params": {"c": 1.0}},
            {"op": "add_flow", "id": "empty", "from": "buffer", "to": None, "equation": "k * buffer", "params": {"k": 0.1}},
            horizon_s=3600, step_s=1)
    b = r["stocks"]["buffer"]
    for t, v in zip(r["t"], b["experiment"]["central"]):
        assert v == pytest.approx(10 - 5 * math.exp(-0.1 * t / 60), rel=2e-3, abs=2e-3)
    assert b["base"] is None and b["difference"] is None and b["start"] == {"base": None, "experiment": 5.0}
    assert not b["trusted"] and any(w.startswith("hidden: no series measures it; it starts at 5") for w in b["why"])


def test_delay_and_smooth_follow_a_step_in_an_input():
    m = Model("m", "m", time_unit="minute", stocks=[Stock("q", "queue")],
              flows=[Flow("in", "in", None, "q", equations=[Equation("proportional", {"k": 1.0}, "fitted", inputs=["input:demand"],
                                                                      quality={"events": 400.0})])])
    m.discovery = {"inputs": {"demand": {"name": "demand", "labels": {}}}}
    h = history(inputs={"demand": [[0.0, 2.0], [3600.0, 2.0]]})
    step = {"op": "set_input", "input": "demand", "scenario": {"kind": "step", "at_s": 600, "value": 4.0}}
    r = run(m, h, step, {"op": "replace_flow", "id": "in", "equation": "delay(demand, 10)"}, horizon_s=1800, step_s=1)
    for t, v in zip(r["t"], r["stocks"]["q"]["experiment"]["central"]):
        want = L0 + 2 * t / 60 if t <= 1200 else L0 + 40 + 4 * (t - 1200) / 60
        assert v == pytest.approx(want, abs=0.1), "the step reaches the flow ten minutes late"
    r = run(m, h, step, {"op": "replace_flow", "id": "in", "equation": "smooth(demand, 10)"}, horizon_s=1800, step_s=1, points=181)
    for t, v in zip(r["t"], r["flows"]["in"]["experiment"]["central"]):
        want = 2.0 if t <= 600 else 4 - 2 * math.exp(-(t - 600) / 600)
        assert v == pytest.approx(want, abs=0.02)
    assert r["flows"]["in"]["base"]["central"][-1] == pytest.approx(2.0), "the base holds the input at its last value"


def test_the_band_comes_from_the_recorded_error_and_holds_the_central_run():
    up = {"op": "set_params", "flow": "in", "params": {"c": 3.0}}
    sure = run(queue(events=10_000.0), history(), up, horizon_s=3600, members=64)
    loose = run(queue(events=25.0), history(), up, horizon_s=3600, members=64)
    assert loose["band"]["spread"]["out"]["rel"] == pytest.approx(1 / 5)          # sqrt(1 / 25 events)
    assert loose["band"]["spread"]["in"]["rel"] == 0.5, "the experiment's equation is declared: ±50% until it is fitted"
    width = lambda r, side: r["stocks"]["q"][side]["hi"][-1] - r["stocks"]["q"][side]["lo"][-1]
    assert width(loose, "base") > 5 * width(sure, "base") > 0
    for r in (sure, loose):
        for side in ("base", "experiment", "difference"):
            b = r["stocks"]["q"][side]
            assert b["lo"][-1] <= b["central"][-1] <= b["hi"][-1]
    assert run(queue(events=25.0), history(), up, horizon_s=3600, members=64) == loose, "seeded: the same question, the same answer"


def test_a_stock_drained_below_zero_meets_its_floor():
    r = run(queue(), history(), {"op": "replace_flow", "id": "in", "equation": "0"},
            {"op": "replace_flow", "id": "out", "equation": "k * q + d", "params": {"k": K, "d": 1.0}}, horizon_s=3600, step_s=15,
            bounds={"q": (2.0, None)})
    floor = next(x for x in r["limits"] if x["run"] == "experiment" and x["kind"] == "floor")
    # out at 0.1 q + 1 per minute, nothing in: q = (L0 + 10) e^(−0.1 t) − 10 reaches 0 at t = 10 ln(1.5) min
    assert floor["at_s"] == pytest.approx(600 * math.log(1.5), abs=20) and floor["new"]
    assert min(r["stocks"]["q"]["experiment"]["central"]) == 0.0
    below = next(x for x in r["limits"] if x["run"] == "experiment" and x["kind"] == "below bound")
    assert below["bound"] == 2.0 and below["at_s"] < floor["at_s"]
    assert not any(x["run"] == "base" for x in r["limits"])


def test_leaving_the_observed_range_is_extrapolation():
    r = run(queue(), history(level=20.0, lo=15.0, hi=25.0), {"op": "set_params", "flow": "in", "params": {"c": 6.0}}, horizon_s=7200)
    s = r["stocks"]["q"]
    assert not s["trusted"] and any(w.startswith("extrapolation: leaves the observed range 15–25") for w in s["why"])


@pytest.mark.parametrize(("change", "says"), [
    (lambda m: setattr(m.flows[0].equations[0], "origin", "declared"), "declared: an assumption"),
    (lambda m: [f.equations[0].quality.update(events=6.0) for f in m.flows], "fitted on 6 events"),
    (lambda m: m.flows[0].equations[0].quality.update(r2=0.2, stretches=40.0), "fitted at R² 0.20"),
    (lambda m: m.flows[0].evidence.update(net_flow_of="q"), "a net flow"),
    (lambda m: setattr(m.flows[0], "equations", []), "replayed"),
])
def test_a_weak_or_declared_equation_is_not_trusted(change, says):
    m = queue()
    change(m)
    assert run(queue(), history(lo=0.0, hi=25.0), {"op": "set_level", "stock": "q", "level": 5.0}, horizon_s=600)["trusted"]
    r = run(m, history(lo=0.0, hi=25.0), {"op": "set_level", "stock": "q", "level": 5.0}, horizon_s=600)
    assert not r["trusted"] and not r["stocks"]["q"]["trusted"]
    flow = next(x for x in r["not_trusted"] if x["kind"] == "flow")
    assert flow["id"] == "in" and any(says in w for w in flow["why"])


def test_a_model_that_misses_its_own_history_is_not_trusted():
    h = history()
    h["stocks"]["q"] = [[t, 5.0 + 4 * math.sin(t / 300)] for t in range(0, 3601, 15)]
    r = forward(queue(), queue(), h, horizon_s=600)
    assert any("misses its measured level" in w for w in r["stocks"]["q"]["why"]) and not r["trusted"]


def test_bad_questions_say_what_is_wrong():
    with pytest.raises(ValueError, match="no stock"):
        forward(queue(), queue(), history(), stocks=["nope"])
    with pytest.raises(ValueError, match="horizon"):
        forward(queue(), queue(), history(), horizon_s=0)


# the bakery

def bakery() -> tuple[Model, dict]:
    with gzip.open(BAKERY, "rt") as fh:
        d = json.load(fh)
    return Model.from_json(d["model"]), d["history"]


def test_on_the_bakery_the_base_run_is_the_models_own_simulation_and_a_draft_runs_as_its_equations_say():
    from orchestra.sd.simulate import simulate

    m, h = bakery()
    r = run(m, h, {"op": "set_params", "flow": "bakery_orders_baked_total", "params": {"k": 1.5 * 1.004081}},
            horizon_s=1800, step_s=15, points=0)
    same = simulate(m, h, now=h["at"], start=h["start"], horizon_s=1800, step_s=15)["projection"]
    changed = copy.deepcopy(m)
    changed.flow("bakery_orders_baked_total").current().params["k"] *= 1.5
    faster = simulate(changed, h, now=h["at"], start=h["start"], horizon_s=1800, step_s=15)["projection"]
    for sid, s in r["stocks"].items():
        assert s["base"]["central"] == pytest.approx([v for _, v in same[sid]], abs=1e-3)
        assert s["experiment"]["central"] == pytest.approx([v for _, v in faster[sid]], abs=1e-3)


def test_on_the_bakery_a_faster_bottleneck_moves_its_stocks_as_a_reader_expects():
    m, h = bakery()
    # orders pile up waiting: assigning them to bakers half as fast again empties the waiting queue
    # and, at first, fills the ovens; written as a whole new equation, not a scaling
    r = run(m, h, {"op": "replace_flow", "id": "bakery_orders_assigned_total", "equation": "1.5 * (c + k * bakery_shelf_items)",
                   "params": {"c": 3.330217, "k": -0.73954}}, horizon_s=1800, stocks=["bakery_orders_waiting", "bakery_orders_baking"],
            members=24)
    waiting, baking = (r["stocks"][s]["difference"] for s in ("bakery_orders_waiting", "bakery_orders_baking"))
    assert waiting["central"][-1] < 0 and max(waiting["central"]) <= 1e-9
    assert r["band"]["spread"]["bakery_orders_assigned_total"]["rel"] == 0.5, "a declared equation's band is wide: ±50%"
    assert max(baking["central"][:5]) > 0.1
    rate = r["rates_now"]["bakery_orders_assigned_total"]
    assert rate["experiment"] == pytest.approx(1.5 * rate["base"], rel=1e-3)
    weak = {x["id"]: x["why"] for x in r["not_trusted"] if x["kind"] == "flow"}
    assert any(w.startswith("declared") for w in weak["bakery_orders_assigned_total"]), "the new equation is an assumption"
