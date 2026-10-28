"""Discovery strategies: Orchestra's conservation step, and SD Lab's strategies behind it."""

import random

import pytest
from test_discover import simulate  # pytest puts this folder on the path
from test_discover_ends import T0, write

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.rates import reads as _reads
from orchestra.sd.rates import scale as _scale
from orchestra.sd.strategies import CONSERVATION, available, discover_with, sd_installed


def test_rates_per_step_become_rates_per_time_unit():
    f = 2.0                                     # 30 s steps, per minute
    assert _scale({"form": "constant", "value": 3}, f)["value"] == 6
    assert _scale({"form": "proportional", "stock": "s", "k": 0.1}, f)["k"] == 0.2
    lin = _scale({"form": "linear", "c": 1, "terms": [{"stock": "a", "k": 0.5}]}, f)
    assert lin["c"] == 2 and lin["terms"][0]["k"] == 1.0
    assert _scale({"form": "gap", "stock": "s", "goal": 10, "time": 4}, f)["time"] == 2


def test_what_a_rate_reads():
    rate = {"form": "linear", "c": 0, "terms": [{"stock": "a", "k": 1}, {"stock": "b", "k": -1}],
            "effects": [{"stock": "c", "shape": "linear"}, {"stock": "a"}]}
    assert _reads(rate) == ["a", "b", "c"]


def test_conservation_is_always_available():
    names = [s["name"] for s in available()["strategies"]]
    assert names[0] == CONSERVATION
    if sd_installed():
        assert {"kalman_lna", "combined2", "matrix_v2"} <= set(names)


def _fake(seen, flows):
    """A strategy that records what it was given (over every group it was run on) and answers
    with ``flows``, those whose ends are among the stocks it was given."""
    def run(strategy, stocks, run, opts):
        known = {**seen.get("known", {}), **opts.get("known", {})}
        seen.update(opts)
        seen["known"] = known
        seen["stocks"] = seen.get("stocks", []) + stocks
        ids = {s["id"] for s in stocks}
        return {"flows": [f for f in flows if {f.get("from"), f.get("to")} & ids]}
    return run


def _bakery_with_gauges(tmp_path, minutes=60):
    """The simulated bakery, plus the oven's two instances each writing a busy flag and a
    temperature (a gauge that is not a flag)."""
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=minutes)
    rng = random.Random(8)
    pts, busy, temp = [], {1: 0, 2: 1}, {1: 180.0, 2: 200.0}
    for i in range(minutes * 60):
        for inst in (1, 2):
            if rng.random() < 0.02:
                busy[inst] = 1 - busy[inst]
            temp[inst] += rng.gauss(0, 0.5)
            lab = {"project": "p", "machine": "oven", "instance": str(inst)}
            pts += [Point("oven_busy", busy[inst], start + i, lab), Point("oven_temp", round(temp[inst], 2), start + i, lab)]
    store.write(pts)
    return store, start, end


def _with_a_cooling_kiln(store, start, end):
    """A kiln cooling after a firing, its temperature written every 30 s and no counter of it: a
    stock by its fitted net flow. It loses heat faster the hotter it is (2e-5 × temp² a step), which
    the net flow's straight line in the level follows only roughly."""
    rng, temp, pts = random.Random(9), 900.0, []
    for i in range(int((end - start) // 30) + 1):
        pts.append(Point("kiln_temperature_celsius", round(temp, 2), start + 30 * i, {"project": "p", "machine": "kiln"}))
        temp += -2e-5 * temp * temp + rng.gauss(0, 0.5)
    store.write(pts)


# what an SD Lab strategy that found the kiln's law would answer: an outflow in proportion to the
# temperature, times the temperature (a linear effect of the kiln on its own outflow)
KILN_LAW = {"from": "kiln_temperature_celsius", "to": None, "rate": {"form": "proportional", "stock": "kiln_temperature_celsius", "k": 0.02},
            "effects": [{"stock": "kiln_temperature_celsius", "shape": "linear", "normal": 1000, "min": 0, "max": 10}]}


def _every_measured_stock(monkeypatch):
    """Hand SD Lab every measured stock, exact or not, to test how its flows are merged."""
    monkeypatch.setattr("orchestra.sd.strategies.handed", lambda base: [s for s in base.stocks if s.series is not None])


def test_sdlab_is_given_no_stock_its_counters_balance_exactly(tmp_path, monkeypatch):
    # the bakery's two counted stocks balance exactly: nothing is left to explain, so an SD Lab
    # strategy is not run on them, and their flows keep conservation's fits
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60)
    dump = [x for x in store.dump("", {"project": "p"}) if x[0] != "weather_temperature_celsius"]
    seen = {}
    monkeypatch.setattr("orchestra.sd.strategies.run_strategy", _fake(seen, [{"from": None, "to": "bakery_shelf_loaves", "rate": {"form": "constant", "value": 1.0}}]))
    m = discover_with(dump, start=start, end=end, step=30, strategy="fake")
    assert seen == {} and m.discovery["sdlab"].startswith("not run: the counters balance every stock exactly")
    assert m.flow("bakery_loaves_baked_total").current().method == "poisson-mle"
    assert not [f for f in m.flows if f.id.startswith("unmeasured:")]


def test_sdlab_is_given_the_stocks_no_counters_balance(tmp_path, monkeypatch):
    # a kiln beside the bakery cools toward the room: a stock of its own by its fitted net flow.
    # SD Lab is given that stock alone, and its flows take the place of conservation's
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60)
    _with_a_cooling_kiln(store, start, end)
    seen = {}
    monkeypatch.setattr("orchestra.sd.strategies.run_strategy", _fake(seen, [KILN_LAW]))
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="fake")
    assert [s["id"] for s in seen["stocks"]] == ["kiln_temperature_celsius"], seen.get("stocks")
    assert m.check() == []
    [sd] = [f for f in m.flows if f.src == "kiln_temperature_celsius" or f.dst == "kiln_temperature_celsius"]
    assert sd.current().method == "sdlab:fake" and sd.current().quality["events"] > 0
    assert m.stock("kiln_temperature_celsius").evidence["conservation_fit"]
    assert "sdlab_rejected" not in m.stock("kiln_temperature_celsius").evidence
    assert m.flow("bakery_loaves_baked_total").current().method == "poisson-mle"


def test_sdlab_flows_that_predict_a_net_flow_stock_worse_are_dropped(tmp_path, monkeypatch):
    # an SD Lab answer of a steady inflow into the cooling kiln predicts its held-out half worse
    # than the fitted net flow: the net flow's flows stay, and the stock says why
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60)
    _with_a_cooling_kiln(store, start, end)
    flows = [{"from": None, "to": "kiln_temperature_celsius", "rate": {"form": "constant", "value": 1.0}}]
    monkeypatch.setattr("orchestra.sd.strategies.run_strategy", _fake({}, flows))
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="fake")
    kiln = m.stock("kiln_temperature_celsius")
    assert "worse than the fitted net flow" in kiln.evidence["sdlab_rejected"]
    assert "conservation_fit" not in kiln.evidence
    mine = [f for f in m.flows if "kiln_temperature_celsius" in (f.src, f.dst)]
    assert mine and all(f.current().method == "least-squares" for f in mine)
    assert {"from": None, "to": "kiln_temperature_celsius"}.items() <= m.discovery["dropped"][0].items()


def _kiln_flows(tmp_path, monkeypatch, flows):
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60)
    _with_a_cooling_kiln(store, start, end)
    monkeypatch.setattr("orchestra.sd.strategies.run_strategy", _fake({}, flows))
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="fake")
    return m, m.stock("kiln_temperature_celsius"), [f for f in m.flows if "kiln_temperature_celsius" in (f.src, f.dst)]


def test_sdlab_flows_are_published_at_the_scale_they_were_judged_at(tmp_path, monkeypatch):
    # SD Lab found the kiln's law at half its strength: it is judged with a scale fitted to the
    # level (about 2), and what is published is that judged flow, not SD Lab's half-strength one
    half = {**KILN_LAW, "rate": {**KILN_LAW["rate"], "k": 0.01}}
    _, kiln, [sd] = _kiln_flows(tmp_path, monkeypatch, [half])
    assert "sdlab_rejected" not in kiln.evidence
    e = sd.current()
    assert e.method == "sdlab:fake" and 1.6 < e.quality["judged_scale"] < 2.4, e.quality
    assert abs(e.params["k"] - 0.02 * 2) < 0.008, e.params          # 0.02 a step of 30 s is 0.04 a minute


def test_an_sdlab_flow_whose_judged_scale_turns_it_around_is_not_published(tmp_path, monkeypatch):
    # SD Lab wrote the kiln's law as an inflow: the kiln would heat the hotter it is. Fitted to the
    # level, its scale is below zero (the kiln cools), so the flow that would be published (an
    # inflow) is not the one that was judged (an outflow): the net flow's flows stay
    backwards = {**KILN_LAW, "from": None, "to": "kiln_temperature_celsius"}
    _, kiln, mine = _kiln_flows(tmp_path, monkeypatch, [backwards])
    assert "below zero" in kiln.evidence["sdlab_rejected"], kiln.evidence.get("sdlab_rejected")
    assert mine and all(f.current().method == "least-squares" for f in mine)
    nf = kiln.evidence["net_flow"]["params"]
    assert nf["b"] < 0 and [f.id for f in mine if f.src == "kiln_temperature_celsius"], "it loses heat in proportion to itself"


def test_an_sdlab_flow_that_moves_nothing_is_not_published(tmp_path, monkeypatch):
    # beside the kiln's law, SD Lab answered a second outflow of 1e-23 times the temperature: it
    # moves nothing, and a scale fitted to it would invent a flow; it is dropped and recorded
    nothing = {"from": "kiln_temperature_celsius", "to": None, "rate": {"form": "proportional", "stock": "kiln_temperature_celsius", "k": 1e-23}}
    m, kiln, mine = _kiln_flows(tmp_path, monkeypatch, [KILN_LAW, nothing])
    assert "sdlab_rejected" not in kiln.evidence
    [sd] = mine
    assert sd.current().form == "proportional" and sd.current().params["k"] > 0.01, sd.current().params
    assert any("less than the 1% a flow must" in d["why"] for d in m.discovery["dropped"]), m.discovery["dropped"]


def test_the_measured_moves_are_known_to_sdlab_and_its_invented_flows_are_dropped_where_nothing_remains(tmp_path, monkeypatch):
    # handed the bakery's two stocks, which are balanced exactly by their counters, an SD Lab
    # strategy's flows that no counter measures are dropped there; its flows on the counters are
    # kept, and two between the same ends become one with two terms
    store, start, end = _bakery_with_gauges(tmp_path)
    seen = {}
    _every_measured_stock(monkeypatch)
    flows = [{"from": None, "to": "bakery_shelf_loaves", "rate": {"form": "constant", "value": 1.0}, "perStep": 1.0},
             {"from": None, "to": "bakery_shelf_loaves", "rate": {"form": "linear", "c": 0.0, "terms": [{"stock": "weather_temperature_celsius", "k": 0.1}]}},
             {"from": "bakery_oven_orders_pending", "to": "bakery_shelf_loaves", "rate": {"form": "proportional", "stock": "bakery_oven_orders_pending", "k": 0.2}},
             {"from": "bakery_shelf_loaves", "to": "bin", "rate": {"form": "constant", "value": 0.5}}]
    monkeypatch.setattr("orchestra.sd.strategies.run_strategy", _fake(seen, flows))
    monkeypatch.setattr("orchestra.sd.strategies.explains_residual", lambda *a: False)      # a strategy that ignored known
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="fake")
    assert m.check() == [] and m.discovery["sdlab_explains"] == "whole change"
    assert {s.id for s in m.stocks} - {"weather_temperature_celsius"} == {"bakery_shelf_loaves", "bakery_oven_orders_pending"}, \
        "no hidden stock from a dropped flow"
    assert all(s.evidence["exact_steps"] >= 0.97 for s in m.stocks if "net_flow" not in s.evidence)
    # the measured moves were handed over: each stock's change per step, nothing at the first time
    n = m.discovery["steps"]
    assert set(seen["known"]) == {"bakery_shelf_loaves", "bakery_oven_orders_pending"}
    assert all(len(v) == n + 1 and v[0] == 0.0 and any(v) for v in seen["known"].values())
    assert not [f.id for f in m.flows if f.id.startswith("unmeasured:")]
    assert [(d["from"], d["to"]) for d in m.discovery["dropped"]] == [("bakery_oven_orders_pending", "bakery_shelf_loaves"), ("bakery_shelf_loaves", "bin")]
    ids = [f.id for f in m.flows]
    assert len(ids) == len(set(ids))
    baked = m.flow("bakery_loaves_baked_total").current()
    assert baked.method == "sdlab:fake" and baked.form == "linear"
    assert baked.inputs in (["input:weather_temperature_celsius"], ["weather_temperature_celsius"]), "an input, or a stock of its own"
    assert baked.spec["combined"] == 2 and baked.params["c"] == 2.0 and baked.params["k1"] == 0.2, "per step → per minute"


def test_a_strategy_that_explains_the_residual_adds_flows_beside_the_counters(tmp_path, monkeypatch):
    # when the strategy read the known changes, its flows are what the counters leave: one between
    # two ends a counter already joins is another flow, not that counter's equation; and where
    # the counters balance the stock exactly it is dropped (nothing remained there)
    store, start, end = _bakery_with_gauges(tmp_path)
    _every_measured_stock(monkeypatch)
    flows = [{"from": None, "to": "bakery_shelf_loaves", "rate": {"form": "constant", "value": 0.5}}]
    monkeypatch.setattr("orchestra.sd.strategies.run_strategy", _fake({}, flows))
    monkeypatch.setattr("orchestra.sd.strategies.explains_residual", lambda *a: True)
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="fake")
    assert m.discovery["sdlab_explains"] == "residual" and m.check() == []
    assert m.flow("bakery_loaves_baked_total").current().method == "poisson-mle", "the counter keeps conservation's fit"
    assert not [f for f in m.flows if f.id.startswith("unmeasured:")] and len(m.discovery["dropped"]) == 1


def test_inputs_offered_to_sdlab_leave_out_flags_and_sum_a_machines_instances(tmp_path, monkeypatch):
    store, start, end = _bakery_with_gauges(tmp_path)
    _every_measured_stock(monkeypatch)
    seen = {}
    monkeypatch.setattr("orchestra.sd.strategies.run_strategy", _fake(seen, []))
    monkeypatch.setattr("orchestra.sd.strategies.explains_residual", lambda *a: True)
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="fake")
    assert not [k for k in seen["inputs"] if k.startswith("oven_busy")], "a flag drives nothing"
    assert any(why.startswith("a flag") for k, why in m.discovery["left_out"].items() if k.startswith("oven_busy"))
    assert "oven_temp" in seen["inputs"] and not [k for k in seen["inputs"] if k.startswith("oven_temp_")]
    assert m.discovery["inputs"]["oven_temp"]["summed"] == "summed over 2 instances"
    assert 370 < seen["inputs"]["oven_temp"][0] < 390, "the instances' values are summed"
    weather = [s for s in m.stocks if s.id == "weather_temperature_celsius"]
    assert ("weather_temperature_celsius" in seen["inputs"]) != bool(weather), "an input, or a stock of its own"


def test_rates_between_the_same_ends_combine():
    from orchestra.sd.rates import combine
    lin = combine([{"form": "constant", "value": 1}, {"form": "proportional", "stock": "a", "k": 2}, {"form": "linear", "c": 3, "terms": [{"stock": "b", "k": 4}]}])
    assert lin == {"form": "linear", "c": 4.0, "terms": [{"stock": "a", "k": 2.0}, {"stock": "b", "k": 4.0}], "combined": 3}
    other = combine([{"form": "gap", "stock": "a", "goal": 1, "time": 2}, {"form": "constant", "value": 1}])
    assert other["form"] == "sum" and len(other["parts"]) == 2 and _reads(other) == ["a"]


def test_a_model_reports_ids_used_twice():
    from orchestra.sd.model import Flow, Model, Stock
    m = Model("x", "x", stocks=[Stock("A", "A"), Stock("A", "A")], flows=[Flow("f", "f", "A", None), Flow("f", "f", None, "A")])
    assert {e for e in m.check()} == {"stock id A is used 2 times", "flow id f is used 2 times"}


def test_the_host_skips_a_discovery_another_process_holds(tmp_path):
    import fcntl
    from types import SimpleNamespace

    from orchestra.sd.rediscover import Busy, rediscover
    project = SimpleNamespace(key="p", state_dir=tmp_path, config=SimpleNamespace(
        discovery_strategy=CONSERVATION, discovery_options={}, discovery_window=600.0, discovery_step=30.0, discovery_every=300.0))
    store = FileMetrics(tmp_path / "m.jsonl")
    with open(tmp_path / "discovery.lock", "w") as other:            # another process's discovery, under way
        fcntl.flock(other, fcntl.LOCK_EX)
        with pytest.raises(Busy):
            rediscover(project, store, skip_if_busy=True)
    assert rediscover(project, store, skip_if_busy=True).strategy == CONSERVATION


@pytest.mark.skipif(not sd_installed(), reason="SD Lab's strategies need orchestra[sd]")
def test_an_sdlab_strategy_adds_nothing_where_the_counters_balance_exactly(tmp_path):
    # the bakery's stocks are balanced exactly by their counters: a real strategy is not run on
    # them, so it leaves no unmeasured flow, every counter keeps its fitted equation, and every id
    # is used once
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=90)
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="matrix_v2", deadline=120)
    assert m.check() == []
    assert {s.id for s in m.stocks} == {"bakery_oven_orders_pending", "bakery_shelf_loaves"}
    assert all(s.evidence["exact_steps"] >= 0.97 for s in m.stocks)
    assert m.discovery["strategy"] == "matrix_v2" and m.discovery["sdlab"].startswith("not run")
    assert not [f for f in m.flows if f.id.startswith("unmeasured:")], [f.id for f in m.flows]
    assert {f.id for f in m.flows} == {"bakery_loaves_baked_total", "bakery_loaves_sold_total", "bakery_loaves_discarded_total",
                                       "bakery_loaves_ordered_total", "bakery_orders_filled_total"}
    assert all(f.current() and f.current().origin in ("fitted", "discovered") for f in m.flows)


def test_an_unmeasured_flow_is_kept_where_a_stock_is_not_balanced_exactly(tmp_path, monkeypatch):
    # b's gauge reads one high now and then (scraped a moment off its counters): its balance is not
    # exact, so a residual flow into it is kept, as unmeasured, with its origin and SD Lab's rate per
    # minute. (Until 2026-10-28 b got an item a minute from a supplier no counter measured; its
    # counters no longer reproduce such a level, which drifts from them by more than it moves, so it is
    # no conservation stock now: sd.accept.CUM_RATIO.)
    store = FileMetrics(tmp_path / "m.jsonl")
    rates = {"a_in_total": 6.0, "a_out_total": 5.0, "b_in_total": 5.0, "b_out_total": 5.0}
    machines = dict.fromkeys([*rates, "a", "b"], "m")
    start, end = write(store, 90, random.Random(6), rates, {"a": {"a_in_total": 1, "a_out_total": -1}, "b": {"b_in_total": 1, "b_out_total": -1}},
                       machines, initial={"a": 30, "b": 30}, extra=lambda t, v: [Point("b", v["b"] + (1 if int(t - T0) // 30 % 7 == 0 else 0), t, {"project": "p", "machine": "m"})])
    flows = [{"from": None, "to": "b", "rate": {"form": "constant", "value": 0.5}}, {"from": None, "to": "a", "rate": {"form": "constant", "value": 0.1}}]
    seen = {}
    monkeypatch.setattr("orchestra.sd.strategies.run_strategy", _fake(seen, flows))
    monkeypatch.setattr("orchestra.sd.strategies.explains_residual", lambda *a: True)
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="fake")
    assert m.check() == []
    assert m.stock("a").evidence["exact_steps"] >= 0.97 > m.stock("b").evidence["exact_steps"]
    assert [s["id"] for s in seen["stocks"]] == ["b"], "a stock balanced exactly is not handed over"
    unmeasured = [f for f in m.flows if f.id.startswith("unmeasured:")]
    assert [(f.id, f.src, f.dst) for f in unmeasured] == [("unmeasured:outside>b", None, "b")]
    eq = unmeasured[0].current()
    assert (eq.origin, eq.method, eq.form, eq.params["value"]) == ("discovered", "sdlab:fake", "constant", 1.0), "0.5 per 30 s step is 1 per minute"
    assert m.flow("b_in_total").current().method == "poisson-mle" and m.discovery["dropped"] == []


def test_runs_a_few_seconds_apart_discover_over_the_same_grid(tmp_path, monkeypatch):
    # the host and the CLI each end their window when they run; seven seconds apart, they must
    # still sample the same grid, or a state seen in a step or two comes and goes between them
    import time
    from types import SimpleNamespace

    from orchestra.sd import rediscover as rd
    project = SimpleNamespace(key="p", state_dir=tmp_path, config=SimpleNamespace(
        discovery_strategy=CONSERVATION, discovery_options={}, discovery_window=600.0, discovery_step=30.0, discovery_every=300.0))
    store = FileMetrics(tmp_path / "m.jsonl")
    windows = []
    for now in (1_800_000_013.0, 1_800_000_020.0):
        monkeypatch.setattr(time, "time", lambda now=now: now)
        d = rd.rediscover(project, store).model.discovery
        windows.append((d["start"], d["end"]))
    assert windows[0] == windows[1] == (1_799_999_400.0, 1_800_000_000.0)
    assert rd.aligned(100.0, 707.0, 30.0) == (90.0, 690.0)


def test_a_strategy_past_its_deadline_leaves_conservations_fits(tmp_path, monkeypatch):
    # SD Lab's strategies keep budgets of their own that some outlast; past the discovery's
    # deadline the strategy's process is stopped and the model is conservation's, saying why
    from orchestra.sd.bounded import Late

    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60)
    _with_a_cooling_kiln(store, start, end)

    def late(jobs, deadline):
        raise Late(f"stopped at its deadline of {deadline:g} s")
    monkeypatch.setattr("orchestra.sd.strategies.run_jobs", late)
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="fake", deadline=5)
    assert m.discovery["sdlab"] == "stopped at its deadline of 5 s: conservation's fits are kept"
    assert all(f.current().method in ("poisson-mle", "least-squares") for f in m.flows)


def test_a_strategy_runs_in_a_process_of_its_own_under_a_deadline():
    import pytest as _pytest

    from orchestra.sd.bounded import Late, run_jobs
    with _pytest.raises(Late, match="its process failed"):
        run_jobs([("no_such_strategy", [], {"t": [0, 1], "levels": {}}, {})], deadline=60)


def test_past_its_deadline_a_strategy_process_is_stopped_with_every_process_it_started(tmp_path):
    # a strategy that works in a pool of worker processes: at the deadline its whole process
    # group is killed, the workers too, not only the process the jobs were handed to
    import os
    import sys
    import time as _time

    from orchestra.sd.bounded import Late, _bounded

    pidfile = tmp_path / "grandchild.pid"
    script = (f"import subprocess, sys, time; p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
              f"open({str(pidfile)!r}, 'w').write(str(p.pid)); time.sleep(60)")
    started = _time.monotonic()
    with pytest.raises(Late, match="stopped at its deadline"):
        _bounded([sys.executable, "-c", script], "", 2.0)
    assert _time.monotonic() - started < 10
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        _time.sleep(0.1)
    else:
        os.kill(pid, 9)
        raise AssertionError(f"the strategy's worker {pid} outlived the deadline")


def test_each_stock_gets_a_behaviour_trust_beside_its_identity_trust(tmp_path):
    # the bakery's stocks are found by their balances (identity trust); run forward from part-way
    # through the window, the model is judged against the measured levels, and that is kept beside
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=60)
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert m.discovery["behaviour"]["stocks"] == len(m.stocks) > 0
    for s in m.stocks:
        t = s.evidence["trust"]
        b = t["behaviour"]
        assert 0.0 <= b["score"] <= 1.0 and b["score"] == pytest.approx(1 / (1 + b["error"]), abs=1e-3)
        assert b["growth"] >= 0 and b["z"] > 0 and b["pairs"] > 10
        assert t["score"] == pytest.approx(min(t["components"].values())), "the identity trust is still the weakest of its own"
