"""Co-flows in the ground-truth engine: a flow that uses up another stock as it moves (`uses`)."""

import json

from sdlab.sdtruth import Truth


def run(tmp_path, flows, stocks, steps=400, noise=None):
    model = {"id": "t", "seed": 3, "steps": steps, "noise": {"counts": True} if noise is None else noise,
             "stocks": [{"name": s["id"], "unit": "x", **s} for s in stocks], "flows": [{"name": f["id"], **f} for f in flows]}
    p = tmp_path / "truth.model.json"
    p.write_text(json.dumps(model))
    t = Truth(p)
    return t, t.run(steps=steps)


def test_each_unit_moved_uses_up_per_of_the_used_stock(tmp_path):
    t, r = run(tmp_path, stocks=[{"id": "blanks", "initial": 50}, {"id": "parts"}, {"id": "bits", "initial": 1000}],
               flows=[{"id": "in", "from": None, "to": "blanks", "rate": {"form": "constant", "value": 5}},
                      {"id": "mill", "from": "blanks", "to": "parts", "rate": {"form": "proportional", "stock": "blanks", "k": 0.2}, "uses": [{"stock": "bits", "per": 0.1}]}])
    milled = sum(r["counters"]["mill"])
    assert milled > 1000
    assert abs((1000 - r["levels"]["bits"][-1]) - 0.1 * milled) <= 1, "bits used = 0.1 x parts milled"
    key = t.truth()
    assert key["coflows"] == [{"stock": "bits", "per": 0.1, "from": "blanks", "to": "parts", "flow": "mill", "what": "mill", "rate": key["coflows"][0]["rate"]}]


def test_a_flow_stops_when_what_it_uses_runs_out(tmp_path):
    _, r = run(tmp_path, stocks=[{"id": "blanks", "initial": 50}, {"id": "parts"}, {"id": "bits", "initial": 20}],
               flows=[{"id": "in", "from": None, "to": "blanks", "rate": {"form": "constant", "value": 5}},
                      {"id": "mill", "from": "blanks", "to": "parts", "rate": {"form": "proportional", "stock": "blanks", "k": 0.2}, "uses": [{"stock": "bits", "per": 0.1}]}])
    assert sum(r["counters"]["mill"]) <= 200, "20 bits mill at most 200 parts"
    assert min(r["levels"]["bits"]) >= 0
    assert r["levels"]["blanks"][-1] > 1000, "once the bits are gone, blanks pile up"


def test_a_stock_shares_what_it_holds_between_its_outflows_and_the_flows_that_use_it(tmp_path):
    _, r = run(tmp_path, noise={}, stocks=[{"id": "a", "initial": 100}, {"id": "b"}, {"id": "fuel", "initial": 10}, {"id": "spill"}],
               flows=[{"id": "move", "from": "a", "to": "b", "rate": {"form": "constant", "value": 30}, "uses": [{"stock": "fuel", "per": 1}]},
                      {"id": "leak", "from": "fuel", "to": "spill", "rate": {"form": "constant", "value": 10}}], steps=1)
    assert r["counters"]["move"] == [7.5] and r["counters"]["leak"] == [2.5], "fuel's 10 shared in proportion to the 30 and 10 wanted"
    assert r["levels"]["fuel"] == [0.0]
