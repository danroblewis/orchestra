"""Unannounced eras: recurring regimes in a row's coefficients, found as a Markov-switching regression.

An internal flow's equation may change without anyone announcing it (a supplier that is slow for a
while, posting that falls at night). Inflow pieces absorb only the constant part of such a change;
the coefficient part (a gap's 1/time, a link's k) is left in the row's numbers, averaged over the
regimes. Here each stock's change in a step is fitted as

    change of s at t  =  a[z_t] + sum_j b[z_t][j] x level of j at t-1  (+ noise with variance v[z_t])

with z_t a hidden regime that follows a Markov chain (Hamilton 1989; EM with the forward-backward
smoother, Kim 1994). A regime is kept only if it recurs (at least `min_spells` spells of each
regime) and changes a level's number, not only the constant (a change in the constant alone is an
outside inflow's change, which pieces handle). Rows whose regimes switch at the same times share
them; the shared regimes are then fitted jointly over those rows, and handed to the era machinery
(matrix.py) as eras, merged with the announced ones.
"""

from __future__ import annotations

import math

import numpy as np
from numba import njit

from .changes import pelt
from .matrix import configurations
from .regression import demean


@njit(cache=True)
def _smooth(logf: np.ndarray, P: np.ndarray, pi: np.ndarray):
    """Forward-backward (scaled): the regime probabilities at each step, the expected transition
    counts, and the log likelihood."""
    T, K = logf.shape
    f = np.empty((T, K))
    m = np.empty(T)
    for t in range(T):
        mx = logf[t, 0]
        for k in range(1, K):
            if logf[t, k] > mx:
                mx = logf[t, k]
        m[t] = mx
        for k in range(K):
            f[t, k] = math.exp(logf[t, k] - mx)
    alpha = np.empty((T, K))
    c = np.empty(T)
    s = 0.0
    for k in range(K):
        alpha[0, k] = pi[k] * f[0, k]
        s += alpha[0, k]
    s = max(s, 1e-300)
    c[0] = s
    for k in range(K):
        alpha[0, k] /= s
    for t in range(1, T):
        s = 0.0
        for k in range(K):
            a = 0.0
            for j in range(K):
                a += alpha[t - 1, j] * P[j, k]
            alpha[t, k] = a * f[t, k]
            s += alpha[t, k]
        s = max(s, 1e-300)
        c[t] = s
        for k in range(K):
            alpha[t, k] /= s
    beta = np.empty((T, K))
    for k in range(K):
        beta[T - 1, k] = 1.0
    xi = np.zeros((K, K))
    for t in range(T - 2, -1, -1):
        for j in range(K):
            b = 0.0
            for k in range(K):
                w = P[j, k] * f[t + 1, k] * beta[t + 1, k] / c[t + 1]
                b += w
                xi[j, k] += alpha[t, j] * w
            beta[t, j] = b
    gamma = alpha * beta
    for t in range(T):
        s = 0.0
        for k in range(K):
            s += gamma[t, k]
        s = max(s, 1e-300)
        for k in range(K):
            gamma[t, k] /= s
    ll = 0.0
    for t in range(T):
        ll += math.log(c[t]) + m[t]
    return gamma, xi, ll


def _design(prev: np.ndarray, cols: list[int]) -> np.ndarray:
    """Steps x (1 + columns): the constant and the levels at the start of each step."""
    return np.column_stack([np.ones(prev.shape[1])] + [prev[j] for j in cols])


def _m_step(ys, Xs, gamma, floors, shared: bool, nu: float | None, us: list[np.ndarray] | None):
    """Weighted least squares per row and regime; returns the coefficients, variances (one per row
    shared by the regimes, or one per regime), the log densities of every step under every regime
    (summed over the rows) and, with Student-t noise (nu degrees of freedom), each step's weight for
    the next pass (a step far off its regime's line, a one-off spike, counts less)."""
    T, K = gamma.shape
    logf = np.zeros((T, K))
    betas, vars_, new_us = [], [], []
    for n, (y, X, floor) in enumerate(zip(ys, Xs, floors)):
        u = us[n] if us is not None else np.ones((T, K))
        B, R = [], []
        for k in range(K):
            w = gamma[:, k] * u[:, k]
            Xw = X * w[:, None]
            G = X.T @ Xw
            G[np.diag_indices_from(G)] += 1e-8 * (np.abs(np.diag(G)) + 1)
            b = np.linalg.solve(G, Xw.T @ y)
            B.append(b)
            R.append(y - X @ b)
        wr = [gamma[:, k] * u[:, k] * R[k] ** 2 for k in range(K)]
        if shared:
            v = max(float(sum(x.sum() for x in wr) / T), floor)
            V = [v] * K
        else:
            V = [max(float(wr[k].sum() / max(gamma[:, k].sum(), 1e-9)), floor) for k in range(K)]
        nu_u = np.ones((T, K))
        for k in range(K):
            q = R[k] ** 2 / V[k]
            if nu:
                logf[:, k] += (math.lgamma((nu + 1) / 2) - math.lgamma(nu / 2) - 0.5 * math.log(nu * math.pi * V[k])
                               - (nu + 1) / 2 * np.log1p(q / nu))
                nu_u[:, k] = (nu + 1) / (nu + q)
            else:
                logf[:, k] += -0.5 * math.log(2 * math.pi * V[k]) - 0.5 * q
        betas.append(B)
        vars_.append(V)
        new_us.append(nu_u)
    return betas, vars_, logf, new_us


def fit_switching(ys: list[np.ndarray], Xs: list[np.ndarray], K: int, gamma0: np.ndarray, iters: int = 60, stick: float = 2.0,
                  shared: bool = True, nu: float | None = 4.0) -> dict:
    """EM for a K-regime Markov-switching regression shared by several rows (one regime path), from
    the starting regime probabilities gamma0 (steps x K); noise Student-t with nu degrees of freedom
    (None: Gaussian)."""
    T = gamma0.shape[0]
    floors = [max(1e-6, 1e-4 * float(np.var(y))) for y in ys]
    gamma = gamma0.copy()
    P = np.full((K, K), 1.0 / K)
    pi = np.full(K, 1.0 / K)
    ll_old = -np.inf
    us = None
    for _ in range(iters):
        betas, vars_, logf, us = _m_step(ys, Xs, gamma, floors, shared, nu, us)
        gamma, xi, ll = _smooth(logf, P, pi)
        # a little stickiness (pseudo-counts on staying) keeps a regime from flickering on noise
        P = xi + stick * np.eye(K) + 1e-3
        P /= P.sum(axis=1, keepdims=True)
        pi = np.maximum(gamma[0], 1e-6)
        pi /= pi.sum()
        if abs(ll - ll_old) < 1e-6 * T:
            break
        ll_old = ll
    p = sum(K * X.shape[1] + (1 if shared else K) for X in Xs) + K * (K - 1)
    return {"K": K, "gamma": gamma, "P": P, "ll": ll, "betas": betas, "vars": vars_, "bic": -2 * ll + p * math.log(T)}


def _soft(z: np.ndarray, K: int) -> np.ndarray:
    g = np.full((len(z), K), 0.1 / max(1, K - 1))
    g[np.arange(len(z)), z] = 0.9
    return g


def _kmeans_1d(v: np.ndarray, w: np.ndarray, K: int) -> np.ndarray:
    """Weighted 1-D k-means of v into K groups (labels), from the weighted quantiles."""
    order = np.argsort(v)
    cw = np.cumsum(w[order]) / w.sum()
    centres = np.array([v[order][min(len(v) - 1, int(np.searchsorted(cw, (k + 0.5) / K)))] for k in range(K)], dtype=float)
    lab = np.zeros(len(v), int)
    for _ in range(50):
        lab = np.abs(v[:, None] - centres[None, :]).argmin(axis=1)
        new = np.array([np.average(v[lab == k], weights=w[lab == k]) if (lab == k).any() else centres[k] for k in range(K)])
        if np.allclose(new, centres):
            break
        centres = new
    return lab


def _starts(ys, Xs, K: int, seeds: list[np.ndarray] | None = None) -> list[np.ndarray]:
    """Starting regime probabilities: steps split by the pooled fit's residual (summed over rows,
    each scaled), raw and smoothed over a few steps; and, for each seed series (what a simpler fit of
    the row leaves unexplained), its pieces of constant mean (PELT) grouped by their values: a
    regime's switches show there as changes, which the pooled fit (whose levels follow the regimes)
    blurs."""
    T = len(ys[0])
    res = np.zeros(T)
    for y, X in zip(ys, Xs):
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        r = y - X @ b
        res += r / (r.std() or 1)
    out = []
    for series in (res, np.convolve(res, np.ones(3) / 3, mode="same")):
        edges = np.quantile(series, np.linspace(0, 1, K + 1)[1:-1])
        out.append(_soft(np.searchsorted(edges, series), K))
    for r0 in seeds or []:
        cuts = pelt(r0, 1, 1)
        if len(cuts) - 1 >= K:
            a, b = np.array(cuts[:-1]), np.array(cuts[1:])
            vals = np.array([r0[i:j].mean() for i, j in zip(a, b)])
            lab = _kmeans_1d(vals, (b - a).astype(float), K)
            out.append(_soft(np.repeat(lab, b - a), K))
    return out


def best_switching(ys, Xs, K: int, seeds=None, shared: bool = True, nu: float | None = 4.0) -> dict:
    fits = [fit_switching(ys, Xs, K, g, shared=shared, nu=nu) for g in _starts(ys, Xs, K, seeds)]
    return max(fits, key=lambda f: f["ll"])


def spells(z: np.ndarray) -> list[tuple[int, int, int]]:
    """(regime, first step, end step) for each run of one regime."""
    cut = np.flatnonzero(np.diff(z)) + 1
    a = np.concatenate([[0], cut])
    b = np.concatenate([cut, [len(z)]])
    return [(int(z[i]), int(i), int(j)) for i, j in zip(a, b)]


def recurs(z: np.ndarray, K: int, min_spells: int) -> bool:
    sp = spells(z)
    return all(sum(1 for r, _, _ in sp if r == k) >= min_spells for k in range(K))


def path_gains(ys, Xs, z: np.ndarray, K: int, cuts: list | None = None) -> tuple[float, float]:
    """Along the regime path z, in BIC summed over the rows: how much better the rows fit with every
    number per regime than with no regimes at all, each switch priced as a parameter (as a change in
    an inflow's pieces is), and how much better than with a constant per regime and shared levels'
    numbers (the part of the regimes that is a coefficient change). With the rows' own inflow pieces
    (cuts, one list per row or None), the coefficient part is measured with each piece's mean taken
    out, so a regime's number cannot stand in for a change in the outside inflow."""
    T = len(z)
    log_t = math.log(T)
    exist, coef = -(int((z[1:] != z[:-1]).sum())) * log_t, 0.0
    ind = np.eye(K)[z]                                       # steps x K
    for n, (y, X) in enumerate(zip(ys, Xs)):
        lev = X[:, 1:]
        designs = (X, np.column_stack([ind, lev]), np.column_stack([ind] + [lev * ind[:, [k]] for k in range(K)]))
        rss = []
        for d, D in enumerate(designs):
            c = cuts[n] if cuts and d > 0 else None
            yy, DD = (demean(y, c), demean(D.T, c).T) if c and len(c) > 2 else (y, D)
            b = np.linalg.lstsq(DD, yy, rcond=None)[0]
            rss.append(max(float(((yy - DD @ b) ** 2).sum()), 1e-12))
        if cuts and cuts[n] and len(cuts[n]) > 2:
            # the existence test compares with the plain fit, the coefficient test within pieces
            D = designs[2]
            b = np.linalg.lstsq(D, y, rcond=None)[0]
            rss_b_plain = max(float(((y - D @ b) ** 2).sum()), 1e-12)
        else:
            rss_b_plain = rss[2]
        p = lev.shape[1]
        exist += T * math.log(rss[0] / rss_b_plain) - (K - 1) * (p + 1) * log_t
        coef += T * math.log(rss[1] / rss[2]) - (K - 1) * p * log_t
    return exist, coef


def switch_match(za: np.ndarray, zb: np.ndarray, tol: int = 1) -> float:
    """The share of switches (in both paths) that have a switch in the other path within tol steps."""
    a = np.flatnonzero(np.diff(za)) + 1
    b = np.flatnonzero(np.diff(zb)) + 1
    if not len(a) or not len(b):
        return 0.0
    near = lambda u, v: np.abs(u[:, None] - v[None, :]).min(axis=1) <= tol  # noqa: E731
    return float((near(a, b).sum() + near(b, a).sum()) / (len(a) + len(b)))


def row_columns(stocks: list[dict], row: dict | None, s: int, which: str) -> list[int]:
    """The levels a row's regimes are looked for on: those the found row uses (in any
    configuration) and its own ("chosen"), or every level it may use ("allowed": same group, and not
    its own if it is final), as the matrix method allows them."""
    ids = [x["id"] for x in stocks]
    group = [x.get("group") for x in stocks]
    final = bool(stocks[s].get("final"))
    allowed = [j for j in range(len(ids)) if (j == s or not group[j] or not group[s] or group[j] == group[s]) and not (final and j == s)]
    if which == "allowed" or row is None:
        return allowed
    used = {k for c in row.get("coefL") or [row.get("coef") or {}] for k, v in c.items() if v}
    return [j for j in allowed if ids[j] in used or j == s]


def row_residual(row: dict, ids: list[str], s: int, prev: np.ndarray, dy: np.ndarray, conf) -> np.ndarray:
    """What the found row's numbers (per announced configuration) leave unexplained in s's changes."""
    coefs = row.get("coefL") or [row.get("coef") or {}]
    cfg = conf[1] if conf and len(coefs) == len(conf[0]) else np.zeros(dy.shape[1], int)
    res = dy[s].copy()
    for c, coef in enumerate(coefs):
        m = cfg == c
        for j, k in coef.items():
            if j in ids:
                res[m] -= k * prev[ids.index(j)][m]
    return res


def find(stocks: list[dict], run: dict, rows: list[dict], opts: dict) -> list[dict]:
    """Recurring regimes in the rows' coefficients: a list of processes, each {"z": regime per step,
    "K", "rows": the stock ids it was found in, "gain"} (strongest first)."""
    ids = [s["id"] for s in stocks]
    lv = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, [0] * len(run["t"])), dtype=float) for i in ids]))
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    T = dy.shape[1]
    min_spells = opts.get("min_spells", 3)
    max_k = opts.get("max_regimes", 3)
    need_coef = opts.get("coefficient_regimes", True)
    shared = opts.get("shared_variance", True)
    nu = opts.get("nu", 4.0)
    by_id = {r["id"]: r for r in rows}
    conf = configurations(opts.get("eras"), run["t"])
    found = []
    for s, sid in enumerate(ids):
        row = by_id.get(sid)
        if row is None or not np.any(dy[s]):
            continue
        ys, Xs = [dy[s]], [_design(prev, row_columns(stocks, row, s, opts.get("detect_on", "allowed")))]
        own = np.column_stack([np.ones(T), prev[s]])
        res = row_residual(row, ids, s, prev, dy, conf)
        # the row's outside-inflow pieces: the found row's own, else those of what its numbers leave
        pieces = row["cuts"] if row.get("cuts") and len(row["cuts"]) > 2 else pelt(res, opts.get("min_piece", 5), 1)
        seeds = [res, dy[s] - own @ np.linalg.lstsq(own, dy[s], rcond=None)[0]]
        best = None
        for K in range(2, max_k + 1):
            f = best_switching(ys, Xs, K, seeds, shared, nu)
            z = f["gamma"].argmax(axis=1)
            if len(set(z.tolist())) < K or not recurs(z, K, min_spells):
                continue
            exist, coef = path_gains(ys, Xs, z, K, [pieces] if opts.get("coef_within_pieces", True) else None)
            if exist <= (best["gain"] if best else 0.0) + math.log(T) or (need_coef and coef <= math.log(T)):
                continue
            best = {**f, "z": z, "gain": exist, "coef_gain": coef}
        if best is not None:
            found.append({"rows": [sid], "ys": ys, "Xs": Xs, **best})
    # rows whose regimes switch at the same times share them: fitted again jointly
    groups: list[list[dict]] = []
    for f in sorted(found, key=lambda f: -f["gain"]):
        g = next((g for g in groups if switch_match(g[0]["z"], f["z"]) >= opts.get("share", 0.7)), None)
        if g is None:
            groups.append([f])
        else:
            g.append(f)
    out = []
    for g in groups:
        lead = g[0]
        if len(g) == 1:
            out.append({"z": lead["z"], "K": lead["K"], "rows": lead["rows"], "gain": lead["gain"], "coef_gain": lead["coef_gain"]})
            continue
        ys = [y for f in g for y in f["ys"]]
        Xs = [X for f in g for X in f["Xs"]]
        K = lead["K"]
        joint = fit_switching(ys, Xs, K, lead["gamma"], shared=shared, nu=nu)
        z = joint["gamma"].argmax(axis=1)
        if len(set(z.tolist())) < K or not recurs(z, K, min_spells):
            z, joint = lead["z"], lead
        out.append({"z": z, "K": K, "rows": [r for f in g for r in f["rows"]], "gain": sum(f["gain"] for f in g), "coef_gain": sum(f["coef_gain"] for f in g)})
    return out[: opts.get("max_processes", 2)]


def eras_with(processes: list[dict], announced: list[dict] | None, t: list) -> list[dict]:
    """Eras (start, label) for every step's configuration: the announced era in force and each
    process's regime. Step k (from t[k] to t[k+1]) is in the configuration that holds at t[k+1]."""
    T = len(t) - 1
    ann = sorted((e for e in announced or [] if e and e.get("start") is not None), key=lambda e: e["start"])

    def ann_at(time):
        lab = ""
        for e in ann:
            if time >= e["start"]:
                lab = e.get("label") or str(e["start"])
        return lab

    labels = []
    for k in range(T):
        parts = [ann_at(t[k + 1])] + [f"regime {chr(65 + n)}{int(p['z'][k]) + 1}" for n, p in enumerate(processes)]
        labels.append(" / ".join(x for x in parts if x))
    eras = [{"start": t[0], "label": labels[0]}]
    for k in range(1, T):
        if labels[k] != labels[k - 1]:
            eras.append({"start": t[k + 1], "label": labels[k]})
    return eras
