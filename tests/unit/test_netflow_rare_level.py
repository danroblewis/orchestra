"""A level that changed too rarely to fit a net flow says only what is known: how often it changed and
how many changes a fit needs, never that it "looks like an input"; and a counter whose counts over the
same stretches explain most of its changes is named beside it, not fitted yet."""

from orchestra.sd.netflow import EVENTS_PER_PARAM, fit
from orchestra.sd.series import Series

T0 = 1_800_000_000.0


def level(values):
    return Series("commits", {}, [(T0 + 30 * i, v) for i, v in enumerate(values)], values, False)


def test_a_rarely_changed_level_says_how_often_and_what_a_fit_needs():
    vals = [0.0] * 40
    for i in range(20, 40):
        vals[i] = 1.0
    got, why = fit(level(vals), [], 30.0, 60.0)
    assert got is None
    assert "looks like an input" not in why
    assert why.startswith("and it changed in only 1 of its 39 stretches of 30 s;")
    assert f"at least {EVENTS_PER_PARAM * 2} are needed to fit a net flow" in why
    assert "follows" not in why


def test_a_counter_it_changes_with_is_named_not_fitted():
    vals = [(1.0 if i >= 10 else 0.0) + (1.0 if i >= 25 else 0.0) for i in range(40)]
    count = [v + 7.0 for v in vals]                      # a counter that counted the same moves, from 7
    c = Series("moves_total", {"to": "main"}, [(T0 + 30 * i, v) for i, v in enumerate(count)], count, True)
    _, why = fit(level(vals), [], 30.0, 60.0, counters=[c])
    assert "follows moves_total{to=\"main\"}, R² 1.00, not fitted yet" in why, why
