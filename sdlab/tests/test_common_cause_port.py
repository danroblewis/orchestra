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
