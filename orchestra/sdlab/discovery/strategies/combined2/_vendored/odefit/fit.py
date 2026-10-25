# Vendored for combined2 from sdlab/discovery/strategies/odefit/fit.py at commit 333f814 (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""Output-error fit of a per-step model linear in its numbers (docs/research/odefit.md).

Each stock's change in one step is a sum of terms, each a number times a column: a level, a
measured input, the constant 1, a product of two levels, or a hinge max(0, ...) of its own
(hinge.py). The numbers are chosen so that the model, run from an estimated state at the start of
each segment of the data, follows the measured levels (output error), not so that one step
predicts the next (equation error). Measurement error in the levels then sits only where it is
seen, on the outputs, and does not bias the numbers towards zero as it does in a one-step
regression (errors in variables).

The segments' starting states are solved exactly for each trial of the numbers (they enter the
linear part linearly: variable projection), so only the numbers are searched.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares


class Data:
    """The measured levels Y (steps x stocks), inputs U (steps x inputs), the injections J (steps x
    stocks: what is added at the start of each step, before its flows), aligned with t."""

    def __init__(self, Y: np.ndarray, U: np.ndarray, J: np.ndarray):
        self.Y, self.U, self.J = Y, U, J
        self.n, self.S = Y.shape
        self.m = U.shape[1]


def columns(X: np.ndarray, u: np.ndarray, spec: "Spec") -> np.ndarray:
    """The terms' columns for states X (S x k) and inputs u (m x k): levels, inputs, 1, products."""
    parts = [X, u, np.ones((1, X.shape[1]))]
    if spec.products:
        with np.errstate(over="ignore", invalid="ignore"):      # a trial's run that blows up is scored, not warned about
            parts.append(np.array([X[a] * X[b] for a, b in spec.products]).reshape(len(spec.products), X.shape[1]))
    return np.vstack(parts)


class Spec:
    """Which terms each stock's change reads: mask (S x P) over the columns of `columns`."""

    def __init__(self, S: int, m: int, products: list[tuple[int, int]] | None = None, mask: np.ndarray | None = None,
                 hinges: list[tuple[int, int]] | None = None):
        self.S, self.m = S, m
        self.products = list(products or [])
        self.P = S + m + 1 + len(self.products)
        self.mask = np.ones((S, self.P), bool) if mask is None else mask.copy()
        # hinges: (stock, sign): sign x max(0, h . [levels, inputs, 1]) added to the stock's change,
        # h free (S + m + 1 numbers each): a linear rate whose floor at 0 binds
        self.hinges = list(hinges or [])

    def copy(self) -> "Spec":
        return Spec(self.S, self.m, self.products, self.mask, self.hinges)

    def linear(self) -> bool:
        return not self.products and not self.hinges

    @property
    def nW(self) -> int:
        return int(self.mask.sum())

    @property
    def H(self) -> int:
        return self.S + self.m + 1

    def unpack(self, theta: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        W = np.zeros((self.S, self.P))
        W[self.mask] = theta[: self.nW]
        Hs = theta[self.nW:].reshape(len(self.hinges), self.H)
        return W, Hs


def segments(n: int, length: int) -> list[tuple[int, int]]:
    """Consecutive (start, end) index ranges covering 0..n, each at least length // 2 long."""
    length = max(4, min(n, length))
    k = max(1, n // length)
    edges = np.linspace(0, n, k + 1).round().astype(int)
    return [(int(a), int(b)) for a, b in zip(edges[:-1], edges[1:])]


def simulate(W: np.ndarray, spec: Spec, d: Data, starts: np.ndarray, segs: list[tuple[int, int]], Hs: np.ndarray | None = None) -> np.ndarray:
    """Levels (n x S) from each segment's start state, the model stepped through the segment (all
    segments at once)."""
    out = np.empty((d.n, d.S))
    st = np.array([a for a, _ in segs])
    en = np.array([b for _, b in segs])
    X = np.array(starts, dtype=float).T.copy()                 # S x seg
    out[st] = X.T
    rows = np.array([i for i, _ in spec.hinges], int)
    sg = np.array([g for _, g in spec.hinges], float)
    for j in range(1, int((en - st).max())):
        idx = st + j
        live = idx < en
        if not live.any():
            break
        k = idx[live]
        x = X[:, live] + d.J[k].T
        u = d.U[k].T
        dx = W @ columns(x, u, spec)
        if spec.hinges:
            lin = np.vstack([x, u, np.ones((1, x.shape[1]))])
            amt = np.maximum(0.0, Hs @ lin) * sg[:, None]
            np.add.at(dx, rows, amt)
        X[:, live] = x + dx
        out[k] = X[:, live].T
    return out


def _linear_parts(W: np.ndarray, spec: Spec, d: Data, segs: list[tuple[int, int]]):
    """For a linear spec: each segment's response to its start state (Phi: steps x S x S) and to
    the inputs, constant and injections (r: steps x S), stepped for all segments at once."""
    S, m = d.S, d.m
    A = np.eye(S) + W[:, :S]
    B = W[:, S:S + m]
    c = W[:, S + m]
    L = max(b - a for a, b in segs)
    nseg = len(segs)
    Phi = np.zeros((d.n, S, S))
    r = np.zeros((d.n, S))
    M = np.repeat(np.eye(S)[None], nseg, axis=0)          # seg x S x S
    v = np.zeros((nseg, S))
    starts = np.array([a for a, _ in segs])
    ends = np.array([b for _, b in segs])
    for j in range(L):
        idx = starts + j
        live = idx < ends
        if j > 0:
            k = idx[live]
            M[live] = A @ M[live]
            v[live] = (v[live] + d.J[k]) @ A.T + d.U[k] @ B.T + c
        Phi[idx[live]] = M[live]
        r[idx[live]] = v[live]
    return Phi, r


def residuals(theta: np.ndarray, spec: Spec, d: Data, segs: list[tuple[int, int]], w: np.ndarray, out: dict | None = None) -> np.ndarray:
    """Weighted output errors (n x S, flattened) with every segment's start state solved for."""
    W, Hs = spec.unpack(theta)
    Yw = d.Y * w
    if spec.linear():
        Phi, r = _linear_parts(W, spec, d, segs)
        zs = []
        res = np.empty_like(d.Y)
        for a, b in segs:
            F = Phi[a:b] * w[None, :, None]                        # steps x S x S (weighted rows)
            G = np.einsum("kij,kil->jl", F, F)
            h = np.einsum("kij,ki->j", F, Yw[a:b] - r[a:b] * w)
            try:
                z = np.linalg.solve(G + 1e-12 * np.trace(G) * np.eye(spec.S), h)
            except np.linalg.LinAlgError:
                z = d.Y[a].copy()
            zs.append(z)
            res[a:b] = Yw[a:b] - (np.einsum("kij,j->ki", Phi[a:b], z) + r[a:b]) * w
    else:
        # nonlinear: the start states are fitted inside the search (out["starts"] is their guess)
        zs = (out or {}).get("starts")
        if zs is None:
            zs = [d.Y[a].copy() for a, _ in segs]
        res = Yw - simulate(W, spec, d, np.array(zs), segs, Hs) * w
    if out is not None:
        out["starts"], out["W"], out["Hs"] = zs, W, Hs
    res = np.where(np.isfinite(res), res, 1e6)
    return np.clip(res, -1e6, 1e6).ravel()


def one_step(spec: Spec, d: Data) -> np.ndarray:
    """Equation-error numbers (one step ahead by least squares): the search's starting point."""
    X = (d.Y[:-1] + d.J[1:]).T
    C = columns(X, d.U[1:].T, spec)                           # P x (n - 1)
    dY = (d.Y[1:] - X.T)
    W = np.zeros((spec.S, spec.P))
    sc = np.maximum(np.abs(C).max(axis=1), 1e-12)
    for i in range(spec.S):
        cols = np.flatnonzero(spec.mask[i])
        if len(cols):
            W[i, cols] = np.linalg.lstsq((C[cols] / sc[cols, None]).T, dY[:, i], rcond=None)[0] / sc[cols]
    return W[spec.mask]


def fit(spec: Spec, d: Data, seg_len: int, w: np.ndarray, theta0: np.ndarray | None = None, max_nfev: int = 200,
        starts0: list | None = None) -> dict:
    """The numbers of `spec` by output error over segments of `seg_len` steps."""
    segs = segments(d.n, seg_len)
    theta0 = one_step(spec, d) if theta0 is None else theta0
    if theta0.size == 0:
        out: dict = {}
        r = residuals(theta0, spec, d, segs, w, out)
        return {"theta": theta0, "W": out["W"], "Hs": out["Hs"], "rss": _rss(r, d.S), "starts": out["starts"], "segs": segs, "nfev": 1}
    scale = _scale(spec, d)
    th = theta0 / scale
    if not spec.linear():
        return _fit_nonlinear(spec, d, segs, w, theta0, scale, max_nfev, starts0)
    sol = least_squares(lambda x: residuals(x * scale, spec, d, segs, w), th, method="trf", x_scale="jac", max_nfev=max_nfev)
    out = {}
    r = residuals(sol.x * scale, spec, d, segs, w, out)
    return {"theta": sol.x * scale, "W": out["W"], "Hs": out["Hs"], "rss": _rss(r, d.S), "starts": out["starts"], "segs": segs, "nfev": sol.nfev}


def simulate_batch(Ws: np.ndarray, Hss: np.ndarray, Z: np.ndarray, spec: Spec, d: Data, segs: list[tuple[int, int]]) -> np.ndarray:
    """simulate() for K sets of numbers at once: Ws (K x S x P), Hss (K x hinges x H), Z (K x seg x
    S) -> levels (K x n x S)."""
    K = Ws.shape[0]
    out = np.empty((K, d.n, d.S))
    st = np.array([a for a, _ in segs])
    en = np.array([b for _, b in segs])
    X = np.transpose(Z, (0, 2, 1)).astype(float).copy()       # K x S x seg
    out[:, st] = np.transpose(X, (0, 2, 1))
    rows = np.array([i for i, _ in spec.hinges], int)
    sg = np.array([g for _, g in spec.hinges], float)
    S, m = d.S, d.m
    with np.errstate(over="ignore", invalid="ignore"):
        _batch_steps(X, out, Ws, Hss, spec, d, st, en, rows, sg, K, S, m)
    return out


def _batch_steps(X, out, Ws, Hss, spec, d, st, en, rows, sg, K, S, m):
    for j in range(1, int((en - st).max())):
        idx = st + j
        live = idx < en
        if not live.any():
            break
        k = idx[live]
        x = X[:, :, live] + d.J[k].T[None]                     # K x S x L
        u = np.broadcast_to(d.U[k].T[None], (K, m, len(k)))
        parts = [x, u, np.ones((K, 1, len(k)))]
        if spec.products:
            parts.append(np.stack([x[:, a] * x[:, b] for a, b in spec.products], axis=1))
        C = np.concatenate(parts, axis=1)                      # K x P x L
        dx = np.einsum("ksp,kpl->ksl", Ws, C)
        if spec.hinges:
            amt = np.maximum(0.0, np.einsum("khq,kql->khl", Hss, C[:, : S + m + 1])) * sg[None, :, None]
            for h, i in enumerate(rows):
                dx[:, i] += amt[:, h]
        X[:, :, live] = x + dx
        out[:, k] = np.transpose(X[:, :, live], (0, 2, 1))


def fit_starts(spec: Spec, d: Data, seg_len: int, w: np.ndarray, theta: np.ndarray, max_nfev: int = 50) -> np.ndarray:
    """Per-stock weighted output error of fixed numbers, each segment's start state fitted (held-out
    checks)."""
    segs = segments(d.n, seg_len)
    if spec.linear():
        return _rss(residuals(theta, spec, d, segs, w), d.S)
    return _fit_nonlinear(spec, d, segs, w, theta, np.ones_like(theta), max_nfev, None, fixed=True)["rss"]


def _fit_nonlinear(spec, d, segs, w, theta0, scale, max_nfev, starts0=None, fixed=False):
    """Numbers and start states together (products make the start states enter nonlinearly); the
    Jacobian by forward differences, every perturbed set stepped in one batch."""
    S = d.S
    nseg = len(segs)
    z0 = np.array(starts0) if starts0 is not None and len(starts0) == nseg else np.array([d.Y[a] for a, _ in segs])
    zs = np.maximum(np.abs(d.Y).max(axis=0), 1e-9)
    nt = theta0.size
    nh = len(spec.hinges)

    def unpack(X):                                             # K x (nt + nseg S) scaled -> Ws, Hss, Z
        th = X[:, :nt] * scale
        K = X.shape[0]
        Ws = np.zeros((K, spec.S, spec.P))
        Ws[:, spec.mask] = th[:, : spec.nW]
        Hss = th[:, spec.nW:].reshape(K, nh, spec.H)
        Z = X[:, nt:].reshape(K, nseg, S) * zs
        return Ws, Hss, Z

    def res(X):
        Ws, Hss, Z = unpack(X)
        R = (d.Y[None] - simulate_batch(Ws, Hss, Z, spec, d, segs)) * w
        R = np.where(np.isfinite(R), R, 1e6)
        return np.clip(R, -1e6, 1e6).reshape(X.shape[0], -1)

    def f(x):
        return res(x[None])[0]

    def jac(x):
        h = 1e-6 * np.maximum(1.0, np.abs(x))
        X = np.vstack([x[None], x[None] + np.diag(h)])
        R = res(X)
        return ((R[1:] - R[0]) / h[:, None]).T

    x0 = np.concatenate([theta0 / scale, (z0 / zs).ravel()])
    if fixed:                                                  # the numbers held: only the start states move
        th0 = x0[:nt]
        fz = lambda z: f(np.concatenate([th0, z]))  # noqa: E731
        jz = lambda z: jac_z(np.concatenate([th0, z]))  # noqa: E731

        def jac_z(x):
            h = 1e-6 * np.maximum(1.0, np.abs(x[nt:]))
            X = np.repeat(x[None], len(h) + 1, axis=0)
            X[1:, nt:] += np.diag(h)
            R = res(X)
            return ((R[1:] - R[0]) / h[:, None]).T
        sol = least_squares(fz, x0[nt:], jac=jz, method="trf", x_scale="jac", max_nfev=max_nfev)
        sol.x = np.concatenate([th0, sol.x])
    else:
        sol = least_squares(f, x0, jac=jac, method="trf", x_scale="jac", max_nfev=max_nfev)
    th = sol.x[:nt] * scale
    z = list(sol.x[nt:].reshape(nseg, S) * zs)
    out = {"starts": z}
    r = residuals(th, spec, d, segs, w, out)
    return {"theta": th, "W": out["W"], "Hs": out["Hs"], "rss": _rss(r, S), "starts": z, "segs": segs, "nfev": sol.nfev}


def _scale(spec: Spec, d: Data) -> np.ndarray:
    """A typical size for each number: the stock's typical change over the column's typical size."""
    X = d.Y.T
    C = columns(X, d.U.T, spec)
    csz = np.maximum(np.sqrt((C ** 2).mean(axis=1)), 1e-9)
    dsz = np.maximum(np.abs(np.diff(d.Y, axis=0)).mean(axis=0), 1e-9 * np.maximum(1, np.abs(d.Y).max(axis=0)))
    sc = (dsz[:, None] / csz[None, :])[spec.mask]
    if spec.hinges:
        hsz = np.concatenate([dsz[i] / csz[: spec.H] for i, _ in spec.hinges])
        sc = np.concatenate([sc, hsz])
    return sc


def _rss(r: np.ndarray, S: int) -> np.ndarray:
    return (r.reshape(-1, S) ** 2).sum(axis=0)
