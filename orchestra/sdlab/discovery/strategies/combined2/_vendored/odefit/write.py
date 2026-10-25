# Vendored for combined2 from sdlab/discovery/strategies/odefit/write.py at commit 333f814 (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""The fitted numbers written as SD Lab flows.

A stock's own negative number is a drain; what other stocks of its unit gain in proportion to its
level is moved out of that drain (a move), as far as the drain goes, and the rest of a gain is a
link (an inflow that reads the other level). Positive numbers on inputs, the constant and other
stocks' levels feed the stock through one inflow; negative ones drain it through one outflow
(both linear rates, floored at 0 by the engine). A product X x Y is a proportional rate on X times
a linear effect of Y (Y / normal, unclamped above); a hinge is its own flow (hinge.py).
"""

from __future__ import annotations

import math

import numpy as np

TOL = 1e-9


def sig(v: float, n: int = 6) -> float:
    """v to n significant figures."""
    v = float(v)
    if v == 0 or not math.isfinite(v):
        return 0.0
    return round(v, n - 1 - int(math.floor(math.log10(abs(v)))))


def _flow(src, dst, rate, **extra) -> dict:
    return {"from": src, "to": dst, "ratio": 1, "rate": rate, **extra}


def _linear(c: float, terms: list[tuple[str, float]]) -> dict:
    return {"form": "linear", "c": sig(c), "terms": [{"stock": s, "k": sig(k)} for s, k in terms]}


def to_flows(W: np.ndarray, ids: list[str], inputs: list[str], products: list[tuple[int, int]], units: dict[str, str],
             means: np.ndarray, hinges: list[dict] | None = None) -> list[dict]:
    """Flows for the per-step model x' = x + W @ columns(x, u) (fit.columns' order)."""
    S, m = len(ids), len(inputs)
    flows: list[dict] = []
    A = W[:, :S].copy()
    for a in range(S):
        left = -A[a, a] if A[a, a] < 0 else 0.0
        for s in sorted((s for s in range(S) if s != a and A[s, a] > 0), key=lambda s: -A[s, a]):
            if units.get(ids[s], "") != units.get(ids[a], "") or left <= TOL:
                continue
            move = min(A[s, a], left)
            flows.append(_flow(ids[a], ids[s], {"form": "proportional", "stock": ids[a], "k": sig(move)}))
            left -= move
            A[s, a] -= move
        if left > TOL:
            flows.append(_flow(ids[a], None, {"form": "proportional", "stock": ids[a], "k": sig(left)}))
        if A[a, a] < 0:
            A[a, a] = 0.0
    for i in range(S):
        row = np.concatenate([A[i], W[i, S:S + m]])
        names = ids + inputs
        c = float(W[i, S + m])
        pos = [(names[j], float(row[j])) for j in range(S + m) if row[j] > TOL]
        neg = [(names[j], -float(row[j])) for j in range(S + m) if row[j] < -TOL]
        if pos or c > TOL:
            flows.append(_flow(None, ids[i], _linear(max(c, 0.0), pos)))
        if neg or c < -TOL:
            flows.append(_flow(ids[i], None, _linear(max(-c, 0.0), neg)))

    for p, (a, b) in enumerate(products):
        col = S + m + 1 + p
        normal = max(float(abs(means[b])), 1e-9)
        for i in range(S):
            k = float(W[i, col])
            if abs(k) <= TOL:
                continue
            # k X_a X_b = (k normal) X_a x (X_b / normal); unclamped above
            effect = {"stock": ids[b], "shape": "linear", "normal": sig(normal), "min": 0, "max": 1e9}
            rate = {"form": "proportional", "stock": ids[a], "k": sig(abs(k) * normal)}
            flows.append(_flow(None, ids[i], rate, effects=[effect]) if k > 0 else _flow(ids[i], None, rate, effects=[effect]))

    for h in hinges or []:
        flows.append(h)
    return flows
