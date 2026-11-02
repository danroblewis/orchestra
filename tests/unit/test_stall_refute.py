"""Adversarial cases for the stall guards (sd.stall.due): events due at the usual rate, and a fit's
minimum of events. The xfail(strict) cases are where the rule, as committed, does what its own
docstring says it should not."""

import pytest

from orchestra.sd.balance import MIN_EVENTS
from orchestra.sd.model import Equation, Flow, Model, Stock
from orchestra.sd.stall import find, step

T = 1_800_000_000.0
STEP = 60


def model(fit_events=None, c=None) -> Model:
    m = Model("system", "s", time_unit="minute", stocks=[Stock("q", "queue")],
              flows=[Flow("in", "arrivals", None, "q"), Flow("out", "done", "q", None)])
    if fit_events is not None:
        m.flows[1].equations.append(Equation("constant", {"c": c if c is not None else 1.0}, "fitted",
                                             quality={"events": float(fit_events)}))
    return m


def history(now: float, out_rate) -> dict:
    ts = range(int(now) - 3600, int(now) + 1, STEP)
    return {"stocks": {"q": [[t, 10 + max(0.0, t - (now - 900)) / 60] for t in ts]},
            "flows": {"in": [[t, 1.0] for t in ts], "out": [[t, out_rate(t)] for t in ts]}}


def test_one_a_minute_silent_for_ten_minutes_in_a_ten_minute_window_stalls():
    now = T
    stalled, _ = find(model(fit_events=50), history(now, lambda t: 1.0 if t < now - 600 else 0.0), now, 600, 0.1)
    assert "flow:out" in stalled and stalled["flow:out"]["usual"] == 1.0


def test_fitted_on_four_events_does_not_stall():
    now = T
    stalled, judged = find(model(fit_events=4), history(now, lambda t: 1.0 if t < now - 900 else 0.0), now, 900, 0.1)
    assert "flow:out" in judged and "flow:out" not in stalled and "stock:q" not in stalled
    assert MIN_EVENTS == 5


def test_one_an_hour_in_a_thirty_minute_window_does_not_stall():
    now = T
    one = lambda t: 1.0 if int(now - 3000) <= t < int(now - 3000) + STEP else 0.0     # one event, 50 min ago
    stalled, judged = find(model(), history(now, one), now, 1800, 0.1)
    assert "flow:out" in judged and "flow:out" not in stalled


@pytest.mark.xfail(strict=True, reason="usual is the pre-window mean, not the fitted rate: 10 events in one burst "
                                       "40 min ago read as 3.3 due in 15 min though the fit (10/h) says 2.5")
def test_a_burst_then_silence_is_not_a_stall_where_the_fit_says_too_few_were_due():
    now = T
    burst = lambda t: 10.0 if int(now - 2400) <= t < int(now - 2400) + STEP else 0.0
    stalled, _ = find(model(fit_events=10, c=10 / 60), history(now, burst), now, 900, 0.1)
    assert "flow:out" not in stalled


@pytest.mark.xfail(strict=True, reason="UC-1 bakery orders_cancelled_inspecting: fitted c=0.1/min (1.5 due), "
                                       "usual from the shorter pre-window history 0.235/min (3.5 due): announced")
def test_usual_from_a_window_shorter_than_the_fit_does_not_override_the_fit():
    now = T
    # the history holds only the last 41 minutes (the store's points begin there); the fit saw 6 events
    # in 60 live minutes (c = 0.1/min, 1.5 due in 15). All 6 fell in the 26 minutes before the window.
    h = history(now, lambda t: 6 / 26 if t < now - 900 else 0.0)
    h["flows"] = {k: [[t, v] for t, v in pts if t >= now - 2460] for k, pts in h["flows"].items()}
    h["stocks"] = {k: [[t, v] for t, v in pts if t >= now - 2460] for k, pts in h["stocks"].items()}
    stalled, _ = find(model(fit_events=6, c=0.1), h, now, 900, 0.1)
    assert "flow:out" not in stalled


@pytest.mark.xfail(strict=True, reason="a stall whose usual rate decays below MIN_EXPECTED/window while still silent "
                                       "is announced resumed (at 35 min of silence; before the change, at 60)")
def test_a_still_silent_flow_is_not_announced_resumed():
    stop = T
    rate = lambda t: 0.3 if t < stop else 0.0
    state, resumed = {}, []
    for k in range(15, 60, 5):
        now = stop + k * 60
        state, went, came = step(state, model(fit_events=20), history(now, rate), now, 900, 0.1)
        resumed += [(k, c["id"]) for c in came if c["kind"] == "flow"]
    assert resumed == []
