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
    def run(strategy, stocks, run, opts):
        seen.update(opts)
        seen["stocks"] = stocks
        return {"flows": flows}
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


def test_the_measured_moves_are_known_to_sdlab_and_its_invented_flows_are_dropped_where_nothing_remains(tmp_path, monkeypatch):
    # the bakery's two stocks are balanced exactly by their counters: nothing is left for an
    # SD Lab strategy to explain there, so its flows that no counter measures are dropped; its
    # flows on the counters are kept, and two between the same ends become one with two terms
    store, start, end = _bakery_with_gauges(tmp_path)
    seen = {}
    flows = [{"from": None, "to": "bakery_shelf_loaves", "rate": {"form": "constant", "value": 1.0}, "perStep": 1.0},
             {"from": None, "to": "bakery_shelf_loaves", "rate": {"form": "linear", "c": 0.0, "terms": [{"stock": "weather_temperature_celsius", "k": 0.1}]}},
             {"from": "bakery_oven_orders_pending", "to": "bakery_shelf_loaves", "rate": {"form": "proportional", "stock": "bakery_oven_orders_pending", "k": 0.2}},
             {"from": "bakery_shelf_loaves", "to": "bin", "rate": {"form": "constant", "value": 0.5}}]
    monkeypatch.setattr("orchestra.sd.strategies.run_strategy", _fake(seen, flows))
    monkeypatch.setattr("orchestra.sd.strategies.explains_residual", lambda *a: False)      # a strategy that ignored known
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="fake")
    assert m.check() == [] and m.discovery["sdlab_explains"] == "whole change"
    assert {s.id for s in m.stocks} == {"bakery_shelf_loaves", "bakery_oven_orders_pending"}, "no hidden stock from a dropped flow"
    assert all(s.evidence["exact_steps"] >= 0.97 for s in m.stocks)
    # the measured moves were handed over: each stock's change per step, nothing at the first time
    n = m.discovery["steps"]
    assert set(seen["known"]) == {"bakery_shelf_loaves", "bakery_oven_orders_pending"}
    assert all(len(v) == n + 1 and v[0] == 0.0 and any(v) for v in seen["known"].values())
    assert not [f.id for f in m.flows if f.id.startswith("unmeasured:")]
    assert [(d["from"], d["to"]) for d in m.discovery["dropped"]] == [("bakery_oven_orders_pending", "bakery_shelf_loaves"), ("bakery_shelf_loaves", "bin")]
    ids = [f.id for f in m.flows]
    assert len(ids) == len(set(ids))
    baked = m.flow("bakery_loaves_baked_total").current()
    assert baked.method == "sdlab:fake" and baked.form == "linear" and baked.inputs == ["input:weather_temperature_celsius"]
    assert baked.spec["combined"] == 2 and baked.params["c"] == 2.0 and baked.params["k1"] == 0.2, "per step → per minute"


def test_a_strategy_that_explains_the_residual_adds_flows_beside_the_counters(tmp_path, monkeypatch):
    # when the strategy read the known changes, its flows are what the counters leave: one between
    # two ends a counter already joins is another flow, not that counter's equation; and where
    # the counters balance the stock exactly it is dropped (nothing remained there)
    store, start, end = _bakery_with_gauges(tmp_path)
    flows = [{"from": None, "to": "bakery_shelf_loaves", "rate": {"form": "constant", "value": 0.5}}]
    monkeypatch.setattr("orchestra.sd.strategies.run_strategy", _fake({}, flows))
    monkeypatch.setattr("orchestra.sd.strategies.explains_residual", lambda *a: True)
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="fake")
    assert m.discovery["sdlab_explains"] == "residual" and m.check() == []
    assert m.flow("bakery_loaves_baked_total").current().method == "poisson-mle", "the counter keeps conservation's fit"
    assert not [f for f in m.flows if f.id.startswith("unmeasured:")] and len(m.discovery["dropped"]) == 1


def test_inputs_offered_to_sdlab_leave_out_flags_and_sum_a_machines_instances(tmp_path, monkeypatch):
    store, start, end = _bakery_with_gauges(tmp_path)
    seen = {}
    monkeypatch.setattr("orchestra.sd.strategies.run_strategy", _fake(seen, []))
    monkeypatch.setattr("orchestra.sd.strategies.explains_residual", lambda *a: True)
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="fake")
    assert not [k for k in seen["inputs"] if k.startswith("oven_busy")], "a flag drives nothing"
    assert any(why.startswith("a flag") for k, why in m.discovery["left_out"].items() if k.startswith("oven_busy"))
    assert "oven_temp" in seen["inputs"] and not [k for k in seen["inputs"] if k.startswith("oven_temp_")]
    assert m.discovery["inputs"]["oven_temp"]["summed"] == "summed over 2 instances"
    assert 370 < seen["inputs"]["oven_temp"][0] < 390, "the instances' values are summed"
    assert "weather_temperature_celsius" in seen["inputs"]


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
    # the bakery's stocks are balanced exactly by their counters: given the measured moves as
    # known, a real strategy leaves no unmeasured flow on them, every counter keeps a fitted or
    # discovered equation, and every id is used once
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=90)
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="matrix_v2", deadline=120)
    assert m.check() == []
    assert all(s.evidence["exact_steps"] >= 0.97 for s in m.stocks)
    assert m.discovery["known"] == ["bakery_oven_orders_pending", "bakery_shelf_loaves"] and m.discovery["deadline_s"] == 120
    assert m.discovery["sdlab_explains"] in ("residual", "whole change")
    assert not [f for f in m.flows if f.id.startswith("unmeasured:")], [f.id for f in m.flows]
    assert {f.id for f in m.flows} == {"bakery_loaves_baked_total", "bakery_loaves_sold_total", "bakery_loaves_discarded_total",
                                       "bakery_loaves_ordered_total", "bakery_orders_filled_total"}
    assert all(f.current() and f.current().origin in ("fitted", "discovered") for f in m.flows)


def test_an_unmeasured_flow_is_kept_where_a_stock_is_not_balanced_exactly(tmp_path, monkeypatch):
    # b gets one item a minute from a supplier no counter measures: its balance is not exact, so
    # a residual flow into it is kept, as unmeasured, with its origin and SD Lab's rate per minute
    store = FileMetrics(tmp_path / "m.jsonl")
    rates = {"a_in_total": 6.0, "a_out_total": 5.0, "b_in_total": 5.0, "b_out_total": 5.0}
    machines = dict.fromkeys([*rates, "a", "b"], "m")
    start, end = write(store, 90, random.Random(6), rates, {"a": {"a_in_total": 1, "a_out_total": -1}, "b": {"b_in_total": 1, "b_out_total": -1}},
                       machines, initial={"a": 30, "b": 30}, extra=lambda t, v: [Point("b", v["b"] + int(t - T0) // 60, t, {"project": "p", "machine": "m"})])
    flows = [{"from": None, "to": "b", "rate": {"form": "constant", "value": 0.5}}, {"from": None, "to": "a", "rate": {"form": "constant", "value": 0.1}}]
    monkeypatch.setattr("orchestra.sd.strategies.run_strategy", _fake({}, flows))
    monkeypatch.setattr("orchestra.sd.strategies.explains_residual", lambda *a: True)
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="fake")
    assert m.check() == []
    assert m.stock("a").evidence["exact_steps"] >= 0.97 > m.stock("b").evidence["exact_steps"]
    unmeasured = [f for f in m.flows if f.id.startswith("unmeasured:")]
    assert [(f.id, f.src, f.dst) for f in unmeasured] == [("unmeasured:outside>b", None, "b")]
    eq = unmeasured[0].current()
    assert (eq.origin, eq.method, eq.form, eq.params["value"]) == ("discovered", "sdlab:fake", "constant", 1.0), "0.5 per 30 s step is 1 per minute"
    assert m.flow("b_in_total").current().method == "poisson-mle" and [d["to"] for d in m.discovery["dropped"]] == ["a"]


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
