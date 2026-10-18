"""What changes over time: outside inflows in pieces (unannounced changes), and numbers per announced
era. Both are kept only where the likelihood pays for them (BIC)."""

from __future__ import annotations

import math

import numpy as np

from ...changes import pelt
from .atoms import Atom, features, stoich
from .fit import Data, Fitted, fit


def _moments(cur: Fitted, d: Data) -> tuple[np.ndarray, np.ndarray]:
    """Each stock's residual and its counting-noise standard deviation, step by step."""
    S = d.dy.shape[0]
    V, Z = stoich(cur.atoms, S), features(cur.atoms, d.prev, d.cfg)
    q = cur.theta[:, None] * Z
    return d.dy - V @ q, np.sqrt((V * V) @ q + d.delta)


def pieces(cur: Fitted, d: Data, min_len: int = 5, mult: float = 1.0, price: float | None = None) -> Fitted:
    """Each stock's outside inflow, cut where its standardised residual changes level (PELT), kept
    if the likelihood gains more than the BIC price of the extra pieces."""
    S, T = d.dy.shape
    price = 0.5 * math.log(T) if price is None else price
    for s in range(S):
        r, sd = _moments(cur, d)
        z = r[s] / sd[s]
        cuts = pelt(z, min_len, mult)
        if len(cuts) <= 2:
            continue
        idx = [i for i, a in enumerate(cur.atoms) if a.kind == "in" and a.dst == s]
        if not idx:
            continue
        base = sum(cur.theta[i] for i in idx if cur.atoms[i].span is None) / max(1, len({cur.atoms[i].era for i in idx}))
        keep = [i for i in range(len(cur.atoms)) if i not in idx]
        new = []
        for a, b in zip(cuts[:-1], cuts[1:]):
            # the inflow over the piece: what was there plus the piece's mean residual
            old = sum(cur.theta[i] for i in idx if cur.atoms[i].span and cur.atoms[i].span[0] <= a < cur.atoms[i].span[1])
            new.append((a, b, max(1e-3, base + old + float(r[s, a:b].mean()))))
        atoms = [cur.atoms[i] for i in keep] + [Atom("in", dst=s, span=(a, b)) for a, b, _ in new]
        g = fit(atoms, d, np.append(cur.theta[keep], [v for _, _, v in new]))
        n_old = max(1, sum(1 for i in idx if cur.theta[i] > 0))
        if cur.nll - g.nll > price * (len(new) - n_old):
            cur = g
    return cur


def split_eras(atoms: list[Atom], labels: int) -> list[Atom]:
    """Every atom with a number per era."""
    return [a.with_(era=c) for a in atoms for c in range(labels)]


def merge_eras(cur: Fitted, d: Data) -> Fitted:
    """A flow whose numbers per era the data does not tell apart gets one number (greedy, the
    cheapest merge first, while it costs less than the BIC price of the numbers it saves)."""
    if d.cfg is None:
        return cur
    T = d.dy.shape[1]
    price = 0.5 * math.log(T)
    while True:
        best = None
        for key in dict.fromkeys(a.key() for a in cur.atoms if a.era is not None):
            split = [i for i, a in enumerate(cur.atoms) if a.key() == key and a.era is not None]
            if len(split) < 2:
                continue
            rest = [j for j in range(len(cur.atoms)) if j not in split]
            th = float(np.mean([cur.theta[i] for i in split]))
            g = fit([cur.atoms[j] for j in rest] + [cur.atoms[split[0]].with_(era=None)], d, np.append(cur.theta[rest], th), maxiter=300)
            cost = (g.nll - cur.nll) / (len(split) - 1)
            if cost < price and (best is None or cost < best[0]):
                best = (cost, g)
        if best is None:
            return cur
        cur = best[1]
