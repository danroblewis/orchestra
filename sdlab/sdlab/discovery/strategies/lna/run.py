"""The strategy's steps: the data, the noise check, the atoms chosen, co-flows, the flows."""

from __future__ import annotations

import math

import numpy as np

from ...matrix import configurations, injected
from .atoms import Atom, features, restricted, stoich, superset, variances
from .fit import Data, extra_variance, fit, mean_start, numbers, prune
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
    # the residuals' step-to-step part (half the variance of their differences): counting noise is
    # white, while a misfit (a floor, an effect the atoms lack) is smooth and barely counts here
    # and a few steps where it jumps (a stock that empties) do not count either: the median step,
    # scaled so that counting noise gives about 1 (chi-square with S degrees of freedom, roughly)
    white = 0.5 * (np.diff(r, axis=1) ** 2).sum(axis=0) / np.maximum(1e-12, var[:, 1:].sum(axis=0))
    return float(np.median(white) / (1 - 2 / (9 * S)) ** 3)


def screen(prev: np.ndarray, dy: np.ndarray, z: float = 2.5) -> list[dict[int, float]]:
    """Each row regressed on every level and a constant: the levels with |t| > z (robust standard
    errors), and the row's own level always."""
    S, T = prev.shape
    X = np.vstack([prev, np.ones(T)]).T
    XtX = np.linalg.pinv(X.T @ X)
    out = []
    for s in range(S):
        b = XtX @ X.T @ dy[s]
        e = dy[s] - X @ b
        cov = XtX @ (X.T * e**2) @ X @ XtX
        se = np.sqrt(np.maximum(np.diag(cov), 1e-30))
        out.append({j: float(b[j]) for j in range(S) if j == s or abs(b[j] / se[j]) > z})
    return out


def buckets(cfg: np.ndarray, L: int, least: int = 50, share: float = 0.05) -> list[int]:
    """Each era label's own numbers only if it holds long enough to measure them; the short ones
    share one set (a label held for a few steps would let any reading fit those steps)."""
    n = np.bincount(cfg, minlength=L)
    long = [c for c in range(L) if n[c] >= max(least, share * len(cfg))]
    out = [long.index(c) if c in long else len(long) for c in range(L)]
    return out


SCRATCH = 4          # up to this many stocks, every atom between them is tried


def search(cur, d: Data):
    """From a fitted superset to the chosen atoms: co-flows offered, pruning, pieces re-cut and gap
    swaps until nothing changes, co-flow ratios refined, era numbers merged."""
    cur = prune(with_coflows(cur, d), d)
    for _ in range(3):
        before = cur.atoms
        cur = prune(pieces(prune(swaps(cur, d), d), d), d)
        if cur.atoms == before:
            break
    cur = prune(refine_per(cur, d), d)
    return merge_eras(cur, d)


def bic(cur, d: Data) -> float:
    return 2 * cur.nll + numbers(cur.atoms, range(len(cur.atoms))) * math.log(d.dy.shape[1])


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
        # many stocks: only the readings of numbers the data shows (a row's level clearly nonzero in
        # a regression on every level) or the matrix found (its chosen model's rows)
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
        return None                    # no counting noise to read: the matrix's reading stands
    if conf:
        atoms = split_eras(atoms, max(bucket) + 1)
    cur = fit(atoms, d)
    d.free = extra_variance(cur, d)
    full = fit(atoms, d, cur.theta, tau=cur.tau)
    # changes in the outside inflows first, beside every flow (so that levels do not stand in for
    # them); and, when that found any, the search again without them first (the fine pass can also
    # lock in pieces that a level or a gap would explain): the lower BIC wins
    cur = search(pieces(full, d, mult=0.5), d)
    if any(a.span for a in cur.atoms):
        other = search(full, d)
        if bic(other, d) < bic(cur, d):
            cur = other
    at = lambda k: t[k + 1]  # noqa: E731
    flows = to_flows(cur.atoms, cur.theta, ids, prev, at, *((conf[0], conf[2], bucket) if conf else ()))
    return {**{k: base[k] for k in ("candidates", "tried", "chosen") if k in base},
            "flows": flows, "method": "lna", "dispersion": phi, "extra_variance": {ids[k]: float(cur.tau[k]) for k in range(S) if d.free[k]}, "nll": cur.nll, "windows": len(t) - 1, "window": 1,
            "atoms": [{"kind": a.kind, "src": a.src, "dst": a.dst, "driver": a.driver, "uses": list(a.uses), "theta": float(th)} for a, th in zip(cur.atoms, cur.theta)]}

