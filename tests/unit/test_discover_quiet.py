"""A quiet window holds the model (sd.quiet, sd.rediscover): the core demo, 2026-11-01. v3 had
seven stocks; an hour in which the tickets' levels did not change (or changed in two to four
steps) found one, was saved as v4 ("the structure changed"), and the next discovery drew DONE=34
as gone. A stock whose series was written to the end of the window and moved fewer than five
times in it is carried from the current version (a hidden one when all its counters are, however
discovery folded them); one whose series stopped being written goes. A quiet window saves no
version, and the record says the current one stands."""

from __future__ import annotations

from itertools import pairwise
from types import SimpleNamespace

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd import quiet
from orchestra.sd import rediscover as rd
from orchestra.sd.model import Equation, Flow, Machine, Model, SeriesRef, Stock
from orchestra.sd.store import ModelStore
from orchestra.sd.strategies import CONSERVATION

STATES = ("OPEN", "IN_PROGRESS", "READY_FOR_REVIEW", "IN_REVIEW", "DONE", "REJECTED")
def _ref(state: str) -> SeriesRef:
    return SeriesRef("tasks_tickets", {"state": state, "project": "p", "instrument": "tasks.tickets"})


def _flow(src: str | None, dst: str | None) -> Flow:
    name = f"{src or 'in'}_{dst or 'out'}"
    return Flow(name, name, src and f"t_{src}", dst and f"t_{dst}", SeriesRef(f"{name}_total", {"instrument": "tasks.tickets"}),
                [Equation("constant", {"c": 0.8}, "fitted", "poisson-mle", quality={"events": 28.0})])


def _v3() -> Model:
    m = Model("system", "The system")
    m.stocks = [Stock(f"t_{s}", s, series=_ref(s), evidence={}) for s in STATES]
    path = [None, *STATES[:5]]
    m.flows = [_flow(a, b) for a, b in pairwise(path)] + [_flow("IN_REVIEW", "REJECTED"), _flow("REJECTED", "IN_PROGRESS")]
    m.machines = [Machine("reviewer", "reviewer", "machine", attributed=["IN_REVIEW_REJECTED"])]
    return m


START, END, STEP = 1_800_000_000.0, 1_800_003_600.0, 5.0


def _quiet_hour(stocks: tuple[str, ...] = ()) -> Model:
    m = Model("system", "The system")
    m.stocks = [Stock(f"t_{s}", s, series=_ref(s), evidence={}) for s in stocks]
    m.discovery = {"start": START, "end": END, "step": STEP, "left_out": {}}
    return m


def _written(state: str, value: float = 3.0, until: float = END, moves: tuple[float, ...] = ()) -> tuple:
    """A level written every second from before the window, stepping up by one at each of ``moves``."""
    pts, t = [], START - 600
    while t <= until:
        pts.append((t, value + sum(1 for m in moves if m <= t)))
        t += 1.0
    return ("tasks_tickets", {"state": state, "instrument": "tasks.tickets"}, pts)


def _counter(name: str, at: tuple[float, ...] = ()) -> tuple:
    pts = [(t, float(sum(1 for m in at if m <= t))) for t in range(int(START) - 600, int(END) + 1, 15)]
    return (f"{name}_total", {"instrument": "tasks.tickets"}, pts)


def test_hold_carries_the_still_stocks_and_their_flows_and_nothing_that_moved():
    dump = [_written(s, moves=(START - 300,) if s == "DONE" else ()) for s in STATES if s != "OPEN"]
    dump.append(_written("OPEN", moves=tuple(START + 60 * k for k in range(8))))   # moved, and did not balance: it goes
    got = quiet.hold(_quiet_hour(), _v3(), 3, dump)
    assert sorted(s.id for s in got.stocks) == sorted(f"t_{s}" for s in STATES if s != "OPEN")
    assert all(s.evidence["quiet"]["version"] == 3 for s in got.stocks)
    assert {f.id for f in got.flows} == {"IN_PROGRESS_READY_FOR_REVIEW", "READY_FOR_REVIEW_IN_REVIEW", "IN_REVIEW_DONE",
                                         "IN_REVIEW_REJECTED", "REJECTED_IN_PROGRESS"}               # none reaches OPEN
    assert [m.id for m in got.machines] == ["reviewer"]
    q = got.discovery["quiet"]
    assert q["since_by_stock"]["t_DONE"] == START - 300            # when it last moved
    assert q["since_by_stock"]["t_REJECTED"] == START               # never moved in what was read: the window's start
    assert q["version"] == 3 and q["since"] == START - 300


def test_a_series_that_stopped_inside_the_window_is_not_still():
    dump = [_written(s) for s in STATES if s != "DONE"] + [_written("DONE", until=END - 561)]
    got = quiet.hold(_quiet_hour(), _v3(), 3, dump)
    assert "t_DONE" not in {s.id for s in got.stocks} and len(got.stocks) == len(STATES) - 1
    assert quiet.hold(_quiet_hour(), _v3(), 3, []).stocks == []          # nothing read: nothing held


def test_a_hidden_stock_is_held_when_every_counter_of_its_flows_is_still_however_discovery_folded_them():
    cur = _v3()
    cur.stocks.append(Stock("after_review", "after review", evidence={"hidden": True}))
    cur.flows += [_flow("READY_FOR_REVIEW", None), _flow(None, "DONE")]
    cur.flows[-2].dst, cur.flows[-1].src = "after_review", "after_review"
    once = START + 1000.0                                            # each moved once, at the same instant
    dump = [_written(s) for s in STATES] + [_counter("READY_FOR_REVIEW_out", (once,)), _counter("in_DONE", (once,))]
    m = _quiet_hour()
    m.discovery["left_out"] = {'in_DONE_total{instrument="tasks.tickets"}': 'the same as READY_FOR_REVIEW_out_total{instrument="tasks.tickets"} (counts the same events)'}
    got = quiet.hold(m, cur, 3, dump)
    assert "after_review" in got.discovery["quiet"]["stocks"] and got.discovery["quiet"]["since_by_stock"]["after_review"] == once + 5   # the write that showed it
    busy = [_written(s) for s in STATES] + [_counter("READY_FOR_REVIEW_out", tuple(START + 100 * k for k in range(9))),
                                            _counter("in_DONE", (once,))]
    assert "after_review" not in {s.id for s in quiet.hold(_quiet_hour(), cur, 3, busy).stocks}


def test_a_quiet_hour_saves_no_version_and_the_current_one_stands(tmp_path, monkeypatch):
    project = SimpleNamespace(key="p", state_dir=tmp_path, config=SimpleNamespace(
        discovery_strategy=CONSERVATION, discovery_options={}, discovery_window=3600.0, discovery_step=5.0, discovery_every=300.0,
        eras_from=None, prior_for=None))
    store = ModelStore.for_state(tmp_path)
    found = iter([_v3(), _quiet_hour(("DONE",)), _quiet_hour()])

    def discovered(*a, **k):
        m = next(found)
        m.discovery = {"start": k["start"], "end": k["end"], "step": k["step"], **{x: y for x, y in m.discovery.items() if x == "left_out"}}
        return m

    monkeypatch.setattr(rd.simulated, "discovered", discovered)
    metrics = FileMetrics(tmp_path / "m.jsonl")
    metrics.write([Point("tasks_tickets", 3.0 + (s == "DONE" and t >= 1_800_000_000), t, {"state": s, "project": "p", "instrument": "tasks.tickets"})
                   for s in STATES for t in range(1_799_996_400, 1_800_007_201, 5)])
    first = rd.rediscover(project, metrics, now=1_800_000_000.0)
    assert first.version == 1
    for now in (1_800_003_600.0, 1_800_007_200.0):          # a quiet hour (DONE found alone), then a silent one
        r = rd.rediscover(project, metrics, now=now)
        assert r.version is None and len(r.model.stocks) == len(STATES)
        q = r.model.discovery["quiet"]
        assert q["stands"] and q["note"] == "quiet: the model of v1 stands, nothing refitted"
        assert isinstance(q["since"], float | int) and "UTC" not in q["note"]      # the page says the time in the viewer's zone
    assert [v["version"] for v in store.versions()] == [1]
    assert store.latest_discovery()[1].stock("t_DONE") is not None
    since = store.latest_discovery()[1].discovery["quiet"]["since_by_stock"]
    assert since["t_DONE"] == 1_800_000_000.0 and since["t_OPEN"] == 1_800_003_600.0   # DONE last moved then; OPEN never, in the window read


def test_a_found_flow_from_outside_gets_back_the_end_a_held_stock_claims():
    # the Slack demo's v17: "late → awaiting_check" was in both stocks' balances yet drawn from
    # outside: discovery did not find the quiet "late" (so the move began outside), and holding
    # "late" left the found move as it was, so "threads waiting at late" only filled
    fresh = _quiet_hour(("IN_PROGRESS",))
    fresh.flows = [_flow(None, "IN_PROGRESS")]
    fresh.flows[0].id = "OPEN_IN_PROGRESS"
    m = quiet.hold(fresh, _v3(), 3, [_written(s) for s in STATES])
    f = {x.id: x for x in m.flows}
    assert (f["OPEN_IN_PROGRESS"].src, f["OPEN_IN_PROGRESS"].dst) == ("t_OPEN", "t_IN_PROGRESS")
    assert f["OPEN_IN_PROGRESS"].evidence["quiet_end"]["ends"] == ["src"]
    assert "quiet" not in f["OPEN_IN_PROGRESS"].evidence          # found, not carried: its numbers are this window's


def _found_open_move() -> Model:
    fresh = _quiet_hour(("IN_PROGRESS",))
    fresh.flows = [_flow(None, "IN_PROGRESS")]
    fresh.flows[0].id = "OPEN_IN_PROGRESS"
    fresh.flows[0].counter = SeriesRef("OPEN_IN_PROGRESS_total", {"instrument": "tasks.tickets"})
    return fresh


def test_a_found_flow_a_still_stock_could_not_have_fed_stays_drawn_from_outside():
    # refuter round: OPEN held still at 3 and nothing came into it, while 28 items moved on: they
    # did not come from OPEN, whatever v3 said; the end stays outside and the record says why
    moved = tuple(START + 100 * k for k in range(1, 29))
    dump = [_written(s) for s in STATES] + [_counter("OPEN_IN_PROGRESS", moved), _counter("in_OPEN")]
    f = {x.id: x for x in quiet.hold(_found_open_move(), _v3(), 3, dump).flows}["OPEN_IN_PROGRESS"]
    assert (f.src, f.dst) == (None, "t_IN_PROGRESS")
    assert "leaves room for 0 of its 28 events" in f.evidence["quiet_end"]["kept_outside"]["src"]


def test_a_found_flow_a_still_stock_passed_through_gets_its_end_back():
    # the same 28 items, each arriving at OPEN as one leaves: its level still, its balance whole
    moved = tuple(START + 100 * k for k in range(1, 29))
    dump = [_written(s) for s in STATES] + [_counter("OPEN_IN_PROGRESS", moved), _counter("in_OPEN", moved)]
    f = {x.id: x for x in quiet.hold(_found_open_move(), _v3(), 3, dump).flows}["OPEN_IN_PROGRESS"]
    assert (f.src, f.dst) == ("t_OPEN", "t_IN_PROGRESS") and f.evidence["quiet_end"]["ends"] == ["src"]


def test_a_found_flow_between_two_held_stocks_gets_both_ends_back():
    fresh = _quiet_hour(("DONE",))
    fresh.flows = [_flow(None, None)]
    fresh.flows[0].id = "IN_PROGRESS_READY_FOR_REVIEW"
    m = quiet.hold(fresh, _v3(), 3, [_written(s) for s in STATES])
    f = {x.id: x for x in m.flows}["IN_PROGRESS_READY_FOR_REVIEW"]
    assert (f.src, f.dst) == ("t_IN_PROGRESS", "t_READY_FOR_REVIEW") and f.evidence["quiet_end"]["ends"] == ["src", "dst"]
