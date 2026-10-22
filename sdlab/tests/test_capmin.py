"""capmin.py (docs/research/k8s-306-s1.md): the capacity limit offered to each kubernetes survivor's fit.

Each strategy carries its own copy (strategies are isolated); the copies are written identical.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from sdlab.ladder import cases as casemod, data

ROOT = Path(__file__).resolve().parents[1] / "sdlab" / "discovery" / "strategies"
COPIES = sorted(p.parent.name for p in ROOT.glob("*/capmin.py"))


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


def test_copies_exist_and_most_are_unchanged():
    """The copies were written identical; a strategy may change its own (CLAUDE.md rule 11: strategies are improved
    freely; combined2, structures and engine_forms did in the kubernetes climb, 2026-10-21/22), so only the bulk is
    checked to be the original."""
    texts = [(ROOT / s / "capmin.py").read_text() for s in COPIES]
    assert len(COPIES) >= 40
    assert max(texts.count(x) for x in set(texts)) >= len(COPIES) - 8


@pytest.mark.parametrize("variant", ["none-short", "counts-short"])
def test_offers_the_dispatch_limit_on_306(variant):
    capmin = importlib.import_module(f"sdlab.discovery.strategies.{COPIES[0]}.capmin")
    stocks, run, opts = _args("306-k8s-ready-replicas-cap", variant)
    o, cap = capmin.offer(stocks, run, opts)
    assert cap and (cap["source"], cap["cap"], cap.get("to")) == ("queue", "ready", "inflight")
    assert abs(cap["theta"] - 40 / 0.6) < 1.0
    assert capmin.readers(cap["name"], o) == ("queue", "inflight")
    r = capmin.restore({"flows": [{"from": "queue", "to": "inflight",
                                   "rate": {"form": "linear", "c": 0, "terms": [{"stock": cap["name"], "k": 0.6}]}}]}, cap)
    assert r["flows"][0]["rate"]["form"] == "expr" and r["flows"][0]["rate"]["expr"].startswith("min(0.6 * queue,")


@pytest.mark.parametrize("variant", ["none-short", "counts-short"])
def test_no_offer_without_a_limit(variant):
    capmin = importlib.import_module(f"sdlab.discovery.strategies.{COPIES[0]}.capmin")
    stocks, run, opts = _args("305-k8s-retries", variant)
    o, cap = capmin.offer(stocks, run, opts)
    assert cap is None and o.get("inputs") == opts.get("inputs")
