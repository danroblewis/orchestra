"""kalman_lna's state-space likelihood, written on found flows (any form the simulator runs), so that the
numbers of a chosen structure can be sampled whichever reading produced it.

The stocks (measured ones and any the flows name that nobody measures) are hidden states on the grid
of every step from the first report to the last; one step k (grid time k-1 to k) is

    x_k = x_(k-1) + inj_k + f(x_(k-1) + inj_k, t_k - lag) + w_k,    w_k ~ N(0, Q_k)
    Q_k = phi * sum_f a_fk v_f v_f' + diag(tau)          (counting noise, as lna's LNA, plus extra)

with f the flows' change (sdlab.discovery.simulate.Model), linearised at a fixed reference path (the
reports interpolated, a hidden stock's inferred levels), a_fk each flow's amount there and v_f its
stoichiometry. A report is the level (or the mean over the `span` steps ending at it) times the stock's
scale, with N(0, 1/12 + alpha + rho2 level^2) error, as in kalman_lna's kf.py. Gaps and uneven times
are grid steps without a report; values a first pass finds beyond Z_OUT standardised innovations are
left out (kalman_lna's rule).

Parameters: the flows' numbers (eiv.slots), then log tau per state, log phi, log alpha, log rho2.
"""

from __future__ import annotations

import copy
import math

import numpy as np
from numba import njit

from ...simulate import Model
from .eiv import slots
from .model import Layout

Z_OUT = 5.0
LOG_LO = {"tau": 1e-8, "phi": 1e-4, "alpha": 1e-6, "rho2": 1e-8}


@njit(cache=True)
def _filter(A, b, Q, obs_at, Y, mask, Rv, scale, meas, span, reset, m0, P0, z_out):
    """Negative log-likelihood (without 2 pi) and each report's standardised innovation (z_out,
    points x measured, written in place). The reports at a point are taken one at a time (their
    errors are independent), so no matrix is inverted."""
    K, S = b.shape
    nm = meas.shape[0]
    aug = span > 1
    D = 2 * S if aug else S
    m = np.zeros(D)
    P = np.zeros((D, D))
    for i in range(S):
        m[i] = m0[i]
        P[i, i] = P0[i]
        if aug:
            m[S + i] = m0[i]
            P[S + i, S + i] = P0[i]
            P[i, S + i] = P0[i]
            P[S + i, i] = P0[i]
    T = np.zeros((D, D))
    TP = np.zeros((D, D))
    mn = np.zeros(D)
    kv = np.zeros(D)
    row = np.zeros(D)
    total = 0.0
    for k in range(K):
        if k > 0:
            for i in range(D):
                for j in range(D):
                    T[i, j] = 0.0
            for i in range(S):
                for j in range(S):
                    T[i, j] = A[k, i, j]
                    if aug:
                        T[S + i, j] = A[k, i, j]
                if aug and not reset[k]:
                    T[S + i, S + i] = 1.0
            for i in range(D):
                v = 0.0
                for j in range(D):
                    v += T[i, j] * m[j]
                mn[i] = v
            for i in range(S):
                mn[i] += b[k, i]
                if aug:
                    mn[S + i] += b[k, i]
            for i in range(D):
                m[i] = mn[i]
            for i in range(D):
                for j in range(D):
                    v = 0.0
                    for c in range(D):
                        v += T[i, c] * P[c, j]
                    TP[i, j] = v
            for i in range(D):
                for j in range(i + 1):
                    v = 0.0
                    for c in range(D):
                        v += TP[i, c] * T[j, c]
                    P[i, j] = v
                    P[j, i] = v
            for i in range(S):
                for j in range(S):
                    q = Q[k, i, j]
                    P[i, j] += q
                    if aug:
                        P[S + i, S + j] += q
                        P[i, S + j] += q
                        P[S + i, j] += q
        p = obs_at[k]
        if p < 0:
            continue
        for r in range(nm):
            if not mask[p, r]:
                continue
            col = meas[r] + (S if aug else 0)
            h = scale[r] / (span if aug else 1.0)
            sv = h * h * P[col, col] + Rv[p, r]
            if not sv > 0.0:
                return math.inf
            e = Y[p, r] - h * m[col]
            total += 0.5 * (math.log(sv) + e * e / sv)
            z_out[p, r] = e / math.sqrt(sv)
            for i in range(D):
                kv[i] = P[i, col] * h / sv
                row[i] = h * P[col, i]
            for i in range(D):
                m[i] += kv[i] * e
            for i in range(D):
                for j in range(D):
                    P[i, j] -= kv[i] * row[j]
    return total


class Likelihood:
    """The run, the flows and everything fixed while their numbers are sampled."""

    def __init__(self, flows: list[dict], stocks: list[dict], run: dict, opts: dict, found: dict):
        self.flows = copy.deepcopy(flows)
        self.places = slots(self.flows)
        self.theta0 = np.array([float(d[k]) for d, k in self.places])
        self.p = len(self.places)
        ids = [s["id"] for s in stocks]
        inputs = opts.get("inputs") or {}
        named = []
        for f in self.flows:
            named += [f.get("from"), f.get("to")]
            for r in [g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]:
                named += [r.get("stock")] + [x.get("stock") for x in r.get("terms") or []]
            named += [e.get("stock") for e in f.get("effects") or []] + [u.get("stock") for u in f.get("uses") or []]
        hidden = list(dict.fromkeys(s for s in named if s and s not in ids and s not in inputs))
        self.ids, self.hidden = ids, hidden
        self.states = ids + hidden
        S = self.S = len(self.states)
        span = int(found.get("span") or 1)
        lag = int(found.get("lag") or 0)
        t = np.asarray(run["t"], dtype=np.int64)
        Y = np.array([np.asarray(run["levels"].get(i, [np.nan] * len(t)), dtype=float) for i in ids]).T
        lay = Layout(ids, t, Y, span=span, lag=lag, injections=opts.get("injections"))
        self.lay = lay
        K = self.K = lay.K
        ref = np.zeros((S, K))
        ref[: len(ids)] = lay.interpolated()
        inferred = found.get("inferred_levels") or {}
        for j, h in enumerate(hidden):
            v = inferred.get(h)
            if v is not None and len(v) == len(t):
                ref[len(ids) + j] = np.interp(lay.grid, t, np.asarray(v, dtype=float))
        self.ref = ref
        self.inj = np.zeros((K, S))
        self.inj[:, : len(ids)] = lay.inj
        self.times = (lay.grid - lag).astype(float)
        self.inputs = {"t": list(run["t"]), "values": inputs} if inputs else None
        sc = found.get("scales") or {}
        self.scale = np.array([float(sc.get(i, 1.0)) for i in ids])
        self.span, self.reset = span, lay.reset
        self.obs_at = lay.obs_at
        self.Y = lay.Y
        self.mask = lay.mask.copy()
        self.meas = np.arange(len(ids), dtype=np.int64)
        # the report's reference value (for the relative error): the reference path at the point
        rep = np.zeros_like(self.Y)
        k_of = lay.t - lay.t0
        for r in range(len(ids)):
            if span > 1:
                c = np.cumsum(np.concatenate([[0.0], ref[r]]))
                rep[:, r] = (c[k_of + 1] - c[np.maximum(0, k_of + 1 - span)]) / span
            else:
                rep[:, r] = ref[r, k_of]
        self.rep2 = (rep * self.scale) ** 2
        self.m0 = np.maximum(ref[:, 0], 0.0)
        first = np.nan_to_num(np.nanvar(np.diff(Y, axis=0), axis=0), nan=1.0) if len(t) > 2 else np.ones(len(ids))
        self.P0 = np.concatenate([1.0 + first, 10.0 + ref[len(ids):, 0] ** 2])
        # each flow's stoichiometry over the states
        index = {s: i for i, s in enumerate(self.states)}
        V = np.zeros((len(self.flows), S))
        for i, f in enumerate(self.flows):
            if f.get("to") in index:
                V[i, index[f["to"]]] += 1.0
            if f.get("from") in index:
                V[i, index[f["from"]]] -= float(f.get("ratio") or 1)
            for u in f.get("uses") or []:
                if u.get("stock") in index:
                    V[i, index[u["stock"]]] -= float(u.get("per") or 0)
        self.V = V
        dy = np.nan_to_num(np.nanvar(np.diff(Y, axis=0), axis=0), nan=1.0) if len(t) > 2 else np.ones(len(ids))
        top = float(max(1.0, np.max(dy) if len(dy) else 1.0))
        lv = float(max(1.0, np.nanmax(np.abs(Y)) ** 2 if np.isfinite(Y).any() else 1.0))
        # bounds of the log noise numbers (uniform priors on these boxes)
        self.lo = np.array([math.log(LOG_LO["tau"])] * S + [math.log(LOG_LO["phi"]), math.log(LOG_LO["alpha"]), math.log(LOG_LO["rho2"])])
        self.hi = np.array([math.log(100.0 * top)] * S + [math.log(100.0), math.log(lv), math.log(1.0)])
        self.z = np.full(self.Y.shape, np.nan)
        self.evals = 0

    # ---- parameters ----
    @property
    def dim(self) -> int:
        return self.p + self.S + 3

    def start(self, noise: dict | None = None) -> np.ndarray:
        """The found numbers, small extra variance, phi 1, and the found measurement error."""
        tau = np.full(self.S, math.log(1e-3))
        alpha = (noise or {}).get("abs") or 1e-3
        rho = (noise or {}).get("rel") or 1e-4
        eta = np.concatenate([tau, [0.0, math.log(max(alpha ** 2, 1e-6)), math.log(max(rho ** 2, 1e-8))]])
        return np.concatenate([self.theta0, np.clip(eta, self.lo + 1e-9, self.hi - 1e-9)])

    def set(self, theta: np.ndarray) -> list[dict]:
        for (d, k), v in zip(self.places, theta):
            d[k] = float(v)
        return self.flows

    # ---- the likelihood ----
    def system(self, theta: np.ndarray):
        """A_k, b_k and each flow's amount at the reference (k = 1..K-1; row 0 unused)."""
        self.set(theta)
        mod = Model(self.flows, self.states, inputs=self.inputs)
        K, S = self.K, self.S
        R = self.ref[:, :-1] + self.inj[1:].T          # the reference just after each step's injections
        tt = self.times[1:]
        f0 = mod.change(R, tt)
        A = np.zeros((K, S, S))
        b = np.zeros((K, S))
        J = np.zeros((K - 1, S, S))
        for j in range(S):
            h = 1e-3 * max(1.0, float(np.mean(np.abs(R[j]))))
            Rj = R.copy()
            Rj[j] += h
            J[:, :, j] = ((mod.change(Rj, tt) - f0) / h).T
        A[1:] = np.eye(S)[None] + J
        b[1:] = np.einsum("kij,kj->ki", A[1:], self.inj[1:]) + f0.T - np.einsum("kij,jk->ki", J, R)
        am = np.abs(np.array(mod._amounts(R, tt), dtype=float)) if self.flows else np.zeros((0, K - 1))
        return A, b, am

    def nll(self, x: np.ndarray, outliers: bool = False) -> float:
        """Negative log-likelihood at x (theta then the log noise numbers); inf off the boxes."""
        self.evals += 1
        theta, eta = x[: self.p], x[self.p:]
        if np.any(eta < self.lo) or np.any(eta > self.hi) or not np.all(np.isfinite(x)):
            return math.inf
        tau, phi, alpha, rho2 = np.exp(eta[: self.S]), math.exp(eta[self.S]), math.exp(eta[self.S + 1]), math.exp(eta[self.S + 2])
        with np.errstate(all="ignore"):
            A, b, am = self.system(theta)
            if not (np.all(np.isfinite(A)) and np.all(np.isfinite(b)) and np.all(np.isfinite(am))):
                return math.inf
            Q = np.zeros((self.K, self.S, self.S))
            Q[1:] = phi * np.einsum("fk,fi,fj->kij", am, self.V, self.V)
            Q[1:] += np.diag(tau + 1e-9)[None]
            Rv = 1.0 / 12.0 + alpha + rho2 * self.rep2
            z = np.full(self.Y.shape, np.nan)
            try:
                out = _filter(A, b, Q, self.obs_at, self.Y, self.mask, Rv, self.scale, self.meas, self.span, self.reset,
                              self.m0, self.P0, z)
            except Exception:                                   # noqa: BLE001  (not positive definite)
                return math.inf
        if outliers:
            self.z = z
        return float(out) if math.isfinite(out) else math.inf

    def leave_out(self, x: np.ndarray) -> int:
        """Reports beyond Z_OUT standardised innovations at x left out (one pass); how many."""
        self.nll(x, outliers=True)
        bad = self.mask & (np.abs(np.nan_to_num(self.z)) > Z_OUT)
        self.mask &= ~bad
        return int(bad.sum())
