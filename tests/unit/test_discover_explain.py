"""The discovery record says everything it tried for every series it considered (``sd.explain``,
``discovery["explain"]``): the kind it took the series for and why, the exact query it was read
with and what came back, each role tried (a level to balance, a level to drive, a move, an input)
and the verdict. The owner's case first: per-method gauges of a per-interval count, under one
match, with nothing else there (C20)."""

import math
import random
import subprocess

from orchestra.sd.discover import discover
from orchestra.sd.series import Declared

T0 = 1_800_000_000.0
NAME = "chrono_grpc_client_callmillis_count"
MATCH = '{__name__="grpc_client_callMillis:count", method=~"A|B|C"}'


def owner_case():
    """Three per-method gauges of calls per scrape interval, read from a Chronosphere source with
    ``split = ["method"]``, and no other series under the match."""
    rng = random.Random(3)
    dump, kinds, prov = [], {}, {}
    for m in "ABC":
        key = f'{NAME}{{method="{m}"}}'
        dump.append((NAME, {"method": m}, [(T0 + 60 * i, float(max(0, round(rng.gauss(100, 15))))) for i in range(181)]))
        kinds[key] = Declared("level", resolution_s=60.0)
        sel = f'{{__name__="grpc_client_callMillis:count",method="{m}"}}'
        prov[key] = {"source": "chrono", "query": f"sum by (method) ({MATCH})", "kind": "level", "selector": sel,
                     "store_query": sel, "summed": ["instance", "pod"], "resolution_s": 60.0, "view": "level",
                     "family": "grpc_client_callMillis:count", "candidate": "chrono:level:grpc_client_callMillis:count"}
    return discover(dump, start=T0, end=T0 + 3 * 3600, step=60.0, kinds=kinds, provenance=prov)


def test_the_owners_per_interval_counts_say_what_was_tried_and_against_what():
    m = owner_case()
    assert not m.stocks
    for meth in "ABC":
        key = f'{NAME}{{method="{meth}"}}'
        rec = m.discovery["explain"][key]
        # the verdict is the record's left-out reason, unchanged
        assert rec["verdict"] == m.discovery["left_out"][key] and not rec["kept"]
        # a gauge, on its source's word, whose readings are new each time: a rate
        assert rec["kind"]["as"] == "gauge" and "source's definition" in rec["kind"]["why"]
        assert rec["kind"]["reads_as"] == "rate" and rec["kind"]["evidence"]["whole"]
        # the exact query, the window and step, and what came back
        rd = rec["read"]
        assert rd["source"] == "chrono" and rd["query"] == f"sum by (method) ({MATCH})" and rd["summed"] == ["instance", "pod"]
        assert rd["window"] == [T0, T0 + 3 * 3600] and rd["step"] == 60.0 and rd["points"] == 181 and rd["span_s"] == 3 * 3600
        assert len(rd["spark"]) == 60 and all(v is not None for v in rd["spark"]) and rd["min"] <= min(rd["spark"])
        # as a level to balance: no counter in the window at all, so R² 0.00 compares with nothing
        b = rec["roles"]["balance"]
        assert b["in_window"] == 0 and b["counters"] == {"n": 0, "keys": []} and b["terms"] == [] and b["r2"] == 0.0
        assert b["outcome"] == "no balance fits"
        # as a driven level: no input offered (the other two share its name), the constant and one form
        dv = rec["roles"]["driven"]
        assert dv["offered"] == 0 and len(dv["own_name"]) == 2 and key not in dv["own_name"]
        forms = dv["forms"]
        assert [f["form"] for f in forms] == ["c", "c + b × level"] and forms[0]["outcome"] == "reference"
        assert forms[1]["inputs"] == [] and forms[1]["own"] and forms[1]["outcome"] == "refuted"
        assert "scatter around a mean" in forms[1]["why"] and forms[1]["r2"] is not None
        assert "of 1 forms tried" in dv["why"]
        # as an input: there was nothing to offer it to
        assert rec["roles"]["input"]["to_flows"] == [] and rec["roles"]["input"]["to_levels"] == []


def test_a_balanced_stock_says_which_counters_were_tried_and_why_it_was_kept(tmp_path):
    from test_discover import simulate  # pytest puts this folder on the path

    from orchestra.metrics.file import FileMetrics
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=90)
    m = discover(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    ex = m.discovery["explain"]
    shelf = ex['bakery_shelf_loaves{machine="shop"}']
    assert shelf["kept"] and shelf["stock"] == "bakery_shelf_loaves" and shelf["verdict"].startswith("a stock: its changes are balanced by")
    b = shelf["roles"]["balance"]
    assert b["outcome"] == "fits" and b["r2"] >= 0.9 and b["in_window"] >= 3 and b["counters"]["n"] >= 3
    assert {t["series"] for t in b["terms"]} >= {'bakery_loaves_sold_total{machine="shop"}'}
    assert shelf["kind"]["as"] == "gauge" and "not named a counter" in shelf["kind"]["why"]
    # a counter: the levels its balance was offered to, the balance it is in, and its flow
    sold = ex['bakery_loaves_sold_total{machine="shop"}']
    assert sold["kind"]["as"] == "counter" and sold["kind"]["evidence"]["never_falls"] and "_total" in sold["kind"]["why"]
    mv = sold["roles"]["move"]
    assert "bakery_shelf_loaves" in mv["in_balances"] and mv["flow"] and 'bakery_shelf_loaves{machine="shop"}' in mv["offered_to"]["keys"]
    # the weather: a gauge offered to flows' rates as an input
    weather = ex['weather_temperature_celsius{machine="weather"}']
    assert weather["roles"]["input"]["name"] == "weather_temperature_celsius" and weather["roles"]["input"]["to_flows"]
    assert not weather["kept"]


def test_a_driven_level_records_its_forms_and_its_driver_records_where_it_was_offered():
    rng = random.Random(1)
    outside = [(T0 + 60 * i, round(10 + 6 * math.sin(i / 47) + 3 * math.sin(i / 13) + rng.gauss(0, 0.2), 2)) for i in range(4 * 60 + 1)]
    t, room = 20.0, []
    for when, o in outside:
        t += 0.08 * (o - t) + rng.gauss(0, 0.05)
        room.append((when, round(t, 3)))
    m = discover([("outside_celsius", {"machine": "weather"}, outside), ("room_celsius", {"machine": "thermostat"}, room)],
                 start=T0, end=T0 + 4 * 3600, step=5.0)
    ex = m.discovery["explain"]
    r = ex['room_celsius{machine="thermostat"}']
    assert r["kept"] and r["verdict"].startswith("a stock: no counters balance it, and its net flow is fitted")
    dv = r["roles"]["driven"]
    assert dv["offered"] == 1
    chosen = [f for f in dv["forms"] if f["outcome"] == "chosen"]
    assert len(chosen) == 1 and chosen[0]["inputs"] == ['outside_celsius{machine="weather"}'] and chosen[0]["r2"] > 0.4
    assert {f["outcome"] for f in dv["forms"]} - {"chosen"}          # the others say why they lost
    assert all(f["why"] for f in dv["forms"])
    o = ex['outside_celsius{machine="weather"}']
    [lv] = o["roles"]["input"]["to_levels"]
    assert lv["level"] == 'room_celsius{machine="thermostat"}' and lv["outcome"] == "chosen"
    assert "no other series explains its changes" in o["verdict"]


def test_the_model_answer_keeps_its_shape_and_one_series_is_served_apart(tmp_path, monkeypatch):
    from orchestra.config import init_project
    from orchestra.sd.store import ModelStore
    from orchestra.web.dynamics import explain_view, model_view
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    (tmp_path / "repo").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path / "repo", check=True)
    project = init_project(tmp_path / "repo")
    m = owner_case()
    ModelStore.for_state(project.state_dir).write_discovery(m)
    out = model_view(project)
    assert not out["ok"] and "explain" not in out["discovery"]          # the polled answer is as before
    key = f'{NAME}{{method="B"}}'
    got = explain_view(project, key)
    assert got["ok"] and got["explain"]["roles"]["balance"]["in_window"] == 0 and got["left_out"] == m.discovery["left_out"][key]
    assert got["window"] == {"start": T0, "end": T0 + 3 * 3600, "step": 60.0}
    assert not explain_view(project, "nothing{}")["ok"]
