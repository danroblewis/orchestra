"""The strategy's steps: the data, the noise check, the atoms chosen, co-flows, the flows."""

from __future__ import annotations

import numpy as np

from ...matrix import configurations, injected
from .atoms import Atom, features, stoich, superset
from .fit import Data, fit, mean_start, prune
from .changes import merge_eras, pieces, split_eras
from .coflows import refine_per, with_coflows
from .flows import to_flows


def dispersion(atoms: list[Atom], theta: np.ndarray, d: Data) -> float:
    """What the changes' spread is of what counting noise would give the flows (each stock's squared
    residuals over the variance its flows would draw): about 1 under counting noise, 0 without."""
    S, T = d.dy.shape
    V, Z = stoich(atoms, S), features(atoms, d.prev, d.cfg)
    q = theta[:, None] * Z
    r = d.dy - V @ q
    var = (V * V) @ q
    return float((r * r).sum() / max(1e-12, var.sum()))


def discover(stocks: list[dict], run: dict, opts: dict, base: dict) -> dict | None:
    ids = [s["id"] for s in stocks]
    S = len(ids)
    t = run["t"]
    if len(t) < 30 or S > 6:
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
    atoms = superset(S, unit, final, group)
    phi = dispersion(atoms, mean_start(atoms, d), d)
    if phi < 0.2:
        return None                    # no counting noise to read: the matrix's reading stands
    if conf:
        atoms = split_eras(atoms, len(conf[0]))
    cur = fit(atoms, d)
    # changes in the outside inflows first, beside every flow (so that levels do not stand in for them)
    cur = pieces(cur, d, mult=0.5)
    cur = prune(with_coflows(cur, d), d)
    cur = pieces(cur, d)
    cur = prune(refine_per(cur, d), d)
    cur = merge_eras(cur, d)
    at = lambda k: t[k + 1]  # noqa: E731
    flows = to_flows(cur.atoms, cur.theta, ids, prev, at, *((conf[0], conf[2]) if conf else ()))
    return {"flows": flows, "method": "lna", "dispersion": phi, "nll": cur.nll, "windows": len(t) - 1, "window": 1,
            "atoms": [{"kind": a.kind, "src": a.src, "dst": a.dst, "driver": a.driver, "uses": list(a.uses), "theta": float(th)} for a, th in zip(cur.atoms, cur.theta)]}

