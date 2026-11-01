"""A quiet window holds the model (sd.quiet, sd.rediscover): the core demo, 2026-11-01. v3 had
seven stocks; an hour in which the tickets' levels did not change (or changed in two to four
steps) found one, was saved as v4 ("the structure changed"), and the next discovery drew DONE=34
as gone. A stock whose series did not move is carried from the current version; a quiet window
saves no version, and the record says the current one stands."""

from __future__ import annotations

from itertools import pairwise
from types import SimpleNamespace

from orchestra.metrics.file import FileMetrics
from orchestra.sd import quiet
from orchestra.sd import rediscover as rd
from orchestra.sd.model import Equation, Flow, Machine, Model, SeriesRef, Stock
from orchestra.sd.store import ModelStore
from orchestra.sd.strategies import CONSERVATION

STATES = ("OPEN", "IN_PROGRESS", "READY_FOR_REVIEW", "IN_REVIEW", "DONE", "REJECTED")
UNCHANGED = "a level that did not change in the window while it was live"
FEW = "a level that changed in only 2 steps: fewer than 5, too few to tell a balance from coincidence"


def _ref(state: str) -> SeriesRef:
    return SeriesRef("tasks_tickets", {"state": state, "project": "p", "instrument": "tasks.tickets"})


def _key(state: str) -> str:
    return f'tasks_tickets{{instrument="tasks.tickets",state="{state}"}}'


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


def _quiet_hour(left_out: dict, stocks: tuple[str, ...] = ()) -> Model:
    m = Model("system", "The system")
    m.stocks = [Stock(f"t_{s}", s, series=_ref(s), evidence={}) for s in stocks]
    m.discovery = {"start": 1_800_000_000.0, "end": 1_800_003_600.0, "step": 5.0, "left_out": left_out}
    return m


def test_hold_carries_the_quiet_stocks_and_their_flows_and_nothing_that_moved():
    cur = _v3()
    left = {_key(s): UNCHANGED for s in STATES if s != "OPEN"} | {_key("IN_REVIEW"): FEW}
    got = quiet.hold(_quiet_hour(left), cur, 3)
    assert sorted(s.id for s in got.stocks) == sorted(f"t_{s}" for s in STATES if s != "OPEN")     # OPEN moved, and failed: it goes
    assert all(s.evidence["quiet"]["version"] == 3 for s in got.stocks)
    assert {f.id for f in got.flows} == {"IN_PROGRESS_READY_FOR_REVIEW", "READY_FOR_REVIEW_IN_REVIEW", "IN_REVIEW_DONE",
                                         "IN_REVIEW_REJECTED", "REJECTED_IN_PROGRESS"}               # none reaches OPEN
    assert [m.id for m in got.machines] == ["reviewer"]
    q = got.discovery["quiet"]
    assert q["since"] == 1_800_000_000.0 and q["version"] == 3 and "t_DONE" in q["stocks"]


def test_a_stock_no_longer_written_is_not_quiet():
    got = quiet.hold(_quiet_hour({_key("DONE"): "no longer written: last point 3 h before the window's end"}), _v3(), 3)
    assert got.stocks == [] and "quiet" not in got.discovery


def test_a_quiet_hour_saves_no_version_and_the_current_one_stands(tmp_path, monkeypatch):
    project = SimpleNamespace(key="p", state_dir=tmp_path, config=SimpleNamespace(
        discovery_strategy=CONSERVATION, discovery_options={}, discovery_window=3600.0, discovery_step=5.0, discovery_every=300.0,
        eras_from=None, prior_for=None))
    store = ModelStore.for_state(tmp_path)
    found = iter([_v3(), _quiet_hour({_key(s): UNCHANGED for s in STATES}, ("DONE",)), _quiet_hour({_key(s): UNCHANGED for s in STATES})])

    def discovered(*a, **k):
        m = next(found)
        m.discovery = {"start": k["start"], "end": k["end"], "step": k["step"], **{x: y for x, y in m.discovery.items() if x == "left_out"}}
        return m

    monkeypatch.setattr(rd.simulated, "discovered", discovered)
    metrics = FileMetrics(tmp_path / "m.jsonl")
    first = rd.rediscover(project, metrics, now=1_800_000_000.0)
    assert first.version == 1
    for now in (1_800_003_600.0, 1_800_007_200.0):          # a quiet hour (DONE found alone), then a silent one
        r = rd.rediscover(project, metrics, now=now)
        assert r.version is None and len(r.model.stocks) == len(STATES)
        assert r.model.discovery["quiet"]["note"].startswith("quiet since ") and r.model.discovery["quiet"]["note"].endswith("the model of v1 stands")
    assert [v["version"] for v in store.versions()] == [1]
    assert store.latest_discovery()[1].stock("t_DONE") is not None
    since = store.latest_discovery()[1].discovery["quiet"]["since_by_stock"]
    assert since["t_OPEN"] == 1_800_000_000.0 < since["t_DONE"] == 1_800_003_600.0   # held since the first quiet window's start; DONE since the second's
