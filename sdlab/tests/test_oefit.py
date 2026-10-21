"""oefit.py (docs/research/k8s-306-r3-oefit.md): the output-error refit and revision under measurement error.

Each strategy that uses it carries its own copy (strategies are isolated); the copies are written identical.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np

from sdlab.ladder import cases as casemod, data

ROOT = Path(__file__).resolve().parents[1] / "sdlab" / "discovery" / "strategies"
COPIES = sorted(p.parent.name for p in ROOT.glob("*/oefit.py"))
oe = importlib.import_module(f"sdlab.discovery.strategies.{COPIES[0]}.oefit")


def test_copies_identical():
    texts = {(ROOT / s / "oefit.py").read_text() for s in COPIES}
    assert len(COPIES) >= 5 and len(texts) == 1


def _flow(src, dst, terms=(), mins=(), c=None):
    return {"src": src, "dst": dst, "c": c, "terms": list(terms), "mins": list(mins), "fixed": False, "orig": None}


def test_simulates_as_the_engine_steps():
    """A drain past 1 a step takes what the stock holds; an injection lands before its step's flows;
    a MIN takes the lesser of its arms."""
    net = oe._Net([_flow(0, 1, [(0, 1.5)]), _flow(1, -1, mins=[(1, 2, 2.0, 0.5)])], [])
    A = np.zeros((3, 4))
    inj = np.zeros((3, 4))
    inj[0, 2] = 10.0
    d = oe._Data(A, inj, np.zeros((0, 4)))
    X = oe._run(net, d, np.array([4.0, 0.0, 1.0]))
    assert X[0].tolist() == [4.0, 0.0, 0.0, 0.0]
    assert X[1, 1] == 4.0 and X[1, 2] == 4.0 - 1.0 + 10.0      # out: min(0.5 x 4, 0.5 x 2 x 1) = 1
    assert X[2].tolist() == [1.0, 1.0, 1.0, 1.0]


def test_canonical_form_runs_the_same():
    """A stock that always empties: its outflows written as shares of 1, the run unchanged."""
    net = oe._Net([_flow(0, 1, [(0, 0.9)]), _flow(0, -1, [(0, 0.6)])], [])
    d = oe._Data(np.zeros((2, 30)), np.zeros((2, 30)), np.zeros((0, 30)))
    d.inj[0, 5] = 7.0
    start = np.array([5.0, 0.0])
    can = oe._canonical(net)
    assert np.allclose([f["terms"][0][1] for f in can.flows], [0.6, 0.4])
    assert np.allclose(oe._run(net, d, start), oe._run(can, d, start))


def test_gate_reads_measurement_error_only():
    """The gate fires on 306 meas-short and not on its none or counts runs (the MIN read as 0.5 x queue)."""
    c = casemod.load("306-k8s-ready-replicas-cap")
    got = {}
    for v in ("none-short", "counts-short", "meas-short"):
        model = casemod.truth_model(c, v)
        d = {**data.load(c, v), **casemod.announced(c)}
        ids = [s["id"] for s in casemod.page_stocks(model)]
        flows = [{"from": f.get("from"), "to": f.get("to"),
                  "rate": f["rate"] if f["rate"].get("form") != "expr" else {"form": "proportional", "stock": "queue", "k": 0.5}}
                 for f in model["flows"]]
        got[v] = oe._measurement_error(flows, ids, {"t": d["t"], "levels": d["levels"]}, {"inputs": {k: list(x) for k, x in d["inputs"].items()}})
    assert got == {"none-short": False, "counts-short": False, "meas-short": True}
