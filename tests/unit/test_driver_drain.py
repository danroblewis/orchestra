"""An outflow takes only what its source holds (sd.driverchoice.drains_empty): R3, :8096 fitted
gate → end = 0.366 + 4.82 × items held at review, a rate that drains 22 items an hour from an
empty gate. A driver form of an outflow is refuted when it expects events while its source was
empty, or, its source never empty, when its intercept alone expects one over the window."""

from orchestra.sd.driverchoice import _empty, drains_empty, read_empty
from orchestra.sd.path import Path

T0 = 1_800_000_000.0
LIVE = [(T0, T0 + 3600)]


def _path(levels: list[float]) -> Path:
    return Path.of([(T0 + 60 * i, v) for i, v in enumerate(levels)], LIVE, 60.0)


def test_the_stretches_a_source_was_empty():
    p = _path([2, 0, 0, 3] + [1] * 56)
    assert _empty(p) == [(T0 + 60, T0 + 180)]


def test_a_driver_with_an_intercept_on_an_outflow_whose_source_never_empties_is_refuted():
    src, drv = _path([3] * 60), _path([0, 1] * 30)
    line = {"form": "linear", "params": {"c": 0.366, "k": 4.82}}
    why = drains_empty(line, drv, _empty(src), 60.0, 0.0)
    assert "never falls below 0.366" in why and "22.0 items" in why
    # through the origin: the rate goes to zero with its driver, so nothing says it drains an empty stock
    assert drains_empty({"form": "proportional", "params": {"k": 4.82}}, drv, [], 60.0, 0.0) == ""
    # a driver that never reads zero: its rate never does either
    assert "never falls below 4.82" in drains_empty({"form": "proportional", "params": {"k": 4.82}}, _path([1, 2] * 30), [], 60.0, 0.0)
    # unless the form it would fall back to never falls lower: refusing it would drain an empty source faster
    assert drains_empty(line, drv, [], 60.0, 5.5) == ""
    assert drains_empty(line, drv, [], 60.0, None) == ""                 # the own line: not held to the floor
    assert drains_empty({"form": "linear", "params": {"c": 0.001, "k": 4.82}}, drv, [], 60.0, 0.0) == ""


def test_a_driver_that_expects_events_while_its_source_is_empty_is_refuted_one_that_does_not_is_kept():
    src = _path([0] * 20 + [4] * 40)               # empty for the first 20 min
    busy = _path([2] * 60)                          # the driver held 2 while the source was empty
    idle = _path([0] * 20 + [2] * 40)               # the driver held nothing then
    prop = {"form": "proportional", "params": {"k": 0.5}}
    assert "over the 20 min its source was empty this form expects 20.0 events" in drains_empty(prop, busy, _empty(src), 60.0, 0.0)
    assert drains_empty(prop, idle, _empty(src), 60.0, 0.0) == ""


def test_the_flows_own_line_is_held_only_to_what_it_expects_while_its_source_was_empty():
    full, gaps = _path([3] * 60), _path([0] * 10 + [3] * 50)
    line = {"form": "linear", "params": {"c": 0.5, "k": 0.2}}
    assert drains_empty(line, full, _empty(full), 60.0) == ""        # never empty: its intercept is extrapolation
    assert "expects 5.0 events" in drains_empty(line, gaps, _empty(gaps), 60.0)


def test_fit_flow_keeps_a_driver_with_an_intercept_whose_floor_is_below_its_own_forms():
    """End to end: an outflow whose events follow a demand with a base rate, its source never empty.
    The refuter round (T16): refused, it fell back to a constant draining faster still."""
    import random

    from orchestra.sd.discover import fit_flow

    rng = random.Random(1)
    out, t, v = [], 0, 1.0
    while t < 3600:
        out.append((t, v))
        t += rng.randint(60, 300)
        v = 4.0 if v == 1.0 else 1.0
    demand = lambda x: next(val for start, val in reversed(out) if start <= x - T0)
    events = [(T0 + i, 1.0) for i in range(3600) if rng.random() < (0.5 + 2.0 * demand(T0 + i)) / 60]
    src = Path.of([(T0 + i, 5.0) for i in range(0, 3600, 15)], LIVE, 60.0)
    drv = Path.of([(T0 + i, demand(T0 + i)) for i in range(0, 3600, 15)], LIVE, 60.0)
    as_inflow = fit_flow(events, 60.0, {"d": drv}, None, {"d"})[0]
    assert as_inflow["inputs"] == ["d"], as_inflow["driver"]
    best = fit_flow(events, 60.0, {"s": src, "d": drv}, "s", {"d"})[0]
    # its floor (0.5 + 2 × 1) is below the flow's own constant (the mean, about 5.5): refusing it
    # would leave a form that drains an empty source faster, so it is kept
    assert best["inputs"] == ["d"], best["driver"]


def test_a_source_that_read_empty_while_the_flows_items_left_is_no_evidence():
    src = _path([0] * 20 + [4] * 40)
    assert read_empty(src, [(T0 + 30 * 60, 1.0)]) == _empty(src)            # every event while it held something
    assert read_empty(src, [(T0 + 5 * 60, 1.0), (T0 + 30 * 60, 1.0)]) == []  # one left while it read empty
