"""What a noisy variant's data can say about the truth's numbers (noise.py): the truth as a linear
Gaussian state-space model over every step of the run, observed the way the variant reports it, and
the Fisher information of its numbers from a Kalman filter. The scorer's side (noise_oracle.py,
noise_analysis.py); discovery never sees it.

**The model.** Every stock, hidden ones too, steps as the truth's linear system (the window's B and
u, injections added at the start of their step) plus counting noise:

    x_t = (I + B_t)(x_(t-1) + inj_t) + u_t + w_t,      w_t ~ N(0, S diag(r_t) S')

with S the stoichiometry and r_t every flow's true rate at the true levels (held at the truth: the
information in the noise's variance is not used, as the linear oracle does not use it). A reported
point is

    y_i = b * x_(at_i) + v_i             (point)        or    y_i = b * mean(x over span_i steps) + v_i   (weekly means)

with v_i ~ N(0, 1/12 + abs^2 + (rel x)^2) (the meas numbers; 1/12: whole numbers), b the bias (1
unless the variant biases that stock; then a free number, so what the data cannot tell from it shows
as unidentified), and a point the variant made an outlier left out (a robust method can find a few
gross errors; the bound is what it could do then). Missing points, weekly reports and the lag are
simply the steps that are observed. Weekly means are filtered with an accumulator beside the state.

**The numbers (theta).** Every number in the truth's equations, per schedule segment (fisher.py's
leaves), and the bias. The Fisher information is the Gauss-Newton one of the innovations:
I = sum_i J_i' S_i^-1 J_i (J_i = d e_i / d theta by central differences, S_i the innovations'
covariance at the truth). The SE of a scorer's part (or a number the truth does not have, added as
one more free number) follows from I^-1, by the parts' Jacobian (fisher.part_map's way).

Only for a truth that is linear (constant, proportional, gap and linear rates; no effects, co-flows
or other forms): otherwise `ok` is False and the tolerances alone apply.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math

import numpy as np
from numba import njit

from .fisher import _rate, _rate_leaves, _set, bound
from .parts import ONE, linear_form, linear_system, parts

READ_VAR = 1.0 / 12                     # every reported level is at best a whole number
_CACHE: dict[str, "SSM | None"] = {}


@njit(cache=True)
def _kf(A_cfg, cfg, d, Q, obs_at, Y, R, mask, hscale, span, reset, meas, m0, P0, aug, want_S):
    N = cfg.shape[0]
    n = A_cfg.shape[1]
    nm = meas.shape[0]
    D = 2 * n if aug else n
    m = np.zeros(D)
    P = np.zeros((D, D))
    m[:n] = m0
    P[:n, :n] = P0
    if aug:
        m[n:] = m0
        P[n:, n:] = P0
        P[:n, n:] = P0
        P[n:, :n] = P0
    M = Y.shape[0]
    E = np.zeros((M, nm))
    S_out = np.zeros((M if want_S else 1, nm, nm))
    T = np.zeros((D, D))
    dd = np.zeros(D)
    QQ = np.zeros((D, D))
    for k in range(N):
        if k > 0:
            A = A_cfg[cfg[k]]
            T[:, :] = 0.0
            T[:n, :n] = A
            dd[:n] = d[k]
            QQ[:n, :n] = Q[k]
            if aug:
                T[n:, :n] = A
                if not reset[k]:
                    for j in range(n):
                        T[n + j, n + j] = 1.0
                dd[n:] = d[k]
                QQ[:n, n:] = Q[k]
                QQ[n:, :n] = Q[k]
                QQ[n:, n:] = Q[k]
            m = T @ m + dd
            P = T @ P @ T.T + QQ
        i = obs_at[k]
        if i < 0:
            continue
        H = np.zeros((nm, D))
        for r in range(nm):
            if mask[i, r]:
                if aug and span[i] > 1:
                    H[r, n + meas[r]] = hscale[r] / span[i]
                else:
                    H[r, meas[r]] = hscale[r]
        Sk = H @ P @ H.T
        e = np.zeros(nm)
        yp = H @ m
        for r in range(nm):
            if mask[i, r]:
                Sk[r, r] += R[i, r]
                e[r] = Y[i, r] - yp[r]
            else:
                for c in range(nm):
                    Sk[r, c] = 0.0
                    Sk[c, r] = 0.0
                Sk[r, r] = 1.0
        Si = np.linalg.inv(Sk)
        K = P @ H.T @ Si
        m = m + K @ e
        P = P - K @ H @ P
        P = 0.5 * (P + P.T)
        E[i] = e
        if want_S:
            S_out[i] = Sk
    return E, S_out


@njit(cache=True)
def _kl(A_cfg, cfg, Q1, Q2, obs_at, R, mask, hscale, span, reset, meas, P0, aug):
    """sum over the reported points of KL(truth's predictive || the alternative's), when both have
    the same means and differ only in the process noise (Q1: the truth's, Q2: the alternative's):
    filter 2's actual error covariance under the truth is followed beside its own."""
    N = cfg.shape[0]
    n = A_cfg.shape[1]
    nm = meas.shape[0]
    D = 2 * n if aug else n
    P1 = np.zeros((D, D))
    P2 = np.zeros((D, D))
    Pi = np.zeros((D, D))
    for X in (P1, P2, Pi):
        X[:n, :n] = P0
        if aug:
            X[n:, n:] = P0
            X[:n, n:] = P0
            X[n:, :n] = P0
    T = np.zeros((D, D))
    QQ1 = np.zeros((D, D))
    QQ2 = np.zeros((D, D))
    total = 0.0
    for k in range(N):
        if k > 0:
            A = A_cfg[cfg[k]]
            T[:, :] = 0.0
            T[:n, :n] = A
            QQ1[:n, :n] = Q1[k]
            QQ2[:n, :n] = Q2[k]
            if aug:
                T[n:, :n] = A
                if not reset[k]:
                    for j in range(n):
                        T[n + j, n + j] = 1.0
                for X, Qk in ((QQ1, Q1[k]), (QQ2, Q2[k])):
                    X[:n, n:] = Qk
                    X[n:, :n] = Qk
                    X[n:, n:] = Qk
            P1 = T @ P1 @ T.T + QQ1
            P2 = T @ P2 @ T.T + QQ2
            Pi = T @ Pi @ T.T + QQ1
        i = obs_at[k]
        if i < 0:
            continue
        H = np.zeros((nm, D))
        Rk = np.zeros((nm, nm))
        for r in range(nm):
            if mask[i, r]:
                if aug and span[i] > 1:
                    H[r, n + meas[r]] = hscale[r] / span[i]
                else:
                    H[r, meas[r]] = hscale[r]
                Rk[r, r] = R[i, r]
            else:
                Rk[r, r] = 1.0
        S1 = H @ P1 @ H.T + Rk
        S2 = H @ P2 @ H.T + Rk
        Se = H @ Pi @ H.T + Rk
        S2i = np.linalg.inv(S2)
        _, ld1 = np.linalg.slogdet(S1)
        _, ld2 = np.linalg.slogdet(S2)
        total += 0.5 * (np.trace(S2i @ Se) - nm + ld2 - ld1)
        K1 = P1 @ H.T @ np.linalg.inv(S1)
        K2 = P2 @ H.T @ S2i
        P1 = P1 - K1 @ H @ P1
        P2 = P2 - K2 @ H @ P2
        I_KH = np.eye(D) - K2 @ H
        Pi = I_KH @ Pi @ I_KH.T + K2 @ Rk @ K2.T
        P1 = 0.5 * (P1 + P1.T)
        P2 = 0.5 * (P2 + P2.T)
        Pi = 0.5 * (Pi + Pi.T)
    return total


def _seg(flow: dict, t: int) -> int:
    segs = flow["byTime"]
    for i, g in enumerate(segs):
        if g["from"] <= t <= g["to"]:
            return i
    if t < segs[0]["from"]:
        return 0
    return max(i for i, g in enumerate(segs) if g["from"] <= t)


def covered(flows: list[dict]) -> bool:
    """A truth this model covers: every flow linear in every segment, no effects or co-flows."""
    for f in flows:
        if f.get("effects") or f.get("uses") or f.get("delay") or f.get("exact"):
            return False
        for g in f.get("byTime") or [{"rate": f.get("rate")}]:
            if (g.get("rate") or {}).get("form") not in ("constant", "proportional", "gap", "linear") or linear_form(g.get("rate")) is None:
                return False
    return True


class SSM:
    """The truth on one noisy run as a state-space model; Fisher information and SEs of its numbers."""

    def __init__(self, data: dict, wins: list[tuple[int, int]]):
        obs, clean = data["observation"], data["clean"]
        self.wins = [tuple(w) for w in wins]
        self.flows = json.loads(json.dumps(clean["flows"]))             # segments that share a rate dict no longer do
        self.measured = list(data["levels"])
        lv = clean["all_levels"]
        self.ids = list(lv)
        self.idx = {s: i for i, s in enumerate(self.ids)}
        self.hidden = [s for s in self.ids if s not in self.measured]
        self.t = [int(x) for x in clean["t"]]
        N, n = len(self.t), len(self.ids)
        self.X = np.array([np.asarray(lv[s], dtype=float) for s in self.ids])     # true levels, n x N
        # the numbers
        self.leaves, self.labels, theta = [], [], []
        for fi, f in enumerate(self.flows):
            for gi, g in enumerate(f["byTime"]):
                for path, v in _rate_leaves(g["rate"]):
                    self.leaves.append((fi, gi, ("byTime", gi, "rate", *path)))
                    self.labels.append(f"{f['id']}.{'.'.join(str(p) for p in path)}" + (f" (steps {g['from']}-{g['to']})" if len(f["byTime"]) > 1 else ""))
                    theta.append(v)
        self.bias = [s for s in self.measured if s in (obs.get("bias") or {})]
        for s in self.bias:
            self.leaves.append(("bias", s, None))
            self.labels.append(f"bias({s})")
            theta.append(float(obs["bias"][s]))
        self.theta0 = np.array(theta, dtype=float)
        self.P = len(theta)
        self.dsteps = np.array([max(1e-6, 1e-4 * abs(v)) for v in self.theta0])
        # steps: each one's configuration (every flow's segment, and the scorer's window)
        def window(tt):
            for w, (a, b) in enumerate(self.wins):
                if a <= tt <= b:
                    return w
            return 0 if tt < self.wins[0][0] else len(self.wins) - 1
        keys, self.cfg, self.cfg_t, self.cfg_w = {}, np.zeros(N, dtype=np.int64), [], []
        for k, tt in enumerate(self.t):
            key = (tuple(_seg(f, tt) for f in self.flows), window(tt))
            if key not in keys:
                keys[key] = len(keys)
                self.cfg_t.append(tt)
                self.cfg_w.append(key[1])
            self.cfg[k] = keys[key]
        # injections at the start of their step
        self.inj = np.zeros((N, n))
        tindex = {v: i for i, v in enumerate(self.t)}
        for j in clean.get("injections") or []:
            if j.get("stock") in self.idx and j["t"] in tindex:
                self.inj[tindex[j["t"]], self.idx[j["stock"]]] += float(j["amount"])
        self.D0 = np.ones(n)                                              # the bias, per stock (reported units)
        for s in self.bias:
            self.D0[self.idx[s]] = float(obs["bias"][s])
        self.Q = self.process_noise(self.flows)
        # what is reported
        at = np.asarray(obs["at"], dtype=np.int64)
        Mo = len(at)
        self.meas = np.array([self.idx[s] for s in self.measured], dtype=np.int64)
        self.obs_at = np.full(N, -1, dtype=np.int64)
        self.obs_at[at] = np.arange(Mo)
        self.Y = np.array([[float(data["levels"][s][i]) for s in self.measured] for i in range(Mo)])
        self.mask = np.ones((Mo, len(self.measured)), dtype=np.bool_)
        for i, s in obs.get("outliers") or []:
            if s in self.measured and 0 <= int(i) < N:
                j = np.flatnonzero(at == int(i))
                if len(j):
                    self.mask[j[0], self.measured.index(s)] = False
        L = int(obs.get("span") or 1)
        self.aug = L > 1
        self.span = np.full(Mo, L, dtype=np.int64)
        self.reset = np.array([k % L == 0 for k in range(N)], dtype=np.bool_)
        b = np.array([float((obs.get("bias") or {}).get(s, 1.0)) for s in self.measured])
        Xm = self.X[self.meas]
        if self.aug:
            seen = np.array([np.convolve(x, np.ones(L) / L, mode="full")[:N] for x in Xm])[:, at]
        else:
            seen = Xm[:, at]
        seen = (seen * b[:, None]).T
        rel, ab = (float(obs.get("rel") or 0), float(obs.get("abs") or 0)) if obs["kind"] == "meas" else (0.0, 0.0)
        self.R = READ_VAR + ab ** 2 + (rel * seen) ** 2
        x0 = self.X[:, 0]
        self.m0 = x0 * self.D0
        self.P0 = np.diag(1e4 * (np.abs(x0) + 10.0) ** 2)                # diffuse: the start is not known (nor its units)
        self._J: dict = {}
        self._S0i = None

    # ---- theta -> the system ----
    def flows_at(self, theta: np.ndarray) -> list[dict]:
        out = copy.deepcopy(self.flows)
        for (fi, _gi, path), v in zip(self.leaves, theta):
            if fi != "bias":
                _set(out[fi], path, float(v))
        return out

    def process_noise(self, flows: list[dict]) -> np.ndarray:
        """Each step's counting-noise covariance (steps x stocks x stocks) at the true levels."""
        N, n = self.X.shape[1], len(self.ids)
        pre = np.concatenate([self.X[:, :1], self.X[:, :-1]], axis=1) + self.inj.T     # the level a step starts from
        Q = np.zeros((N, n, n))
        for f in flows:
            r = np.zeros(N)
            segs = np.array([_seg(f, tt) for tt in self.t])
            for gi, g in enumerate(f["byTime"]):
                m = np.flatnonzero(segs == gi)
                if len(m):
                    r[m] = _rate(g["rate"], pre[:, m], self.idx, f)
            s = np.zeros(n)
            if f.get("to") in self.idx:
                s[self.idx[f["to"]]] += 1.0
            if f.get("from") in self.idx:
                s[self.idx[f["from"]]] -= float(f.get("ratio") or 1)
            Q += r[:, None, None] * np.outer(s, s)[None]
        Q[0] = 0.0
        return Q * np.outer(self.D0, self.D0)[None] + 1e-9 * np.eye(n)[None]

    def system(self, theta: np.ndarray, extras: list[tuple] = (), values: np.ndarray | None = None):
        """(A per configuration, d per step, the bias per measured stock)."""
        flows = self.flows_at(theta)
        n = len(self.ids)
        C = len(self.cfg_t)
        A = np.zeros((C, n, n))
        u = np.zeros((C, n))
        for c, tt in enumerate(self.cfg_t):
            here = [{**{k: v for k, v in f.items() if k != "byTime"}, "rate": f["byTime"][_seg(f, tt)]["rate"]} for f in flows]
            B, uu = linear_system(here, self.ids, (tt, tt))
            for (rows, col, w), val in zip(extras, values if values is not None else np.zeros(len(extras))):
                if w is not None and w != self.cfg_w[c]:
                    continue
                for s, sign in rows.items():
                    if col == ONE:
                        uu[self.idx[s]] += sign * val
                    else:
                        B[self.idx[s], self.idx[col]] += sign * val
            A[c] = np.eye(n) + B
            u[c] = uu
        # a biased stock is followed in its reported units (x' = b x): the bias enters the means only, not
        # the counting noise's size (held at the truth's), so what it confounds stays unidentified
        Dv = np.ones(n)
        for (fi, s, _), v in zip(self.leaves, theta):
            if fi == "bias":
                Dv[self.idx[s]] = v
        A = Dv[None, :, None] * A / Dv[None, None, :]
        d = np.einsum("kij,kj->ki", A[self.cfg], self.inj * Dv) + (u * Dv)[self.cfg]
        return A, d, np.ones(len(self.measured))

    def innovations(self, theta: np.ndarray, extras: list[tuple] = (), values=None, want_S: bool = False):
        A, d, h = self.system(theta, extras, values)
        return _kf(A, self.cfg, d, self.Q, self.obs_at, self.Y, self.R, self.mask, h, self.span, self.reset,
                   self.meas, self.m0, self.P0, self.aug, want_S)

    # ---- information ----
    def _S0inv(self) -> np.ndarray:
        if self._S0i is None:
            _, S = self.innovations(self.theta0, want_S=True)
            self._S0i = np.linalg.inv(S)
        return self._S0i

    def _jac(self, key) -> np.ndarray:
        """d innovations / d one number (a leaf index, or an extra direction (rows, col, window))."""
        if key in self._J:
            return self._J[key]
        if isinstance(key, int):
            h = self.dsteps[key]
            a, b = self.theta0.copy(), self.theta0.copy()
            a[key] += h
            b[key] -= h
            J = (self.innovations(a)[0] - self.innovations(b)[0]) / (2 * h)
        else:
            rows, col, w = key
            ex = [(dict(rows), col, w)]
            scale = max(1e-6, 1e-4 * (1.0 if col == ONE else 1.0 / max(1.0, float(np.mean(np.abs(self.X[self.idx[col]]))))))
            J = (self.innovations(self.theta0, ex, np.array([scale]))[0] - self.innovations(self.theta0, ex, np.array([-scale]))[0]) / (2 * scale)
        self._J[key] = J
        return J

    def fisher(self, extras: list = (), leaves: list[int] | None = None) -> np.ndarray:
        """The information of the truth's numbers (or only `leaves` of them) and `extras`, numbers
        added to the truth: (rows {stock: sign}, column (a stock or "1"), window or None)."""
        keys = list(range(self.P) if leaves is None else leaves) + [_freeze(e) for e in extras]
        J = np.array([self._jac(k) for k in keys])
        return np.einsum("pmi,mij,qmj->pq", J, self._S0inv(), J)

    def kl(self, flows: list[dict]) -> float | None:
        """KL(the truth's reported data || an alternative's), summed over the reported points, for an
        alternative structure with the same linear system (the same means) on every step: only the
        counting noise's covariance differs. None when the means differ."""
        for c, tt in enumerate(self.cfg_t):
            here = lambda fl: [{**{k: v for k, v in f.items() if k != "byTime"}, "rate": f["byTime"][_seg(f, tt)]["rate"]} for f in fl]  # noqa: E731
            a, b = linear_system(here(self.flows), self.ids, (tt, tt)), linear_system(here(flows), self.ids, (tt, tt))
            if a is None or b is None or np.abs(a[0] - b[0]).max() > 1e-9 or np.abs(a[1] - b[1]).max() > 1e-9 * max(1.0, np.abs(a[1]).max()):
                return None
        A, _, h = self.system(self.theta0)
        return float(_kl(A, self.cfg, self.Q, self.process_noise(flows), self.obs_at, self.R, self.mask, h, self.span, self.reset,
                         self.meas, self.P0, self.aug))

    def bound(self, extras: list = ()) -> tuple[np.ndarray, np.ndarray]:
        return bound(self.fisher(extras))

    def refit(self, iters: int = 20) -> np.ndarray:
        """The truth's own structure fitted to the reported data (Gauss-Newton on the whitened
        innovations from the truth's numbers, the bias too, with the Jacobian renewed each step and
        the step halved until the fit improves): what a method that knows the structure gets. A
        direction the data say nothing about stays where it is."""
        Si = self._S0inv()
        cost = lambda e: float(np.einsum("mi,mij,mj->", e, Si, e))  # noqa: E731
        th = self.theta0.copy()
        e = self.innovations(th)[0]
        f = cost(e)
        for _ in range(iters):
            J = np.zeros((self.P, *e.shape))
            for p in range(self.P):
                h = max(1e-6, 1e-4 * abs(th[p]))
                a, b = th.copy(), th.copy()
                a[p] += h
                b[p] -= h
                J[p] = (self.innovations(a)[0] - self.innovations(b)[0]) / (2 * h)
            C, _ = bound(np.einsum("pmi,mij,qmj->pq", J, Si, J))
            step = C @ np.einsum("pmi,mij,mj->p", J, Si, e)
            for _half in range(30):
                new = th - step
                e_new = self.innovations(new)[0]
                f_new = cost(e_new)
                if f_new <= f:
                    break
                step = step / 2
            else:
                break
            done = f - f_new <= 1e-10 * max(f, 1.0)
            th, e, f = new, e_new, f_new
            if done:
                break
        return th

    # ---- the scorer's parts as functions of theta ----
    def part_values(self, theta: np.ndarray) -> dict:
        """{(window, key, sub): value}: numbers of flow and co-flow parts (sub None) and a hidden
        part's k_in and delay, per window."""
        fl = self.flows_at(theta)
        out = {}
        for w, win in enumerate(self.wins):
            here = [{**{k: v for k, v in f.items() if k != "byTime"}, "rate": f["byTime"][_seg(f, win[0])]["rate"]} for f in fl]
            pw, _ = parts(here, set(self.measured), win)
            for k, v in pw.items():
                if k[0] in ("flow", "uses") and isinstance(v, (int, float)):
                    out[(w, k, None)] = float(v)
                elif k[0] == "hidden" and isinstance(v, dict):
                    out[(w, k, "k_in")] = float(v["k_in"])
                    if math.isfinite(v["delay"]):
                        out[(w, k, "delay")] = float(v["delay"])
        return out

    def entry_values(self, theta: np.ndarray) -> dict:
        """{(window, row, col): value}: the measured stocks' linear system per window (no hidden stock)."""
        fl = self.flows_at(theta)
        out = {}
        for w, win in enumerate(self.wins):
            here = [{**{k: v for k, v in f.items() if k != "byTime"}, "rate": f["byTime"][_seg(f, win[0])]["rate"]} for f in fl]
            sys_ = linear_system(here, self.measured, win)
            if sys_ is None:
                return {}
            B, u = sys_
            for i, r in enumerate(self.measured):
                out[(w, r, ONE)] = float(u[i])
                for j, c in enumerate(self.measured):
                    out[(w, r, c)] = float(B[i, j])
        return out

    def jacobian(self, fn) -> tuple[list, np.ndarray, np.ndarray]:
        base = fn(self.theta0)
        keys = list(base)
        D = np.zeros((len(keys), self.P))
        for p in range(self.P):
            if self.leaves[p][0] == "bias":
                continue
            h = self.dsteps[p]
            a, b = self.theta0.copy(), self.theta0.copy()
            a[p] += h
            b[p] -= h
            va, vb = fn(a), fn(b)
            D[:, p] = [(va.get(k, 0.0) - vb.get(k, 0.0)) / (2 * h) for k in keys]
        return keys, np.array([base[k] for k in keys]), D


def _freeze(e: tuple) -> tuple:
    rows, col, w = e
    return (tuple(sorted(rows.items(), key=lambda x: str(x[0]))), col, w)


def model(data: dict, wins: list[tuple[int, int]]) -> SSM | None:
    """The state-space model of a noisy run (cached per run and windows); None when the truth is not
    covered or the data are not a noisy variant's."""
    if not data.get("observation") or not (data.get("clean") or {}).get("flows"):
        return None
    if not covered(data["clean"]["flows"]):
        return None
    h = hashlib.sha256()
    h.update(json.dumps([data["clean"]["flows"], data["observation"], [list(w) for w in wins]], sort_keys=True, default=str).encode())
    for s in sorted(data["levels"]):
        h.update(np.asarray(data["levels"][s], dtype=float).tobytes())
    for s in sorted(data["clean"]["all_levels"]):
        h.update(np.asarray(data["clean"]["all_levels"][s], dtype=float).tobytes())
    key = h.hexdigest()
    if key not in _CACHE:
        if len(_CACHE) > 64:
            _CACHE.clear()
        try:
            _CACHE[key] = SSM(data, wins)
        except (ValueError, np.linalg.LinAlgError, TypeError, KeyError):
            _CACHE[key] = None
    return _CACHE[key]
