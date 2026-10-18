"""The strategy's steps: the data, the noise check, the atoms chosen, co-flows, the flows."""

from __future__ import annotations

import numpy as np

from ...matrix import configurations, injected
from .atoms import Atom, features, restricted, stoich, superset, variances
from .fit import Data, extra_variance, fit, mean_start, prune
from .changes import merge_eras, pieces, split_eras
from .coflows import refine_per, with_coflows
from .flows import to_flows
from .swaps import swaps


def dispersion(atoms: list[Atom], theta: np.ndarray, d: Data) -> float:
    """What the changes' spread is of what counting noise would give the flows (each stock's squared
    residuals over the variance its flows would draw): about 1 under counting noise, 0 without."""
    S, T = d.dy.shape
    V, Z = stoich(atoms, S), features(atoms, d.prev, d.cfg)
    r = d.dy - V @ (theta[:, None] * Z)
    var = variances(atoms, theta, Z, S)
    return float((r * r).sum() / max(1e-12, var.sum()))


SCRATCH = 6          # up to this many stocks, every atom between them is tried


def discover(stocks: list[dict], run: dict, opts: dict, base: dict) -> dict | None:
    ids = [s["id"] for s in stocks]
    S = len(ids)
    t = run["t"]
    if len(t) < 30:
        return None
    lv = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, [0] * len(t)), dtype=float) for i in ids]))
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    if opts.get("injections"):
        inj = injected(opts["injections"], ids, t)[:, 1:]
        prev, dy = prev + inj, dy - inj
    conf = configurations(opts.get("eras"), t)
    d = Data(prev, dy, conf[1] if conf else None)
    unit = [s.get("unit") or "" for s in stocks]
    final = {k for k, s in enumerate(stocks) if s.get("final")}
    group = [s.get("group") for s in stocks]
    if S <= SCRATCH:
        atoms = superset(S, unit, final, group, gaps=False)
    else:
        # many stocks: only the readings of the numbers the matrix found (its chosen model's rows)
        index = {v: i for i, v in enumerate(ids)}
        coef = [{index[j]: k for j, k in (row.get("coef") or {}).items() if j in index and abs(k) > 1e-9} for row in base.get("matrix") or []]
        if len(coef) != S:
            return None
        atoms = restricted(S, coef, unit, final)
    phi = dispersion(atoms, mean_start(atoms, d), d)
    if phi < 0.2:
        return None                    # no counting noise to read: the matrix's reading stands
    if conf:
        atoms = split_eras(atoms, len(conf[0]))
    cur = fit(atoms, d)
    d.free = extra_variance(cur, d)
    cur = fit(atoms, d, cur.theta, tau=cur.tau)
    # changes in the outside inflows first, beside every flow (so that levels do not stand in for them)
    cur = pieces(cur, d, mult=0.5)
    cur = prune(with_coflows(cur, d), d)
    for _ in range(3):
        before = cur.atoms
        cur = prune(swaps(prune(pieces(cur, d), d), d), d)
        if cur.atoms == before:
            break
    cur = prune(refine_per(cur, d), d)
    cur = merge_eras(cur, d)
    at = lambda k: t[k + 1]  # noqa: E731
    flows = to_flows(cur.atoms, cur.theta, ids, prev, at, *((conf[0], conf[2]) if conf else ()))
    return {**{k: base[k] for k in ("candidates", "tried", "chosen") if k in base},
            "flows": flows, "method": "lna", "dispersion": phi, "extra_variance": {ids[k]: float(cur.tau[k]) for k in range(S) if d.free[k]}, "nll": cur.nll, "windows": len(t) - 1, "window": 1,
            "atoms": [{"kind": a.kind, "src": a.src, "dst": a.dst, "driver": a.driver, "uses": list(a.uses), "theta": float(th)} for a, th in zip(cur.atoms, cur.theta)]}

