"""Liveness is the machine's: a gauge written only when it changes holds its value while its
machine is alive, and goes stale only when the machine goes silent."""

import random

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.discover import discover
from orchestra.sd.live import held, stretches, usual_interval

T0 = 1_800_000_000.0


def test_a_gauge_written_on_change_holds_while_its_machine_is_alive(tmp_path):
    # The board writes its waiting count, and the counters that move it, only when they change,
    # as a ticket tracker writes its tickets by state: no schedule, no heartbeat. In the last
    # twenty minutes nothing arrives or leaves, so the count is not written at all, while the
    # board keeps counting other things. The count is still the count: the level is live while
    # its machine is, the balance is exact, and the model records how long the value was held.
    rng = random.Random(2)
    lab = lambda m: {"project": "p", "machine": m}
    waiting = arrived = served = other = 0
    pts = []
    for i in range(60 * 60):
        t, busy = T0 + i, i < 40 * 60
        if busy and rng.random() < 0.1:
            arrived, waiting = arrived + 1, waiting + 1
            pts += [Point("arrived_total", arrived, t, lab("board")), Point("waiting", waiting, t, lab("board"))]
        if busy and waiting and rng.random() < 0.09:
            served, waiting = served + 1, waiting - 1
            pts += [Point("served_total", served, t, lab("board")), Point("waiting", waiting, t, lab("board"))]
        if rng.random() < 0.05:
            other += 1
            pts.append(Point("other_total", other, t, lab("board")))
    store = FileMetrics(tmp_path / "m.jsonl")
    store.write(pts)
    m = discover(store.dump("", {"project": "p"}), start=T0, end=T0 + 3600, step=30)
    assert [s.id for s in m.stocks] == ["waiting"], m.discovery["left_out"]
    ev = m.stock("waiting").evidence
    assert ev["exact_steps"] == 1.0 and ev["balance_r2"] == 1.0
    assert ev["balance_steps"] >= 118, "live from its first write to the end of the window"
    assert {(b["series"].split("{")[0], b["sign"]) for b in ev["balance"]} == {("arrived_total", 1), ("served_total", -1)}
    assert m.discovery["held"]["waiting"]["at_end_minutes"] >= 19, m.discovery["held"]
    assert ev["held_minutes"] >= 19


def test_a_machine_on_a_schedule_is_silent_past_its_limit_and_one_without_is_not():
    # a heartbeat every 15 s: alive between writes less than ten times that apart (at least a
    # minute), and a lone write after a silence does not bridge it; a machine with no schedule
    # is alive from its first write to the end
    beat = [T0 + 15 * i for i in range(20)] + [T0 + 1000] + [T0 + 1200 + 15 * i for i in range(10)]
    assert usual_interval([(t, 1.0) for t in beat[:20]]) == 15.0
    alive = stretches(beat, 150.0, T0, T0 + 1400)
    assert alive == [(T0, T0 + 285), (T0 + 1200, T0 + 1400)], alive
    assert stretches(beat, None, T0, T0 + 1400) == [(T0, T0 + 1400)]
    # a gauge last written before the silence is not carried past it: live again from its next write
    gauge = [(T0 + 100, 3.0), (T0 + 1300, 0.0)]
    assert held(gauge, alive, T0, T0 + 1400) == [(T0 + 100, T0 + 285), (T0 + 1300, T0 + 1400)]
    assert usual_interval([(T0 + t, 1.0) for t in (0, 3, 3, 6, 180, 183, 186, 400, 403, 406, 900, 903)]) is None, \
        "a burst of writes seconds apart, then minutes of nothing, is no schedule"
