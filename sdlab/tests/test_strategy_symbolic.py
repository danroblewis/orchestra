"""Mechanism test for the symbolic effect search (strategy "symbolic", docs/DISCOVERY-EXPERIMENTS.md).

A flow whose rate is k x A x f(C) (an effect: a curve of a third stock's level) is not a sum of
levels, so the matrix method reads it as one constant rate plus links. The grammar search finds the
pair (A, C) and a curve, the matrix fits it as a virtual stock, and translation makes it an SD Lab
effect (a table sampled from the curve) on the flow A -> B. Checked on the smallest models: a steep
table (sharpness of the saw) and an exponent-shaped saturating one (experience), comparing the
recovered rate per unit of A with the truth's over the middle 90% of C's observed range.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from synth import generate, skill

from sdlab.discovery.curves import grammar
from sdlab.discovery.effects import only_rows, screen, translate, virtual
from sdlab.discovery.matrix import identify_one
from sdlab.discovery.strategies import load
from sdlab.runner import effect_value

STEEP = [[0, 0.1], [20, 0.12], [40, 0.25], [55, 0.55], [70, 0.85], [80, 0.97], [90, 1], [100, 1]]
EXPO = [[x, round(1 - 0.8 * math.exp(-x / 40), 3)] for x in (0, 10, 20, 40, 60, 80, 120, 160, 200)]


def _model(a: str, b: str, c: str, k: float, points: list, inflow: float, c_in: list[float], c_out: float, c_init: float) -> dict:
    """Stuff arrives in a, moves a -> b at k x a x table(c), leaves b; c is filled by a supply that
    changes every 50 steps (unannounced) and drains in proportion, so its level sweeps the curve."""
    stocks = [{"id": a, "initial": 100}, {"id": b, "initial": 40}, {"id": c, "initial": c_init, "unit": "points"}]
    flows = [
        {"id": "arrive", "from": None, "to": a, "rate": {"form": "constant", "value": inflow}},
        {"id": "move", "from": a, "to": b, "rate": {"form": "proportional", "stock": a, "k": k},
         "effects": [{"stock": c, "shape": "table", "points": points}]},
        {"id": "leave", "from": b, "to": None, "rate": {"form": "proportional", "stock": b, "k": 0.2}},
        {"id": "supply", "from": None, "to": c, "rate": {"form": "constant", "value": c_in[0]}},
        {"id": "decay", "from": c, "to": None, "rate": {"form": "proportional", "stock": c, "k": c_out}},
    ]
    every = 50 * len(c_in)
    changes = [{"t": 1 + 50 * i, "set": {"supply": {"form": "constant", "value": v}}} for i, v in enumerate(c_in)]
    # arrivals change too (out of step with c's supply), so a's level moves on its own, not only with c's
    changes += [{"t": t, "set": {"arrive": {"form": "constant", "value": inflow * m}}} for t, m in ((1, 1), (76, 1.4), (126, 0.7))]
    sched = {"every": every, "changes": changes}
    return generate(stocks, flows, 2000, schedule=sched)


CASES = {
    "steep": dict(a="logs", b="planks", c="sharp", k=0.25, points=STEEP, inflow=10, c_in=[5.5, 1.5, 3.5, 2.5], c_out=0.06, c_init=80),
    "saturating": dict(a="backlog", b="done", c="skill", k=0.3, points=EXPO, inflow=20, c_in=[8, 1, 5, 0.5], c_out=0.05, c_init=50),
}


def _rate_per_unit(flows: list[dict], a: str, b: str, c: str, xs: np.ndarray) -> np.ndarray:
    """What moves a -> b per unit of a, as a function of c's level (every flow a -> b in a)."""
    out = np.zeros(len(xs))
    for f in flows:
        r = f.get("rate") or {}
        if f.get("from") != a or f.get("to") != b or f.get("inflow"):
            continue
        k = r.get("k") if r.get("form") == "proportional" else r["terms"][0]["k"] if r.get("form") == "linear" and r["terms"][0]["stock"] == a else None
        if k is not None:
            out += [k * math.prod(effect_value(e, {c: x}) for e in f.get("effects") or []) for x in xs]
    return out


@pytest.fixture(scope="module", params=list(CASES))
def case(request):
    p = CASES[request.param]
    d = _model(**p)
    x = np.asarray(d["run"]["levels"][p["c"]], dtype=float)
    xs = np.linspace(np.percentile(x, 5), np.percentile(x, 95), 50)
    truth = np.array([p["k"] * effect_value({"stock": p["c"], "shape": "table", "points": p["points"]}, {p["c"]: v}) for v in xs])
    return request.param, p, d, xs, truth


def test_the_grammar_has_rising_falling_and_saturating_curves():
    u = np.linspace(0, 1, 11)
    kinds = {c.kind for c in grammar()}
    assert {"lin", "sat", "rise", "fall", "acc", "decay", "cap"} <= kinds
    for c in grammar():
        v = c(u)
        assert np.all(np.isfinite(v)) and v.shape == u.shape
        t = c.turned(float(v.max()))
        assert np.allclose(t(u), v.max() - v)


def test_the_screen_finds_which_stock_curves_which_flow(case):
    name, p, d, xs, truth = case
    cols = screen(d["stocks"], d["run"])
    assert cols, name
    first = cols[0]
    assert (first["base"], first["stock"]) == (p["a"], p["c"]), first
    assert set(first["rows"]) >= {p["a"], p["b"]}


def test_the_curve_is_recovered_and_becomes_an_effect_on_the_flow(case):
    name, p, d, xs, truth = case
    cols = screen(d["stocks"], d["run"])
    vstocks, vrun, meta = virtual(d["stocks"], d["run"], cols)
    only = only_rows(meta, [s["id"] for s in d["stocks"]])
    flows = translate(identify_one(vstocks, vrun, {"only_rows": only})["flows"], meta, d["stocks"])
    moves = [f for f in flows if f["from"] == p["a"] and f["to"] == p["b"]]
    assert any(e["stock"] == p["c"] and e["shape"] == "table" for f in moves for e in f.get("effects") or []), moves
    found = _rate_per_unit(flows, p["a"], p["b"], p["c"], xs)
    err = float(np.max(np.abs(found - truth))) / p["k"]
    # steep: 6.8% of k at worst over the middle 90% of the range; saturating: 4.4%
    assert err < 0.08, (name, err, np.round(found[::7], 3), np.round(truth[::7], 3))

    # the matrix reads one constant rate (plus links): off by 72% (steep) and 37% (saturating) of k
    base = load("matrix")(d["stocks"], d["run"], {"eras": d["eras"]})
    assert not any(f.get("effects") for f in base["flows"])
    m_err = float(np.max(np.abs(_rate_per_unit(base["flows"], p["a"], p["b"], p["c"], xs) - truth))) / p["k"]
    assert m_err > 0.3, m_err
    assert skill({"flows": flows}, d) > skill(base, d) + 0.3
