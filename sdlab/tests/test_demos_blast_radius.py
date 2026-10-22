"""Demo 12, blast radius (docs/demos/blast-radius.md): a slowdown at one service, in a copy of the true model and in a
stored found model, and how it spreads; checked against the truth it is built on."""

import numpy as np
import pytest

from sdlab.demos import blast_radius as B


def test_graph_reads_calls_and_moves_between_services():
    stocks = ["a_queue", "a_inflight", "b_queue", "b_inflight", "c_queue"]
    flows = [{"from": None, "to": "b_queue", "rate": {"form": "linear", "c": 0, "terms": [{"stock": "a_inflight", "k": 0.3}]}},
             {"from": "b_queue", "to": "b_inflight", "rate": {"form": "proportional", "stock": "b_queue", "k": 0.6}},
             {"from": "c_queue", "to": "a_queue", "rate": {"form": "proportional", "stock": "c_queue", "k": 0.01}},
             {"from": None, "to": "c_queue", "rate": {"form": "expr", "expr": "0.2 * b_inflight + traffic"}}]
    assert B.graph(flows, stocks) == [["a", "b"], ["b", "c"], ["c", "a"]]
    lay = B._layout(["a", "b", "c"], [["a", "b"], ["b", "c"]])
    assert [lay[s]["col"] for s in "abc"] == [0, 1, 2]


def _have(key, variant, strategy):
    try:
        return B._found(key, variant, strategy) is not None
    except Exception:                                                  # noqa: BLE001  (no store here)
        return False


needs_315 = pytest.mark.skipif(not _have("fan-out", "none-long", "kalman_lna"), reason="no stored passing kalman_lna result on 315 none-long")
needs_315c = pytest.mark.skipif(not _have("fan-out", "counts-long", "kalman_lna"), reason="no stored passing kalman_lna result on 315 counts-long")


@needs_315
def test_found_baseline_follows_the_truth():
    base, found = B._truth_base("fan-out"), B._found_base("fan-out", "none-long", "kalman_lna")
    for s in B._case("fan-out")["stocks"]:
        a, b = np.asarray(base["levels"][s]), np.asarray(found[s])
        assert np.max(np.abs(a - b)) <= 1e-3 * max(1.0, np.max(np.abs(a))), s


@needs_315
def test_slow_catalog_spreads_to_pricing_only_in_both_models():
    r = B.spread("fan-out", "none-long", "kalman_lna", "catalog", "completion", 0.5, 1000)
    for side in ("true", "found"):
        sv = r["services"][side]
        assert sv["catalog"]["reached"] and sv["catalog"]["after"] == 0
        assert sv["pricing"]["reached"] and sv["pricing"]["after"] == 1
        assert not sv["frontend"]["reached"] and not sv["cart"]["reached"]
    assert abs(r["services"]["found"]["pricing"]["peak"] - r["services"]["true"]["pricing"]["peak"]) < 0.01
    assert r["differences"] == []


@needs_315c
def test_counts_model_false_link_shows_as_a_false_spread():
    """kalman_lna on 315 counts-long has a small cart_queue -> frontend_queue flow the truth lacks: with cart stopped,
    the found model says frontend, catalog and pricing are hit; the truth says only cart is."""
    r = B.spread("fan-out", "counts-long", "kalman_lna", "cart", "dispatch", 0.0, 1000)
    assert ["cart", "frontend"] in r["edges"]["found"] and ["cart", "frontend"] not in r["edges"]["true"]
    assert not r["services"]["true"]["frontend"]["reached"] and r["services"]["found"]["frontend"]["reached"]
    kinds = {(d["kind"], d["about"], d["service"]) for d in r["differences"]}
    assert ("false", "service", "frontend") in kinds and ("false", "link", "frontend") in kinds


@needs_315
def test_ranking_puts_the_shared_caller_first():
    r = B.ranking("fan-out", "none-long", "kalman_lna", "completion", 0.5, 1000)
    assert r["same_order"] and r["same_reach"]
    assert r["rows"][0]["service"] == "frontend" and r["rows"][0]["true"]["reached"] == ["cart", "catalog", "pricing"]
    assert r["rows"][1]["service"] == "catalog"


@needs_315
def test_routes():
    from fastapi.testclient import TestClient

    from sdlab.server import create_app
    c = TestClient(create_app())
    assert c.get("/api/demos/blast-radius/setup").status_code == 200
    r = c.get("/api/demos/blast-radius/spread", params={"case": "fan-out", "service": "cart", "kind": "dispatch", "factor": 0.25})
    assert r.status_code == 200 and r.json()["fault"]["true_flow"] == "cart_dispatched"
    assert c.get("/api/demos/blast-radius/spread", params={"service": "nope"}).status_code == 404
    assert c.get("/api/demos/blast-radius/spread", params={"t": 5}).status_code == 422
    assert c.get("/api/demos/blast-radius/ranking", params={"case": "chain"}).status_code == 200
    assert "/static/demos-blast-radius.js" in c.get("/api/demos/manifest").json()["scripts"]
