"""Mechanism test for the `impulses` strategy (docs/research/impulse-inputs.md).

Doses arrive 450 at a time on one day a week, expire at 0.02 a day and are used by vaccination at
0.2 x the waiting list (bookings switch between 30 and 60 a day, unannounced, so the waiting list
moves). The change scan's pieces are at least 5 steps long, so the main line (`matrix`) cannot hold
a one-day delivery: its doses row drains ~0.3-0.7 a day and links the other stocks to make up the
deliveries, and the found model runs away (skill@20 about -20). Found as pulses, jointly with the
row's numbers, the deliveries are taken out of the row: the drain comes out at 0.02 and the model
behaves as the truth.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from synth import generate, skill  # noqa: E402

from sdlab.discovery.strategies import load  # noqa: E402
from sdlab.discovery.strategies.impulses import find_pulses  # noqa: E402


def doses(steps: int = 1000) -> dict:
    stocks = [{"id": "waiting", "initial": 225}, {"id": "done", "initial": 450}, {"id": "doses", "initial": 900, "unit": "doses"}]
    flows = [{"id": "book", "from": None, "to": "waiting", "rate": {"form": "constant", "value": 45}},
             {"id": "vacc", "from": "waiting", "to": "done", "rate": {"form": "proportional", "stock": "waiting", "k": 0.2}, "uses": [{"stock": "doses", "per": 1}]},
             {"id": "fu", "from": "done", "to": None, "rate": {"form": "proportional", "stock": "done", "k": 0.1}},
             {"id": "deliver", "from": None, "to": "doses", "rate": {"form": "constant", "value": 450}},
             {"id": "expire", "from": "doses", "to": None, "rate": {"form": "proportional", "stock": "doses", "k": 0.02}}]
    ch = []
    for k in range(20):
        ch.append({"t": 1 + 7 * k, "set": {"deliver": {"form": "constant", "value": 450}}})
        ch.append({"t": 2 + 7 * k, "set": {"deliver": {"form": "constant", "value": 0}}})
    ch += [{"t": 1, "set": {"book": {"form": "constant", "value": 30}}}, {"t": 71, "set": {"book": {"form": "constant", "value": 60}}}]
    return generate(stocks, flows, steps, schedule={"every": 140, "changes": ch})


@pytest.fixture(scope="module")
def data():
    return doses()


def drain(result: dict, stock: str) -> float:
    return -next(r for r in result["matrix"] if r["id"] == stock)["coef"].get(stock, 0.0)


def test_main_line_lets_the_drain_absorb_the_deliveries(data):
    r = load("matrix")(data["stocks"], data["run"], {})
    assert drain(r, "doses") > 0.2
    assert skill(r, data) < 0


def test_pulses_found_and_the_drain_recovered(data):
    found = find_pulses(data["stocks"], data["run"], {})
    # a delivery on step t (t = 1 + 7k) is the change into level index t - 1: known index t - 1
    T = len(data["run"]["t"])
    true = {7 * k for k in range(1, T) if 7 * k < T}
    got = set(np.nonzero(found.get("doses", np.zeros(0)))[0] + 1)
    assert len(got & true) >= 0.95 * len(true)
    assert len(got - true) <= 2
    assert set(found) == {"doses"}                        # nothing found in the other stocks
    r = load("impulses")(data["stocks"], data["run"], {})
    assert abs(drain(r, "doses") - 0.02) < 0.005
    assert skill(r, data) > 0.9
    assert skill(r, data, 100) > 0.9


def test_counting_noise_gives_no_pulses():
    d = generate([{"id": "a", "initial": 200}, {"id": "b", "initial": 20}],
                 [{"id": "in", "from": None, "to": "a", "rate": {"form": "constant", "value": 20}},
                  {"id": "out", "from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.1}},
                  {"id": "gone", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.5}},
                  {"id": "trickle", "from": None, "to": "b", "rate": {"form": "constant", "value": 1}}], 2000)
    assert find_pulses(d["stocks"], d["run"], {}) == {}


def test_a_level_shift_is_a_piece_not_pulses():
    d = generate([{"id": "a", "initial": 200}],
                 [{"id": "in", "from": None, "to": "a", "rate": {"form": "constant", "value": 20}},
                  {"id": "out", "from": "a", "to": None, "rate": {"form": "proportional", "stock": "a", "k": 0.5}}], 1000,
                 schedule={"every": 0, "changes": [{"t": 500, "set": {"in": {"form": "constant", "value": 60}}}]})
    assert find_pulses(d["stocks"], d["run"], {}) == {}
    r = load("impulses")(d["stocks"], d["run"], {})
    assert any(f.get("changes") for f in r["flows"])      # the change is in the outside inflow's pieces
    assert r["flows"] == load("matrix")(d["stocks"], d["run"], {})["flows"]   # no pulses: the main line's model
