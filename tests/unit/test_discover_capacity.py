"""A flag whose items are another stock's is that stock's capacity of one (sd.capacity): the head
chef's busy flag, balanced exactly by inspections started less inspections done, holds one of the
orders inspecting while the chef works on it. UC-1's run of 2026-11-01 (the U1 snapshot) kept it
as a seventh stock: 114 baked and 114 started, 113 inspections done and 77 passed + 30 failed + 6
cancelled while inspecting, the flag never above the orders inspecting (121 of 121 steps), busy a
quarter of the time. The orders under inspection were counted twice and the flag's inflow came
from outside. A flag fed by another stock's flow (the shelf, fed by the inspections passed; the
state after a stock, fed by its outflow) is a stock of its own and stays one."""

import random

from orchestra.sd.capacity import capacity_views, is_flag, same_events
from orchestra.sd.discover import discover
from orchestra.sd.series import Series

T0 = 1_800_000_000.0
HOUR = 3600.0


def _inspections(seed: int = 7):
    """The bakery's inspection station: orders baked about every 31 s, one head chef inspecting
    them in turn (5 to 20 s each), each passed (70%), failed (25%) or cancelled while inspecting."""
    rng = random.Random(seed)
    t, baked = 0.0, []
    while True:
        t += rng.expovariate(1 / 31)
        if t >= HOUR - 60:
            break
        baked.append(t)
    free, starts, ends = 0.0, [], []
    for b in baked:
        s = max(b, free)
        e = s + rng.uniform(5, 20)
        r = rng.random()
        starts.append(s)
        ends.append((e, "passed" if r < 0.7 else "failed" if r < 0.95 else "cancelled"))
        free = e
    ticks = [5.0 * i for i in range(int(HOUR / 5) + 1)]
    count = lambda ts: [(T0 + k, float(sum(1 for x in ts if x <= k))) for k in ticks]
    level = lambda ins, outs: [(T0 + k, float(sum(1 for x in ins if x <= k) - sum(1 for x in outs if x <= k))) for k in ticks]
    done = [e for e, _ in ends]
    by = {w: [e for e, how in ends if how == w] for w in ("passed", "failed", "cancelled")}
    board, chef = {"instrument": "board"}, {"instrument": "head_chef"}
    return [
        ("bakery_orders_baked_total", board, count(baked)),
        ("bakery_inspections_started_total", board, count(starts)),
        ("bakery_inspections_passed_total", board, count(by["passed"])),
        ("bakery_inspections_failed_total", board, count(by["failed"])),
        ("bakery_orders_cancelled_inspecting_total", board, count(by["cancelled"])),
        ("bakery_inspections_total", chef, count(done)),
        ("bakery_orders_inspecting", board, level(baked, done)),
        ("bakery_chef_busy", chef, level(starts, done)),
    ]


def test_the_chef_busy_flag_is_the_inspecting_stocks_capacity_of_one():
    dump = _inspections()
    assert max(v for _, v in dump[-2][2]) >= 2 and {v for _, v in dump[-1][2]} == {0.0, 1.0}
    m = discover(dump, start=T0, end=T0 + HOUR, step=30.0)
    ids = {s.id for s in m.stocks}
    assert "bakery_orders_inspecting" in ids and "bakery_chef_busy" not in ids, ids
    flows = {f.id for f in m.flows}
    assert not any("inspections_started" in f or f == "bakery_inspections_total" for f in flows), flows
    inspecting = next(s for s in m.stocks if s.id == "bakery_orders_inspecting")
    [view] = inspecting.evidence["views"]
    assert view["series"] == 'bakery_chef_busy{instrument="head_chef"}' and view["capacity"] == 1
    assert view["contained_steps"] == 1.0 and 0 < view["utilisation"] < 0.6
    assert view["starts"] == ['bakery_inspections_started_total{instrument="board"}']
    assert set(view["ends_as"]) == {'bakery_inspections_passed_total{instrument="board"}', 'bakery_inspections_failed_total{instrument="board"}',
                                    'bakery_orders_cancelled_inspecting_total{instrument="board"}'}
    left = m.discovery["left_out"]
    why = left['bakery_chef_busy{instrument="head_chef"}']
    assert why.startswith("a flag: the same items as bakery_orders_inspecting") and "capacity 1" in why, why
    assert "within that stock" in left['bakery_inspections_started_total{instrument="board"}']
    assert "bakery_chef_busy" not in {r["name"] for r in m.discovery["inputs"].values()}   # a flag is never an input


def _counter(name: str, per_step: list[float]) -> Series:
    v, vals = 0.0, [0.0]
    for d in per_step:
        v += d
        vals.append(v)
    return Series(name, {}, [(T0 + 30 * i, x) for i, x in enumerate(vals)], vals, True)


def _level(name: str, ins: list[Series], outs: list[Series]) -> Series:
    vals = [sum(c.values[i] for c in ins) - sum(c.values[i] for c in outs) for i in range(len(ins[0].values))]
    return Series(name, {}, [(T0 + 30 * i, x) for i, x in enumerate(vals)], vals, False)


def _at(*phases: int, first: dict[int, int] | None = None) -> list[float]:
    """One event at each of ``phases`` of every eight steps (``first``: a phase moved in the first eight)."""
    moved = {(first or {}).get(p, p) for p in phases}
    return [1.0 if i % 8 in (moved if i < 8 else phases) else 0.0 for i in range(120)]


# the U1 snapshot's shape on a small grid, every eight steps: orders A and B baked, the chef starts
# A at once and B when A is done; C baked and started a step later, then done. The orders
# inspecting reach two; the flag never exceeds them
BAKED, STARTED, DONE = _at(0, 1, 4), _at(0, 2, 5), _at(2, 3, 6)


def _station():
    baked, started, done = _counter("baked", BAKED), _counter("started", STARTED), _counter("done", DONE)
    passed = _counter("passed", DONE)
    inspecting = _level("inspecting", [baked], [passed])
    busy = _level("busy", [started], [done])
    return baked, started, done, passed, inspecting, busy


def _same(a, b):
    return same_events(a.deltas, b.deltas)


def _views(found):
    left: dict[str, str] = {}
    kept, views, notes = capacity_views(found, {s.key: list(range(120)) for s, *_ in found}, left, _same)
    return kept, views, notes, left


def test_a_flag_whose_items_are_another_stocks_is_its_view():
    baked, started, done, passed, inspecting, busy = _station()
    assert is_flag(busy) and max(inspecting.values) == 2
    kept, views, notes, left = _views([(inspecting, [(baked, 1), (passed, -1)], 1.0, 1.0), (busy, [(started, 1), (done, -1)], 1.0, 1.0)])
    assert [x[0].name for x in kept] == ["inspecting"]
    [view] = views["inspecting"]
    assert view["series"] == "busy" and view["ends_as"] == ["passed"] and view["contained_steps"] == 1.0
    assert view["utilisation"] == round(sum(busy.values[1:]) / 120, 4)
    assert left["busy"].startswith("a flag: the same items as inspecting") and set(notes) == {"started", "done"}


def test_a_declared_flag_is_never_judged():
    baked, started, done, passed, inspecting, busy = _station()
    found = [(inspecting, [(baked, 1), (passed, -1)], 1.0, 1.0), (busy, [(started, 1), (done, -1)], 1.0, 1.0)]
    kept, views, _ = capacity_views(found, {s.key: list(range(120)) for s in (inspecting, busy)}, {}, _same, {"busy"})
    assert len(kept) == 2 and not views


def test_a_shelf_fed_by_another_stocks_outflow_stays_a_stock():
    # the shelf of 0 and 1 the inspections passed fill, inside the customers waiting (who leave
    # as their order is picked up): its items arrive from a stock of the model
    baked, _, _, passed, inspecting, _ = _station()
    picked, ordered = _counter("picked", _at(3, 4, 7)), _counter("ordered", BAKED)
    shelf = _level("shelf", [passed], [picked])
    waiting = _level("customers_waiting", [ordered], [picked])
    assert is_flag(shelf) and all(b <= a for a, b in zip(waiting.values, shelf.values))
    kept, views, _, _ = _views([(inspecting, [(baked, 1), (passed, -1)], 1.0, 1.0), (shelf, [(passed, 1), (picked, -1)], 1.0, 1.0),
                                (waiting, [(ordered, 1), (picked, -1)], 1.0, 1.0)])
    assert len(kept) == 3 and not views


def test_the_state_after_a_stock_fed_by_its_outflow_stays_a_stock():
    # ready for review, filled by in progress's outflow and drained within the step but once: a
    # state after in progress, though in progress holds as much in all but one step (UC-2)
    started, sent = _counter("started", _at(0)), _counter("sent", _at(2))
    taken = _counter("taken", _at(2, first={2: 3}))
    in_progress, ready = _level("in_progress", [started], [sent]), _level("ready", [sent], [taken])
    assert is_flag(ready) and sum(1 for a, b in zip(in_progress.values, ready.values) if b > a) == 1
    kept, views, _, _ = _views([(in_progress, [(started, 1), (sent, -1)], 1.0, 1.0), (ready, [(sent, 1), (taken, -1)], 1.0, 1.0)])
    assert len(kept) == 2 and not views


def test_a_contained_flag_whose_items_leave_by_other_events_stays_a_stock():
    # a flag inside the customers waiting whose items leave by events of their own, two steps
    # before a customer is served: not the same items
    _, started, done, _, _, busy = _station()
    ordered, served = _counter("ordered", BAKED), _counter("served", [0.0, 0.0, *DONE[:-2]])
    waiting = _level("customers_waiting", [ordered], [served])
    assert all(b <= a for a, b in zip(waiting.values, busy.values))
    kept, views, _, _ = _views([(waiting, [(ordered, 1), (served, -1)], 1.0, 1.0), (busy, [(started, 1), (done, -1)], 1.0, 1.0)])
    assert len(kept) == 2 and not views
