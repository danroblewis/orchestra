"""A state each item leaves within a step (sd.passing): the grid sees it empty, and the chain through
it is joined again rather than split into a drain to outside and a fill from outside."""

import random
from itertools import accumulate

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.discover import Series, discover
from orchestra.sd.passing import passages

T0 = 1_800_000_000.0


def chain(store, *, write_x: bool, split: bool = False, minutes: int = 60, seed: int = 3):
    """Items arrive in A, move to X, and leave X for B within a third of a second; B drains. Every
    series is written each second, before that second's events; X, when written, also reads 1 at
    the instant an item enters it and 0 when it leaves (a fraction of a second off the whole
    seconds the 30 s grid samples), so the grid sees it empty in every step. ``split``: every
    third item leaves X for C instead (an order picked up, then accepted or rejected)."""
    rng = random.Random(seed)
    lab = {"project": "p", "machine": "m"}
    lv = {"a_level": 0, "b_level": 0, "c_level": 0} if split else {"a_level": 0, "b_level": 0}
    x = 0
    outs = {"b_level": "passed_total", "c_level": "returned_total"}
    n = dict.fromkeys(["arrived_total", "moved_total", "passed_total", "left_total"] +
                      (["returned_total", "redone_total"] if split else []), 0)
    pts = []
    for i in range(minutes * 60):
        t = T0 + i
        pts += [Point(k, v, t, lab) for k, v in [*n.items(), *lv.items()]]
        if write_x:
            pts.append(Point("x_level", x, t, lab))
        if rng.random() < 0.15:
            lv["a_level"] += 1
            n["arrived_total"] += 1
        if lv["a_level"] and rng.random() < 0.05 * lv["a_level"]:
            lv["a_level"] -= 1
            n["moved_total"] += 1
            pts.append(Point("moved_total", n["moved_total"], t + 0.3, lab))
            if write_x:
                pts.append(Point("x_level", 1, t + 0.3, lab))
            to = "c_level" if split and n["moved_total"] % 3 == 0 else "b_level"
            lv[to] += 1
            n[outs[to]] += 1
            pts.append(Point(outs[to], n[outs[to]], t + 0.6, lab))
            if write_x:
                pts.append(Point("x_level", 0, t + 0.6, lab))
        for level, out in (("b_level", "left_total"), ("c_level", "redone_total")):
            if lv.get(level) and rng.random() < 0.04 * lv[level]:
                lv[level] -= 1
                n[out] += 1
    store.write(pts)
    return discover(store.dump("", {"project": "p"}), start=T0, end=T0 + minutes * 60, step=30)


def test_a_measured_state_the_grid_never_sees_joins_its_chain(tmp_path):
    m = chain(FileMetrics(tmp_path / "m.jsonl"), write_x=True)
    ends = {f.id: (f.src, f.dst) for f in m.flows}
    assert ends["moved_total"] == ("a_level", "x_level"), ends
    assert ends["passed_total"] == ("x_level", "b_level"), ends
    x = m.stock("x_level")
    assert x.series is not None and x.evidence["passing"]["rises_at_ins"][0] == x.evidence["passing"]["rises_at_ins"][1] > 0
    assert m.flow("moved_total").evidence["through"] == ["x_level"]
    assert m.discovery["left_out"].get('passed_total{machine="m"}') is None


def test_a_measured_state_between_a_drain_and_fills_of_two_stocks_joins_its_chain(tmp_path):
    # A drains to outside by moved, B and C fill from outside by passed and returned: X between
    m = chain(FileMetrics(tmp_path / "m.jsonl"), write_x=True, split=True)
    ends = {f.id: (f.src, f.dst) for f in m.flows}
    assert (ends["moved_total"], ends["passed_total"], ends["returned_total"]) == (
        ("a_level", "x_level"), ("x_level", "b_level"), ("x_level", "c_level")), ends


def test_an_unmeasured_state_between_a_drain_and_fills_of_two_stocks_is_a_hidden_stock(tmp_path):
    m = chain(FileMetrics(tmp_path / "m.jsonl"), write_x=False, split=True)
    ends = {f.id: (f.src, f.dst) for f in m.flows}
    assert (ends["moved_total"], ends["passed_total"], ends["returned_total"]) == (
        ("a_level", "after_moved_total"), ("after_moved_total", "b_level"), ("after_moved_total", "c_level")), ends
    hidden = m.stock("after_moved_total")
    assert hidden.series is None and hidden.evidence["hidden"] and "passing" in hidden.evidence


def test_a_drain_and_a_fill_of_one_stock_are_no_passage():
    # a taker called away and free again within a step: the free takers' own balance says it all
    cum = lambda xs: [0.0, *accumulate(xs)]
    lab = {"machine": "m"}
    d = [1.0 if i % 3 == 0 else 0.0 for i in range(120)]
    called, freed = Series("called_total", lab, [], cum(d), True), Series("freed_total", lab, [], cum(d), True)
    free = Series("free_level", lab, [], [3.0] * 121, False)
    other = Series("other_level", lab, [], cum([0.0] * 120), False)
    found = [(free, [(called, -1), (freed, 1)], 1.0, 1.0)]
    assert passages(found, [called, freed], [other], start=T0, end=T0 + 3600, step=30, writer_of=lambda s: "m") == []
    # the same two counters, one draining A and the other filling B, are a passage
    a, b = Series("a_level", lab, [], [3.0] * 121, False), Series("b_level", lab, [], [3.0] * 121, False)
    got = passages([(a, [(called, -1)], 1.0, 1.0), (b, [(freed, 1)], 1.0, 1.0)], [called, freed], [other],
                   start=T0, end=T0 + 3600, step=30, writer_of=lambda s: "m")
    assert [([c.name for c in p.ins], [c.name for c in p.outs], p.measured) for p in got] == [(["called_total"], ["freed_total"], False)]


def test_a_drain_two_stocks_claim_and_a_cancelling_pair_are_no_passage():
    # an event that moves two machines' stocks says nothing of which material passes; and a pair
    # of an in and an out that count the same events cancels, so it may not carry a passage
    cum = lambda xs: [0.0, *accumulate(xs)]
    d = [1.0 if i % 3 == 0 else 0.0 for i in range(120)]
    e = [1.0 if i % 4 == 0 else 0.0 for i in range(120)]
    mk = lambda name, xs, m="m": Series(name, {"machine": m}, [], cum(xs), True)
    called, ordered = mk("called_total", d), mk("ordered_total", d)
    lv = lambda name, m="m": Series(name, {"machine": m}, [], [3.0] * 121, False)
    a, b, line = lv("a_level"), lv("b_level"), lv("line_level", "customers")
    where = {"start": T0, "end": T0 + 3600, "step": 30, "writer_of": lambda s: s.labels["machine"]}
    two = [(a, [(called, -1)], 1.0, 1.0), (line, [(called, -1)], 1.0, 1.0), (b, [(ordered, 1)], 1.0, 1.0)]
    assert passages(two, [called, ordered], [], **where) == []
    # called drains A and other (different events) fills B: two free counters, a copy of each,
    # would make the totals and the steps agree, as an in and an out that cancel
    other, copy_of_other, copy_of_called = mk("other_total", e), mk("other_copy_total", e), mk("called_copy_total", d)
    found = [(a, [(called, -1)], 1.0, 1.0), (b, [(other, 1)], 1.0, 1.0)]
    assert passages(found, [called, other, copy_of_other, copy_of_called], [], **where) == []
