"""Counters discovery joins as one flow, and what a join must never cost: a stock its own counters
balance, judged on another writer's (UC-1: the customers' waiting on the board's placed and
accepted), and a buffer between two counters, which makes them its inflow and its outflow (UC-1:
the shelf between inspections passed and orders picked up)."""

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.discover import discover

T0 = 1_800_000_000.0


def _run(tmp_path, tick, seed):
    import random
    rng, pend, pts = random.Random(seed), [], []
    for i in range(3600):
        pts += tick(rng, T0 + i, pend)
    store = FileMetrics(tmp_path / "m.jsonl")
    store.write(sorted(pts, key=lambda p: p.ts))
    return discover(store.dump("", {"project": "p"}), start=T0, end=T0 + 3600, step=30)


def _due(pend, t):
    out = []
    for due, fn in [p for p in pend if p[0] <= t]:
        pend.remove((due, fn))
        out += fn(due)
    return out


def _balance(m, sid):
    return {(b["series"].partition("{")[0], b["sign"]) for b in m.stock(sid).evidence["balance"]}


def test_a_stock_is_judged_on_its_own_counters_not_another_writers_count_of_the_same_events(tmp_path):
    # the customers order (the board places it a second later) and are served (three seconds after
    # the board's accepted), and give up only in the first half hour. The customers' waiting is
    # exactly ordered - served - gave up; with the board's counts, which unify_same_flows joins to
    # the customers', it misses the steps a lag crosses, and judged on those its halves are another
    # writer's counters (the real run: 113 of 120 steps, refused by the halves' vote)
    cu, bo = {"project": "p", "instrument": "customers"}, {"project": "p", "instrument": "board"}
    st = dict.fromkeys(("ordered", "served", "gave_up", "cwait", "placed", "assigned", "accepted", "cancelled", "bwait", "ready"), 0)

    def tick(rng, t, pend):
        out = _due(pend, t)
        if rng.random() < 0.037:
            st["ordered"] += 1; st["cwait"] += 1
            out += [Point("customers_ordered_total", st["ordered"], t, cu), Point("customers_waiting", st["cwait"], t, cu)]

            def place(tt):
                st["placed"] += 1; st["bwait"] += 1
                return [Point("orders_placed_total", st["placed"], tt, bo), Point("orders_waiting", st["bwait"], tt, bo)]
            pend.append((t + 1, place))
        if t < T0 + 1800 and st["bwait"] > 2 and rng.random() < 0.003 * st["bwait"]:
            st["cancelled"] += 1; st["bwait"] -= 1; st["gave_up"] += 1; st["cwait"] -= 1
            out += [Point("orders_cancelled_total", st["cancelled"], t, bo), Point("orders_waiting", st["bwait"], t, bo),
                    Point("customers_gave_up_total", st["gave_up"], t, cu), Point("customers_waiting", st["cwait"], t, cu)]
        if st["bwait"] and rng.random() < 0.012 * st["bwait"]:
            st["assigned"] += 1; st["bwait"] -= 1; st["ready"] += 1
            out += [Point("orders_assigned_total", st["assigned"], t, bo), Point("orders_waiting", st["bwait"], t, bo),
                    Point("orders_ready", st["ready"], t, bo)]
        if st["ready"] and rng.random() < 0.02 * st["ready"]:
            st["accepted"] += 1; st["ready"] -= 1
            out += [Point("orders_accepted_total", st["accepted"], t, bo), Point("orders_ready", st["ready"], t, bo)]

            def serve(tt):
                st["served"] += 1; st["cwait"] -= 1
                return [Point("customers_served_total", st["served"], tt, cu), Point("customers_waiting", st["cwait"], tt, cu)]
            pend.append((t + 3, serve))
        return out
    m = _run(tmp_path, tick, seed=1)
    assert {"customers_waiting", "orders_waiting", "orders_ready"} <= {s.id for s in m.stocks}, m.discovery["left_out"]
    assert _balance(m, "customers_waiting") == {("customers_ordered_total", 1), ("customers_served_total", -1),
                                                ("customers_gave_up_total", -1)}
    idn = m.stock("customers_waiting").evidence["identification"]
    assert idn["exact_moved"] == 1.0, idn
    assert all(c.split("{")[0].lstrip("+-").startswith("customers_") for half in idn["halves"] for c in half), idn["halves"]


def test_a_measured_level_between_two_counters_keeps_them_apart_however_seldom_it_moves(tmp_path):
    # inspections passed put an order on the shelf; the customer picks it up within the second, so
    # the shelf (scraped every 5 s) reads held in only two stretches of the hour: too few to be a
    # stock, and passed and picked up differ in only four steps of 120. The shelf is still exactly
    # passed - picked up: they are its inflow and outflow, never one flow, and the inspecting
    # orders keep their own outflow (the real run: inspecting exact in 97% with picked up, 100%
    # with passed)
    bo = {"project": "p", "instrument": "board"}
    names = {"baked": "orders_baked_total", "passed": "inspections_passed_total", "failed": "inspections_failed_total",
             "picked": "orders_picked_up_total", "accepted": "orders_accepted_total", "rejected": "orders_rejected_total",
             "insp": "orders_inspecting", "shelf": "orders_on_shelf", "acc": "orders_accepting"}
    st = dict.fromkeys(names, 0)

    def later(t, k):             # the k-th move waits to the next step's first second: across a step's edge
        return t - (t - T0) % 30 + k

    def tick(rng, t, pend):
        _due(pend, t)
        if rng.random() < 0.06:
            st["baked"] += 1; st["insp"] += 1
        if st["insp"] and rng.random() < 0.02 * st["insp"]:
            st["insp"] -= 1
            if rng.random() < 0.3:
                st["failed"] += 1
            else:
                st["passed"] += 1; st["shelf"] += 1

                def pick(tt):
                    st["picked"] += 1; st["shelf"] -= 1; st["acc"] += 1
                    no = st["picked"] % 8 == 3

                    def accept(t3):
                        k = "rejected" if no else "accepted"
                        st[k] += 1; st["acc"] -= 1
                        return []
                    pend.append((later(tt, 32) if st["picked"] in (20, 50, 70) else tt, accept))
                    return []
                pend.append((later(t, 31) if st["passed"] in (10, 40) else t, pick))
        _due(pend, t)
        _due(pend, t)
        return [Point(names[k], v, t, bo) for k, v in st.items()] if (t - T0) % 5 == 0 else []
    m = _run(tmp_path, tick, seed=4)
    assert {"orders_inspecting", "orders_accepting"} <= {s.id for s in m.stocks}, m.discovery["left_out"]
    assert _balance(m, "orders_inspecting") == {("orders_baked_total", 1), ("inspections_failed_total", -1),
                                                ("inspections_passed_total", -1)}
    assert m.stock("orders_inspecting").evidence["exact_steps"] == 1.0
    assert not m.discovery["left_out"].get('inspections_passed_total{instrument="board"}', "").startswith("the same as")
    passed = m.flow("inspections_passed_total")
    assert passed.src == "orders_inspecting" and passed.dst != "orders_accepting", (passed.src, passed.dst)
