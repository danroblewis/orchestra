"""A level is a flag (a baker is busy or not) only when it takes the values 0 and 1. A measurement
that changed once (the day's length, 612 then 613 minutes) or a rate that moves between two values
is not one: it changed too seldom to balance, and stays an input."""

import random

from orchestra.sd.discover import discover

T0 = 1_800_000_000.0


def _busy(rng: random.Random) -> list[tuple[float, float]]:
    v, out = 0, []
    for i in range(241):
        if rng.random() < 0.1:
            v = 1 - v
        out.append((T0 + 60 * i, float(v)))
    return out


def test_a_level_that_stepped_once_is_not_a_flag():
    rng = random.Random(1)
    whole = [(T0 + 60 * i, 612.0 if i < 90 else 613.0) for i in range(241)]
    smooth = [(T0 + 60 * i, 612.4 if i < 90 else 613.1) for i in range(241)]
    m = discover([("day_length_minutes", {"machine": "sky"}, whole), ("day_length_exact_minutes", {"machine": "sky"}, smooth),
                  ("oven_busy", {"machine": "oven"}, _busy(rng))], start=T0, end=T0 + 4 * 3600, step=60.0)
    left = m.discovery["left_out"]
    for key in ('day_length_minutes{machine="sky"}', 'day_length_exact_minutes{machine="sky"}'):
        assert not left[key].startswith("a flag") and "changed" in left[key] and "too few" in left[key], left[key]
    # held, not interpolated into a ramp: the step is one change, in one step
    assert "changed in only 1 step" in left['day_length_exact_minutes{machine="sky"}']
    assert {r["name"] for r in m.discovery["inputs"].values()} >= {"day_length_minutes", "day_length_exact_minutes"}
    assert left['oven_busy{machine="oven"}'].startswith("a flag")
    assert "oven_busy" not in {r["name"] for r in m.discovery["inputs"].values()}
