"""Discovery's structure decisions on synthetic series: contested and shared counters, twin levels,
cancelling sets in a balance, series keys, and flows with too few events."""

import random

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.balance import balance, cancel
from orchestra.sd.discover import Path, Series, discover, fit_flow

T0 = 1_800_000_000.0


def walk(rng, rates: dict[str, float], minutes: int = 60):
    """Per second, which counters fired (Poisson with the given rates per minute)."""
    for i in range(minutes * 60):
        yield i, {k: sum(1 for _ in range(3) if rng.random() < r / 180) for k, r in rates.items()}


def write(store, minutes, rng, rates, levels, machines, extra=None, initial=None):
    """Counters at ``rates`` per minute; each level is ``{counter: sign}`` (starting at ``initial``);
    every series is written each second by its machine."""
    counts = dict.fromkeys(rates, 0)
    value = {lv: (initial or {}).get(lv, 0) for lv in levels}
    pts = []
    for i, fired in walk(rng, rates, minutes):
        t = T0 + i
        for k, n in fired.items():
            counts[k] += n
            for lv, terms in levels.items():
                value[lv] += terms.get(k, 0) * n
        for k in rates:
            pts.append(Point(k, counts[k], t, {"project": "p", "machine": machines[k]}))
        for lv in levels:
            pts.append(Point(lv, value[lv], t, {"project": "p", "machine": machines[lv]}))
        if extra:
            pts += extra(t, value)
    store.write(pts)
    return T0, T0 + minutes * 60


def test_a_counter_three_stocks_claim_is_a_move_and_a_co_flow(tmp_path):
    # X (the board's) leaves A and enters B, both the board's: one move. The expo's C also counts
    # up with X (a baker freed by each bake): the same events move a second material, a co-flow
    # drawn as its own edge, never a silent overwrite of A → B.
    store = FileMetrics(tmp_path / "m.jsonl")
    rates = {"in_total": 6.0, "x_total": 5.0, "out_total": 5.0, "y_total": 5.0}
    machines = {**dict.fromkeys(rates, "board"), "y_total": "expo", "a": "board", "b": "board", "c": "expo"}
    start, end = write(store, 60, random.Random(1), rates,
                       {"a": {"in_total": 1, "x_total": -1}, "b": {"x_total": 1, "out_total": -1}, "c": {"x_total": 1, "y_total": -1}}, machines)
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert m.check() == []
    f = {x.id: x for x in m.flows}
    assert (f["x_total"].src, f["x_total"].dst) == ("a", "b")
    assert (f["x_total@expo"].src, f["x_total@expo"].dst) == (None, "c")
    assert f["x_total@expo"].evidence["co_flow_of"] == "x_total" and f["x_total"].evidence["co_flows"] == ["x_total@expo"]
    assert f["x_total@expo"].counter and f["x_total@expo"].counter.name == "x_total"
    assert "x_total@expo" in {fid for mc in m.machines if mc.id == "board" for fid in mc.attributed}


def test_two_stocks_of_one_machine_claiming_an_end_keep_the_one_the_counter_explains_most(tmp_path):
    # B (= +X −out) and D (= +X −Z, with Z a torrent) both claim X's destination: B's changes
    # are mostly X, D's are mostly Z, so B keeps it and D's claim is recorded
    store = FileMetrics(tmp_path / "m.jsonl")
    rates = {"in_total": 6.0, "x_total": 5.0, "out_total": 5.0, "z_total": 40.0}
    machines = dict.fromkeys([*rates, "a", "b", "d"], "board")
    start, end = write(store, 60, random.Random(2), rates,
                       {"a": {"in_total": 1, "x_total": -1}, "b": {"x_total": 1, "out_total": -1}, "d": {"x_total": 1, "z_total": -1}}, machines)
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert m.check() == []
    x = m.flow("x_total")
    assert (x.src, x.dst) == ("a", "b")
    [conflict] = x.evidence["conflicts"]
    assert conflict["end"] == "dst" and conflict["kept"] == "b" and [o["stock"] for o in conflict["others"]] == ["d"]


def test_twin_levels_are_one_stock_measured_twice(tmp_path):
    # the shelf's count of what is on it is the board's on_shelf plus three orphan files: their
    # changes are equal in every step, so they are one stock; the board, whose counters move it,
    # keeps it and the shelf's copy is its twin
    store = FileMetrics(tmp_path / "m.jsonl")
    rates = {"in_total": 6.0, "out_total": 5.0}
    machines = {**dict.fromkeys(rates, "board"), "on_shelf": "board"}
    start, end = write(store, 60, random.Random(3), rates, {"on_shelf": {"in_total": 1, "out_total": -1}}, machines,
                       extra=lambda t, v: [Point("shelf_items", v["on_shelf"] + 3, t, {"project": "p", "machine": "shelf"})])
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert [s.id for s in m.stocks] == ["on_shelf"]
    [twin] = m.stock("on_shelf").evidence["twins"]
    assert twin["series"] == 'shelf_items{machine="shelf"}' and twin["machine"] == "shelf" and twin["equal_steps"] == 1.0
    assert m.discovery["left_out"]['shelf_items{machine="shelf"}'].startswith('the same as on_shelf{machine="board"} (one stock measured twice')


def _series(name, deltas, counter=True, machine="m"):
    vals, total = [0.0], 0.0
    for d in deltas:
        total += d
        vals.append(total)
    return Series(name, {"machine": machine}, [(T0 + i, v) for i, v in enumerate(vals)], vals, counter)


def test_a_cancelling_set_is_dropped_from_a_balance():
    # p counts q and r together: +p −q −r is identically zero but for one edge step, explains
    # nothing, and no single removal of the three lowers the error; the set goes as a whole
    rng = random.Random(4)
    a = [rng.choice([0, 1, 1, 2]) for _ in range(60)]
    b = [rng.choice([0, 0, 1, 1]) for _ in range(60)]
    q = [rng.choice([0, 1]) for _ in range(60)]
    r = [rng.choice([0, 1, 2]) for _ in range(60)]
    p = [x + y for x, y in zip(q, r)]
    p[-1] += 1                                   # stamped a moment later: the last event lands past the window
    level = _series("level", [x - y for x, y in zip(a, b)], counter=False)
    counters = [_series(n, d) for n, d in (("a", a), ("b", b), ("p", p), ("q", q), ("r", r))]
    xs = [c.deltas for c in counters]
    coef = {0: 1, 1: -1, 2: 1, 3: -1, 4: -1}
    y = level.deltas
    resid = [v - sum(s * xs[j][i] for j, s in coef.items()) for i, v in enumerate(y)]
    sse = sum(v * v for v in resid)
    mean = sum(y) / len(y)
    sst = sum((v - mean) ** 2 for v in y)
    coef, _, _ = cancel(coef, resid, sse, xs, max(0.01 * sst, 1.0), sst)
    assert coef == {0: 1, 1: -1}
    terms, r2, exact = balance(level, counters)
    assert [(c.name, s) for c, s in terms] == [("a", 1), ("b", -1)] and r2 > 0.99 and exact == 1.0


def test_left_out_is_keyed_by_the_machine_too(tmp_path):
    # an old machine's level of the same name, no longer written, is reported apart from the
    # current one, which is a stock (and not "no longer written")
    store = FileMetrics(tmp_path / "m.jsonl")
    rates = {"in_total": 6.0, "out_total": 5.0}
    machines = {**dict.fromkeys(rates, "board"), "waiting": "board"}
    start, end = write(store, 60, random.Random(5), rates, {"waiting": {"in_total": 1, "out_total": -1}}, machines,
                       extra=lambda t, v: [Point("waiting", v["waiting"], t, {"project": "p", "machine": "old"})] if t < T0 + 1500 else [])
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert [s.id for s in m.stocks] == ["waiting"]
    assert m.discovery["left_out"]['waiting{machine="old"}'].startswith("no longer written")
    assert 'waiting{machine="board"}' not in m.discovery["left_out"]


def test_a_flow_with_few_events_gets_the_constant_form_only():
    live = [(T0, T0 + 3600)]
    stock = Path.of([(T0 + i * 60, 10 + (i % 7)) for i in range(60)], live, 60.0)
    forms = fit_flow([(T0 + 700, 1.0), (T0 + 2900, 1.0)], 60.0, {"s": stock}, "s")
    assert [f["form"] for f in forms] == ["constant"]
    forms = fit_flow([(T0 + 100 + 500 * i, 1.0) for i in range(6)], 60.0, {"s": stock}, "s")
    assert {f["form"] for f in forms} >= {"constant", "proportional"}
