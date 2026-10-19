"""combined's judge (_vendored/combined/judge.py) with a discrete likelihood for small counts.

With counts, combined reads each step's change through the linear noise approximation: Gaussian,
mean S a(x), covariance S diag(a(x)) S^T. Near zero the counts are 0, 1 and 2 and a drain is cut
short when the stock empties (nothing leaves a stock that is not there), so the Gaussian is biased
and prefers a wrong drain (056-sweep-zero-floor, 12-31 nats; docs/research/combined.md).

Here, for a model in which every flow touches at most one measured stock (no moves between measured
stocks, no co-flows, no unmeasured stocks: the stocks' changes are then independent given the
levels, as the LNA's covariance is diagonal), each stock's change is read exactly as the engine
draws it: what comes in is Poisson with the inflows' total rate, what goes out is Poisson with the
outflows' total (desired, uncapped) rate, cut at the level the stock holds,

    P(change = d) = sum_{o=0..x} P(out = o) Poisson(d + o; in),  P(out = x) = P(Poisson(out) >= x),

on every step where the two rates add up to at most SMALL; elsewhere the LNA's Gaussian (the same
as combined's for such a model). Other models are scored as combined scores them.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.special import gammaln
from scipy.stats import poisson

from sdlab.discovery.simulate import Model

from ._vendored.combined import judge as J
from ._vendored.combined.params import numbers

SMALL = 30.0          # rates (in + out) up to this are read exactly; above, the Gaussian is good
FLOOR = 1e-30         # the least probability a step may have (a change the model cannot make)


class Desired(Model):
    """simulate.Model that also gives each flow's desired amount, before a stock's outflows are cut
    to what it holds."""

    def desired(self, L: np.ndarray, t: np.ndarray) -> list:
        R = self._read(L, t)
        zero = np.zeros(L.shape[1], int)
        amounts = []
        for src, dst, ratio, segs, rate, vals in self.parts:
            seg = segs(t) if segs is not None else zero
            amounts.append(vals[seg] if vals is not None else rate(R, seg))
        for i, effect in self.effects:
            amounts[i] = amounts[i] * effect(R)
        return amounts


def applies(flows: list[dict], data: J.Data) -> bool:
    """Counts, and every flow touching at most one measured stock (no co-flows, no unmeasured
    stocks, no ratios, no sub-steps)."""
    if not data.counts or not flows:
        return False
    ids = set(data.ids)
    if J.unmeasured(J.expand_via(flows), data):
        return False
    for f in flows:
        if f.get("via") or f.get("uses") or float(f.get("ratio") or 1) != 1:
            return False
        if f.get("from") in ids and f.get("to") in ids:
            return False
    return True


def _pois_logpmf(k: np.ndarray, lam: np.ndarray) -> np.ndarray:
    lam = np.maximum(lam, 1e-12)
    return np.where(k >= 0, k * np.log(lam) - lam - gammaln(np.maximum(k, 0) + 1), -np.inf)


def discrete_nll(flows: list[dict], data: J.Data) -> float:
    S = len(data.ids)
    model = Desired(flows, data.ids, inputs=data.model_inputs)
    X = data.prev
    want = model.desired(X, data.tt)
    lam_in = np.zeros((S, data.T))
    lam_out = np.zeros((S, data.T))
    for (src, dst, ratio, *_), a in zip(model.parts, want):
        a = np.maximum(0.0, np.asarray(a, dtype=float))
        if src is not None and src < S:
            lam_out[src] += a
        if dst is not None and dst < S:
            lam_in[dst] += a
    mu, _ = J._moments(model, X, data)                    # the mean change, outflows cut as the engine cuts them
    d = np.round(data.dy).astype(np.int64)
    x = np.round(np.maximum(0.0, X)).astype(np.int64)
    eps = data.q ** 2 / 6.0
    total = 0.0
    small = (lam_in + lam_out) <= SMALL
    # the Gaussian where the rates are large (the LNA's marginal: variance = what moves, cut outflows)
    big = ~small
    if big.any():
        var = lam_in + np.minimum(lam_out, np.maximum(0.0, X)) + eps
        r = data.dy - mu
        total += float(0.5 * (np.log(2 * math.pi * var[big]) + r[big] ** 2 / var[big]).sum())
    if small.any():
        li, lo, dd, xx = lam_in[small], lam_out[small], d[small], x[small]
        # outflow counts 0..x, but never beyond where Poisson(<= SMALL) has any mass left
        top = int(min(xx.max() if xx.size else 0, SMALL + 10 * math.sqrt(SMALL) + 20))
        o = np.arange(top + 1)[None, :]
        lp_out = _pois_logpmf(np.broadcast_to(o, (len(lo), top + 1)), lo[:, None])
        # P(out = x) = P(Poisson >= x); counts beyond x are impossible
        tail = np.log(np.maximum(poisson.sf(xx - 1, lo), 1e-300))
        lp_out = np.where(o < xx[:, None], lp_out, np.where(o == xx[:, None], tail[:, None], -np.inf))
        lp_in = _pois_logpmf(dd[:, None] + o, li[:, None])
        lp = np.logaddexp.reduce(lp_out + lp_in, axis=1)
        total += float(-np.maximum(lp, math.log(FLOOR)).sum())
    return total


def nll(flows: list[dict], data: J.Data, starts: dict | None = None) -> float:
    if applies(flows, data):
        try:
            v = discrete_nll(flows, data)
            if math.isfinite(v):
                return v
        except Exception:                                  # noqa: BLE001  (the Gaussian then)
            pass
    return J.nll(flows, data, starts)


def score(flows: list[dict], data: J.Data, price: float = 1.0, per_flow: float = 1.0, starts: dict | None = None) -> dict:
    """combined's score (judge.score) with nll() above."""
    k = numbers(flows, set(data.ids))
    n = nll(flows, data, starts)
    kk = k - (1.0 - per_flow) * len(flows or [])
    return {"nll": n, "k": k, "flows": len(flows or []), "bic": n + 0.5 * price * math.log(max(2, data.T)) * kk,
            "discrete": applies(flows, data)}
