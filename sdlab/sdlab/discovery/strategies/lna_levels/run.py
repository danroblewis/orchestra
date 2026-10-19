"""lna's steps (a copy of lna/run.py's discover, importing lna's modules), then each stock's outside
inflow pieces offered as a few recurring levels, and a self-growth term offered as
pieces instead (levels.py)."""

from __future__ import annotations

import numpy as np

from ...matrix import configurations, injected
from ..lna.atoms import restricted, superset
from ..lna.changes import pieces, split_eras
from ..lna.fit import Data, extra_variance, fit, mean_start
from ..lna.flows import to_flows
from ..lna.run import SCRATCH, bic, buckets, dispersion, screen, search
from .levels import level_flows, regroup, without_growth


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
    bucket = buckets(conf[1], len(conf[0])) if conf else None
    if bucket is not None and max(bucket) < 1:
        conf, bucket = None, None
    d = Data(prev, dy, np.asarray(bucket)[conf[1]] if conf else None)
    unit = [s.get("unit") or "" for s in stocks]
    final = {k for k, s in enumerate(stocks) if s.get("final")}
    group = [s.get("group") for s in stocks]
    if S <= SCRATCH:
        atoms = superset(S, unit, final, group, gaps=False)
    else:
        index = {v: i for i, v in enumerate(ids)}
        coef = [{index[j]: k for j, k in (row.get("coef") or {}).items() if j in index and abs(k) > 1e-9} for row in base.get("matrix") or []]
        if len(coef) != S:
            return None
        for s_, row in enumerate(screen(prev, dy)):
            for j, k in row.items():
                coef[s_].setdefault(j, k)
        atoms = restricted(S, coef, unit, final)
    phi = dispersion(atoms, mean_start(atoms, d), d)
    if phi < 0.2:
        return None
    if conf:
        atoms = split_eras(atoms, max(bucket) + 1)
    cur = fit(atoms, d)
    d.free = extra_variance(cur, d)
    full = fit(atoms, d, cur.theta, tau=cur.tau)
    cur = search(pieces(full, d, mult=0.5), d)
    if any(a.span for a in cur.atoms):
        other = search(full, d)
        if bic(other, d) < bic(cur, d):
            cur = other
    lna_bic = bic(cur, d)
    cur = without_growth(cur, d)
    cur, levels, score = regroup(cur, d)
    at = lambda k: t[k + 1]  # noqa: E731
    flows = to_flows(cur.atoms, cur.theta, ids, prev, at, *((conf[0], conf[2], bucket) if conf else ()))
    flows = level_flows(flows, levels, ids, at)
    return {**{k: base[k] for k in ("candidates", "tried", "chosen") if k in base},
            "flows": flows, "method": "lna", "dispersion": phi, "nll": cur.nll, "windows": len(t) - 1, "window": 1,
            "levels": {ids[s]: len(g) for s, g in levels.items()}, "bic": {"lna": float(lna_bic), "levels": float(score)},
            "atoms": [{"kind": a.kind, "src": a.src, "dst": a.dst, "driver": a.driver, "uses": list(a.uses), "theta": float(th)} for a, th in zip(cur.atoms, cur.theta)]}
