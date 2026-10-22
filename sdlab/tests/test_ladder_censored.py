"""The censored strategy: a floored link and a capped demand are recovered in their real form, on
synthetic rows and on ladder rungs 024 (floor binds) and 025 (runs empty), and a plain linear case
is left as the main line found it."""

import numpy as np
import pytest

from sdlab.discovery.strategies import censored
from sdlab.discovery.strategies.censored import cap, floor
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, score


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def test_hinge_search_finds_the_floor():
    rng = np.random.default_rng(1)
    a = np.concatenate([np.full(50, 50.0), np.linspace(50, 200, 50), np.full(100, 200.0), np.linspace(200, 50, 50)]) + rng.normal(0, 1, 250)
    b = rng.uniform(0, 100, 250)
    y = np.maximum(0.0, 30 - 0.25 * a) - 0.1 * b
    fits = floor.search(y, np.array([a, b]), 1, [0])
    best = min(fits, key=lambda f: f["rss"])
    best["i"] = 1
    assert best["j"] == 0 and best["s"] == -1.0
    assert best["theta"] == pytest.approx(120, rel=0.01)
    flows = floor.as_flows(best, ["A", "B"])
    link = next(f for f in flows if f["from"] is None)
    assert link["rate"]["c"] == pytest.approx(30, rel=0.01)
    assert link["rate"]["terms"][0]["k"] == pytest.approx(-0.25, rel=0.01)


def test_cap_profile_separates_demand_from_inflow():
    u = np.concatenate([np.full(100, 2.0), np.full(100, 10.0), np.full(100, 2.0)])
    x = [2.0]
    for k in range(299):
        x.append(x[-1] + u[k] - min(7.0, x[-1]))
    x = np.array(x)
    y = np.diff(x)
    z = np.zeros_like(y)
    fit = cap.search(x[:-1], y, z, z, 0.0, 1e-6)
    assert fit["D"] == pytest.approx(7, rel=0.01)
    assert fit["score"] < fit["plain"]


def run_case(case_id, variant):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    r = censored.identify(casemod.page_stocks(model), {"t": d["t"], "levels": d["levels"]}, {"eras": None})
    return r, score.equations(c, casemod.variant(c, variant)["noise"], model, r["flows"], d)


@pytest.mark.parametrize("variant", ["none-short", "counts-short"])
def test_floor_binds_rung(variant):
    r, s = run_case("024-floor-binds", variant)
    assert s["status"] == "pass", s["parts"]
    assert any("floor on A into B" in x["rewrite"] for x in r["censored"])


@pytest.mark.parametrize("variant", ["none-short", "counts-short"])
def test_runs_empty_rung(variant):
    r, s = run_case("025-runs-empty", variant)
    assert s["status"] == "pass", s["parts"]
    assert any(x["rewrite"].startswith("demand") for x in r["censored"])


def test_linear_case_is_left_alone():
    r, s = run_case("003-chain-2", "none-short")
    assert s["status"] == "pass"
    assert not any("floor" in x["rewrite"] or "demand" in x["rewrite"] for x in r["censored"])


# measured inputs (opts "inputs"): a flow on an input is a column of every fit and moves what the
# input says in every simulation, so its effect is in the model once (before the fix, censored
# stepped its models without the inputs and counted the pump, or the outside temperature, twice)

def _input_cell(case_id, variant):
    from sdlab.ladder import runner

    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    return c, model, d, runner.discover("censored", model, d)


@pytest.mark.parametrize("variant", ["none-long", "counts-long"])
def test_a_measured_pump_is_read_once(variant):
    c, model, d, r = _input_cell("062-tank-fed-by-measured-pump", variant)
    s = score.equations(c, casemod.variant(c, variant)["noise"], model, r["flows"], d)
    assert s["status"] == "pass", r["flows"]
    pump = [f for f in r["flows"] if f.get("to") == "T" and "pump" in str(f.get("rate"))]
    assert len(pump) == 1 and pump[0]["rate"]["terms"][0]["k"] == pytest.approx(2.0, rel=0.03)
    assert not any(f.get("to") == "T" and f.get("inflow") for f in r["flows"]), "no outside pieces beside the pump"


def test_cooling_to_a_measured_outside_temperature_is_read_once():
    from sdlab.ladder import physics

    c, _, d, r = _input_cell("phys-newton-cooling", "none-long")
    s = physics.score_found(c, "none-long", r["flows"], d, data.load(c, "none-long", fresh=True))
    assert s["status"] == "pass", r["flows"]
    drain = sum(f["rate"]["k"] for f in r["flows"] if f.get("from") == "T" and (f.get("rate") or {}).get("stock") == "T")
    warm = sum(t["k"] for f in r["flows"] if f.get("to") == "T" for t in (f.get("rate") or {}).get("terms") or [] if t["stock"] == "outside")
    assert drain == pytest.approx(warm, rel=0.05), "one k: the body warms toward the outside as fast as it cools"


def test_floored_gap_to_a_measured_target():
    """125: hiring k x desired - k x R, floored at 0, beside a drain 0.025 R (the floor tells the gap's
    R term from the drain)."""
    c = casemod.load("125-floored-gap-to-measured-target")
    model = casemod.truth_model(c, "none-short")
    d = data.load(c, "none-short")
    opts = {"eras": None, "inputs": {k: list(v) for k, v in d["inputs"].items()}}
    r = censored.identify(casemod.page_stocks(model), {"t": d["t"], "levels": d["levels"]}, opts)
    s = score.equations(c, "none", model, r["flows"], d)
    assert s["status"] == "pass", s["parts"]
    assert any(x["rewrite"].startswith("gap") for x in r["censored"])


def _run_inputs(case_id, variant):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    opts = {"eras": None, "inputs": {k: list(v) for k, v in d["inputs"].items()}}
    r = censored.identify(casemod.page_stocks(model), {"t": d["t"], "levels": d["levels"]}, opts)
    return r, score.equations(c, casemod.variant(c, variant)["noise"], model, r["flows"], d)


@pytest.mark.parametrize("case_id", ["218-distilled-controller-floored-on-few-steps", "200-control-p-room-heater"])
def test_a_controller_floored_on_a_few_steps(case_id):
    """218: floored on 1 step of 300; 200: the same beside a second inflow on the outdoor temperature
    (a side column of the gap)."""
    r, s = _run_inputs(case_id, "none-short")
    assert s["status"] == "pass", s["parts"]
    assert any(x["rewrite"].startswith("gap") for x in r["censored"])


def test_an_exact_integral_among_counted_stocks():
    """216 counts-long: the integral's change is exactly setpoint - Y; its inflow is 1 x r, not a
    constant at r's mean with pieces."""
    r, s = _run_inputs("216-distilled-exact-integral-fed-by-stepping-input", "counts-long")
    # the exact-row rewrite fires only when the main line missed it; since the main line earns its
    # pieces (earned.py, docs/research/k8s-302.md) it finds 1 x r itself and the rewrite has nothing to do
    into_i = [f for f in r["flows"] if f.get("to") == "I"]
    assert len(into_i) == 1 and into_i[0]["rate"]["terms"] == [{"stock": "r", "k": 1.0}]


# the kubernetes climb's post-stages (censored/post/, copied from structures at dd9d8d1; docs/research/fixes/port-censored.md)

def _k8s(case_id, variant="none-short"):
    from sdlab.ladder import runner

    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = {**data.load(c, variant), **casemod.announced(c)}
    r = runner.discover("censored", model, d)
    return r, score.equations(c, casemod.variant(c, variant)["noise"], model, r["flows"], d)


def test_hpa_controller_is_written_as_its_rule():
    """308: ready's outside sides are the HPA's discrete rule (controller.py), not linear drifts."""
    r, s = _k8s("308-k8s-hpa")
    assert s["status"] == "pass", s["parts"]
    assert any("ceil(cpu" in str((f.get("rate") or {}).get("expr")) for f in r["flows"] if f.get("to") == "ready")


def test_pod_floors_and_no_false_min():
    """309: the source-row guard refuses MIN(desired, ready) (capmin.py), and the floored gaps are fitted (floor.py)."""
    r, s = _k8s("309-k8s-pod-startup")
    assert s["status"] == "pass", s["parts"]
    assert not any("capmin__desired" in str(f.get("rate")) for f in r["flows"])


def test_inflow_pieces_are_read_as_their_pieces():
    """A flow in pieces carries a placeholder rate: the post-stages read its pieces at the step times (311
    none-long: ready's scale-down and the counter's inflow in pieces), or nothing when the times are unknown."""
    from sdlab.discovery.strategies.censored.post import steps
    from sdlab.discovery.strategies.censored.post.hidden import _amount

    f = {"from": None, "to": "A", "rate": {"form": "constant", "value": 20.0},
         "inflow": [{"from": 0, "to": 5, "value": 10.0}, {"from": 5, "to": 9, "value": 40.0}]}
    steps.TIMES = None
    assert _amount(f, {"A": np.ones(9)}, 9) is None
    steps.adjust({}, {}, {"t": list(range(10))}, {}, 9)
    assert list(_amount(f, {"A": np.ones(9)}, 9)) == [10.0] * 4 + [40.0] * 5   # (the first piece covering t, as simulate._Segments)
