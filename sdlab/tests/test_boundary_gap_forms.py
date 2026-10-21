"""The affine form c + k X on a declared estimate side, in matrix/boundary.py and every copy
(docs/research/declared-boundary.md, cause 3): a drain with an offset (104's 0.1 T - 7) and a goal gap
(011's (300 - I) / 5), fitted jointly; nothing changes where no boundary is declared."""

from __future__ import annotations

import importlib
import pathlib

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "sdlab" / "discovery" / "strategies"
COPIES = sorted(".".join(p.relative_to(ROOT).with_suffix("").parts) for p in ROOT.rglob("boundary.py"))


def _flow(a, b, rate, **kw):
    return {"from": a, "to": b, "ratio": 1, "rate": rate, "rates": [rate], **kw}


def _cooling(T: int = 400, seed: int = 1) -> dict:
    """H -> outside = 0.1 H - 7 (cools toward 70), topped up by 100 every 60 steps, small noise."""
    rng = np.random.default_rng(seed)
    H, inj = [180.0], []
    for t in range(1, T + 1):
        h = H[-1] + (100.0 if t % 60 == 0 else 0.0)
        if t % 60 == 0:
            inj.append({"t": t, "stock": "H", "amount": 100.0})
        H.append(h - (0.1 * h - 7) + rng.normal(0, 0.05))
    run = {"t": list(range(T + 1)), "levels": {"H": H}}
    return run, {"injections": inj}


def _gap(T: int = 300, seed: int = 2) -> dict:
    """outside -> P = (300 - I) / 5, P -> I = 0.25 P, I -> outside = 0.1 I."""
    rng = np.random.default_rng(seed)
    P, I = [0.0], [0.0]
    for _ in range(T):
        p, i = P[-1], I[-1]
        o = max(0.0, 60 - 0.2 * i)
        P.append(p + o - 0.25 * p + rng.normal(0, 0.2))
        I.append(i + 0.25 * p - 0.1 * i + rng.normal(0, 0.2))
    return {"t": list(range(T + 1)), "levels": {"P": P, "I": I}}, {}


def _affine(flows, frm, to):
    f = next(f for f in flows if f.get("from") == frm and f.get("to") == to)
    r = f["rate"]
    assert r["form"] == "linear" and len(r["terms"]) == 1, r
    return r["c"], r["terms"][0]["stock"], r["terms"][0]["k"]


@pytest.mark.parametrize("mod", COPIES)
def test_drain_with_an_offset(mod):
    m = importlib.import_module(f"sdlab.discovery.strategies.{mod}")
    run, opts = _cooling()
    run.update(boundary={"H": {"out": ["estimate"]}}, boundary_declared=True)
    r = m.apply({"flows": [_flow("H", None, {"form": "proportional", "stock": "H", "k": 0.03})]},
                [{"id": "H"}], run, opts)
    c, x, k = _affine(r["flows"], "H", None)
    assert x == "H" and abs(k - 0.1) < 0.005 and abs(c + 7) < 0.4, (c, k)
    assert any("c + k H" in s for s in r["boundary"]["changed"])


@pytest.mark.parametrize("mod", COPIES)
def test_goal_gap(mod):
    m = importlib.import_module(f"sdlab.discovery.strategies.{mod}")
    run, opts = _gap()
    run.update(boundary={"P": {"in": ["estimate"]}, "I": {"out": ["estimate"]}}, boundary_declared=True)
    flows = [_flow(None, "P", {"form": "constant", "value": 20.0}),
             _flow("P", "I", {"form": "proportional", "stock": "P", "k": 0.25}),
             _flow("I", None, {"form": "proportional", "stock": "I", "k": 0.1})]
    r = m.apply({"flows": flows}, [{"id": "P"}, {"id": "I"}], run, opts)
    c, x, k = _affine(r["flows"], None, "P")
    assert x == "I" and abs(k + 0.2) < 0.01 and abs(c - 60) < 2, (c, k)


@pytest.mark.parametrize("mod", COPIES)
def test_nothing_where_undeclared(mod):
    m = importlib.import_module(f"sdlab.discovery.strategies.{mod}")
    run, opts = _cooling()
    r = m.apply({"flows": [_flow("H", None, {"form": "proportional", "stock": "H", "k": 0.03})]},
                [{"id": "H"}], run, opts)
    assert not any("c + k" in s for s in r["boundary"]["changed"])


@pytest.mark.parametrize("mod", COPIES)
def test_no_offset_from_measurement_error(mod):
    """A plain drain 0.1 H measured with 10% error: least squares on the one-step changes reads an offset
    (regression to the mean: -7.6 + 0.22 H
    with IV_Z 0); instrumented, it is not there."""
    m = importlib.import_module(f"sdlab.discovery.strategies.{mod}")
    rng = np.random.default_rng(3)
    H = [180.0]
    for t in range(1, 401):
        H.append(H[-1] + (100.0 if t % 60 == 0 else 0.0) - 0.1 * H[-1])
    run = {"t": list(range(401)), "levels": {"H": [round(h * (1 + 0.1 * rng.normal()), 3) for h in H]},
           "boundary": {"H": {"out": ["estimate"]}}, "boundary_declared": True}
    opts = {"injections": [{"t": t, "stock": "H", "amount": 100.0} for t in range(60, 401, 60)]}
    r = m.apply({"flows": [_flow("H", None, {"form": "proportional", "stock": "H", "k": 0.08})]}, [{"id": "H"}], run, opts)
    assert not any("c + k" in s for s in r["boundary"]["changed"]), r["boundary"]["changed"]
