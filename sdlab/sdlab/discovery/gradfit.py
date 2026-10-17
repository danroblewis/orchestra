"""Fitting a model's numbers by gradient descent on its multi-step error (diffsim).

The model is run from many moments in the data (multiple shooting: every run starts from the
measured levels, so an error cannot compound beyond the horizon), over a curriculum of horizons
(short first), and its error at every step is the loss, each stock in units of its own spread.
L-BFGS-B (scipy) does the descent on gradients from JAX.

What may move is chosen by masks: the numbers of the rates the structure has (never a zero one),
effect tables, co-flow ratios, the values of found outside inflows (under a penalty that keeps them
near where they were found), and hidden stocks' starting levels. Hidden stocks' levels over the run
are what their flows imply, stepped through the measured data from a fitted starting level.
Sparsity: a group lasso on candidate effect tables' distance from 1 and an L1 price on candidate
co-flow ratios, so the descent also chooses structure.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import jax
import jax.numpy as jnp
import numpy as np
from scipy.optimize import minimize

from .diffsim import Sim, Spec


@dataclass
class Data:
    A: np.ndarray        # (Sm, n) measured levels, the spec's first Sm states
    sd: np.ndarray       # (Sm,) each stock's spread


def data_of(levels: dict, ids: list[str]) -> Data:
    A = np.nan_to_num(np.array([np.asarray(levels[i], dtype=float) for i in ids]))
    sd = A.std(axis=1)
    sd[sd == 0] = 1
    return Data(A=A, sd=sd)


def default_masks(spec: Spec) -> dict:
    """The numbers the structure has: c where the form has one, k where it reads a stock; existing
    effect tables' points; co-flow ratios."""
    F, G, S = spec.init["K"].shape
    mc = np.zeros((F, G), bool)
    for i, gs in enumerate(spec.groups):
        if spec.inflow[i]:
            continue
        for g, r in enumerate(gs):
            mc[i, g] = (r or {}).get("form") in ("constant", "gap", "linear")
    mk = (spec.init["K"] != 0) & ~spec.inflow[:, None, None]
    me = np.zeros(spec.init["ey"].shape, bool)
    for i in range(F):
        for j in range(spec.es.shape[1]):
            if spec.es[i, j] >= 0:
                me[i, j, : spec.en[i, j]] = True
    mu = spec.uses >= 0
    return {"C": mc, "K": mk, "ey": me, "per": mu, "pieces": np.zeros(spec.init["pieces"].shape, bool)}


class Packer:
    """The numbers that move, as one vector (and back); bounds keep each rate number's sign."""

    def __init__(self, base: dict, masks: dict):
        self.base = {k: jnp.asarray(v) for k, v in base.items()}
        self.idx = {k: np.nonzero(m) for k, m in masks.items() if m.any()}
        self.sizes = {k: len(i[0]) for k, i in self.idx.items()}

    def pack(self, p: dict) -> np.ndarray:
        return np.concatenate([np.asarray(p[k])[i] for k, i in self.idx.items()] or [np.zeros(0)])

    def unpack(self, theta) -> dict:
        out, at = dict(self.base), 0
        for k, i in self.idx.items():
            n = self.sizes[k]
            out[k] = out[k].at[i].set(theta[at: at + n])
            at += n
        return out

    def scales(self, p: dict) -> np.ndarray:
        """Each number's natural size (its starting magnitude, or a floor for its kind), so that the
        descent sees numbers of similar size."""
        floor = {"C": 0.1, "K": 1e-3, "ey": 1.0, "per": 0.1, "pieces": 0.1, "h0": 1.0}
        return np.concatenate([np.maximum(np.abs(np.asarray(p[k])[i]), floor.get(k, 1.0)) for k, i in self.idx.items()] or [np.zeros(0)])

    def bounds(self, p: dict) -> list[tuple]:
        b = []
        for k, i in self.idx.items():
            v = np.asarray(p[k])[i]
            if k in ("C", "K"):
                b += [(0.0, None) if x > 0 else (None, 0.0) if x < 0 else (None, None) for x in v]
            elif k == "ey":
                b += [(0.0, 20.0)] * len(v)
            elif k in ("per", "h0"):
                b += [(0.0, None)] * len(v)
            else:
                b += [(None, None)] * len(v)
        return b


def starts_for(n: int, H: int, count: int) -> np.ndarray:
    every = max(1, (n - H - 1) // count)
    return np.arange(1, n - H, every)


class Fit:
    """One fitting problem: a spec, the data, what moves, and the penalties."""

    def __init__(self, spec: Spec, data: Data, masks: dict | None = None, smooth: float = 0.02, starts: int = 1000,
                 effect_groups: list | None = None, effect_lambda: float = 0.0, use_price: np.ndarray | None = None,
                 piece_lambda: float = 0.0, piece_scale: np.ndarray | None = None, rate_price: dict | None = None,
                 piece_tv: float = 0.0):
        self.spec, self.data = spec, data
        self.Sm = data.A.shape[0]
        self.hidden = spec.S - self.Sm
        p0 = spec.params()
        if self.hidden:
            p0["h0"] = spec.init.get("h0", np.zeros(self.hidden))
        self.p0 = p0
        masks = dict(masks or default_masks(spec))
        if self.hidden:
            masks["h0"] = np.ones(self.hidden, bool)
        self.packer = Packer(p0, masks)
        self.width = smooth * self._typical(p0) if smooth else None
        self.max_starts = starts
        self.effect_groups = effect_groups or []        # (flow, slot) of candidate tables under the group lasso
        self.effect_lambda = effect_lambda
        self.use_price = use_price                      # (F, U) L1 price per unit of each candidate co-flow ratio
        self.piece_lambda = piece_lambda
        self.piece0 = jnp.asarray(p0["pieces"])
        self.piece_scale = jnp.asarray(piece_scale if piece_scale is not None else np.ones_like(p0["pieces"]))
        self.rate_price = {k: jnp.asarray(v) for k, v in (rate_price or {}).items()}   # L1 price per unit of each C and K number
        # total variation between a flow's consecutive pieces (so pieces merge unless the data needs them apart)
        self.piece_tv = piece_tv
        pf = spec.piece_flow
        self.tv_pairs = np.array([i for i in range(len(pf) - 1) if pf[i] == pf[i + 1]], dtype=int)
        self._fns: dict = {}

    def _typical(self, p) -> np.ndarray:
        """Each flow's typical rate on the data (for the width of its smooth floor)."""
        A = self.data.A
        L = np.vstack([A, np.zeros((self.hidden, A.shape[1]))])
        tix = np.arange(A.shape[1])
        C = p["C"][np.arange(self.spec.F)[:, None], self.spec.seg[:, tix]]
        K = p["K"][np.arange(self.spec.F)[:, None], self.spec.seg[:, tix]]
        r = np.abs(C + np.einsum("fms,sm->fm", K, L))
        return np.maximum(1e-6, r.mean(axis=1))

    def hidden_levels(self, p, sim: Sim):
        """Hidden stocks' levels at every time index: their flows stepped through the measured data."""
        A = jnp.asarray(self.data.A)

        def body(h, i):
            L = jnp.concatenate([A[:, i - 1], h])[:, None]
            nxt = sim.step(p, L, jnp.array([i]))[self.Sm:, 0]
            return nxt, nxt
        _, hs = jax.lax.scan(body, p["h0"], jnp.arange(1, A.shape[1]))
        return jnp.concatenate([p["h0"][None, :], hs]).T              # (hidden, n)

    def _loss_fn(self, H: int, exact: bool = False):
        key = (H, exact)
        if key in self._fns:
            return self._fns[key]
        top = np.concatenate([100 * (np.abs(self.data.A).max(axis=1) + self.data.sd), np.full(self.hidden, 1e3 * (np.abs(self.data.A).max() + 1))])
        sim = Sim(self.spec, width=None if exact else self.width, ceiling=top)
        n = self.data.A.shape[1]
        s0 = starts_for(n, H, self.max_starts)
        A = jnp.asarray(self.data.A)
        obs = jnp.asarray(self.data.A[:, s0[None, :] + np.arange(H)[:, None]].transpose(1, 0, 2))   # (H, Sm, M)
        sd = jnp.asarray(self.data.sd)[None, :, None]
        groups = self.effect_groups
        gi = (np.array([g[0] for g in groups]), np.array([g[1] for g in groups])) if groups else None

        def loss(theta):
            p = self.packer.unpack(theta)
            L0 = A[:, s0 - 1]
            if self.hidden:
                L0 = jnp.concatenate([L0, self.hidden_levels(p, sim)[:, s0 - 1]])
            traj = sim.run(p, L0, jnp.asarray(s0), H, keep=True)[:, : self.Sm]
            fit = jnp.mean(((traj - obs) / sd) ** 2)
            pen = 0.0
            if gi is not None and self.effect_lambda:
                d = p["ey"][gi] - 1.0
                mask = jnp.asarray(self.spec_mask_e[gi])
                pen = pen + self.effect_lambda * jnp.sum(jnp.sqrt(jnp.sum((d * mask) ** 2, axis=-1) + 1e-8))
            if self.use_price is not None:
                pen = pen + jnp.sum(jnp.asarray(self.use_price) * p["per"])
            for k, w in self.rate_price.items():
                pen = pen + jnp.sum(w * jnp.abs(p[k]))
            if self.piece_tv and len(self.tv_pairs):
                i = self.tv_pairs
                d = (p["pieces"][i + 1] - p["pieces"][i]) / self.piece_scale[i]
                pen = pen + self.piece_tv * jnp.sum(jnp.sqrt(d * d + 1e-6))
            if self.piece_lambda and p["pieces"].shape[0]:
                pen = pen + self.piece_lambda * jnp.mean(((p["pieces"] - self.piece0) / self.piece_scale) ** 2)
            return fit + pen, fit

        vg = jax.jit(jax.value_and_grad(loss, has_aux=True))
        self._fns[key] = vg
        return vg

    @property
    def spec_mask_e(self) -> np.ndarray:
        m = np.zeros(self.spec.init["ey"].shape, float)
        for i in range(self.spec.F):
            for j in range(self.spec.es.shape[1]):
                if self.spec.es[i, j] >= 0:
                    m[i, j, : self.spec.en[i, j]] = 1
        return m

    def error(self, p: dict, H: int) -> float:
        """The multi-step error alone (exact floors) of numbers p."""
        (_, fit), _ = self._loss_fn(H, exact=True)(jnp.asarray(self.packer.pack(p)))
        return float(fit)

    def run(self, p: dict | None, horizons=(5, 20), maxiter: int = 150, log=None) -> dict:
        p = dict(p or self.p0)
        theta = self.packer.pack(p)
        if not len(theta):
            return p
        bounds = self.packer.bounds(self.p0)
        theta = np.clip(theta, [lo if lo is not None else -np.inf for lo, _ in bounds], [hi if hi is not None else np.inf for _, hi in bounds])
        scale = self.packer.scales(self.p0)
        zb = [(None if lo is None else lo / s, None if hi is None else hi / s) for (lo, hi), s in zip(bounds, scale)]
        for H in horizons:
            if H >= self.data.A.shape[1] / 3:
                continue
            vg = self._loss_fn(H)
            began = time.time()

            def f(z):
                (v, _), g = vg(jnp.asarray(z * scale))
                v, g = float(v), np.asarray(g, dtype=float) * scale
                if not np.isfinite(v) or not np.all(np.isfinite(g)):
                    return 1e12, np.zeros_like(g)
                return v, g
            r = minimize(f, theta / scale, jac=True, method="L-BFGS-B", bounds=zb, options={"maxiter": maxiter})
            if np.isfinite(r.fun) and r.fun < 1e12:
                theta = r.x * scale
            if log:
                log(f"    H={H}: loss {r.fun:.5g} after {r.nit} iterations, {time.time() - began:.1f}s")
        return self.packer.unpack(jnp.asarray(theta))
