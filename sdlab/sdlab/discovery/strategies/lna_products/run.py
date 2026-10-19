"""lna's steps (a copy of lna/run.py's discover, importing lna's modules) with product columns: a
virtual stock a x c / mean(c) for each pair of measured stocks, so that a move a -> b (or a's
outflow) can run at k x a x c / mean(c), a rate scaled by a linear effect of c. Virtual stocks have
no flows of their own and no change (their rows add a constant to the likelihood); only the moves
and outflows read them."""

from __future__ import annotations

import numpy as np

from ...matrix import configurations, injected
from ..lna.atoms import Atom, superset
from ..lna.changes import pieces, split_eras
from ..lna.fit import Data, extra_variance, fit, mean_start
from ..lna.flows import to_flows
from ..lna.run import SCRATCH, bic, buckets, dispersion, search


MARGIN = 1.0         # a model with products must beat lna's by this many log T in BIC (the price of two numbers: the
                     # products offered are many, so one that pays only its own price is too often noise)


def product_atoms(S: int, unit: list[str], final: set[int]) -> tuple[list[Atom], list[tuple[int, int]]]:
    """(atoms, pairs): pairs[v] = (a, c) is virtual stock S + v; each pair's moves a -> b (b != c,
    same unit) and a's outflow."""
    pairs, atoms = [], []
    for a in range(S):
        if a in final:
            continue
        for c in range(S):
            if c == a:
                continue
            v = S + len(pairs)
            pairs.append((a, c))
            atoms.append(Atom("out", src=a, driver=v))
            for b in range(S):
                if b not in (a, c) and unit[a] == unit[b]:
                    atoms.append(Atom("move", src=a, dst=b, driver=v))
    return atoms, pairs


def discover(stocks: list[dict], run: dict, opts: dict, base: dict, margin: float = MARGIN) -> dict | None:
    ids = [s["id"] for s in stocks]
    S = len(ids)
    t = run["t"]
    if len(t) < 30 or S < 3 or S > SCRATCH:
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
    cfg = np.asarray(bucket)[conf[1]] if conf else None
    unit = [s.get("unit") or "" for s in stocks]
    final = {k for k, s in enumerate(stocks) if s.get("final")}
    group = [s.get("group") for s in stocks]
    atoms = superset(S, unit, final, group, gaps=False)
    phi = dispersion(atoms, mean_start(atoms, Data(prev, dy, cfg)), Data(prev, dy, cfg))
    if phi < 0.2:
        return None
    extra, pairs = product_atoms(S, unit, final)
    norm = [float(max(1e-9, np.maximum(prev[c], 0).mean())) for _, c in pairs]
    vprev = np.array([np.maximum(prev[a], 0) * np.maximum(prev[c], 0) / n for (a, c), n in zip(pairs, norm)]).reshape(len(pairs), -1)
    P = np.vstack([prev, vprev])
    D = np.vstack([dy, np.zeros_like(vprev)])
    d = Data(P, D, cfg)
    if conf:
        atoms = split_eras(atoms, max(bucket) + 1)
    # lna's own search first (the virtual rows are inert), then each kept move and outflow offered
    # scaled by every other stock, and the search again from there: the lower BIC wins
    cur = fit(atoms, d)
    d.free = extra_variance(cur, d)
    d.free[S:] = False
    full = fit(atoms, d, cur.theta, tau=cur.tau)
    cur = search(pieces(full, d, mult=0.5), d)
    if any(a.span for a in cur.atoms):
        other = search(full, d)
        if bic(other, d) < bic(cur, d):
            cur = other
    at = lambda k: t[k + 1]  # noqa: E731
    lna_flows = to_flows(cur.atoms, cur.theta, ids + [f"{ids[a]}*{ids[c]}" for a, c in pairs], P, at, *((conf[0], conf[2], bucket) if conf else ()))
    offer = []
    for a, th in zip(cur.atoms, cur.theta):
        if th <= 0 or a.era is not None or a.kind not in ("move", "out") or a.uses:
            continue
        offer += [x for x in extra if x.kind == a.kind and x.src == a.src and x.dst == a.dst and x not in offer]
    gain = None
    if offer:
        g = fit(cur.atoms + offer, d, np.concatenate([cur.theta, np.full(len(offer), 1e-3)]), tau=cur.tau)
        g = search(g, d)
        gain = float(bic(cur, d) - bic(g, d))
        if gain > margin * np.log(d.dy.shape[1]):
            cur = g
    names = ids + [f"{ids[a]}*{ids[c]}" for a, c in pairs]
    flows = to_flows(cur.atoms, cur.theta, names, P, at, *((conf[0], conf[2], bucket) if conf else ()))
    flows = with_effects(flows, ids, pairs, norm, prev)
    if flows is None:
        return None
    return {**{k: base[k] for k in ("candidates", "tried", "chosen") if k in base},
            "flows": flows, "lna_flows": lna_flows, "method": "lna", "dispersion": phi, "nll": cur.nll, "windows": len(t) - 1, "window": 1,
            "product_gain": gain, "products": [f"{names[a.driver]}" for a, th in zip(cur.atoms, cur.theta) if th > 0 and a.driver is not None and a.driver >= S],
            "atoms": [{"kind": a.kind, "src": a.src, "dst": a.dst, "driver": a.driver, "uses": list(a.uses), "theta": float(th)} for a, th in zip(cur.atoms, cur.theta)]}


def with_effects(flows: list[dict], ids: list[str], pairs: list, norm: list[float], prev: np.ndarray) -> list[dict] | None:
    """Flows reading a virtual stock a*c -> a's proportional rate with a linear effect of c (normal
    mean(c), up to the highest c seen); beside a plain flow between the same ends, the two are one
    flow with a table effect through the lowest and highest c seen. None: a virtual reading that
    cannot be written (in eras or pieces)."""
    virt = {f"{ids[a]}*{ids[c]}": (a, c, n) for (a, c), n in zip(pairs, norm)}
    plain, eff = [], []
    for f in flows:
        st = (f.get("rate") or {}).get("stock")
        if st in virt:
            if f.get("byTime") or f.get("inflow"):
                return None
            eff.append(f)
        else:
            plain.append(f)
    out = list(plain)
    for f in eff:
        a, c, n = virt[f["rate"]["stock"]]
        k = float(f["rate"]["k"])
        lo, hi = float(np.maximum(prev[c], 0).min()), float(np.maximum(prev[c], 0).max())
        twin = next((g for g in out if g.get("from") == f.get("from") and g.get("to") == f.get("to") and (g.get("rate") or {}).get("form") == "proportional"
                     and g["rate"].get("stock") == ids[a] and not (g.get("byTime") or g.get("uses") or g.get("effects"))), None)
        if twin is None:
            effect = {"stock": ids[c], "shape": "linear", "normal": round(n, 4), "min": 0, "max": round(max(1.0, 1.25 * hi / n), 4)}
            rate = {"form": "proportional", "stock": ids[a], "k": k}
        else:
            k0 = float(twin["rate"]["k"])
            out.remove(twin)
            pts = [[round(x, 4), (k0 + k * x / n) / (k0 + k)] for x in (lo, hi)]
            effect = {"stock": ids[c], "shape": "table", "points": pts}
            rate = {"form": "proportional", "stock": ids[a], "k": k0 + k}
        out.append({**f, "rate": rate, "rates": [rate], "effects": [effect], "driver": ids[a], "uses": f.get("uses") or []})
        if not out[-1]["uses"]:
            out[-1].pop("uses")
    return out
