# Vendored for combined2 from sdlab/discovery/strategies/archetypes/holdout.py at commit 3c3e009 (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""Choosing between the search's model and the base's on a series long enough for both: each is
refitted on the first part of the run (the first 75%, at least 3 samples held out) and runs free
from the last level it saw (announced injections made, its unmeasured stocks from its own estimate
or the observer), and the one whose forecast of the rest is closer wins (squared error, each stock
scaled by its spread over the first part). A base that cannot run on the first part (fewer than 20
steps) is not compared: the search's model must then beat holding the last level."""

from __future__ import annotations

import numpy as np

from sdlab.discovery.observer import observe, unmeasured
from sdlab.discovery.simulate import Model


def cut_run(run: dict, opts: dict, n: int) -> tuple[dict, dict]:
    t = list(run["t"])[:n]
    r = {"t": t, "levels": {k: list(v)[:n] for k, v in run["levels"].items()}}
    o = dict(opts)
    if o.get("injections"):
        o["injections"] = [j for j in o["injections"] if float(j["t"]) <= float(t[-1])]
    if o.get("inputs"):
        o["inputs"] = {k: list(v)[:n] for k, v in o["inputs"].items()}
    return r, o


def forecast(found: dict | None, ids: list[str], run: dict, opts: dict, n: int) -> np.ndarray | None:
    """The found model's free run from sample n - 1 to the end (stocks x samples after n - 1)."""
    if not found or not found.get("flows"):
        return None
    flows = found["flows"]
    t = list(run["t"])
    Y = np.array([np.asarray(run["levels"][k], dtype=float) for k in ids])
    inferred = found.get("inferred_levels") or {}
    hidden = list(dict.fromkeys(unmeasured(flows, ids) + list(inferred)))
    est = {h: v[-1] for h, v in inferred.items() if v}
    if any(h not in est for h in hidden):
        try:
            obs = observe(flows, ids, t[:n], {k: list(v)[:n] for k, v in run["levels"].items()}, [h for h in hidden if h not in est], {})
            est.update({h: v[-1] for h, v in obs.items() if len(v)})
        except Exception:                                      # noqa: BLE001
            pass
    L = np.array([[float(x)] for x in Y[:, n - 1]] + [[float(est.get(h, 0.0) or 0.0)] for h in hidden])
    try:
        m = Model(flows, ids + hidden)
        out = []
        for k in range(n, len(t)):
            L = m.run(L, np.array([[t[k]]]), opts.get("injections"))
            out.append(L[: len(ids), 0].copy())
    except Exception:                                          # noqa: BLE001
        return None
    return np.array(out).T


def error(P: np.ndarray | None, ids: list[str], run: dict, n: int) -> float:
    Y = np.array([np.asarray(run["levels"][k], dtype=float) for k in ids])
    if P is None:
        return float("inf")
    sd = np.maximum(np.std(Y[:, :n], axis=1), 1e-9 * np.maximum(1.0, np.max(np.abs(Y), axis=1)))
    e = ((P - Y[:, n:]) / sd[:, None]) ** 2
    return float(np.sum(np.where(np.isfinite(e), e, 1e6)))


def persistence(ids: list[str], run: dict, n: int) -> np.ndarray:
    Y = np.array([np.asarray(run["levels"][k], dtype=float) for k in ids])
    return np.repeat(Y[:, n - 1: n], Y.shape[1] - n, axis=1)
