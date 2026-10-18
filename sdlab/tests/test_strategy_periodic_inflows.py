"""Mechanism test for the periodic_inflows strategy (docs/research/periodic-inflows.md).

A chain a -> b -> c (0.2, 0.1, 0.05), a fed from outside on a 24-step day (4 / 12 / 9 an hour), each
day's level scaled by its own factor in 0.8..1.2; 2000 steps, counting noise.

The main line (`matrix`) cannot follow the day with pieces (its change scan finds 56 in 2000 steps,
for about 250 changes): it reads part of a's intake as dynamics (a -> b at 0.172, "a drains faster
when b is high" at 0.107, and a link a -> b), and its model runs away: skill@20 about -460%.
The strategy finds the 24-step period, keeps a's drain within 0.02 of the truth with no outside
inflow into b or c, and behaves as the truth. Control: the same intake changing at random times has
no period, and the strategy gives the main line's result.
"""

from __future__ import annotations

import random

import pytest
from synth import generate, skill

from sdlab.discovery.strategies import load


def chain(random_times: bool, steps: int = 2000, seed: int = 3) -> dict:
    rng = random.Random(seed)
    changes = []
    if random_times:
        t = 1
        while t <= steps:
            changes.append({"t": t, "set": {"in": {"form": "constant", "value": rng.choice([4, 12, 9]) * rng.uniform(0.8, 1.2)}}})
            t += rng.randint(3, 30)
    else:
        for d in range(steps // 24 + 1):
            f = rng.uniform(0.8, 1.2)
            for phase, v in ((1, 4), (7, 12), (17, 9)):
                changes.append({"t": 24 * d + phase, "set": {"in": {"form": "constant", "value": round(v * f, 3)}}})
    stocks = [{"id": "a", "initial": 50}, {"id": "b", "initial": 40}, {"id": "c", "initial": 30}]
    flows = [{"id": "in", "from": None, "to": "a", "rate": {"form": "constant", "value": 8}},
             {"id": "ab", "from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.2}},
             {"id": "bc", "from": "b", "to": "c", "rate": {"form": "proportional", "stock": "b", "k": 0.1}},
             {"id": "co", "from": "c", "to": None, "rate": {"form": "proportional", "stock": "c", "k": 0.05}}]
    return generate(stocks, flows, steps, schedule={"every": steps + 10, "changes": changes})


def find(r, src, dst, driver=None):
    return [f for f in r["flows"] if f["from"] == src and f["to"] == dst and f.get("driver") == driver]


@pytest.fixture(scope="module")
def daily():
    d = chain(random_times=False)
    return d, load("matrix")(d["stocks"], d["run"], {}), load("periodic_inflows")(d["stocks"], d["run"], {})


def test_the_main_line_reads_a_daily_intake_as_dynamics_and_runs_away(daily):
    d, base, _ = daily
    pieces = find(base, None, "a")[0]["changes"] + 1
    assert pieces < 100                                                    # far fewer than the ~250 changes
    assert find(base, "a", None, driver="b")                              # "a drains faster when b is high"
    assert skill(base, d) < 0


def test_the_strategy_finds_the_day_and_recovers_the_chain(daily):
    d, base, r = daily
    assert r["periods"]["a"]["period"] == 24
    assert set(r["periods"]) == {"a"}
    ab = find(r, "a", "b")
    assert len(ab) == 1 and abs(ab[0]["rate"]["k"] - 0.2) <= 0.02
    assert not find(r, None, "b") and not find(r, None, "c")
    assert not [f for f in r["flows"] if f.get("driver")]
    assert skill(r, d) >= max(0.9, skill(base, d))
    assert skill(r, d, 100) >= 0.9


def test_an_intake_changing_at_random_times_has_no_period_and_gets_the_main_line_result():
    d = chain(random_times=True)
    base = load("matrix")(d["stocks"], d["run"], {})
    r = load("periodic_inflows")(d["stocks"], d["run"], {})
    assert r["periods"] == {}
    assert r["flows"] == base["flows"]
