"""The true model as a vector of numbers, and what a run says about them: the Fisher information
and the Cramér-Rao bound (the best standard error any unbiased method can reach), and a maximum
likelihood refit of the true structure (to check the bound by Monte Carlo). The scorer's side of
the ladder (analysis.py): discovery never sees any of it.

**The numbers (theta).** Every number in the truth's equations: a rate's numbers (constant: value;
proportional: k; gap: goal, time; linear: c and each k), a co-flow's per, a linear effect's normal,
min and max, a table effect's multipliers. A flow whose rate changes over the run (a schedule)
has its numbers once per segment, as the scorer compares them per window.

**The noise.** Each step's change of the measured stocks, given the levels at its start, is

    dy_k = S q_k,      q_k ~ Poisson(r_k(theta)) per flow, independently      (counts)
    dy_k = S r_k(theta) + rounding                                             (none: 4 decimals)

with S the stoichiometry (+1 into a stock, -ratio out, -per for a co-flow) and r_k the flows' rates
on the run's levels (floored at 0, outflows capped at what the stock holds, as the engine does;
measured inputs read at their value during the step, as the oracle reads them). A floor that binds
(a rate at 0 on some steps) is in the information: those steps' changes do not depend on that
rate's numbers, which is what separates, e.g., a floored gap from a drain (125).
Taken as Gaussian, dy_k ~ N(mu_k, Sigma_k), mu_k = S r_k, Sigma_k = S diag(r_k) S' (+ 1/12 for
whole numbers); without noise Sigma_k = sigma^2 I, sigma^2 = 2 (1e-4)^2 / 12 (two rounded levels).

**Fisher information** of that likelihood, conditional on the run's levels:

    I = sum_k  J_k' Sigma_k^-1 J_k  +  1/2 tr(Sigma_k^-1 dSigma_i Sigma_k^-1 dSigma_j)

(J_k = d mu_k / d theta). The first term is the information in the mean (what least squares
uses); the second is in the variance (counting noise grows with the rate, so a variance says
something about the numbers too: it is what separates births from deaths). The bound is I^-1.
Derivatives are central differences.

Only for a truth whose stocks are all measured (a hidden stock: hidden_oracle.py).
"""

from __future__ import annotations

import copy
import json
import math

import numpy as np
from scipy.optimize import minimize

from ..skill import truth_by_time
from .parts import parts, windows

ROUND_VAR = 2 * (1e-4) ** 2 / 12          # the noise-free data: each level rounded to 4 decimals
COUNT_VAR = 1.0 / 12                       # whole numbers


class TruthParams:
    """The truth's numbers on one run: theta0, labels, and mean / covariance / Fisher at any theta."""

    def __init__(self, truth_model: dict, data: dict, noise: str):
        self.noise = noise
        self.t = list(data["t"])
        self.measured = list(data["levels"])
        lv_all = data.get("all_levels") or data["levels"]
        self.ids = list(lv_all)
        self.ok = set(self.ids) == set(self.measured) and len(self.t) > 3
        self.inputs: set = set()
        flows, _ = truth_by_time(truth_model, self.t)
        flows = json.loads(json.dumps(flows))                       # segments that share a rate dict no longer do
        self.flows = flows
        if not self.ok:
            return
        idx = {s: i for i, s in enumerate(self.ids)}
        lv = np.array([np.asarray(lv_all[s], dtype=float) for s in self.ids])
        inj = np.zeros_like(lv)
        tindex = {v: i for i, v in enumerate(self.t)}
        for j in data.get("injections") or []:
            if j.get("stock") in idx and j["t"] in tindex:
                inj[idx[j["stock"]], tindex[j["t"]]] += float(j["amount"])
        self.prev = lv[:, :-1] + inj[:, 1:]
        self.dy = np.diff(lv, axis=1) - inj[:, 1:]
        # measured inputs: read as levels are (their value during the step, the oracle's convention);
        # rows after the stocks in prev, so a rate that reads one is not taken as reading 0 (2026-10-19)
        ins = {k: v for k, v in (data.get("inputs") or {}).items() if k not in idx}
        self.inputs = set(ins)
        for k, v in ins.items():
            idx[k] = len(idx)
            self.prev = np.vstack([self.prev, np.asarray(v, dtype=float)[None, 1: len(self.t)]])
        self.steps = np.asarray(self.t[1:])
        self.K = len(self.steps)
        self.idx = idx
        self.wins = windows(truth_model, self.t)
        # each flow's segments over the steps (byTime); a flow whose rate never changes has one
        self.seg_at = []                                            # per flow: per segment, the steps it covers
        for f in flows:
            self.seg_at.append([np.flatnonzero((self.steps >= g["from"]) & (self.steps <= g["to"])) for g in f["byTime"]])
        # stoichiometry, measured stocks x flows (co-flows included)
        F = len(flows)
        self.S = np.zeros((len(self.measured), F))
        for fi, f in enumerate(flows):
            if f.get("to") in self.measured:
                self.S[self.measured.index(f["to"]), fi] += 1.0
            if f.get("from") in self.measured:
                self.S[self.measured.index(f["from"]), fi] -= float(f.get("ratio") or 1)
        self.leaves, self.labels, theta = [], [], []
        for fi, f in enumerate(flows):
            segs = f["byTime"]
            for gi, g in enumerate(segs):
                for path, v in _rate_leaves(g["rate"]):
                    self.leaves.append((fi, gi, ("byTime", gi, "rate", *path)))
                    seg = f" (steps {g['from']}-{g['to']})" if len(segs) > 1 else ""
                    self.labels.append(f"{f['id']}.{'.'.join(str(p) for p in path)}{seg}")
                    theta.append(v)
            for ui, u in enumerate(f.get("uses") or []):
                self.leaves.append((fi, None, ("uses", ui, "per")))
                self.labels.append(f"{f['id']}.uses({u['stock']})")
                theta.append(float(u.get("per") or 0))
            for ei, e in enumerate(f.get("effects") or []):
                if e.get("shape") == "table":
                    for pi, p in enumerate(e.get("points") or []):
                        self.leaves.append((fi, None, ("effects", ei, "points", pi, 1)))
                        self.labels.append(f"{f['id']}.effect({e['stock']}).y{pi}")
                        theta.append(float(p[1]))
                else:
                    for k in ("normal", "min", "max"):
                        if e.get(k) is not None:
                            self.leaves.append((fi, None, ("effects", ei, k)))
                            self.labels.append(f"{f['id']}.effect({e['stock']}).{k}")
                            theta.append(float(e[k]))
        self.theta0 = np.array(theta, dtype=float)
        self.P = len(theta)
        # the co-flows' stoichiometry depends on theta (per): kept apart
        self.uses = [(fi, ui, self.measured.index(u["stock"])) for fi, f in enumerate(flows)
                     for ui, u in enumerate(f.get("uses") or []) if u.get("stock") in self.measured]
        self.dsteps = self._steps_for_derivative()

    # ---- theta -> flows ----
    def flows_at(self, theta: np.ndarray) -> list[dict]:
        out = copy.deepcopy(self.flows)
        for (fi, _gi, path), v in zip(self.leaves, theta):
            _set(out[fi], path, float(v))
        return out

    def _steps_for_derivative(self) -> np.ndarray:
        return np.array([max(1e-6, 1e-4 * abs(v)) for v in self.theta0])

    # ---- rates, mean and covariance ----
    def rates(self, theta: np.ndarray, cap: bool = True) -> np.ndarray:
        """Each flow's amount per step on the run's levels (flows x steps): rate x effects, floored
        at 0, outflows capped at what their stock holds (the engine's order)."""
        flows = self.flows_at(theta)
        x = self.prev
        q = np.zeros((len(flows), self.K))
        for fi, f in enumerate(flows):
            r = np.zeros(self.K)
            for gi, g in enumerate(f["byTime"]):
                m = self.seg_at[fi][gi]
                if len(m):
                    r[m] = _rate(g["rate"], x[:, m], self.idx, f)
            for e in f.get("effects") or []:
                r = r * _effect(e, x, self.idx)
            q[fi] = r
        if not cap:
            return q
        users: dict[str, list] = {}
        for fi, f in enumerate(flows):
            for u in f.get("uses") or []:
                if float(u.get("per") or 0) > 0:
                    users.setdefault(u["stock"], []).append((fi, float(u["per"])))
        for s, si in self.idx.items():
            take = {fi: float(f.get("ratio") or 1) for fi, f in enumerate(flows) if f.get("from") == s}
            for fi, per in users.get(s, []):
                take[fi] = take.get(fi, 0.0) + per
            if not take:
                continue
            want = sum(q[fi] * w for fi, w in take.items())
            level = x[si]
            k = np.where((want > level) & (level > -1), np.maximum(0.0, level) / np.maximum(want, 1e-300), 1.0)
            for fi in take:
                q[fi] = q[fi] * k
        return q

    def stoich(self, theta: np.ndarray) -> np.ndarray:
        S = self.S.copy()
        flows = None
        for fi, ui, si in self.uses:
            if flows is None:
                flows = self.flows_at(theta)
            S[si, fi] -= float(flows[fi]["uses"][ui].get("per") or 0)
        return S

    def mean_var(self, theta: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """mu (steps x stocks) and Sigma (steps x stocks x stocks)."""
        q = self.rates(theta)
        S = self.stoich(theta)
        mu = (S @ q).T
        n = len(self.measured)
        if self.noise == "none":
            Sig = np.broadcast_to(np.eye(n) * ROUND_VAR, (self.K, n, n)).copy()
        else:
            Sig = np.einsum("if,fk,jf->kij", S, np.maximum(q, 0.0), S) + np.eye(n) * COUNT_VAR
        return mu, Sig

    # ---- information ----
    def jacobians(self, theta: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """mu, Sigma, dmu (P x steps x stocks), dSigma (P x steps x stocks x stocks)."""
        th = self.theta0 if theta is None else theta
        mu, Sig = self.mean_var(th)
        dmu = np.zeros((self.P, *mu.shape))
        dS = np.zeros((self.P, *Sig.shape))
        for p in range(self.P):
            h = self.dsteps[p]
            a, b = th.copy(), th.copy()
            a[p] += h
            b[p] -= h
            ma, Sa = self.mean_var(a)
            mb, Sb = self.mean_var(b)
            dmu[p] = (ma - mb) / (2 * h)
            dS[p] = (Sa - Sb) / (2 * h)
        return mu, Sig, dmu, dS

    def fisher(self, theta: np.ndarray | None = None) -> dict:
        """{"mean": information in the means, "full": with the variances' information, "J": the
        stacked mean Jacobian (steps*stocks x P)}."""
        mu, Sig, dmu, dS = self.jacobians(theta)
        Si = np.linalg.inv(Sig)
        A = np.einsum("kij,pkj->pki", Si, dmu)                        # Sigma^-1 dmu
        Im = np.einsum("pki,qki->pq", dmu, A)
        if self.noise == "none":
            Iv = np.zeros_like(Im)
        else:
            M = np.einsum("kij,pkjl->pkil", Si, dS)                   # Sigma^-1 dSigma_p
            Iv = 0.5 * np.einsum("pkil,qkli->pq", M, M)
        J = dmu.transpose(1, 2, 0).reshape(-1, self.P)
        return {"mean": Im, "full": Im + Iv, "J": J}

    # ---- the true structure refitted by maximum likelihood ----
    def nll(self, theta: np.ndarray) -> float:
        mu, Sig = self.mean_var(theta)
        r = self.dy.T - mu
        sign, logdet = np.linalg.slogdet(Sig)
        if np.any(sign <= 0):
            return 1e300
        sol = np.linalg.solve(Sig, r[..., None])[..., 0]
        return float(0.5 * (np.einsum("ki,ki->", r, sol) + logdet.sum()))

    def ml_fit(self) -> np.ndarray:
        """The truth's own structure fitted by maximum likelihood (the Gaussian above, variance
        included), started at the truth's numbers."""
        scale = np.where(np.abs(self.theta0) > 0, np.abs(self.theta0), 1.0)

        def f(z):
            return self.nll(z * scale)

        res = minimize(f, self.theta0 / scale, method="L-BFGS-B",
                       options={"maxiter": 500})
        return res.x * scale


def _rate_leaves(rate: dict | None) -> list[tuple[tuple, float]]:
    r = rate or {}
    form = r.get("form")
    if form == "constant":
        return [(("value",), float(r.get("value") or 0))]
    if form == "proportional":
        return [(("k",), float(r.get("k") or 0))]
    if form == "gap":
        return [(("goal",), float(r.get("goal") or 0)), (("time",), float(r.get("time") or 1))]
    if form == "linear":
        out = [(("c",), float(r.get("c") or 0))] if r.get("c") is not None else []
        return out + [(("terms", i, "k"), float(x.get("k") or 0)) for i, x in enumerate(r.get("terms") or [])]
    return []


def _set(obj, path: tuple, value: float) -> None:
    for p in path[:-1]:
        obj = obj[p]
    obj[path[-1]] = value


def _rate(rate: dict | None, x: np.ndarray, idx: dict, flow: dict) -> np.ndarray:
    """runner.desired_rate, vectorised over steps (x: stocks x steps)."""
    r = rate or {}
    form = r.get("form")
    n = x.shape[1]
    lvl = lambda s: x[idx[s]] if s in idx else np.zeros(n)  # noqa: E731
    if form == "constant":
        return np.full(n, max(0.0, float(r.get("value") or 0)))
    if form == "proportional":
        return np.maximum(0.0, float(r.get("k") or 0) * lvl(r.get("stock")))
    if form == "gap":
        return np.maximum(0.0, (float(r.get("goal") or 0) - lvl(r.get("stock"))) / max(1e-9, float(r.get("time") or 1)))
    if form == "linear":
        v = np.full(n, float(r.get("c") or 0))
        for t in r.get("terms") or []:
            v = v + float(t.get("k") or 0) * lvl(t.get("stock"))
        return np.maximum(0.0, v)
    if form == "available":
        src = r.get("stock") or flow.get("from")
        return lvl(src) / (float(flow.get("ratio") or 1) or 1) if src else np.zeros(n)
    return np.zeros(n)


def _effect(e: dict, x: np.ndarray, idx: dict) -> np.ndarray:
    """runner.effect_value, vectorised."""
    lv = x[idx[e["stock"]]] if e.get("stock") in idx else np.zeros(x.shape[1])
    if e.get("shape") == "table" and e.get("points"):
        pts = sorted((float(a), float(b)) for a, b in e["points"])
        return np.maximum(0.0, np.interp(lv, [p[0] for p in pts], [p[1] for p in pts]))
    normal = max(1e-9, float(e.get("normal") or 1))
    lo = float(e["min"]) if e.get("min") is not None else 0.0
    hi = float(e["max"]) if e.get("max") is not None else 1.0
    return np.minimum(hi, np.maximum(lo, lv / normal))


def bound(fi: np.ndarray, rel_tol: float = 1e-10) -> tuple[np.ndarray, np.ndarray]:
    """The Cramér-Rao bound (the inverse information, pseudo-inverse on what the run says) and
    the directions it says nothing about (columns of an orthonormal basis; P x m)."""
    d = np.sqrt(np.maximum(np.diag(fi), 1e-300))
    G = fi / np.outer(d, d)                                           # scaled to unit diagonal
    w, V = np.linalg.eigh((G + G.T) / 2)
    keep = w > rel_tol * max(w.max(), 1e-300)
    Ginv = (V[:, keep] / w[keep]) @ V[:, keep].T
    C = Ginv / np.outer(d, d)
    null = (V[:, ~keep] / d[:, None])
    if null.size:
        null = null / np.linalg.norm(null, axis=0, keepdims=True)
    return C, null


def part_map(tp: TruthParams, theta: np.ndarray | None = None) -> tuple[list[tuple], np.ndarray, np.ndarray]:
    """The scorer's numeric parts (per window) as a function of theta: [(window, key)], their
    values, and the Jacobian (parts x P), by central differences."""
    th = tp.theta0 if theta is None else theta
    measured = set(tp.measured)

    def values(z):
        fl = tp.flows_at(z)
        out = {}
        for w, win in enumerate(tp.wins):
            # the flows as they are in this window (a window lies inside one segment of each flow)
            here = [{**{k: v for k, v in f.items() if k != "byTime"}, "rate": _segment_at(f, win[0])["rate"]} for f in fl]
            pw, _ = parts(here, measured, win, tp.inputs)
            for k, v in pw.items():
                if k[0] in ("flow", "uses") and isinstance(v, (int, float)):
                    out[(w, k)] = float(v)
        return out

    base = values(th)
    keys = list(base)
    D = np.zeros((len(keys), tp.P))
    for p in range(tp.P):
        h = tp.dsteps[p]
        a, b = th.copy(), th.copy()
        a[p] += h
        b[p] -= h
        va, vb = values(a), values(b)
        D[:, p] = [(va.get(k, 0.0) - vb.get(k, 0.0)) / (2 * h) for k in keys]
    return keys, np.array([base[k] for k in keys]), D


def _segment_at(flow: dict, t: int) -> dict:
    for g in flow["byTime"]:
        if g["from"] <= t <= g["to"]:
            return g
    return flow["byTime"][-1]


def amounts_jacobian(tp: TruthParams, ends: tuple, theta: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """The amount per step of the flows between `ends` (rate x effects, uncapped, as the scorer
    compares a flow with effects) and its Jacobian (steps x P)."""
    th = tp.theta0 if theta is None else theta
    sel = [fi for fi, f in enumerate(tp.flows)
           if ((f.get("from") if f.get("from") in tp.measured else None), (f.get("to") if f.get("to") in tp.measured else None)) == ends]
    amt = lambda z: tp.rates(z, cap=False)[sel].sum(axis=0)  # noqa: E731
    base = amt(th)
    G = np.zeros((tp.K, tp.P))
    for p in range(tp.P):
        h = tp.dsteps[p]
        a, b = th.copy(), th.copy()
        a[p] += h
        b[p] -= h
        G[:, p] = (amt(a) - amt(b)) / (2 * h)
    return base, G


def finite(x: float) -> float | None:
    return x if x is not None and math.isfinite(x) else None
