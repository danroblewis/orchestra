# Vendored for combined2 from sdlab/discovery/strategies/odefit/compare.py at commit 333f814 (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""Comparing any two models (SD Lab flows) by output error, as the numbers were fitted.

The main line's judge runs each model from measured levels. Under measurement error those starting
levels are off, and a model that pulls every run towards the mean (a one-step fit shrunk by the
noise) looks better than the true one. Here each segment's starting state is estimated too (a few
Gauss-Newton steps on that segment's own error, all segments at once), so a model is judged by how
well it can follow the measurements, not by how it forgives a bad start.
"""

from __future__ import annotations

import numpy as np

from sdlab.discovery.simulate import Model

SEG = 20
ITER = 6


def output_error(flows: list[dict], ids: list[str], run: dict, opts: dict, w: np.ndarray, seg: int = SEG) -> float:
    """Weighted squared output error over consecutive `seg`-step segments, each from its fitted start."""
    if not flows:
        return float("inf")
    if any(s not in ids for f in flows for s in (f.get("from"), f.get("to")) if s):
        return float("nan")                                   # a hidden stock of the model's own: not comparable here
    t = np.asarray(run["t"], dtype=float)
    Y = np.nan_to_num(np.array([np.asarray(run["levels"][i], dtype=float) for i in ids]))     # S x n
    S, n = Y.shape
    inputs = opts.get("inputs")
    model = Model(flows, ids, inputs={"t": run["t"], "values": inputs} if inputs else None)
    pulses: dict[float, list] = {}
    for j in opts.get("injections") or []:
        if j.get("stock") in ids:
            pulses.setdefault(float(j["t"]), []).append((ids.index(j["stock"]), float(j["amount"])))
    starts = np.arange(0, n - 1, seg)
    lens = np.minimum(seg, n - starts)
    nseg = len(starts)
    h = 1e-4 * np.maximum(Y.std(axis=1), 1e-6)

    def trajectories(Z):                                        # Z: S x (nseg * k) -> S x L x (nseg * k)
        k = Z.shape[1] // nseg
        st = np.tile(starts, k)
        out = np.full((S, seg, Z.shape[1]), np.nan)
        L = Z.copy()
        out[:, 0] = L
        for j in range(1, seg):
            idx = np.minimum(st + j, n - 1)
            tt = t[idx]
            for tj, i, amount in [(tj, i, a) for tj, lst in pulses.items() for i, a in lst]:
                hit = tt == tj
                if hit.any():
                    L[i, hit] = np.maximum(0.0, L[i, hit] + amount)
            L = model.step(L, tt)
            out[:, j] = L
        return out

    obs = np.full((S, seg, nseg), np.nan)
    for s_, (a, m) in enumerate(zip(starts, lens)):
        obs[:, :m, s_] = Y[:, a:a + m]
    valid = ~np.isnan(obs)
    Z = Y[:, starts].copy()
    for _ in range(ITER):
        pert = [Z] + [Z + np.eye(S)[:, [i]] * h[i] for i in range(S)]
        T = trajectories(np.hstack(pert)).reshape(S, seg, S + 1, nseg)
        r = np.where(valid, (obs - T[:, :, 0]) * w[:, None, None], 0.0)          # S x seg x nseg
        J = np.stack([(T[:, :, i + 1] - T[:, :, 0]) / h[i] for i in range(S)], axis=-1) * w[:, None, None, None]
        J = np.where(valid[..., None], J, 0.0)                                   # S x seg x nseg x S
        G = np.einsum("aksi,aksj->sij", J, J) + 1e-9 * np.eye(S)[None]
        g = np.einsum("aksi,aks->si", J, r)
        try:
            step = np.linalg.solve(G, g[..., None])[..., 0]                     # nseg x S
        except np.linalg.LinAlgError:
            break
        Z = np.maximum(0.0, Z + step.T)
    T = trajectories(Z)
    r = np.where(valid, (obs - T) * w[:, None, None], 0.0)
    e = float((r ** 2).sum())
    return e if np.isfinite(e) else float("inf")
