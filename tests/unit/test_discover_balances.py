"""Discovery's balances on synthetic series, each case the shape of a bakery failure: a level's
stale value from before a silence, a collinear group of counters, a gauge that drives a flow,
Orchestra's event counter standing in for the machine counters it sums, another machine's copy of
a machine's own counters, and one flow counted by two machines."""

import math
import random
from itertools import accumulate

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.balance import LeastSquares, balance
from orchestra.sd.collinear import decompose
from orchestra.sd.discover import discover, sample
from orchestra.sd.series import Series

T0 = 1_800_000_000.0


def run(store, minutes, rates, levels, machines, *, seed=1, silent=None, extra=None):
    """Counters fired by Poisson draws at ``rates`` per minute (a number, or a function of the
    time), each level ``{counter: sign}`` summed from them; every series written each second by
    its machine, except while ``silent(name, t)``. ``extra(t, counts) -> [Point]`` adds other series."""
    rng = random.Random(seed)
    counts = dict.fromkeys(rates, 0)
    value = dict.fromkeys(levels, 0)
    pts = []
    for i in range(minutes * 60):
        t = T0 + i
        for k, r in rates.items():
            rate = r(t) if callable(r) else r
            n = sum(1 for _ in range(3) if rng.random() < rate / 180)
            counts[k] += n
            for lv, terms in levels.items():
                value[lv] += terms.get(k, 0) * n
        for name, v in [*counts.items(), *value.items()]:
            if not (silent and silent(name, t)):
                pts.append(Point(name, v, t, {"project": "p", "machine": machines[name]}))
        if extra:
            pts += extra(t, counts)
    store.write(pts)
    return T0, T0 + minutes * 60


def balance_of(m, sid):
    return {(b["series"].split("{")[0], b["sign"]) for b in m.stock(sid).evidence["balance"]}


def test_a_level_silent_with_a_stale_value_still_balances_exactly(tmp_path):
    # the board was restarted with a cleared state: its waiting level was last written long before
    # the window (11 orders) and is written again only from the window's second third, at 0. The
    # stale 11 carried to the first fresh value is not a change any counter explains; the balance
    # is found on the steps the level was being written, and the stock is exact there.
    store = FileMetrics(tmp_path / "m.jsonl")
    store.write([Point("waiting", 11, T0 - 3000, {"project": "p", "machine": "board"})])
    rates = {"in_total": 6.0, "out_total": 5.0}
    machines = {**dict.fromkeys(rates, "board"), "waiting": "board"}
    start, end = run(store, 60, rates, {"waiting": {"in_total": 1, "out_total": -1}}, machines,
                     silent=lambda name, t: name == "waiting" and t < T0 + 1200)
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert [s.id for s in m.stocks] == ["waiting"], m.discovery["left_out"]
    ev = m.stock("waiting").evidence
    assert ev["exact_steps"] == 1.0 and ev["balance_r2"] == 1.0
    assert ev["balance_steps"] < ev["steps"] == 120, "the silent third is cut, and the cut is recorded"
    assert balance_of(m, "waiting") == {("in_total", 1), ("out_total", -1)}


def test_a_collinear_group_gives_way_to_the_counter_that_is_their_sum(tmp_path):
    # c counts a and b together (orders queued = taken + app orders); the level moves by +c −d. The
    # balance is {+c, −d}: never {+a, +b, −d}, which fits the same and costs a penalty more. Least
    # squares, pulled about by the collinear counters, may land on a and b (it did on the bakery),
    # and a search that changes one counter at a time cannot leave that: the group is traded as a
    # whole for the counter that is its sum, and the search also starts from each pair.
    rng = random.Random(3)
    a = [rng.choice([0, 0, 1, 2]) for _ in range(3600)]
    b = [rng.choice([0, 0, 0, 1]) for _ in range(3600)]
    d = [rng.choice([0, 0, 1, 1]) for _ in range(3600)]
    pts, ca, cb, cd, level = [], 0, 0, 0, 50
    for i in range(3600):
        ca, cb, cd = ca + a[i], cb + b[i], cd + d[i]
        level += a[i] + b[i] - d[i]
        for name, v in (("a_total", ca), ("b_total", cb), ("c_total", ca + cb), ("d_total", cd), ("level", level)):
            pts.append(Point(name, v, T0 + i, {"project": "p", "machine": "m"}))
    store = FileMetrics(tmp_path / "m.jsonl")
    store.write(pts)
    m = discover(store.dump("", {"project": "p"}), start=T0, end=T0 + 3600, step=30)
    assert [s.id for s in m.stocks] == ["level"]
    assert balance_of(m, "level") == {("c_total", 1), ("d_total", -1)}, m.stock("level").evidence["balance"]

    series = {s.key: s for s in sample(store.dump("", {"project": "p"}), T0, 30, 120)}
    counters = [series[k] for k in ('a_total{machine="m"}', 'b_total{machine="m"}', 'c_total{machine="m"}', 'd_total{machine="m"}')]

    class LandsOnTheParts(LeastSquares):
        def solve(self, y):
            return [1.0, 1.0, 0.0, -1.0]
    terms, _, exact = balance(series['level{machine="m"}'], counters, LandsOnTheParts([c.deltas for c in counters]))
    assert [(c.name, s) for c, s in terms] == [("c_total", 1), ("d_total", -1)] and exact == 1.0


def test_a_flow_whose_rate_follows_a_gauge_reads_the_gauge(tmp_path):
    # the arrivals' rate follows the rating (a measured gauge that is not a stock), not any stock:
    # the gauge is offered to the fit beside the stocks and chosen by AIC, as input:<name>
    store = FileMetrics(tmp_path / "m.jsonl")
    rating = lambda t: round(3.0 + 2.0 * math.sin(2 * math.pi * (t - T0) / 1200), 2)     # 1 to 5, a 20 min cycle
    rates = {"arrived_total": lambda t: 1.2 * rating(t), "served_total": 4.0}
    machines = {**dict.fromkeys(rates, "shop"), "waiting": "shop"}
    start, end = run(store, 90, rates, {"waiting": {"arrived_total": 1, "served_total": -1}}, machines,
                     extra=lambda t, _: [Point("yelp_rating", rating(t), t, {"project": "p", "machine": "yelp"})])
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert [s.id for s in m.stocks] == ["waiting"]
    eq = m.flow("arrived_total").current()
    assert eq.form == "proportional" and eq.inputs == ["input:yelp_rating"] and eq.origin == "fitted", (eq.form, eq.inputs, eq.quality)
    assert abs(eq.params["k"] - 1.2) < 0.15, eq.params
    assert "yelp_rating" in m.discovery["inputs"], "the gauge is recorded as an input the model reads"


def test_an_event_counter_gives_way_to_the_machine_counters_it_sums(tmp_path):
    # order.rejected is returns plus refunds: the one event counter is cheaper for the accepting
    # stock's balance, and a refund with few events can never pay its way alone; but returns go
    # back to the waiting stock (another stock claims them), so the parts are the flows
    store = FileMetrics(tmp_path / "m.jsonl")
    rates = {"picked_total": 6.0, "accepted_total": 5.2, "returns_total": 0.6, "refunds_total": 0.1, "assigned_total": 0.6}
    machines = {**dict.fromkeys(rates, "board"), "accepting": "board", "waiting": "board",
                "returns_total": "customers", "refunds_total": "customers"}
    last = [None]

    def rejected(t, counts):                       # Orchestra's count, written when an event comes
        n = counts["returns_total"] + counts["refunds_total"]
        if n == last[0]:
            return []
        last[0] = n
        return [Point("orchestra_events_total", n, t, {"project": "p", "source": "customers", "type": "order.rejected"})]
    start, end = run(store, 90, rates, {"accepting": {"picked_total": 1, "accepted_total": -1, "returns_total": -1, "refunds_total": -1},
                                         "waiting": {"returns_total": 1, "assigned_total": -1}}, machines, extra=rejected)
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert balance_of(m, "accepting") == {("picked_total", 1), ("accepted_total", -1), ("returns_total", -1), ("refunds_total", -1)}, \
        m.stock("accepting").evidence["balance"]
    f = {x.id: x for x in m.flows}
    assert (f["returns_total"].src, f["returns_total"].dst) == ("accepting", "waiting")
    assert f["refunds_total"].src == "accepting"
    assert not any(x.counter and x.counter.name == "orchestra_events_total" for x in m.flows)
    why = [v for k, v in m.discovery["left_out"].items() if k.startswith("orchestra_events_total")]
    assert why and why[0].startswith("the same as"), why


def test_another_machines_copy_does_not_replace_a_machines_own_counters(tmp_path):
    # every customer served or giving up posts a review: yelp's count equals the two customers'
    # counters summed, and would balance the customers' waiting in one term; the customers'
    # waiting is the customers' to account for, and the copy is left out
    store = FileMetrics(tmp_path / "m.jsonl")
    rates = {"ordered_total": 6.0, "served_total": 5.0, "gave_up_total": 0.8}
    machines = {**dict.fromkeys(rates, "customers"), "waiting": "customers"}
    start, end = run(store, 60, rates, {"waiting": {"ordered_total": 1, "served_total": -1, "gave_up_total": -1}}, machines)
    served = store.raw("served_total", {"project": "p", "machine": "customers"})
    gave = store.raw("gave_up_total", {"project": "p", "machine": "customers"})
    store.write([Point("yelp_reviews_total", a[1] + b[1], a[0], {"project": "p", "machine": "yelp"}) for a, b in zip(served, gave)])
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert balance_of(m, "waiting") == {("ordered_total", 1), ("served_total", -1), ("gave_up_total", -1)}, m.stock("waiting").evidence["balance"]
    assert 'yelp_reviews_total{machine="yelp"}' in m.discovery["left_out"]


def test_one_flow_counted_by_two_machines_joins_the_stocks(tmp_path):
    # the board counts an order picked up and the shelf counts it handed over: the same events,
    # written by two machines. Each stock takes its own machine's count; they are one flow, from
    # the shelf's stock to the board's, not one out to outside and another in from it.
    store = FileMetrics(tmp_path / "m.jsonl")
    rates = {"passed_total": 6.0, "picked_total": 5.5, "accepted_total": 5.5}
    machines = {**dict.fromkeys(rates, "board"), "on_shelf": "board", "accepting": "board"}
    start, end = run(store, 60, rates, {"on_shelf": {"passed_total": 1, "picked_total": -1},
                                         "accepting": {"picked_total": 1, "accepted_total": -1}}, machines)
    picked = store.raw("picked_total", {"project": "p", "machine": "board"})
    on_shelf = store.raw("on_shelf", {"project": "p", "machine": "board"})
    store.write([Point("handed_total", v, t, {"project": "p", "machine": "shelf"}) for t, v in picked]
                + [Point("shelf_items", v, t, {"project": "p", "machine": "shelf"}) for t, v in on_shelf])
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert m.check() == []
    f = {x.id: x for x in m.flows}
    joins = [x for x in m.flows if x.src and x.dst and x.dst == "accepting"]
    assert len(joins) == 1 and joins[0].src in ("on_shelf", "shelf_items"), [(x.id, x.src, x.dst) for x in m.flows]
    assert not [x for x in m.flows if x.src is None and x.dst == "accepting"], f.keys()


def test_another_machines_counter_never_replaces_the_machines_own_balance(tmp_path):
    # the board's waiting count is balanced by its own arrivals and departures, which it stamps a
    # second after the count (the few at a step's edge land in the next step: the balance is
    # within tolerance, not exact). The till counts every departure too, stamped with the
    # count, so it would balance the count exactly, in as few terms. The count is the board's to
    # account for: its own counters keep it, and another machine's enters only to explain what
    # they leave, which here is noise at the edges.
    rng = random.Random(4)
    lab = lambda m: {"project": "p", "machine": m}
    waiting = arrived = served = 0
    pts = []
    for i in range(60 * 60):
        t = T0 + i
        if rng.random() < 0.1:
            arrived, waiting = arrived + 1, waiting + 1
            pts += [Point("arrived_total", arrived, t, lab("board")), Point("waiting", waiting, t, lab("board"))]
        if waiting and rng.random() < 0.09:
            served, waiting = served + 1, waiting - 1
            pts += [Point("waiting", waiting, t, lab("board")), Point("served_total", served, t + 1, lab("board")),
                    Point("receipts_total", served, t, lab("till"))]
    store = FileMetrics(tmp_path / "m.jsonl")
    store.write(sorted(pts, key=lambda p: p.ts))
    m = discover(store.dump("", {"project": "p"}), start=T0, end=T0 + 3600, step=30)
    assert [s.id for s in m.stocks] == ["waiting"], m.discovery["left_out"]
    ev = m.stock("waiting").evidence
    assert balance_of(m, "waiting") == {("arrived_total", 1), ("served_total", -1)}, ev["balance"]
    assert 0.9 <= ev["balance_r2"] < 1.0 and ev["exact_steps"] < 0.97, "within tolerance, not exact"
    assert 'receipts_total{machine="till"}' in m.discovery["left_out"]


def test_a_level_and_a_counter_that_coincide_on_a_few_steps_are_no_stock_and_flow(tmp_path):
    # a planner woken three times, each wake counted: the level changes on three steps and the
    # counter moves on the same three. Three coincidences are no conservation law. Nor is a level
    # that moves six times balanced by two counters of three events each: counters that counted
    # too few events may complete a balance, never carry one.
    lab = lambda m: {"project": "p", "machine": m}
    pts = []
    for i in range(60 * 60):
        t = T0 + i
        wakes = sum(1 for w in (600, 1500, 2400) if i >= w)
        ups, downs = sum(1 for w in (300, 600, 900) if i >= w), sum(1 for w in (1500, 2100, 2700) if i >= w)
        pts += [Point("planner_awake", wakes, t, lab("planner")), Point("planner_wakes_total", wakes, t, lab("planner")),
                Point("shelf_items", ups - downs, t, lab("shelf")), Point("shelf_put_total", ups, t, lab("shelf")),
                Point("shelf_taken_total", downs, t, lab("shelf"))]
    store = FileMetrics(tmp_path / "m.jsonl")
    store.write(pts)
    m = discover(store.dump("", {"project": "p"}), start=T0, end=T0 + 3600, step=30)
    assert m.stocks == [] and m.flows == [], [(s.id, s.evidence) for s in m.stocks]
    why = m.discovery["left_out"]
    assert "changed in only 3 steps" in why['planner_awake{machine="planner"}'], why
    assert "only 3 events" in why['planner_wakes_total{machine="planner"}'], why
    assert why['shelf_items{machine="shelf"}'].startswith("no counters balance it"), why
    assert "only 3 events" in why['shelf_put_total{machine="shelf"}'] and "only 3 events" in why['shelf_taken_total{machine="shelf"}']


def test_an_event_counter_splits_into_the_levels_own_machines_counters_first(tmp_path):
    # Orchestra counts an order queued, for the board, whenever an order is placed or rejected
    # back to the queue; the customers count every rejection too, as a return, stamped with the
    # board's, and the expo keeps a copy of the queue. The board's rejected and the customers'
    # return split the event count alike, and the customers' key happens to be the shorter. The
    # waiting orders are the board's record: its own rejected is the part, whichever set the search
    # meets first, and the customers' copy is left out. (The copy of the queue is a twin, dropped
    # later; while it is in the running it may claim the same counters, which on the bakery barred
    # the pass that would otherwise have swapped the customers' copy for the board's own.)
    store = FileMetrics(tmp_path / "m.jsonl")
    rates = {"orders_placed_total": 6.0, "orders_rejected_total": 0.8, "orders_assigned_total": 6.5}
    machines = {**dict.fromkeys(rates, "board"), "waiting": "board"}
    last = [None]

    def copies(t, counts):
        out = [Point("returns_total", counts["orders_rejected_total"], t, {"project": "p", "machine": "customers"}),
               Point("bake_queue", counts["orders_placed_total"] + counts["orders_rejected_total"] - counts["orders_assigned_total"], t,
                     {"project": "p", "machine": "expo"})]
        n = counts["orders_placed_total"] + counts["orders_rejected_total"]
        if n != last[0]:
            last[0] = n
            out.append(Point("orchestra_events_total", n, t, {"project": "p", "source": "board", "type": "order.queued"}))
        return out
    start, end = run(store, 90, rates, {"waiting": {"orders_placed_total": 1, "orders_rejected_total": 1, "orders_assigned_total": -1}},
                     machines, extra=copies)
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert balance_of(m, "waiting") == {("orders_placed_total", 1), ("orders_rejected_total", 1), ("orders_assigned_total", -1)}, \
        m.stock("waiting").evidence["balance"]
    assert m.flow("orders_rejected_total").dst == "waiting"
    assert 'returns_total{machine="customers"}' in m.discovery["left_out"], m.discovery["left_out"]


def test_decompose_breaks_a_tie_for_the_levels_own_machines_parts():
    # the pool is in key order, so the committed search met the customers' copy first and stopped
    # at the first exact set; among exact sets the one with the fewest parts another machine wrote
    # wins, then the smallest
    rng = random.Random(6)
    placed = [rng.choice([0, 1, 1, 2]) for _ in range(60)]
    rejected = [rng.choice([0, 0, 0, 1]) for _ in range(60)]
    cum = lambda xs: [0.0, *accumulate(xs)]
    mk = lambda name, labels, xs: Series(name, labels, [], cum(xs), True)
    queued = mk("orchestra_events_total", {"source": "board", "type": "order.queued"}, [a + b for a, b in zip(placed, rejected)])
    pool = [mk("returns_total", {"machine": "customers"}, rejected), mk("orders_placed_total", {"machine": "board"}, placed),
            mk("orders_rejected_total", {"machine": "board"}, rejected)]
    steps = list(range(60))
    assert [p.key for p in decompose(queued, pool, steps)] == ['returns_total{machine="customers"}', 'orders_placed_total{machine="board"}']
    own = {'orders_placed_total{machine="board"}', 'orders_rejected_total{machine="board"}'}
    assert [p.key for p in decompose(queued, pool, steps, own=own)] == ['orders_placed_total{machine="board"}', 'orders_rejected_total{machine="board"}']


def test_a_stock_whose_balance_counts_the_flows_own_events_does_not_drive_it(tmp_path):
    # orders come at the rate the rating sets: most through a taker, who is free again at the
    # instant the order is placed (the takers' count of orders taken is a part of the board's
    # count of orders placed: the same events), the rest online. The free takers just before each
    # placing are one fewer by construction, and as an influence that beats the rating on
    # likelihood; the takers are no driver of placed, and the rating is read
    rng = random.Random(5)
    lab = lambda m: {"project": "p", "machine": m}
    rating = lambda t: round(3.0 + 2.0 * math.sin(2 * math.pi * (t - T0) / 1200), 2)
    free, busy_until = 2, []
    placed = taken = called = served = waiting = 0
    pts = []
    for i in range(90 * 60):
        t = T0 + i
        for u in [u for u in busy_until if u <= t]:          # a taker finishes: the order is placed
            busy_until.remove(u)
            free, taken, placed, waiting = free + 1, taken + 1, placed + 1, waiting + 1
        if rng.random() < 0.9 * rating(t) / 60 and free:     # a customer walks in and a taker takes the order
            free, called = free - 1, called + 1
            busy_until.append(t + rng.randint(3, 8))
        if rng.random() < 0.3 * rating(t) / 60:              # an order placed online, no taker involved
            placed, waiting = placed + 1, waiting + 1
        if waiting and rng.random() < 0.1:
            served, waiting = served + 1, waiting - 1
        pts += [Point("orders_placed_total", placed, t, lab("board")), Point("orders_waiting", waiting, t, lab("board")),
                Point("orders_served_total", served, t, lab("board")), Point("orders_taken_total", taken, t, lab("taker")),
                Point("customers_called_total", called, t, lab("expo")), Point("takers_free", free, t, lab("expo")),
                Point("yelp_rating", rating(t), t, lab("yelp"))]
    store = FileMetrics(tmp_path / "m.jsonl")
    store.write(pts)
    m = discover(store.dump("", {"project": "p"}), start=T0, end=T0 + 5400, step=30)
    assert {s.id for s in m.stocks} == {"orders_waiting", "takers_free"}, m.discovery["left_out"]
    f = m.flow("orders_placed_total")
    eq = f.current()
    assert eq.inputs == ["input:yelp_rating"], (eq.form, eq.inputs, eq.quality)
    assert "orders_taken_total" in f.evidence["not_drivers"]["takers_free"], f.evidence


def test_a_terminal_level_fed_only_by_another_stocks_outflow_is_a_stock(tmp_path):
    # orders go from baking to delivered; delivered only ever fills, by the very counter that
    # drains baking. A level that is measured and exactly balanced is a stock whatever feeds it:
    # that is what a terminal state is, and the flow ends in it instead of outside
    store = FileMetrics(tmp_path / "m.jsonl")
    rates = {"started_total": 5.0, "finished_total": 4.5}
    machines = {**dict.fromkeys(rates, "board"), "baking": "board", "delivered": "board"}
    start, end = run(store, 60, rates, {"baking": {"started_total": 1, "finished_total": -1}, "delivered": {"finished_total": 1}}, machines)
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert {s.id for s in m.stocks} == {"baking", "delivered"}, m.discovery["left_out"]
    assert m.stock("delivered").evidence["accumulator"] and balance_of(m, "delivered") == {("finished_total", 1)}
    f = m.flow("finished_total")
    assert (f.src, f.dst) == ("baking", "delivered")


def events_each_second(seconds, step, *, seed=1):
    """A toy run written as things happen: ``step(rng, t) -> [Point]`` each second."""
    rng = random.Random(seed)
    pts = []
    for i in range(seconds):
        pts += step(rng, T0 + i)
    return sorted(pts, key=lambda p: p.ts)


def test_one_event_counted_by_two_machines_is_one_flow_and_a_co_flow(tmp_path):
    # the board starts an order (its waiting drops, its baking rises) and the oven counts the same
    # loaf loaded (its loaves rise): one event, counted by two machines, moving each one's own
    # material. One counter is kept in every balance: the board's, which moves material between
    # its own stocks; so there is one flow, waiting -> baking, and a co-flow of the same events
    # into the oven's loaves, with one equation (one event has one rate), proportional to the
    # waiting orders, which none of the stocks the event moves is kept from driving
    lab = lambda m: {"project": "p", "machine": m}
    st = {"waiting": 0, "baking": 0, "loaves": 0, "placed": 0, "started": 0, "baked": 0, "loaded": 0, "cooled": 0}

    def tick(rng, t):
        out = []
        if rng.random() < 0.1:
            st["placed"] += 1; st["waiting"] += 1
            out += [Point("placed_total", st["placed"], t, lab("board")), Point("waiting", st["waiting"], t, lab("board"))]
        if st["waiting"] and rng.random() < 0.04 * st["waiting"]:
            st["started"] += 1; st["loaded"] += 1; st["waiting"] -= 1; st["baking"] += 1; st["loaves"] += 1
            out += [Point("started_total", st["started"], t, lab("board")), Point("waiting", st["waiting"], t, lab("board")),
                    Point("baking", st["baking"], t, lab("board")), Point("loaded_total", st["loaded"], t, lab("oven")),
                    Point("oven_loaves", st["loaves"], t, lab("oven"))]
        if st["baking"] and rng.random() < 0.05 * st["baking"]:
            st["baked"] += 1; st["baking"] -= 1
            out += [Point("baked_total", st["baked"], t, lab("board")), Point("baking", st["baking"], t, lab("board"))]
        if st["loaves"] and rng.random() < 0.05 * st["loaves"]:
            st["cooled"] += 1; st["loaves"] -= 1
            out += [Point("cooled_total", st["cooled"], t, lab("oven")), Point("oven_loaves", st["loaves"], t, lab("oven"))]
        return out
    store = FileMetrics(tmp_path / "m.jsonl")
    store.write(events_each_second(3600, tick, seed=9))
    m = discover(store.dump("", {"project": "p"}), start=T0, end=T0 + 3600, step=30)
    assert m.check() == []
    assert {s.id for s in m.stocks} == {"waiting", "baking", "oven_loaves"}, m.discovery["left_out"]
    f = {x.id: x for x in m.flows}
    assert (f["started_total"].src, f["started_total"].dst) == ("waiting", "baking"), [(x.id, x.src, x.dst) for x in m.flows]
    co = f["started_total@oven"]
    assert (co.src, co.dst) == (None, "oven_loaves") and co.evidence["co_flow_of"] == "started_total"
    assert f["started_total"].evidence["co_flows"] == ["started_total@oven"]
    assert not any(x.src is None and x.dst == "oven_loaves" and x.id != co.id for x in m.flows)
    assert 'loaded_total{machine="oven"}' in m.discovery["left_out"]
    assert [o["name"] for o in f["started_total"].evidence["same_as"]] == ["loaded_total"]
    assert not ({"baking", "oven_loaves"} & set(f["started_total"].evidence.get("not_drivers", {}))), f["started_total"].evidence
    eq = f["started_total"].current()
    assert eq.form == "proportional" and eq.inputs == ["waiting"], (eq.form, eq.inputs, eq.quality)
    assert abs(eq.params["k"] - 2.4) < 0.5, eq.params
    assert co.current() == eq, "the co-flow is the same events: one equation"


def test_a_counter_stamped_a_moment_after_another_of_the_same_events_joins_the_stocks(tmp_path):
    # the board moves an order from waiting to the pass and, a second later when the kitchen takes
    # it, from the pass to cooking: the same events counted twice, a few of them across a step's
    # edge, and the pass never seen held on the grid (no stock between the two). They are one flow
    # from waiting to cooking, not one out to outside and another in from it; the counter stamped
    # first is kept and the other is recorded on it
    lab = lambda m: {"project": "p", "machine": m}
    st = {"waiting": 0, "cooking": 0, "placed": 0, "handed": 0, "received": 0, "cooked": 0}

    def tick(rng, t):
        out = []
        if rng.random() < 0.1:
            st["placed"] += 1; st["waiting"] += 1
            out += [Point("placed_total", st["placed"], t, lab("board")), Point("waiting", st["waiting"], t, lab("board"))]
        if st["cooking"] and rng.random() < 0.05 * st["cooking"]:
            st["cooked"] += 1; st["cooking"] -= 1
            out += [Point("cooked_total", st["cooked"], t, lab("board")), Point("cooking", st["cooking"], t, lab("board"))]
        if st["waiting"] and rng.random() < 0.04 * st["waiting"]:
            st["handed"] += 1; st["waiting"] -= 1; st["received"] += 1; st["cooking"] += 1
            out += [Point("handed_total", st["handed"], t, lab("board")), Point("waiting", st["waiting"], t, lab("board")),
                    Point("received_total", st["received"], t + 1, lab("board")), Point("cooking", st["cooking"], t + 1, lab("board"))]
        return out
    store = FileMetrics(tmp_path / "m.jsonl")
    store.write(events_each_second(3600, tick, seed=10))
    m = discover(store.dump("", {"project": "p"}), start=T0, end=T0 + 3600, step=30)
    assert m.check() == []
    assert {s.id for s in m.stocks} == {"waiting", "cooking"}, m.discovery["left_out"]
    [f] = [x for x in m.flows if x.src == "waiting"]
    assert (f.id, f.dst) == ("handed_total", "cooking"), [(x.id, x.src, x.dst) for x in m.flows]
    assert [o["name"] for o in f.evidence["same_as"]] == ["received_total"]
    assert not [x for x in m.flows if x.src is None and x.dst == "cooking"]
    assert m.discovery["left_out"]['received_total{machine="board"}'].startswith("the same as")


def test_two_lagged_counters_with_a_stock_between_them_stay_its_inflow_and_outflow():
    # on the grid, y counts x's events, a few of them a step later. With nothing between them
    # measured, the balances take one counter (the one stamped first); with a stock whose balance
    # is +x -y (the pass: handed over, picked up a moment later), x and y are its inflow and
    # outflow and both stay, so the flows run A -> B -> C
    from orchestra.sd.drivers import behind
    from orchestra.sd.restate import unify_same_flows
    n = 100
    cum = lambda xs: [0.0, *accumulate(xs)]
    mk = lambda name, m, xs, counter=True: Series(name, {"machine": m}, [], cum(xs), counter)
    dx = [1.0 if i % 2 == 0 else 0.0 for i in range(n)]
    dy = list(dx)
    for i in (20, 60):                                    # two events recorded a step late
        dy[i], dy[i + 1] = 0.0, 1.0
    din = [1.0 if i % 2 == 1 else 0.0 for i in range(n)]
    dout = [1.0 if i % 4 == 1 else 0.0 for i in range(n)]
    x, y, inn, out = mk("handed_total", "board", dx), mk("received_total", "kitchen", dy), mk("placed_total", "board", din), mk("cooked_total", "kitchen", dout)
    a = mk("waiting", "board", [i - o for i, o in zip(din, dx)], False)
    c = mk("cooking", "kitchen", [i - o for i, o in zip(dy, dout)], False)
    b = mk("pass", "board", [i - o for i, o in zip(dx, dy)], False)
    masks = {s.key: list(range(n)) for s in (a, b, c)}
    same = lambda p, q: behind(p.deltas, q.deltas) or behind(q.deltas, p.deltas)
    first = lambda p, q: p is x
    fits = lambda s, r2, exact: r2 >= 0.9
    found = [(a, [(inn, 1), (x, -1)], 1.0, 1.0), (c, [(y, 1), (out, -1)], 1.0, 1.0)]
    got, notes, joined = unify_same_flows(found, masks, same, first, lambda s: s.labels["machine"], fits)
    assert joined == [(x, y)] and y.key in notes
    assert [(k.name, sg) for k, sg in got[1][1]] == [("handed_total", 1), ("cooked_total", -1)] and 0.9 <= got[1][2] < 1.0
    found = [*found, (b, [(x, 1), (y, -1)], 1.0, 1.0)]
    got, notes, joined = unify_same_flows(found, masks, same, first, lambda s: s.labels["machine"], fits)
    assert joined == [] and notes == {} and got == found
