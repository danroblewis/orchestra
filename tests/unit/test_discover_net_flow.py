"""A level no counters balance is a stock when the other series explain its net flow (a room's
temperature pulled toward the weather outside, a backlog nobody counts filled by a demand),
and stays an input when nothing explains it better than a constant (a random walk), or when it
is another series measured again. It also stays an input when what explains it is only a smooth
series standing in for time (a tide against a power demand), when the driver is its own total, or
when the level is an average (a mean age), which summarises and does not store."""

import math
import random

import pytest

from orchestra.sd.discover import discover

T0 = 1_800_000_000.0
HOURS = 4


def _outside(rng: random.Random) -> list[tuple[float, float]]:
    """The weather outside, written every minute: a slow swing with some noise."""
    return [(T0 + 60 * i, round(10 + 6 * math.sin(i / 47) + 3 * math.sin(i / 13) + rng.gauss(0, 0.2), 2)) for i in range(HOURS * 60 + 1)]


def _room(outside: list[tuple[float, float]], rng: random.Random, k: float = 0.08) -> list[tuple[float, float]]:
    """A room whose temperature relaxes toward the outside's (Newton's cooling), written every minute."""
    t, out = 20.0, []
    for when, o in outside:
        t += k * (o - t) + rng.gauss(0, 0.05)
        out.append((when, round(t, 3)))
    return out


def test_a_level_pulled_toward_another_is_a_stock_with_a_fitted_net_flow():
    rng = random.Random(1)
    outside = _outside(rng)
    dump = [("outside_celsius", {"machine": "weather"}, outside), ("room_celsius", {"machine": "thermostat"}, _room(outside, rng))]
    m = discover(dump, start=T0, end=T0 + HOURS * 3600, step=5.0)
    [room] = [s for s in m.stocks if s.id == "room_celsius"]
    assert room.evidence["net_flow"]["driver"] == "input:outside_celsius"
    flows = {f.id: f for f in m.flows if f.evidence.get("net_flow_of") == "room_celsius"}
    inflow, outflow = flows["room_celsius_inflow"], flows["room_celsius_outflow"]
    assert (inflow.src, inflow.dst, outflow.src, outflow.dst) == (None, "room_celsius", "room_celsius", None)
    for f in (inflow, outflow):
        assert f.current().origin == "fitted" and f.current().method == "least-squares" and f.counter is None
    # the rate per minute is k × (outside − room): inflow k × outside, outflow k × room
    assert inflow.current().inputs == ["input:outside_celsius"]
    assert abs(inflow.current().params["k"] - 0.08) < 0.03
    assert abs(outflow.current().params["k"] - 0.08) < 0.03
    assert "outside_celsius" not in [s.id for s in m.stocks]          # the weather drifts on its own: nothing explains it
    assert "no other series explains its changes" in m.discovery["left_out"]['outside_celsius{machine="weather"}']


def test_a_random_walk_stays_an_input():
    rng = random.Random(2)
    v, walk = 50.0, []
    for i in range(HOURS * 60 + 1):
        v += rng.gauss(0, 1)
        walk.append((T0 + 60 * i, round(v, 3)))
    other = [(T0 + 60 * i, round(5 + rng.gauss(0, 1), 3)) for i in range(HOURS * 60 + 1)]
    m = discover([("price", {"machine": "feed"}, walk), ("noise", {"machine": "feed"}, other)], start=T0, end=T0 + HOURS * 3600, step=5.0)
    assert m.stocks == []
    why = m.discovery["left_out"]['price{machine="feed"}']
    assert why.startswith("no counters balance it") and "no other series explains its changes better than a constant" in why, why


def test_a_level_measured_twice_is_an_input_not_two_stocks():
    # the same room read by two collectors, one stamping a minute later than the other
    rng = random.Random(3)
    outside = _outside(rng)
    room = _room(outside, rng)
    again = [(t + 60, v) for t, v in room]
    dump = [("outside_celsius", {"machine": "weather"}, outside), ("room_celsius", {"machine": "thermostat"}, room),
            ("room_temperature", {"machine": "sensor"}, again)]
    m = discover(dump, start=T0, end=T0 + HOURS * 3600, step=5.0)
    assert m.stocks == []
    assert "the same quantity measured again" in m.discovery["left_out"]['room_temperature{machine="sensor"}']


def test_a_backlog_nobody_counts_is_filled_by_its_demand():
    # requests arrive at a rate a demand gauge says, and are worked off in proportion to what waits;
    # only the backlog's length is written (every 30 s), no counter of either
    rng = random.Random(4)
    demand, backlog, pts_d, pts_b = 4.0, 0.0, [], []
    for i in range(HOURS * 120 + 1):
        t = T0 + 30 * i
        demand = max(0.5, demand + rng.gauss(0, 0.25) + 0.05 * (4 - demand))
        backlog = max(0.0, backlog + 0.5 * demand - 0.1 * backlog + rng.gauss(0, 0.3))
        pts_d.append((t, round(demand, 3)))
        pts_b.append((t, round(backlog, 3)))
    m = discover([("demand_per_min", {"machine": "frontend"}, pts_d), ("backlog_length", {"machine": "queue"}, pts_b)],
                 start=T0, end=T0 + HOURS * 3600, step=5.0)
    assert [s.id for s in m.stocks] == ["backlog_length"]
    [inflow] = [f for f in m.flows if f.id == "backlog_length_inflow"]
    assert inflow.current().inputs == ["input:demand_per_min"] and inflow.current().params["k"] > 0
    assert any(f.id == "backlog_length_outflow" for f in m.flows)


@pytest.mark.parametrize("tide_phase,demand_phase", [(0.0, 1.5), (3.0, 1.5), (4.0, 3.0), (0.0, 4.5)])
def test_a_periodic_level_explained_by_a_smooth_series_stays_an_input(tide_phase, demand_phase):
    # a tide (12.4 h period) written every minute over 5 h, next to a power demand that swings once
    # a day, with noise enough to reverse in more than a tenth of the minutes: over a few hours both
    # move smoothly, so the demand fits the tide's rate well while causing none of it
    rng = random.Random(5)
    hours = 5
    tide = [(T0 + 60 * i, round(1.2 * math.sin(2 * math.pi * i / (12.4 * 60) + tide_phase), 3)) for i in range(hours * 60 + 1)]
    demand = [(T0 + 60 * i, round(25000 + 6000 * math.sin(2 * math.pi * i / (24 * 60) + demand_phase) + rng.gauss(0, 60), 1))
              for i in range(hours * 60 + 1)]
    m = discover([("tide_height_m", {"machine": "harbour"}, tide), ("power_demand_mw", {"machine": "grid"}, demand)],
                 start=T0, end=T0 + hours * 3600, step=5.0)
    assert "tide_height_m" not in [s.id for s in m.stocks]
    why = m.discovery["left_out"]['tide_height_m{machine="harbour"}']
    assert "no other series explains its changes better than a constant" in why and "refuted" in why, why


def test_a_level_driven_by_its_own_total_under_another_name_stays_an_input():
    # one program's processes, and every process on the host (that program's among them), written every 30 s
    rng = random.Random(1)
    x, other, part, total = 30.0, 400.0, [], []
    for i in range(HOURS * 120 + 1):
        x = max(0.0, x - 0.1 * (x - 30) + rng.gauss(0, 2))
        other = max(100.0, other - 0.02 * (other - 400) + rng.gauss(0, 2))
        part.append((T0 + 30 * i, float(round(x))))
        total.append((T0 + 30 * i, float(round(x) + round(other))))
    m = discover([("x_processes", {"machine": "host"}, part), ("processes", {"machine": "host"}, total)],
                 start=T0, end=T0 + HOURS * 3600, step=5.0)
    assert m.stocks == []
    why = m.discovery["left_out"]['x_processes{machine="host"}']
    assert 'it may be a part of processes{machine="host"}' in why, why


def test_an_average_age_is_a_summary_not_a_stock():
    # items baked onto a shelf and taken oldest first at a rate a demand gauge says; the shelf
    # writes its items' mean age every 30 s, which the demand moves but which holds nothing
    rng = random.Random(7)
    demand, shelf, now, ages, demands = 3.0, [], 0.0, [], []
    for i in range(HOURS * 120 + 1):
        demand = max(0.5, demand + rng.gauss(0, 0.3) + 0.05 * (3 - demand))
        shelf += [now] * sum(1 for _ in range(6) if rng.random() < 0.25)
        shelf = shelf[sum(1 for _ in range(10) if rng.random() < demand / 20):]
        now += 30
        ages.append((T0 + 30 * i, round(sum(now - b for b in shelf) / len(shelf), 1) if shelf else 0.0))
        demands.append((T0 + 30 * i, round(demand, 3)))
    m = discover([("shelf_mean_age_s", {"machine": "shop"}, ages), ("customer_demand_per_min", {"machine": "shop"}, demands)],
                 start=T0, end=T0 + HOURS * 3600, step=5.0)
    assert "shelf_mean_age_s" not in [s.id for s in m.stocks]
    why = m.discovery["left_out"]['shelf_mean_age_s{machine="shop"}']
    assert "a statistic" in why and "a summary, not a store" in why, why
