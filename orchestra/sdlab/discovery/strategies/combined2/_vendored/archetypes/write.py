# Vendored for combined2 from sdlab/discovery/strategies/archetypes/write.py at commit 3c3e009 (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""Fitted terms -> SD Lab flows, in the forms the model format and the answer key use.

A one-factor term is a proportional rate (a link reading another stock is a linear rate); a
two-factor term theta x a x c is a proportional rate of the flow's own stock (the one it leaves or,
for an inflow, the one it enters) times a linear effect of the other factor (normal: the other's
mean level; its cap, 1000 x the normal, never binds), k = theta x normal, as the published
Lotka-Volterra, SIR and Bass models write them.
"""

from __future__ import annotations

import numpy as np

from .terms import Term


def r6(v: float) -> float:
    return float(f"{float(v):.6g}")


def flows(terms: list[Term], theta: np.ndarray, names: list[str], levels: np.ndarray) -> list[dict]:
    out = []
    for t, th in zip(terms, theta):
        if th <= 0:
            continue
        src = None if t.src is None else names[t.src]
        dst = None if t.dst is None else names[t.dst]
        own = t.src if t.src is not None else t.dst
        f = {"from": src, "to": dst, "ratio": 1}
        if not t.mono:
            rate = {"form": "constant", "value": r6(th)}
        elif len(t.mono) == 1:
            j = t.mono[0]
            rate = ({"form": "proportional", "stock": names[j], "k": r6(th)} if j == own
                    else {"form": "linear", "c": 0, "terms": [{"stock": names[j], "k": r6(th)}]})
            if j != own:
                f["driver"] = names[j]
        else:
            a, c = t.mono
            r, e = (a, c) if a == own else (c, a) if c == own else (a, c)
            normal = float(np.mean(levels[e])) if levels.shape[1] else 1.0
            normal = normal if normal > 1e-9 else 1.0
            rate = {"form": "proportional", "stock": names[r], "k": r6(th * normal)}
            f["effects"] = [{"stock": names[e], "shape": "linear", "normal": r6(normal), "min": 0, "max": 1000}]
            if r != own:
                f["driver"] = names[r]
        f["rate"], f["rates"] = rate, [rate]
        out.append(f)
    return out
