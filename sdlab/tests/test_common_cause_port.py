"""common_cause's port of the kubernetes climb's row and controller passes (docs/research/fixes/port-common_cause.md)."""

from sdlab.discovery.strategies.common_cause import tracker


def test_hidden_stage_is_an_outside_inflow():
    flows = [
        {"from": None, "to": "H", "rate": {"form": "constant", "c": 1.0}},
        {"from": "H", "to": "S", "rate": {"form": "proportional", "stock": "H", "k": 0.5}},
        {"from": None, "to": "S", "rate": {"form": "constant", "c": 2.0}},
        {"from": "S", "to": None, "rate": {"form": "proportional", "stock": "S", "k": 0.1}},
    ]
    assert tracker._stages("S", ["S"], flows) == {"H": [0, 1]}


def test_hidden_stock_with_other_partners_is_not_a_stage():
    flows = [
        {"from": None, "to": "H", "rate": {"form": "constant", "c": 1.0}},
        {"from": "H", "to": "S", "rate": {"form": "proportional", "stock": "H", "k": 0.5}},
        {"from": "H", "to": "Q", "rate": {"form": "proportional", "stock": "H", "k": 0.2}},
    ]
    assert tracker._stages("S", ["S", "Q"], flows) == {}


def test_a_smeared_move_is_carried_by_its_partners_outside_flow():
    """(fix ledger type 4) A move retries -> ready taken off ready's row merges into retries' own outflow."""
    import numpy as np

    flows = [
        {"from": "R", "to": "S", "ratio": 1, "rate": {"form": "proportional", "stock": "R", "k": 0.18}},
        {"from": "R", "to": None, "rate": {"form": "proportional", "stock": "R", "k": 0.22}},
    ]
    states = [{"R": 10.0, "S": 3.0, "__t": float(k + 1)} for k in range(5)]
    g = {"S": "S", "net": np.zeros(5), "base": np.zeros(5), "k_base": 0, "floor": 1e-9, "moved": [],
         "outside": {"in": [], "out": []}}
    got = tracker._moved(g, ["R", "S"], set(), np.zeros((2, 5)), None, states, flows, False, {})
    (n, A, side, m, rate), = got["moved"]
    assert (n, A, side, m) == (0, "R", "out", 1)
    assert rate == {"form": "proportional", "stock": "R", "k": 0.4}
    assert np.allclose(got["net"], 1.8)
