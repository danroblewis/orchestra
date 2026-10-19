"""lna's steps (a copy of lna/run.py's discover, importing lna's modules) with the revisit stages in
order: known pulses taken out of the changes (lna_pulses), product columns (lna_products), lna's
search, products offered on the kept moves and outflows (lna_products), self-growth offered back
as pieces and the pieces regrouped into recurring levels (lna_levels); then the flows, with effects
and levels written out."""

from __future__ import annotations

import numpy as np

from ...matrix import configurations, injected
from ..lna.atoms import restricted, superset
from ..lna.changes import pieces, split_eras
from ..lna.fit import Data, extra_variance, fit, mean_start
from ..lna.flows import to_flows
from ..lna.run import SCRATCH, bic, buckets, dispersion, screen, search
from ..lna_levels.levels import level_flows, regroup, without_growth
from ..lna_products.run import MARGIN, product_atoms, with_effects


def discover(stocks: list[dict], run: dict, opts: dict, base: dict, known: np.ndarray | None = None) -> dict | None:
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
    if known is not None:
        dy = dy - known
    conf = configurations(opts.get("eras"), t)
    bucket = buckets(conf[1], len(conf[0])) if conf else None
    if bucket is not None and max(bucket) < 1:
        conf, bucket = None, None
    cfg = np.asarray(bucket)[conf[1]] if conf else None
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
    phi = dispersion(atoms, mean_start(atoms, Data(prev, dy, cfg)), Data(prev, dy, cfg))
    if phi < 0.2:
        return None
    # product columns (virtual stocks a x c / mean c) for 3 or more stocks, up to lna's scratch size
    extra, pairs, norm = [], [], []
    P, D = prev, dy
    if 3 <= S <= SCRATCH:
        extra, pairs = product_atoms(S, unit, final)
        norm = [float(max(1e-9, np.maximum(prev[c], 0).mean())) for _, c in pairs]
        vprev = np.array([np.maximum(prev[a], 0) * np.maximum(prev[c], 0) / n for (a, c), n in zip(pairs, norm)]).reshape(len(pairs), -1)
        P, D = np.vstack([prev, vprev]), np.vstack([dy, np.zeros_like(vprev)])
    d = Data(P, D, cfg)
    if conf:
        atoms = split_eras(atoms, max(bucket) + 1)
    cur = fit(atoms, d)
    d.free = extra_variance(cur, d)
    d.free[S:] = False
    full = fit(atoms, d, cur.theta, tau=cur.tau)
    cur = search(pieces(full, d, mult=0.5), d)
    if any(a.span for a in cur.atoms):
        other = search(full, d)
        if bic(other, d) < bic(cur, d):
            cur = other
    offer = []
    for a, th in zip(cur.atoms, cur.theta):
        if th > 0 and a.era is None and a.kind in ("move", "out") and not a.uses:
            offer += [x for x in extra if x.kind == a.kind and x.src == a.src and x.dst == a.dst and x not in offer]
    if offer:
        g = search(fit(cur.atoms + offer, d, np.concatenate([cur.theta, np.full(len(offer), 1e-3)]), tau=cur.tau), d)
        if bic(cur, d) - bic(g, d) > MARGIN * np.log(d.dy.shape[1]):
            cur = g
    cur = without_growth(cur, d)
    cur, levels, _ = regroup(cur, d)
    names = ids + [f"{ids[a]}*{ids[c]}" for a, c in pairs]
    at = lambda k: t[k + 1]  # noqa: E731
    flows = to_flows(cur.atoms, cur.theta, names, P, at, *((conf[0], conf[2], bucket) if conf else ()))
    if pairs:
        flows = with_effects(flows, ids, pairs, norm, prev)
        if flows is None:
            return None
    flows = level_flows(flows, levels, ids, at)
    return {**{k: base[k] for k in ("candidates", "tried", "chosen") if k in base},
            "flows": flows, "method": "lna", "dispersion": phi, "nll": cur.nll, "windows": len(t) - 1, "window": 1,
            "levels": {ids[s]: len(g) for s, g in levels.items()},
            "atoms": [{"kind": a.kind, "src": a.src, "dst": a.dst, "driver": a.driver, "uses": list(a.uses), "theta": float(th)} for a, th in zip(cur.atoms, cur.theta)]}
