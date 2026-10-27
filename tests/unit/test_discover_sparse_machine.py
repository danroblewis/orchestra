"""A machine that writes one sparse point late in the window (a collector announcing itself once,
counted by Orchestra's event counter) does not cut the other machines' levels out of the model:
a counter had counted nothing before its first write, so its change there is a measured zero."""

import gzip
import json
import random
from collections import defaultdict
from pathlib import Path

from orchestra.sd.discover import discover
from orchestra.sd.live import before_first_write

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sd" / "board-live.jsonl.gz"
END = 1793081100.0       # the end of the window the owner's live demo found no stocks in
ANNOUNCED = ("orchestra_events_total", {"type": "orchestra.machine.started", "source": "weather"}, [(1793080470.134, 1.0)])
T0 = 1_800_000_000.0


def _board() -> list:
    """A live demo's item board (renamed into neutral words): ten levels by state, the counters of
    the moves between them, written from 22:49:45; the window ends at 23:05."""
    groups: dict[tuple, list] = defaultdict(list)
    with gzip.open(FIXTURE, "rt") as f:
        for line in f:
            r = json.loads(line)
            groups[(r["s"], tuple(sorted(r["l"].items())))].append((r["t"], r["v"]))
    return [(name, dict(labels), sorted(pts)) for (name, labels), pts in groups.items()]


def _stocks(dump, start: float, end: float, step: float) -> list[str]:
    return sorted(s.id for s in discover(dump, start=start, end=end, step=step).stocks)


def test_one_announcement_from_another_machine_leaves_the_stocks_as_they_were():
    # the owner's demo: the board's levels alone give its stocks; one weather collector's
    # announcement, counted once at 22:54:30, left none ("did not change while it was live")
    alone = _stocks(_board(), END - 3600, END, 5.0)
    with_weather = _stocks([*_board(), ANNOUNCED], END - 3600, END, 5.0)
    assert {"items_making", "items_made", "items_checking", "items_shipped"} <= set(alone), alone
    assert with_weather == alone


def test_a_late_sparse_counter_does_not_shorten_the_balances():
    # a board on no schedule moves items from the window's start to its middle; another machine
    # counts one event three quarters in. Before that event it had counted nothing, so the board's
    # balance keeps every step it was live
    rng = random.Random(4)
    lab = {"machine": "board"}
    waiting = arrived = served = 0
    w_pts, a_pts, s_pts = [], [], []
    for i in range(30 * 60):
        t = T0 + i
        if rng.random() < 0.1:
            arrived, waiting = arrived + 1, waiting + 1
            a_pts.append((t, arrived))
            w_pts.append((t, waiting))
        if waiting and rng.random() < 0.09:
            served, waiting = served + 1, waiting - 1
            s_pts.append((t, served))
            w_pts.append((t, waiting))
    board = [("waiting", lab, w_pts), ("arrived_total", lab, a_pts), ("served_total", lab, s_pts)]
    late = ("orchestra_events_total", {"type": "orchestra.machine.started", "source": "weather"}, [(T0 + 2700.0, 1.0)])
    alone = discover(board, start=T0, end=T0 + 3600, step=30)
    m = discover([*board, late], start=T0, end=T0 + 3600, step=30)
    assert [s.id for s in m.stocks] == [s.id for s in alone.stocks] == ["waiting"], m.discovery["left_out"]
    assert m.stock("waiting").evidence["balance_steps"] == alone.stock("waiting").evidence["balance_steps"]


def test_the_steps_before_a_counters_first_write_are_measured_when_it_started_there():
    # written at 95 s: the steps from 0 to the one holding the write (90-120 s) saw nothing, then
    # its first event
    assert before_first_write([(T0 + 95.0, 1.0)], T0, 30.0, 10) == [0, 1, 2, 3]
    assert before_first_write([(T0 + 95.0, 1.0), (T0 + 200.0, 4.0)], T0, 30.0, 10) == [0, 1, 2, 3]
    # counted before the window: nothing to add
    assert before_first_write([(T0 - 10.0, 3.0), (T0 + 95.0, 4.0)], T0, 30.0, 10) == []
    # an exporter scraped for the first time: it was counting long before, so the time before is unknown
    assert before_first_write([(T0 + 95.0, 81_000.0), (T0 + 125.0, 81_004.0)], T0, 30.0, 10) == []
    assert before_first_write([], T0, 30.0, 10) == []
