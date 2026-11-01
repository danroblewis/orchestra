"""A level that counts a stock's servers busy is that stock's capacity (sd.capacity): the head
chef's busy flag, balanced exactly by inspections started less inspections done, holds one of the
orders inspecting while the chef works on it. UC-1's run of 2026-11-01 (the U1 snapshot) kept it
as a seventh stock: 114 baked and 114 started, 113 inspections done and 77 passed + 30 failed + 6
cancelled while inspecting, the flag never above the orders inspecting (121 of 121 steps), busy a
quarter of the time. The orders under inspection were counted twice and the flag's inflow came
from outside. A flag fed by another stock's flow (the shelf, fed by the inspections passed; the
state after a stock, fed by its outflow) is a stock of its own and stays one, and so is another
machine's count of its own work (UC-3's agents at work). Judged on the series' own writes, the
outcome is the same at every step of the grid."""

import random

from orchestra.sd.capacity import capacity, capacity_views
from orchestra.sd.discover import discover
from orchestra.sd.series import Series

T0 = 1_800_000_000.0
HOUR = 3600.0


def _inspections(seed: int = 7, chefs: int = 1, lag: float = 0.0):
    """The bakery's inspection station: orders baked about every 31 s (16 s for two chefs), the
    head chefs inspecting them in turn (5 to 20 s each, 28 for two), each passed (70%), failed
    (25%) or cancelled while inspecting; the chefs report each inspection done ``lag`` seconds
    after the board records its outcome."""
    rng = random.Random(seed)
    t, baked = 0.0, []
    while True:
        t += rng.expovariate(1 / (31 if chefs == 1 else 16))
        if t >= HOUR - 60:
            break
        baked.append(t)
    free, starts, ends = [0.0] * chefs, [], []
    for b in baked:
        k = min(range(chefs), key=lambda i: free[i])
        s = max(b, free[k])
        e = s + rng.uniform(5, 20 if chefs == 1 else 28)
        r = rng.random()
        starts.append(s)
        ends.append((e, "passed" if r < 0.7 else "failed" if r < 0.95 else "cancelled"))
        free[k] = e + lag + 0.01
    ticks = [5.0 * i for i in range(int(HOUR / 5) + 1)]
    count = lambda ts: [(T0 + k, float(sum(1 for x in ts if x <= k))) for k in ticks]
    level = lambda ins, outs: [(T0 + k, float(sum(1 for x in ins if x <= k) - sum(1 for x in outs if x <= k))) for k in ticks]
    done = [e + lag for e, _ in ends]
    by = {w: [e for e, how in ends if how == w] for w in ("passed", "failed", "cancelled")}
    board, chef = {"instrument": "board"}, {"instrument": "head_chef"}
    return [
        ("bakery_orders_baked_total", board, count(baked)),
        ("bakery_inspections_started_total", board, count(starts)),
        ("bakery_inspections_passed_total", board, count(by["passed"])),
        ("bakery_inspections_failed_total", board, count(by["failed"])),
        ("bakery_orders_cancelled_inspecting_total", board, count(by["cancelled"])),
        ("bakery_inspections_total", chef, count(done)),
        ("bakery_orders_inspecting", board, level(baked, [e for e, _ in ends])),
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
    [view] = inspecting.evidence["capacity_of"]
    assert view["series"] == 'bakery_chef_busy{instrument="head_chef"}' and view["capacity"] == 1
    assert 0 < view["utilisation"] < 0.6 and view["utilisation"] == view["mean_occupancy"]
    assert view["starts"] == ['bakery_inspections_started_total{instrument="board"}']
    assert set(view["ends_as"]) == {'bakery_inspections_passed_total{instrument="board"}', 'bakery_inspections_failed_total{instrument="board"}',
                                    'bakery_orders_cancelled_inspecting_total{instrument="board"}'}
    left = m.discovery["left_out"]
    why = left['bakery_chef_busy{instrument="head_chef"}']
    assert why.startswith("the same items as bakery_orders_inspecting") and "capacity 1" in why, why
    assert "within that stock" in left['bakery_inspections_started_total{instrument="board"}']
    assert "bakery_chef_busy" not in {r["name"] for r in m.discovery["inputs"].values()}   # never an input


def _outcome(dump, step: float):
    m = discover(dump, start=T0, end=T0 + HOUR, step=step)
    return sorted(s.id for s in m.stocks), sorted((v["series"], v["capacity"], s.id) for s in m.stocks for v in s.evidence.get("capacity_of", []))


def test_the_outcome_is_the_same_at_every_step_with_the_chef_reporting_late():
    # the refuter's case: a chef who reports 2 s after the board was a view at 30 s and a stock
    # at 1, 5, 15 and 60 s when the check was a share of grid steps; on the series' writes it is a
    # view at every step, and one who reports 8 s late (beyond a 5 s write interval) a stock at every step
    for lag, merged in ((2.0, True), (8.0, False)):
        dump = _inspections(lag=lag)
        outcomes = {step: _outcome(dump, step) for step in (1.0, 5.0, 15.0, 30.0, 60.0)}
        assert len({repr(o) for o in outcomes.values()}) == 1, (lag, outcomes)
        stocks, caps = outcomes[30.0]
        assert ("bakery_chef_busy" not in stocks) == merged and bool(caps) == merged, (lag, stocks, caps)


def test_two_chefs_are_the_inspecting_stocks_capacity_of_two():
    dump = _inspections(chefs=2)
    assert max(v for _, v in dump[-1][2]) == 2
    m = discover(dump, start=T0, end=T0 + HOUR, step=30.0)
    assert "bakery_chef_busy" not in {s.id for s in m.stocks}
    [view] = next(s for s in m.stocks if s.id == "bakery_orders_inspecting").evidence["capacity_of"]
    assert view["capacity"] == 2 and view["utilisation"] == round(view["mean_occupancy"] / 2, 4)
    assert "capacity 2, busy" in m.discovery["left_out"]['bakery_chef_busy{instrument="head_chef"}']


BOARD = {"instrument": "board"}
END = T0 + 30 * 120


def _counter(name: str, per_step: list[float], labels: dict | None = None) -> Series:
    v, vals = 0.0, [0.0]
    for d in per_step:
        v += d
        vals.append(v)
    return Series(name, labels or BOARD, [(T0 + 30 * i, x) for i, x in enumerate(vals)], vals, True)


def _level(name: str, ins: list[Series], outs: list[Series], labels: dict | None = None) -> Series:
    vals = [sum(c.values[i] for c in ins) - sum(c.values[i] for c in outs) for i in range(len(ins[0].values))]
    return Series(name, labels or BOARD, [(T0 + 30 * i, x) for i, x in enumerate(vals)], vals, False)


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


def _views(found, protected=frozenset()):
    left: dict[str, str] = {}
    kept, views, notes = capacity_views(found, left, T0, END, protected)
    return kept, views, notes, left


def test_a_flag_whose_items_are_another_stocks_is_its_view():
    baked, started, done, passed, inspecting, busy = _station()
    assert capacity(busy, T0, END) == 1 and max(inspecting.values) == 2
    kept, views, notes, left = _views([(inspecting, [(baked, 1), (passed, -1)], 1.0, 1.0), (busy, [(started, 1), (done, -1)], 1.0, 1.0)])
    assert [x[0].name for x in kept] == ["inspecting"]
    [view] = views['inspecting{instrument="board"}']
    assert view["series"] == 'busy{instrument="board"}' and view["ends_as"] == ['passed{instrument="board"}']
    assert view["utilisation"] == round(sum(busy.values[:-1]) / 120, 4)
    assert left['busy{instrument="board"}'].startswith('the same items as inspecting{instrument="board"}')
    assert set(notes) == {'started{instrument="board"}', 'done{instrument="board"}'}


def test_a_declared_flag_is_never_judged():
    baked, started, done, passed, inspecting, busy = _station()
    found = [(inspecting, [(baked, 1), (passed, -1)], 1.0, 1.0), (busy, [(started, 1), (done, -1)], 1.0, 1.0)]
    kept, views, _, _ = _views(found, {busy.key})
    assert len(kept) == 2 and not views


def test_a_shelf_fed_by_another_stocks_outflow_stays_a_stock():
    # the shelf of 0 and 1 the inspections passed fill, inside the customers waiting (who leave
    # as their order is picked up): its items arrive from a stock of the model
    baked, _, _, passed, inspecting, _ = _station()
    picked, ordered = _counter("picked", _at(3, 4, 7)), _counter("ordered", BAKED)
    shelf = _level("shelf", [passed], [picked])
    waiting = _level("customers_waiting", [ordered], [picked])
    assert capacity(shelf, T0, END) == 1 and all(b <= a for a, b in zip(waiting.values, shelf.values))
    # (on this toy's 30 s writes the orders inspecting and the customers waiting, a write apart
    # throughout, are one quantity: the question here is only the shelf)
    kept, views, _, _ = _views([(inspecting, [(baked, 1), (passed, -1)], 1.0, 1.0), (shelf, [(passed, 1), (picked, -1)], 1.0, 1.0),
                                (waiting, [(ordered, 1), (picked, -1)], 1.0, 1.0)])
    assert any(x[0] is shelf for x in kept) and not any(r["series"] == shelf.key for rs in views.values() for r in rs)


def test_the_state_after_a_stock_fed_by_its_outflow_stays_a_stock():
    # ready for review, filled by in progress's outflow and drained within the step but once: a
    # state after in progress, though in progress holds as much in all but one step (UC-2)
    started, sent = _counter("started", _at(0)), _counter("sent", _at(2))
    taken = _counter("taken", _at(2, first={2: 3}))
    in_progress, ready = _level("in_progress", [started], [sent]), _level("ready", [sent], [taken])
    assert capacity(ready, T0, END) == 1 and sum(1 for a, b in zip(in_progress.values, ready.values) if b > a) == 1
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


def test_another_machines_count_of_its_own_work_stays_a_stock():
    # UC-3: the reviewer agent at work, one turn per ticket in review, its turns counted by the
    # agents' instrument: that machine's stock, not the tickets' capacity (who serves a flow is a hypothesis)
    baked, _, _, passed, inspecting, _ = _station()
    agents = {"instrument": "agents.turns"}
    started, done = _counter("turns_started", STARTED, agents), _counter("turns_finished", DONE, agents)
    working = _level("agents_working", [started], [done], agents)
    kept, views, _, _ = _views([(inspecting, [(baked, 1), (passed, -1)], 1.0, 1.0), (working, [(started, 1), (done, -1)], 1.0, 1.0)])
    assert len(kept) == 2 and not views
