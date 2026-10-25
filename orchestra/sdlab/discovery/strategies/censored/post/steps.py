"""Announced injections in the post-stages' rows (k8s 311, docs/research/fixes/311-structures.md).

The engine adds an announced injection to its stock at the start of the step that ends at the injection's
time, before that step's flows. A row of stock s therefore reads the levels at a step's start with that step's
injections in, and its change less what was injected is what the flows did. Before 311 the post-stages
(repair.py, hidden.py, counted.py, controller.py) were switched off for a whole run with any injection.
"""

from __future__ import annotations

import numpy as np


def injected(run: dict, opts: dict | None, n: int) -> dict[str, np.ndarray]:
    """{stock: what is injected at the start of each of the first n steps} (only stocks with an injection)."""
    t = np.asarray(run.get("t") or [], dtype=float)
    out: dict[str, np.ndarray] = {}
    for j in (opts or {}).get("injections") or []:
        k = np.nonzero(t == float(j["t"]))[0]
        if not len(k) or k[0] < 1 or k[0] - 1 >= n or j.get("stock") is None:
            continue
        out.setdefault(j["stock"], np.zeros(n))[k[0] - 1] += float(j["amount"])
    return out


TIMES: np.ndarray | None = None   # (censored port) the step times of the run adjust() last saw: t[1:n+1]


def adjust(X: dict, dy: dict, run: dict, opts: dict | None, n: int) -> None:
    """X (levels at each step's start) and dy (each step's change) in place: injections in X, out of dy.
    (censored port) Also notes the steps' times (the engine reads a flow in pieces at t[1:]), so hidden._amount
    can read a flow written in pieces (censored's main line writes declared sides as pieces)."""
    global TIMES
    t = np.asarray(run.get("t") or [], dtype=float)
    TIMES = t[1:n + 1] if len(t) >= n + 1 else None
    for s, a in injected(run, opts, n).items():
        if s in X:
            X[s] = X[s][:n] + a
        if s in dy:
            dy[s] = dy[s][:n] - a
