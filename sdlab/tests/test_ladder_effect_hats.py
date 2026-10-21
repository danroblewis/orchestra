"""Strategy effect_hats (sdlab/discovery/strategies/effect_hats): tent bases behave like SD Lab's
table effects, the joint refit recovers a model's numbers exactly without noise, pooled inflows
are re-cut where the inflow changes, and the strategy recovers the ladder's linear and table
effects (017, 018) without noise while adding none to a plain chain."""

import numpy as np
import pytest

from sdlab.discovery.strategies import effect_hats
from sdlab.discovery.strategies.effect_hats import basis, joint, pieces
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, runner, score
from sdlab.runner import effect_value


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def run_case(case_id, variant):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = {**data.load(c, variant), **casemod.announced(c)}   # as the runner announces it (a declared boundary)
    r = runner.discover("effect_hats", model, d)
    return r, score.equations(c, casemod.variant(c, variant)["noise"], model, r["flows"], d)


def test_tents_sum_to_one_and_match_a_table_effect():
    kn = np.array([10.0, 30.0, 60.0])
    w = np.array([0.5, 1.0, 1.6])
    x = np.linspace(0, 80, 41)
    H = basis.hats(x, kn)
    assert np.allclose(H.sum(axis=0), 1.0)
    table = {"stock": "C", "shape": "table", "points": [[a, b] for a, b in zip(kn, w)]}
    want = [effect_value(table, {"C": v}) for v in x]
    assert np.allclose(basis.curve(x, kn, w), want)


def test_joint_refit_recovers_a_move_with_a_table_effect_exactly():
    rng = np.random.default_rng(0)
    T = 400
    C = 50 + 20 * np.sin(np.arange(T + 1) / 15)
    A = np.zeros(T + 1)
    B = np.zeros(T + 1)
    kn = np.array([30.0, 50.0, 70.0])
    w = np.array([0.2, 0.3, 0.42])                   # 0.3 x table(C) through (30, 0.67), (50, 1), (70, 1.4)
    for i in range(T):
        move = A[i] * basis.curve(np.array([C[i]]), kn, w)[0]
        A[i + 1] = A[i] + 10 - move
        B[i + 1] = B[i] + move - 0.2 * B[i]
    run = {"t": list(range(1, T + 2)), "levels": {"A": list(A), "B": list(B), "C": list(C + 0 * rng.random(T + 1))}}
    start = [
        {"from": None, "to": "A", "rate": {"form": "constant", "value": 7.0}},
        {"from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 1.0},
         "hat": {"stock": "C", "knots": list(kn), "weights": [1.0, 1.0, 1.0]}},
        {"from": "B", "to": None, "rate": {"form": "proportional", "stock": "B", "k": 0.5}},
    ]
    fl, info = joint.refit(start, ["A", "B", "C"], run)
    assert fl[0]["rate"]["value"] == pytest.approx(10, rel=1e-6)
    assert fl[2]["rate"]["k"] == pytest.approx(0.2, rel=1e-6)
    assert np.allclose(fl[1]["hat"]["weights"], w, rtol=1e-6)
    assert info["rss"][:2].sum() < 1e-12


def test_pooled_inflow_is_recut_at_its_changes():
    rng = np.random.default_rng(3)
    T = 1000
    C = np.zeros(T + 1)
    C[0] = 40
    for i in range(T):
        C[i + 1] = C[i] + (3 if (i // 100) % 2 == 0 else 7) - 0.1 * C[i] + rng.normal(0, 0.3)
    run = {"t": list(range(1, T + 2)), "levels": {"C": list(C)}}
    tt = np.arange(2, T + 2)
    many = [{"from": int(a), "to": int(min(a + 24, T + 1)), "value": 5.0} for a in range(2, T + 2, 25)]
    flows = [{"from": None, "to": "C", "rate": {"form": "constant", "value": 5.0}, "inflow": many},
             {"from": "C", "to": None, "rate": {"form": "proportional", "stock": "C", "k": 0.2}}]
    out = pieces.resegment(flows, ["C"], run)
    values = sorted({round(g["value"], 1) for g in out[0]["inflow"]})
    assert values == pytest.approx([3.0, 7.0], abs=0.15)
    assert out[1]["rate"]["k"] == pytest.approx(0.1, rel=0.03)
    starts = [g["from"] for g in out[0]["inflow"]]
    assert all(min(abs(s - (101 + 100 * j)) for j in range(10)) <= 2 for s in starts[1:])
    assert len(starts) == 10 and tt[0] == starts[0]


@pytest.mark.parametrize("case_id", ["017-linear-effect", "018-table-effect"])
def test_recovers_the_ladder_effects_without_noise(case_id):
    r, s = run_case(case_id, "none-short")
    assert s["status"] == "pass", s
    effect_flows = [f for f in r["flows"] if f.get("effects")]
    assert [(f["from"], f["to"], f["effects"][0]["stock"]) for f in effect_flows] == [("A", "B", "C")]
    assert "hat" not in effect_flows[0]


def test_adds_no_effect_to_a_plain_chain():
    r, s = run_case("004-chain-3", "none-short")
    assert s["status"] == "pass"
    assert not any(f.get("effects") for f in r["flows"])


def test_options_from_the_environment(monkeypatch):
    monkeypatch.setenv("SDLAB_EFFECT_HATS_OPTS", '{"seg_base": false, "pool": false}')
    r, s = run_case("003-chain-2", "none-short")
    assert s["status"] == "pass"
    assert effect_hats.DEFAULTS["pool"] is True


# measured inputs (opts "inputs"): a flow on an input is a column of every fit and moves what the
# input says in every simulation, so its effect is in the model once (before the fix, effect_hats
# stepped its models without the inputs and counted the pump, or the outside temperature, twice)

def _input_cell(case_id, variant):
    from sdlab.ladder import runner

    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = {**data.load(c, variant), **casemod.announced(c)}   # as the runner announces it (a declared boundary)
    return c, model, d, runner.discover("effect_hats", model, d)


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
