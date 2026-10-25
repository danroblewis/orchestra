"""A row's outside sides rebuilt by best-subset regression (k8s 311, docs/research/fixes/311-structures.md).

The base's row fit is forward stepwise: it adds the one column that lowers BIC most, then the next. A stock
held near a fast equilibrium (cpu: in 1.25 inflight + 20 ready, out 0.5 cpu) changes by a small difference of
large terms, and no single one of those columns explains much of the change alone. On 311 the step-like
columns (the node count, a counter) win the first two steps, and then no single column pays: the row is left
reading `nodes` and `oom_kills_total` with a misfit 10^6 times the exact one.

Here every measured stock (not a counter) whose one-step residual under the answer is above GATE x the data's
quantum has its outside sides refitted together: what its other flows (moves, effects, expressions, a measured
input) leave is regressed on a constant, the measured levels (counters excluded: a running total is a trend,
not a reader), the measured inputs and the capacity series its row may read (capmin.readers), by exhaustive
best subset of at most MAX_TERMS columns on BIC. The terms are written on the sides the declared boundary
gives (with none declared, the sides that already have an outside flow): with both sides, the positive terms
are the inflow and the negative ones the outflow; with one, all of them on it. The rows are refitted under the
engine's floor (each flow's amount at least 0) and the rebuild replaces the row's outside flows only when the
row's BIC falls by GAIN x log n. Nothing reads the case: the same rule runs on every row of every run.
"""

from __future__ import annotations

import copy
import itertools
import math

import numpy as np

from . import capmin, steps
from ._vendored.combined import judge as J
from .hidden import _amount
from .repair import _fixed_side, _linear, _sign

GATE = 100.0
GAIN = 2.0
MAX_TERMS = 4


def _sides(s: str, flows: list[dict], bound: dict, declared: bool) -> list[str]:
    if declared:
        out = []
        for side in ("in", "out"):
            kinds = (bound.get(s) or {}).get(side) or []
            kinds = [kinds] if isinstance(kinds, str) else list(kinds)
            if "estimate" in kinds:
                out.append(side)
        return out
    have = []
    if any(f.get("to") == s and f.get("from") is None for f in flows):
        have.append("in")
    if any(f.get("from") == s and f.get("to") is None for f in flows):
        have.append("out")
    return have


def _replaceable(f: dict, s: str, bound: dict, declared: bool) -> bool:
    """An outside flow of s with a plain rate on an estimated side (what the rebuild writes anew)."""
    if f.get("from") and f.get("to"):
        return False
    if s not in (f.get("from"), f.get("to")) or _fixed_side(f, bound, declared):
        return False
    return (_linear(f.get("rate")) is not None and not f.get("effects") and not f.get("byTime") and not f.get("via")
            and not f.get("uses") and not f.get("two_way") and float(f.get("ratio") or 1) == 1 and not f.get("input"))


def _best_subset(y: np.ndarray, cols: dict[str, np.ndarray], n: int, floor: float):
    """(bic, names, numbers) of the best linear fit of y on at most MAX_TERMS of cols ("1" is the constant)."""
    names = list(cols)
    A = np.column_stack([cols[k] for k in names])
    sc = np.maximum(np.abs(A).max(axis=0), 1e-300)
    A = A / sc
    G, b, yy = A.T @ A, A.T @ y, float(y @ y)
    best = (n * math.log(max(yy, floor) / n), (), np.zeros(0))
    for k in range(1, MAX_TERMS + 1):
        for idx in itertools.combinations(range(len(names)), k):
            ix = list(idx)
            Gs = G[np.ix_(ix, ix)]
            try:
                beta = np.linalg.solve(Gs, b[ix])
            except np.linalg.LinAlgError:
                continue
            rss = yy - float(beta @ b[ix])
            if not math.isfinite(rss):
                continue
            bic = n * math.log(max(rss, floor) / n) + k * math.log(n)
            if bic < best[0]:
                best = (bic, tuple(names[i] for i in ix), beta / sc[ix])
    return best


def _rate(terms: dict[str, float]) -> dict:
    c = float(terms.get("1", 0.0))
    ks = [{"stock": k, "k": float(v)} for k, v in terms.items() if k != "1"]
    if not ks:
        return {"form": "constant", "value": c}
    if len(ks) == 1 and c == 0.0:
        return {"form": "proportional", "stock": ks[0]["stock"], "k": ks[0]["k"]}
    return {"form": "linear", "c": c, "terms": ks}


def _write(s: str, names: tuple, beta: np.ndarray, sides: list[str]) -> list[dict]:
    pos = {k: float(v) for k, v in zip(names, beta) if v > 0}
    neg = {k: -float(v) for k, v in zip(names, beta) if v < 0}
    parts = []
    if sides == ["in"]:
        parts = [("in", {k: float(v) for k, v in zip(names, beta)})]
    elif sides == ["out"]:
        parts = [("out", {k: -float(v) for k, v in zip(names, beta)})]
    else:
        parts = [(side, t) for side, t in (("in", pos), ("out", neg)) if t]
    out = []
    for side, terms in parts:
        rate = _rate(terms)
        out.append({"id": f"rebuild_{s}_{side}", "from": None if side == "in" else s, "to": s if side == "in" else None,
                    "ratio": 1, "rate": rate, "rates": [rate]})
    return out


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """opts: those the answer was fitted with (the capacity series offered as inputs, capmin.py)."""
    if not isinstance(result, dict) or not result.get("flows") or (opts or {}).get("eras"):
        return result
    try:
        return _apply(result, stocks, run, opts or {})
    except Exception as e:                            # noqa: BLE001  (the answer stands as it was)
        return {**result, "rebuild": {"error": f"{type(e).__name__}: {e}"[:300]}}


def _apply(result: dict, stocks: list[dict], run: dict, opts: dict) -> dict:
    ids = [s["id"] for s in stocks if s["id"] in (run.get("levels") or {})]
    L = {k: np.asarray(run["levels"][k], dtype=float) for k in ids}
    T = min(len(v) for v in L.values())
    if T < 30:
        return result
    n = T - 1
    X = {k: v[:n] for k, v in L.items()}
    inputs = []
    for k, v in (opts.get("inputs") or {}).items():
        if k not in X and len(v) >= T:
            X[k] = np.asarray(v, dtype=float)[1:T]           # an input's value during the step
            inputs.append(k)
    dy = {k: np.diff(v[:T]) for k, v in L.items()}
    steps.adjust(X, dy, run, opts, n)
    q = J.quantum(np.vstack([v[:T] for v in L.values()]))
    floor = n * q * q / 12.0
    finals = {s["id"] for s in stocks if s.get("final")}
    declared = bool(run.get("boundary_declared"))
    bound = run.get("boundary") or {}
    flows = copy.deepcopy(result["flows"])
    notes = []
    for s in ids:
        if s in finals:
            continue
        on = [f for f in flows if s in (f.get("from"), f.get("to"))]
        amts = [_amount(f, X, n) for f in on]
        if any(a is None for a in amts):
            continue                                       # a flow this cannot run: the row is left as it is
        net = sum((_sign(f, s) * a for f, a in zip(on, amts)), np.zeros(n))
        r = dy[s] - net
        if not float(np.sqrt(np.mean(r * r))) > GATE * q:
            continue
        sides = _sides(s, flows, bound, declared)
        if not sides:
            continue
        mine = [f for f in on if _replaceable(f, s, bound, declared)]
        held = sum((_sign(f, s) * a for f, a in zip(on, amts) if f not in mine), np.zeros(n))
        y = dy[s] - held
        r0 = y - sum((_sign(f, s) * _amount(f, X, n) for f in mine), np.zeros(n))
        k0 = 0
        for f in mine:
            c, ks = _linear(f["rate"])
            k0 += len(ks) + (1 if (c or not ks) else 0)
        bic0 = n * math.log(max(float(r0 @ r0), floor) / n) + k0 * math.log(n)
        cols = {"1": np.ones(n)}
        for k in ids:
            if k not in finals and np.ptp(X[k]) > 0:
                cols[k] = X[k]
        for k in inputs:
            rd = capmin.readers(k, opts)
            if (rd is None or s in rd) and np.ptp(X[k]) > 0:
                cols[k] = X[k]
        bic, names, beta = _best_subset(y, cols, n, floor)
        if not names:
            continue
        new = _write(s, names, beta, sides)
        r1 = y - sum((_sign(f, s) * _amount(f, X, n) for f in new), np.zeros(n))    # under the engine's floor
        bic1 = n * math.log(max(float(r1 @ r1), floor) / n) + len(names) * math.log(n)
        if not bic1 < bic0 - GAIN * math.log(n):
            continue
        flows = [f for f in flows if not any(f is g for g in mine)] + new
        notes.append({"row": s, "reads": list(names), "bic": [round(bic0, 1), round(bic1, 1)]})
    if not notes:
        return result
    return {**result, "flows": flows, "rebuild": notes}
