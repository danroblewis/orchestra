"""The boundary kind "input" in every boundary.py copy (the user, 2026-10-21): an "input" side's flow is
exactly 1 x the measured input (never refitted or rescaled, nothing beside it), the stock's other flows
are refitted around it, and a declared side keeps at most as many outside flows as it declares."""

import importlib
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1] / "sdlab" / "discovery" / "strategies"
COPIES = sorted(str(p.relative_to(ROOT.parents[2])).replace("/", ".")[:-3] for p in ROOT.rglob("boundary.py"))


def _data():
    rng = np.random.default_rng(3)
    T = 200
    pump = 20 + 10 * (np.arange(T + 1) % 30 < 8) + rng.normal(0, 1, T + 1)
    A = [100.0]
    for i in range(T):
        A.append(A[-1] + pump[i + 1] - 0.1 * A[-1])
    stocks = [{"id": "A"}]
    run = {"t": list(range(T + 1)), "levels": {"A": A}, "boundary": {"A": {"in": ["input"], "out": ["estimate"]}},
           "boundary_declared": True}
    return stocks, run, {"inputs": {"pump": list(pump)}}


def test_there_are_46_copies():
    assert len(COPIES) == 46


@pytest.mark.parametrize("mod", COPIES)
def test_an_input_side_is_exactly_the_input(mod):
    bd = importlib.import_module(mod)
    stocks, run, opts = _data()
    b = bd.Boundary(run)
    assert b.fixed == {"A": 1} and b.kinds("A", "in") == {"measured"}       # searched as a measured side
    lin = lambda k: {"form": "linear", "c": 0, "terms": [{"stock": "pump", "k": k}]}  # noqa: E731
    flows = [{"from": None, "to": "A", "ratio": 1, "rate": lin(0.8), "rates": [lin(0.8)], "input": "pump"},
             {"from": "A", "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": "A", "k": 0.05}},
             {"from": "A", "to": None, "ratio": 1, "rate": {"form": "constant", "value": 2.0}}]
    for final in (False, True):
        r = bd.apply({"flows": flows}, stocks, run, opts, final=final)
        ins = [f for f in r["flows"] if f.get("from") is None]
        outs = [f for f in r["flows"] if f.get("to") is None]
        assert len(ins) == 1 and ins[0]["rate"] == {"form": "proportional", "stock": "pump", "k": 1.0}, ins
        assert len(outs) == 1, outs                                           # one outflow declared: merged into one
        k = {x["stock"]: x["k"] for x in outs[0]["rate"].get("terms") or []}.get("A", outs[0]["rate"].get("k"))
        assert abs(k - 0.1) < 0.01, outs                                      # refitted around the fixed input


@pytest.mark.parametrize("mod", COPIES[:3])
def test_measured_and_undeclared_unchanged(mod):
    bd = importlib.import_module(mod)
    stocks, run, opts = _data()
    run = {**run, "boundary": {"A": {"in": ["measured"], "out": ["estimate"]}}}
    assert bd.Boundary(run).fixed == {}
    r = bd.apply({"flows": []}, stocks, {k: v for k, v in run.items() if k not in ("boundary", "boundary_declared")}, opts)
    assert r["flows"] == []
