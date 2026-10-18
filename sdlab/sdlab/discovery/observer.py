"""A found model's own unmeasured stocks, estimated from the measured levels with its own flows.

A found model may name stocks nobody measures (a hidden delay between two measured stocks). Their
levels over a run follow from the model itself: step only the flows into and out of them, with the
measured stocks held at their measured levels. This uses nothing but the found model and the data,
so it gives the same kind of estimate on any run of the system, including one the model was not
fitted on.
"""

from __future__ import annotations

import numpy as np

from .simulate import Model, levels_array

REFS = ("from", "to")


def unmeasured(flows: list[dict], measured: list[str]) -> list[str]:
    """The stocks the flows move things into or out of that are not measured, in order of appearance."""
    seen = set(measured)
    return list(dict.fromkeys(f[k] for f in flows for k in REFS if f.get(k) and f[k] not in seen))


def observe(flows: list[dict], ids: list[str], t: list, levels: dict, hidden: list[str], start: dict | None = None) -> dict[str, list[float]]:
    """Each unmeasured stock's level at every time of the run (aligned with t): the found model's flows
    into and out of it, stepped with the measured stocks at their measured levels, from `start` (its
    level at the first time; 0 when not given)."""
    if not hidden:
        return {}
    A = levels_array(levels, ids)
    S, n = A.shape
    hset = set(hidden)
    sub = [f for f in flows if f.get("from") in hset or f.get("to") in hset]
    model = Model(sub, ids + list(hidden))
    H = np.zeros((len(hidden), n))
    H[:, 0] = [float((start or {}).get(h) or 0.0) for h in hidden]
    L = np.zeros((S + len(hidden), 1))
    tt = np.asarray(t, dtype=float)
    for k in range(1, n):
        L[:S, 0] = A[:, k - 1]
        L[S:, 0] = H[:, k - 1]
        H[:, k] = model.step(L, tt[k : k + 1])[S:, 0]
    return {h: H[i].tolist() for i, h in enumerate(hidden)}
