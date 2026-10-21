"""oe.py (docs/research/k8s-306-r3-five.md): the state-space refinement of five kubernetes survivors' answers.

Each strategy carries its own copy (strategies are isolated); the copies are written identical.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from sdlab.ladder import cases as casemod, data

ROOT = Path(__file__).resolve().parents[1] / "sdlab" / "discovery" / "strategies"
COPIES = sorted(p.parent.name for p in ROOT.glob("*/oe.py"))
CASE = "306-k8s-ready-replicas-cap"


def _args(case_id: str, variant: str):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = {**data.load(c, variant), **casemod.announced(c)}
    opts = {"eras": d["eras"] if len(d.get("eras") or []) > 1 else None}
    if d.get("injections"):
        opts["injections"] = [{"t": j["t"], "stock": j["stock"], "amount": j["amount"]} for j in d["injections"]]
    if d.get("inputs"):
        opts["inputs"] = {k: list(v) for k, v in d["inputs"].items()}
    run = {"t": d["t"], "levels": d["levels"]}
    if d.get("boundary_declared"):
        run.update(boundary=d["boundary"], boundary_declared=True)
    return casemod.page_stocks(model), run, opts


def _p(stock, k):
    return {"form": "proportional", "stock": stock, "k": k}


TRUTH = [{"from": None, "to": "queue", "rate": {"form": "linear", "c": 0, "terms": [{"stock": "traffic", "k": 1.0}]}},
         {"from": "queue", "to": "inflight", "rate": {"form": "expr", "expr": "min(0.6 * queue, 40.0 * ready)"}, "id": "d"},
         {"from": "queue", "to": "retries", "rate": _p("queue", 0.08)},
         {"from": "retries", "to": "queue", "rate": _p("retries", 0.6)},
         {"from": "retries", "to": None, "rate": _p("retries", 0.4)},
         {"from": "inflight", "to": "responses_total", "rate": _p("inflight", 0.5)},
         {"from": "inflight", "to": "errors_total", "rate": _p("inflight", 0.03)}]


def test_copies_identical():
    texts = {(ROOT / s / "oe.py").read_text() for s in COPIES}
    assert set(COPIES) >= {"earned_pieces", "latent_eras", "mass_balance", "numopt_powell", "shared_noise"}
    assert len(texts) == 1


def test_parse_capmin_expression():
    oe = importlib.import_module(f"sdlab.discovery.strategies.{COPIES[0]}.oe")
    parts = oe._parse_expr("0.5 + 0.25 * queue + min(0.6 * queue, 40.0 * ready)")
    assert parts == [("c", 0.5), ("t", "queue", 0.25), ("m", "queue", 0.6, "ready", 40.0)]
    with pytest.raises(oe.Unsupported):
        oe._parse_expr("max(queue, ready)")


@pytest.mark.parametrize("variant", ["none-short", "none-long", "counts-short"])
def test_gate_leaves_answers_without_measurement_error(variant):
    """none-long's levels are rounded to 4 decimals: white, but rounding, not measurement error."""
    oe = importlib.import_module(f"sdlab.discovery.strategies.{COPIES[0]}.oe")
    stocks, run, opts = _args(CASE, variant)
    r = {"flows": [dict(f) for f in TRUTH]}
    assert oe.refine(r, stocks, run, opts) is r


def test_true_structure_kept_on_meas_short():
    """On 306 meas-short the true structure is a local optimum of the price: refining it keeps every flow
    (numbers refitted), with the input inflow held at exactly 1 x traffic."""
    oe = importlib.import_module(f"sdlab.discovery.strategies.{COPIES[0]}.oe")
    stocks, run, opts = _args(CASE, "meas-short")
    out = oe.refine({"flows": [dict(f) for f in TRUTH]}, stocks, run, opts)
    pairs = sorted((f["from"] or "", f["to"] or "") for f in out["flows"])
    assert pairs == sorted((f["from"] or "", f["to"] or "") for f in TRUTH)
    inflow = next(f for f in out["flows"] if f["from"] is None)
    assert inflow["rate"]["terms"] == [{"stock": "traffic", "k": 1.0}]
    dispatch = next(f for f in out["flows"] if (f["from"], f["to"]) == ("queue", "inflight"))
    assert dispatch["rate"]["form"] == "expr" and dispatch["rate"]["expr"].startswith("min(")
