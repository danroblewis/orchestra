"""The comparison of the declared layer with the discovered versions, on keys
(docs/proposals/intended-model.md §3, §5; §10 tests 5–14, 22, 29)."""

import json
import time

from orchestra.sd.intended.view import dynamics_block
from orchestra.sd.model import Flow, Model, SeriesRef, Stock
from orchestra.sd.store import ModelStore

OWNER = {"author": "owner", "source": "supervisor", "quote": "track it"}


def st(sid, name=None, instrument="i", **labels):
    return Stock(sid, sid, series=SeriesRef(name or sid, {"instrument": instrument, **labels}))


def fl(fid, a, b, counter=None, **ev):
    return Flow(fid, fid, a, b, SeriesRef(counter, {"instrument": "i"}) if counter else None, evidence=dict(ev))


def model(stocks, flows=(), era=None):
    return Model("system", "s", stocks=list(stocks), flows=list(flows), era=era)


def saved(tmp_path, *models_):
    ms = ModelStore(tmp_path / "model")
    for i, m in enumerate(models_):
        ms.save(m, note=str(i))
    return ms


def block(ms, version=None, since=None, hold=3):
    n = version or ms.current_version()
    return dynamics_block(ms.intended(), ms.load(n), since, version=n, live=False, hold=hold)


def entry(b, **kw):
    return next(e for e in b["expected"] if all(e.get(k) == v for k, v in kw.items()))


def test_a_declared_stock_with_no_series_is_expected_absent_and_unmeasured_and_changes_no_stock(tmp_path):
    ms = saved(tmp_path, model([st("done")]))
    before = json.dumps(ms.load().to_json())
    ms.intended().apply([{"op": "declare_stock", "name": "Features", "near": "done"}], OWNER)
    b = block(ms)
    e = entry(b, id="features")
    assert e["present"] is False and e["measured"] is False and e["declared"] and "not measured" in e["why"]
    assert {"sign": "o", "part": "stock", "id": "features"}.items() <= next(c for c in b["changes"] if c["sign"] == "o").items()
    assert json.dumps(ms.load().to_json()) == before


def test_discovery_is_the_same_with_and_without_a_declared_layer(tmp_path):
    import random

    from orchestra.sd.discover import discover

    rng, t0, lv, inn, out = random.Random(2), 1_800_000_000.0, 0, 0, 0
    L, I, O = [], [], []
    for i in range(720):
        a = rng.random() < 0.3
        d = lv > 0 and rng.random() < 0.05 * lv
        inn, out, lv = inn + a, out + d, lv + a - d
        L.append((t0 + 5 * i, float(lv)))
        I.append((t0 + 5 * i, float(inn)))
        O.append((t0 + 5 * i, float(out)))
    dump = [("q_level", {}, L), ("q_in_total", {}, I), ("q_out_total", {}, O)]
    first = discover(dump, start=t0, end=t0 + 3600, step=10).to_json()
    ms = ModelStore(tmp_path / "model")
    ms.intended().apply([{"op": "declare_stock", "name": "Features"}, {"op": "expect", "part": "stock", "key": "q_level"}], OWNER)
    second = discover(dump, start=t0, end=t0 + 3600, step=10).to_json()
    for m in (first, second):
        m["discovery"].pop("compute_ms", None)
    assert first == second


def test_an_expected_stock_gone_from_a_later_version_is_listed_absent(tmp_path):
    ms = saved(tmp_path, model([st("a"), st("b")]))
    ms.intended().apply([{"op": "expect", "part": "stock", "key": "b"}], OWNER)
    assert entry(block(ms), key="b")["present"] is True
    ms.save(model([st("a")]))
    b = block(ms)
    assert entry(b, key="b")["present"] is False
    assert any(c["sign"] == "o" and c["key"] == "b" for c in b["changes"])


def test_new_by_default_and_since_and_off(tmp_path):
    ms = saved(tmp_path, model([st("a")]), model([st("a"), st("b")]))
    assert block(ms)["marks"]["stocks"] == {"b": ["new"]}
    assert block(ms, since="1")["marks"]["stocks"] == {"b": ["new"]} and block(ms, since="1")["since"] == 1
    off = block(ms, since="off")
    assert off["marks"]["stocks"] == {} and off["since"] is None and not [c for c in off["changes"] if c["sign"] in "+-"]


def test_a_removed_flow_comes_with_its_rate_and_machines(tmp_path):
    from orchestra.sd.model import Equation
    gone = fl("f", "a", "b", "moved_total", machines={"hypotheses": [{"machine": "merge_gate", "confidence": 0.71}]})
    gone.equations = [Equation("constant", {"c": 0.4}, "fitted", quality={"events": 41.0, "live_minutes": 100.0})]
    ms = saved(tmp_path, model([st("a"), st("b")], [gone]), model([st("a"), st("b")]))
    r = block(ms)["removed"]["flows"]
    assert r == [{"key": "a{} -> b{} by moved_total".replace("{}", ""), "id": "f", "from": "a", "to": "b", "rate": "0.41 /min",
                  "machines": [{"machine": "merge_gate", "confidence": 0.71}], "in": 1}]


def test_a_stock_whose_id_changes_keeps_its_key_and_mark_and_a_renamed_collector_too(tmp_path):
    ms = saved(tmp_path, model([st("x", name="x", instrument="old")]))
    ms.intended().apply([{"op": "expect", "part": "stock", "key": "x"}], OWNER)
    ms.save(model([st("x_other", name="x", instrument="renamed")]))
    b = block(ms)
    assert b["marks"]["stocks"] == {"x_other": ["expected"]}
    assert not [c for c in b["changes"] if c["sign"] in "+-"] and entry(b, key="x")["present"]


def test_a_part_carried_from_the_prior_is_not_new_and_a_key_counts_once(tmp_path):
    carried = st("c")
    carried.evidence["prior"] = {"era": "e0"}
    ms = saved(tmp_path, model([st("a")]), model([st("a"), carried, st("b", instrument="one"), st("b_2", name="b", instrument="two")]))
    b = block(ms)
    assert [c["key"] for c in b["changes"] if c["sign"] == "+"] == ["b"]


def test_a_suggestion_settles_after_announce_hold_versions_and_one_that_leaves_came_and_went(tmp_path):
    a, s1, s2 = st("a"), st("s1"), st("s2")
    ms = saved(tmp_path, model([a]), model([a, s1]), model([a, s1, st("t")]), model([a, s1]))
    b = block(ms)
    assert b["settled"] == 1 and "s1" not in b["marks"]["stocks"] and not any(c.get("key") == "s1" for c in b["changes"])
    ms.intended().apply([{"op": "expect", "part": "stock", "key": "s1"}], OWNER)
    assert entry(block(ms), key="s1")["present"]
    assert block(ms)["came_and_went"] == [{"part": "stock", "key": "t", "versions": 1, "last": 3}]
    ms.save(model([a, s1, st("t")]))
    b = block(ms)
    assert any(c.get("key") == "t" and c["sign"] == "+" for c in b["changes"]) and b["came_and_went"] == []
    assert not b["stabilised"]
    ms.save(model([a, s1, s2]))           # t left again, s2 new
    ms.save(model([a, s1, s2]))
    ms.save(model([a, s1, s2, st("u")]))
    ms.save(model([a, s1, s2]))
    assert block(ms)["stabilised"] is True


def test_ignore_and_unignore(tmp_path):
    ms = saved(tmp_path, model([st("a")]), model([st("a"), st("b")]))
    ms.intended().apply([{"op": "ignore", "part": "stock", "key": "b"}], OWNER)
    b = block(ms)
    assert [i["key"] for i in b["ignored"]] == ["b"] and not any(c.get("key") == "b" for c in b["changes"])
    ms.intended().apply([{"op": "unignore", "part": "stock", "key": "b"}], OWNER)
    b = block(ms)
    assert b["ignored"] == [] and any(c.get("key") == "b" and c["sign"] == "+" for c in b["changes"])


def test_a_declared_flow_with_an_outside_end_or_two_matches_gives_candidates_and_no_match(tmp_path):
    ms = saved(tmp_path, model([st("a"), st("b")], [fl("f1", "a", "b", "one_total"), fl("f2", "a", "b", "two_total"),
                                                    fl("f3", "a", None, "out_total")]))
    ms.intended().apply([{"op": "declare_flow", "id": "ab", "from": "a", "to": "b"},
                         {"op": "declare_flow", "id": "out", "from": "a", "to": None}], OWNER)
    b = block(ms)
    ab, out = entry(b, id="ab"), entry(b, id="out")
    assert not ab["present"] and {c["id"] for c in ab["candidates"]} == {"f1", "f2"}
    assert not out["present"] and [c["id"] for c in out["candidates"]] == ["f3"]
    ms.save(model([st("a"), st("b")], [fl("f1", "a", "b", "one_total")]))
    assert entry(block(ms), id="ab")["present"] is True


def test_link_alone_sets_found_as_and_an_effect_may_link_a_series(tmp_path):
    m = model([st("acceptance_tests_passing", instrument="features.acceptance")])
    m.discovery = {"inputs": {"latency": {"name": "latency_seconds", "labels": {"instrument": "x"}}}}
    ms = saved(tmp_path, m)
    it = ms.intended()
    it.apply([{"op": "declare_stock", "name": "Features"}, {"op": "declare_effect", "name": "Latency"},
              {"op": "record_measurement", "part": "stock", "id": "features", "chosen": "a",
               "options": [{"key": "a", "instrument": "features.acceptance"}]}], OWNER)
    e = entry(block(ms), id="features")
    assert not e["present"] and e["key"] is None and [c["key"] for c in e["candidates"]] == ["acceptance_tests_passing"]
    it.apply([{"op": "link", "id": "features", "found_as": "acceptance_tests_passing"},
              {"op": "link", "id": "latency", "found_as": "latency_seconds"}], OWNER)
    b = block(ms)
    assert entry(b, id="features")["present"] and entry(b, id="features")["candidates"] == []
    assert entry(b, id="latency")["present"]
    assert b["marks"]["stocks"]["acceptance_tests_passing"] == ["expected"]


def test_browsing_a_past_version_pairs_it_with_the_declared_layer_of_its_time(tmp_path):
    ms = saved(tmp_path, model([st("a")]))
    it = ms.intended()
    it.apply([{"op": "declare_stock", "name": "Early"}], {**OWNER, "at": time.time() - 100})
    time.sleep(0.01)
    ms.save(model([st("a"), st("b")]))
    it.apply([{"op": "declare_stock", "name": "Late"}], OWNER)
    past = dynamics_block(it, ms.load(1), None, version=1, live=False)
    assert past["version"] == 1 and [e["id"] for e in past["expected"]] == ["early"]
    assert [e["id"] for e in block(ms)["expected"]] == ["early", "late"]


def test_the_cache_holds_structure_only(tmp_path):
    ms = saved(tmp_path, model([st("a")]), model([st("a"), st("b")]))
    ms.intended().apply([{"op": "declare_stock", "name": "Features"}], OWNER)
    block(ms)
    files = list((ms.dir / "intended" / "diff").glob("*.json"))
    assert [f.name for f in files] == ["d1-v2-v1-none.json"]
    body = json.loads(files[0].read_text())["diff"]
    assert set(body) == {"expected", "new", "removed", "status"}
    text = json.dumps(body)
    assert "heard" not in text and "recording" not in text and "measured" not in text


def test_predicted_flows_are_ghosts_with_no_machine(tmp_path):
    ms = saved(tmp_path, model([st("a"), st("b")]))
    ms.intended().apply([{"op": "propose_machine", "id": "improver"},
                         {"op": "set_expected_effect", "machine": "improver", "horizon_s": 60,
                          "edits": [{"from": "a", "to": "b", "appears": True}]}], {"author": "supervisor"})
    p = block(ms)["predicted"]
    assert p == [{"from": "a", "to": "b", "key": None, "present": False, "candidates": [], "state": "predicted", "id": None}]
    assert block(ms)["expected"] == []
