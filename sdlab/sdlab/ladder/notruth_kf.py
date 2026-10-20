"""The Kalman filter of notruth_core.innovations (NO-TRUTH: it gets the found model linearised along the
nominal path and the reports, nothing else), and the maximum-likelihood fit of its noise.

The noise per measured stock i at grid time k: report noise R_ik = v_i (e^a + e^b y_ik^2 / mean y_i^2) +
q_i^2 / 12 (absolute and relative report error, at least the rounding of a whole number), process noise
Q_ik = v_i (e^c + e^d |y_i,k-1| / mean |y_i|) (y: the model's one-step
prediction of the level, not the report) (shocks, counting noise that grows with what flows), v_i the
variance of the stock's clamped one-step errors. The four numbers per stock are fitted by the innovations'
Gaussian likelihood (L-BFGS-B from the moment estimates); the found model's own unmeasured stocks get a
small fixed process noise.
"""

from __future__ import annotations

import numpy as np
from numba import njit

BURN = 10


@njit(cache=True)
def kf(F, P1, X, Y, R, Q, P0, burn):
    D, N = X.shape
    S = Y.shape[0]
    m = X[:, 0].copy()
    P = P0.copy()
    E = np.full((S, N), np.nan)
    SD = np.full((S, N), np.nan)
    M = np.empty((D, N))
    M[:, 0] = m
    ll = 0.0
    obs = np.empty(S, np.int64)
    for k in range(1, N):
        Fk = np.ascontiguousarray(F[k - 1])
        m = P1[:, k - 1] + Fk @ np.ascontiguousarray(m - X[:, k - 1])
        P = Fk @ P @ np.ascontiguousarray(Fk.T)
        for d in range(D):
            P[d, d] += Q[d, k]
        no = 0
        for i in range(S):
            if np.isfinite(Y[i, k]):
                obs[no] = i
                no += 1
        if no == 0:
            M[:, k] = m
            continue
        H = np.empty((no, no))
        PH = np.empty((D, no))
        inn = np.empty(no)
        for a in range(no):
            inn[a] = Y[obs[a], k] - m[obs[a]]
            for b in range(no):
                H[a, b] = P[obs[a], obs[b]]
            H[a, a] += R[obs[a], k]
            for d in range(D):
                PH[d, a] = P[d, obs[a]]
        for a in range(no):
            E[obs[a], k] = inn[a]
            SD[obs[a], k] = np.sqrt(max(H[a, a], 1e-300))
        Hi = np.linalg.inv(H)
        if k > burn:
            sign, logdet = np.linalg.slogdet(H)
            ll += -0.5 * (logdet + inn @ Hi @ inn)
        K = PH @ Hi
        m = m + K @ inn
        P = P - K @ PH.T
        P = 0.5 * (P + P.T)
        M[:, k] = m
    return ll, E, SD, M


class Noise:
    """The noise parametrisation of the module docstring, for one data set."""

    def __init__(self, Y: np.ndarray, Yi: np.ndarray, clamped: np.ndarray, q: np.ndarray, D: int, hidden_q: float):
        """Yi: the level each noise scales with, at each grid time; not the report itself (a variance
        read off the noisy report weights its own error, and biases the filter)."""
        self.S, self.N = Y.shape
        self.D = D
        self.v = np.array([max(float(np.nanmean(clamped[i] ** 2)), 1e-300) if np.isfinite(clamped[i]).any() else 1.0 for i in range(self.S)])
        y2 = Yi ** 2
        self.ry = y2 / np.maximum(y2.mean(axis=1, keepdims=True), 1e-300)
        ya = np.abs(np.concatenate([Yi[:, :1], Yi[:, :-1]], axis=1))
        self.qy = ya / np.maximum(ya.mean(axis=1, keepdims=True), 1e-300)
        self.floor = q ** 2 / 12
        self.hidden_q = hidden_q

    def RQ(self, th: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        a, b, c, d = th.reshape(4, self.S)
        v = self.v[:, None]
        R = v * (np.exp(a)[:, None] + np.exp(b)[:, None] * self.ry) + self.floor[:, None]
        Q = np.full((self.D, self.N), self.hidden_q)
        Q[: self.S] = v * (np.exp(c)[:, None] + np.exp(d)[:, None] * self.qy)
        return R, Q

    def start(self, R0: np.ndarray, Q0: np.ndarray) -> np.ndarray:
        """Parameters from moment estimates (R0, Q0: measured x grid), split evenly between the two terms."""
        v = self.v[:, None]
        r = np.maximum(np.mean(np.maximum(R0 - self.floor[:, None], 0) / v, axis=1), 1e-8)
        qq = np.maximum(np.mean(Q0 / v, axis=1), 1e-8)
        return np.concatenate([np.log(r / 2), np.log(r / 2), np.log(qq / 2), np.log(qq / 2)])


LO, HI = -25.0, 3.0


def fit(F, P1, X, Y, noise: Noise, th0: np.ndarray, P0, maxiter: int = 60) -> tuple[np.ndarray, float, bool]:
    from scipy.optimize import minimize

    def nll(th):
        R, Q = noise.RQ(th)
        ll, _, _, _ = kf(F, P1, X, Y, R, Q, P0, BURN)
        return -ll if np.isfinite(ll) else 1e300

    th0 = np.clip(th0, LO, HI)
    try:
        r = minimize(nll, th0, method="L-BFGS-B", bounds=[(LO, HI)] * len(th0), options={"maxiter": maxiter})
    except Exception:                                       # noqa: BLE001
        return th0, -nll(th0), False
    return r.x, -float(r.fun), bool(r.success)
