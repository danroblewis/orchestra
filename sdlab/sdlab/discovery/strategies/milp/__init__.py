"""milp: structure and numbers found together by one mixed-integer program (docs/research/milp.md).

Every candidate flow the boundary allows (moves between measured stocks, declared outside flows,
capacity-limited flows MIN(a x source, b x another stock or input)) gets a binary "in the model" and
numbers bounded by big-M; a capacity-limited flow also gets a per-step regime binary (which side is the
lesser). HiGHS minimises the misfit of the one-step changes plus a BIC price per number: best-subset
selection (Bertsimas, King and Mazumder 2016; Bertsimas and Gurnee 2023 for SINDy-style discovery) and
piecewise-affine identification (Roll, Bemporad and Ljung 2004) in one program. The chosen structure's
numbers are then refitted by least squares on every step, the noise scales re-estimated from what it
leaves, and the program solved again until the structure no longer changes.

Self-contained: it imports nothing from other strategies or the shared library (highspy, numpy, scipy).
"""

from __future__ import annotations

import time

import numpy as np

from . import candidates, program
from .refit import Structure, drop_tiny, prune
from .steps import Steps

__all__ = ["identify"]

SCREEN = 6            # MIN flows offered beyond those on the flows found: the best by the screen
SAMPLE = 300          # steps the program reads (evenly spaced over the run when it is longer)
PASSES = 4            # program solves at most (each re-estimates the noise scales and offers MINs on the flows found)
TIME_LIMIT = 20.0     # seconds of HiGHS per solve
GAP = 1e-4            # relative MIP gap HiGHS stops at
DEBUG = bool(__import__("os").environ.get("MILP_DEBUG"))
FLOOR = 1e-6          # a stock's noise scale is at least this fraction of its typical level and change


def _floor(st: Steps) -> np.ndarray:
    lv = np.mean(np.abs(st.L), axis=1)
    ch = np.sqrt(np.mean(st.dy ** 2, axis=1))
    return FLOOR * (lv + ch) + 1e-12


def _first_scale(st: Steps) -> np.ndarray:
    """Each stock's scatter left by a plain linear fit of its change on every level and input (an upper
    bound on the noise, to price the first solve)."""
    X = np.column_stack([np.ones(st.T)] + [st.L[i] for i in range(len(st.ids))] + [st.inputs[k] for k in sorted(st.inputs)])
    out = []
    for s in range(len(st.ids)):
        beta = np.linalg.lstsq(X, st.dy[s], rcond=None)[0]
        out.append(float(np.mean(np.abs(st.dy[s] - X @ beta))))
    return np.maximum(np.array(out), _floor(st))


def _scales(st: Steps, base: np.ndarray, gross: np.ndarray | None) -> np.ndarray:
    """Per stock and step: the stock's scale, and for counts a Poisson-like one growing as the square
    root of the amount moved through the stock in the step."""
    sc = np.repeat(base[:, None], st.T, axis=1)
    if st.counts and gross is not None:
        g = np.maximum(gross, 1.0)
        sc = sc * np.sqrt(g / np.mean(g, axis=1, keepdims=True))
    return np.maximum(sc, _floor(st)[:, None])


def _claims(s: Structure, bd) -> float:
    """CLAIM_PRICE log T per outside flow where no boundary is declared."""
    if not bd.claim():
        return 0.0
    n = len({(p[1], p[2]) for p in s.parts if p[1] is None or p[2] is None})
    return program.CLAIM_PRICE * np.log(max(s.st.T, 2)) * n


def _screen(st: Steps, s: Structure, mins: list, scale: np.ndarray) -> list:
    """The MIN flows most worth offering (column generation's pricing step, by least squares): each
    flow's best threshold column, scored by how much of what the structure s leaves unexplained
    (stocks x steps, per noise scale) it would explain alone; the SCREEN best."""
    e = (st.dy - s.change()) / scale
    pos = {x: i for i, x in enumerate(st.ids)}
    scored = []
    for mf in mins:
        x, y = st.series(mf.src), st.series(mf.cap)
        best = 0.0
        for th in candidates.thresholds(st, mf):
            f = np.minimum(x, th * y)
            num, den = 0.0, 0.0
            for end, sign in ((mf.src, -1.0), (mf.dst, 1.0)):
                if end in pos:
                    g = sign * f / scale[pos[end]]
                    num += float(g @ e[pos[end]])
                    den += float(g @ g)
            if den > 0 and num > 0:
                best = max(best, num * num / den)
        scored.append((best, mf))
    scored.sort(key=lambda z: -z[0])
    return [mf for sc, mf in scored[:SCREEN] if sc > 0]


def _sample(T: int) -> np.ndarray:
    return np.arange(T) if T <= SAMPLE else np.unique(np.linspace(0, T - 1, SAMPLE).round().astype(int))


def _num(v: float) -> float:
    return float(f"{v:.6g}")


def _flows(s: Structure) -> list[dict]:
    """The structure in SD Lab's flow format."""
    groups: dict[tuple, list] = {}
    out = []
    for p, v in s.numbers():
        if p[0] == "term" and v[0] > 0:
            groups.setdefault((p[1], p[2]), []).append((p[3], v[0]))
    for (src, dst), parts in groups.items():
        c = sum(v for r, v in parts if r is None)
        reads = [(r, v) for r, v in parts if r is not None]
        if not reads:
            rate = {"form": "constant", "value": _num(c)}
        elif len(reads) == 1 and c == 0:
            rate = {"form": "proportional", "stock": reads[0][0], "k": _num(reads[0][1])}
        else:
            rate = {"form": "linear", "c": _num(c), "terms": [{"stock": r, "k": _num(v)} for r, v in reads]}
        out.append({"from": src, "to": dst, "ratio": 1, "rate": rate})
    for p, v in s.numbers():
        a, b = (v + [0.0])[:2]
        if p[0] == "min" and a > 0 and b > 0:
            out.append({"from": p[1], "to": p[2], "ratio": 1,
                        "rate": {"form": "expr", "expr": f"min({_num(a):g} * {p[1]}, {_num(b):g} * {p[3]})"}})
    return out


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    began = time.perf_counter()
    opts = dict(opts or {})
    st = Steps(stocks, run, opts)
    if st.T < 3 or not st.ids:
        return {"flows": [], "milp": {"note": "too few steps"}}
    bd = candidates.Boundary(run)
    terms, mins = candidates.build(st, bd)
    K = _sample(st.T)
    scale = _scales(st, _first_scale(st), None)
    solves, seen, tried, zoom, start = [], set(), [], None, None
    offer: list = []                       # MIN flows offered: on the flows the last solve chose (none at first)
    for _ in range(PASSES):
        cols = candidates.columns(st, terms, offer, bd.claim(), zoom)
        sol = program.solve(st.ids, st.dy, cols, K, scale[:, K], st.T, bd.claim(), TIME_LIMIT, GAP, start)
        solves.append(sol["report"])
        if not sol["report"]["found"]:
            break
        s = drop_tiny(Structure(st, sol["chosen"]))
        s.refit(scale)
        if DEBUG:
            print("pass", sol["report"], "\n  chosen", [(p, [round(x, 5) for x in v]) for p, v in s.numbers()], "\n  bic", s.bic(scale, _floor(st)))
        price = lambda x: x.bic(scale, _floor(st), _claims(x, bd))  # noqa: E731
        if tried and price(s) >= min(price(x) for x in tried):
            tried.append(s)
            break                          # no better than a structure already found: the search has converged
        tried.append(s)
        pairs = {(p[1], p[2]) for p in s.parts if p[1] is not None and (p[0] == "min" or p[3] == p[1])}
        nxt = [m for m in mins if (m.src, m.dst) in pairs]
        nxt += [m for m in _screen(st, s, mins, scale) if m not in nxt]
        if (s.key(), len(nxt)) in seen:
            break
        seen.add((s.key(), len(nxt)))
        offer, zoom, start = nxt, s.thetas(), sol["chosen"]
        e = np.abs(st.dy - s.change())
        unit = _scales(st, np.ones(len(st.ids)), s.gross())
        scale = _scales(st, np.maximum(np.mean(e / unit, axis=1), _floor(st)), s.gross())
    best = None
    if tried:                               # the solves' structures compared on every step at the last noise scales
        for x in tried:
            x.refit(scale)
        best = min(tried, key=lambda x: x.bic(scale, _floor(st), _claims(x, bd)))
        best = prune(best, scale, _floor(st), lambda x: _claims(x, bd))
        if DEBUG:
            print("  pruned", [(p, [round(x, 5) for x in v]) for p, v in best.numbers()], best.bic(scale, _floor(st)))
    flows = _flows(best) if best is not None else []
    rep = {"solves": solves, "seconds": round(time.perf_counter() - began, 3),
           "solve_seconds": round(sum(r["seconds"] for r in solves), 3),
           "gap": solves[-1]["gap"] if solves else None,
           "gap_closed": bool(solves) and all(r["status"] == "Optimal" for r in solves),
           "candidates": {"terms": len(terms), "min_flows": len(mins), "columns": len(cols)}, "sample": int(len(K)), "counts": st.counts}
    return {"flows": flows, "milp": rep}
