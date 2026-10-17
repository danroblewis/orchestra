"""A differentiable copy of simulate.Model (JAX), for fitting a model's numbers by gradient descent.

A list of flows (the dicts simulate.Model steps) is compiled, for one run's times, into arrays:

  - every rate as c + sum_j k_j x level of j (constant, proportional, gap and linear are all of that
    shape), one (c, k) per distinct rate of the flow (a byTime flow's eras share a number wherever
    they had the same rate), floored at 0;
  - a found outside inflow (`inflow` pieces) as a time series of piece values;
  - effects as tables (a linear clamp is exactly a two-point table), the flow's rate multiplied by
    each table read at its stock's level and floored at 0;
  - co-flows (`uses`): `per` of a stock used up for each unit moved; a used stock's outflows and
    users share what it holds, in the same order simulate.Model shares it;
  - levels floored at 0 after every step.

With the smooth parts off (`smooth=0`) a run gives what simulate.Model gives; with `smooth=s` the
rate floors are softplus curves s x (a typical rate) wide, so gradients pass through them.
`to_flows` writes fitted numbers back into the flows, in their original forms.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field

# the arrays are small: one thread per process (the bench runs several processes at once)
os.environ.setdefault("XLA_FLAGS", "--xla_cpu_multi_thread_eigen=false intra_op_parallelism_threads=1")

import jax  # noqa: E402
import jax.numpy as jnp  # noqa: E402
import numpy as np  # noqa: E402

from .simulate import _Segments  # noqa: E402

jax.config.update("jax_enable_x64", True)


def rate_vector(rate: dict | None, index: dict[str, int], S: int) -> tuple[float, np.ndarray]:
    """A rate in any form as (c, k): c + sum_j k_j x level j (before the floor)."""
    rate = rate or {}
    k = np.zeros(S)
    form = rate.get("form")
    if form == "constant":
        return float(rate.get("value") or 0), k
    if form == "proportional":
        if rate.get("stock") in index:
            k[index[rate["stock"]]] += float(rate.get("k") or 0)
        return 0.0, k
    if form == "gap":
        time = max(1e-9, float(rate.get("time") or 1))
        if rate.get("stock") in index:
            k[index[rate["stock"]]] -= 1 / time
        return float(rate.get("goal") or 0) / time, k
    if form == "linear":
        for t in rate.get("terms") or []:
            if t.get("stock") in index:
                k[index[t["stock"]]] += float(t.get("k") or 0)
        return float(rate.get("c") or 0), k
    return 0.0, k


def effect_table(e: dict) -> tuple[np.ndarray, np.ndarray]:
    """An effect as table points (a linear clamp min(hi, max(lo, x / normal)) is the table
    (lo x normal, lo), (hi x normal, hi), held beyond its ends)."""
    if e.get("shape") == "table" and e.get("points"):
        pts = sorted((float(a), float(b)) for a, b in e["points"])
        return np.array([a for a, _ in pts]), np.array([b for _, b in pts])
    lo = float(e["min"]) if e.get("min") is not None else 0.0
    hi = float(e["max"]) if e.get("max") is not None else 1.0
    normal = max(1e-9, float(e.get("normal") or 1))
    if hi <= lo:
        return np.array([0.0, 1.0]), np.array([hi, hi])
    return np.array([lo * normal, hi * normal]), np.array([lo, hi])


def _pad_table(x: np.ndarray, y: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """A table padded to n points: the extra points lie beyond the last, at its value."""
    extra = n - len(x)
    if extra <= 0:
        return x, y
    span = max(1.0, abs(x[-1]) + (x[-1] - x[0]))
    return np.concatenate([x, x[-1] + span * 1e6 * np.arange(1, extra + 1)]), np.concatenate([y, np.full(extra, y[-1])])


@dataclass
class Spec:
    """A model's structure for one run's times. Arrays are numpy; the numbers to fit are `params()`."""

    ids: list[str]
    flows: list[dict]
    src: np.ndarray                 # (F,) state index or -1
    dst: np.ndarray
    ratio: np.ndarray
    seg: np.ndarray                 # (F, T) the flow's rate group at each time index
    groups: list[list[dict]]        # per flow, the distinct rates (dicts) of its groups
    inflow: np.ndarray              # (F,) whether the flow is an outside inflow in pieces
    piece: np.ndarray               # (F, T) index into piece values (-1: none)
    piece_flow: np.ndarray          # (P,) the flow each piece belongs to
    es: np.ndarray                  # (F, E) effect stock (-1: no effect, -2: a stock not in the model)
    en: np.ndarray                  # (F, E) the table's own number of points
    ex: np.ndarray                  # (F, E, N) table x
    uses: np.ndarray                # (F, U) used stock (-1: none)
    cap: list[int]                  # stocks whose outflows and users share what they hold, in Model's order
    init: dict = field(default_factory=dict)

    @property
    def F(self) -> int:
        return len(self.src)

    @property
    def S(self) -> int:
        return len(self.ids)

    def params(self) -> dict:
        return {k: np.array(v, dtype=float) for k, v in self.init.items()}


def compile_flows(flows: list[dict], ids: list[str], times, extra_effects=None, extra_uses=None, cap_all_users: bool = False) -> Spec:
    """flows -> Spec for the times of a run (one value per time index). extra_effects / extra_uses:
    per flow, more effect tables {"stock", "x", "y"} and uses {"stock", "per"} to fit (candidates);
    cap_all_users: every stock a candidate uses shares what it holds (as it would if it were used)."""
    index = {s: i for i, s in enumerate(ids)}
    S, F = len(ids), len(flows)
    times = np.asarray(times, dtype=float)
    T = len(times)
    src = np.array([index.get(f.get("from"), -1) for f in flows])
    dst = np.array([index.get(f.get("to"), -1) for f in flows])
    ratio = np.array([float(f.get("ratio") or 1) for f in flows])
    seg = np.zeros((F, T), dtype=int)
    groups: list[list[dict]] = []
    inflow = np.zeros(F, dtype=bool)
    piece = np.full((F, T), -1)
    piece_vals, piece_flow = [], []
    for i, f in enumerate(flows):
        if f.get("byTime"):
            segs = f["byTime"]
            keys = [json.dumps(g["rate"], sort_keys=True) for g in segs]
            uniq = list(dict.fromkeys(keys))
            groups.append([segs[keys.index(u)]["rate"] for u in uniq])
            which = _Segments(segs)(times)
            seg[i] = np.array([uniq.index(k) for k in keys])[which]
        elif f.get("inflow"):
            inflow[i] = True
            groups.append([{"form": "constant", "value": 0}])
            segs = f["inflow"]
            piece[i] = len(piece_vals) + _Segments(segs)(times)
            piece_vals += [float(g["value"]) for g in segs]
            piece_flow += [i] * len(segs)
        else:
            groups.append([f.get("rate") or {}])
    G = max(len(g) for g in groups) if groups else 1
    C = np.zeros((F, G))
    K = np.zeros((F, G, S))
    for i, gs in enumerate(groups):
        for g, r in enumerate(gs):
            C[i, g], K[i, g] = rate_vector(r, index, S)

    eff = []
    for i, f in enumerate(flows):
        mine = [(index.get(e.get("stock"), -2), *effect_table(e)) for e in f.get("effects") or []]
        mine += [(index.get(e["stock"], -1), np.asarray(e["x"], float), np.asarray(e["y"], float)) for e in (extra_effects or {}).get(i, [])]
        eff.append(mine)
    E = max([len(m) for m in eff] + [1])
    N = max([len(x) for m in eff for _, x, _ in m] + [2])
    es = np.full((F, E), -1)                     # -1: no effect; -2: an effect of a stock not in the model (reads 0)
    en = np.zeros((F, E), dtype=int)
    ex = np.tile(np.array([0.0, 1.0] + [1e6 * (j + 1) for j in range(N - 2)]), (F, E, 1))
    ey = np.ones((F, E, N))
    for i, m in enumerate(eff):
        for j, (s, x, y) in enumerate(m):
            es[i, j], en[i, j] = s, len(x)
            ex[i, j], ey[i, j] = _pad_table(x, y, N)

    use = []
    for i, f in enumerate(flows):
        mine = [(index[u["stock"]], float(u["per"])) for u in f.get("uses") or [] if u.get("stock") in index and float(u.get("per") or 0) > 0]
        mine += [(index[u["stock"]], float(u["per"])) for u in (extra_uses or {}).get(i, []) if u["stock"] in index]
        use.append(mine)
    U = max([len(m) for m in use] + [1])
    us = np.full((F, U), -1)
    per = np.zeros((F, U))
    for i, m in enumerate(use):
        for j, (s, p) in enumerate(m):
            us[i, j], per[i, j] = s, p
    # the stocks whose takers share what they hold, in the order simulate.Model visits them
    fixed = [(i, index[u["stock"]], float(u["per"])) for i, f in enumerate(flows) for u in f.get("uses") or []
             if u.get("stock") in index and float(u.get("per") or 0) > 0]
    cap = list({c for _, c, _ in fixed})
    if cap_all_users:
        cap += [c for m in use for c, _ in m if c not in cap]
    init = {"C": C, "K": K, "ey": ey, "per": per, "pieces": np.array(piece_vals, dtype=float)}
    return Spec(ids=list(ids), flows=flows, src=src, dst=dst, ratio=ratio, seg=seg, groups=groups, inflow=inflow, piece=piece,
                piece_flow=np.array(piece_flow, dtype=int), es=es, en=en, ex=ex, uses=us, cap=cap, init=init)


def _floor(v, width):
    """max(0, v), or a softplus `width` wide (width > 0) so gradients pass the floor."""
    if width is None:
        return jnp.maximum(0.0, v)
    w = jnp.maximum(width, 1e-12)
    return w * jax.nn.softplus(v / w)


def _interp(x, xp, fp):
    """np.interp along the last axis of the knots: x (..., M), xp and fp (..., N)."""
    N = xp.shape[-1]
    i = jnp.clip(jnp.sum(x[..., None] > xp[..., None, :], axis=-1), 1, N - 1)
    x0 = jnp.take_along_axis(xp, i - 1, axis=-1)
    x1 = jnp.take_along_axis(xp, i, axis=-1)
    y0 = jnp.take_along_axis(fp, i - 1, axis=-1)
    y1 = jnp.take_along_axis(fp, i, axis=-1)
    w = jnp.clip((x - x0) / jnp.where(x1 > x0, x1 - x0, 1.0), 0.0, 1.0)
    return jnp.where(x <= xp[..., :1], fp[..., :1], jnp.where(x >= xp[..., -1:], fp[..., -1:], y0 + (y1 - y0) * w))


class Sim:
    """The compiled stepping function of a Spec: step(p, L, ti) -> next levels, run(p, L, t0, H)."""

    def __init__(self, spec: Spec, width: np.ndarray | None = None, ceiling: np.ndarray | None = None):
        self.spec = spec
        F, S = spec.F, spec.S
        self.fidx = jnp.arange(F)
        self.seg = jnp.asarray(spec.seg)
        self.piece = jnp.asarray(spec.piece)
        self.es = jnp.asarray(np.maximum(spec.es, 0))
        self.has_e = jnp.asarray(spec.es != -1)
        self.reads = jnp.asarray(spec.es >= 0)
        self.ex = jnp.asarray(spec.ex)
        self.us = np.asarray(spec.uses)
        D0 = np.zeros((F, S))
        for f in range(F):
            if spec.src[f] >= 0:
                D0[f, spec.src[f]] -= spec.ratio[f]
            if spec.dst[f] >= 0:
                D0[f, spec.dst[f]] += 1
        self.D0 = jnp.asarray(D0)
        U = self.us.shape[1]
        oh = np.zeros((F, U, S))
        for f in range(F):
            for j in range(U):
                if self.us[f, j] >= 0:
                    oh[f, j, self.us[f, j]] = 1
        self.use_onehot = jnp.asarray(oh)
        # per capped stock: how much of it each flow takes per unit (ratio, as a source; per, as a user), and how often
        self.cap = list(spec.cap)
        self.src_w = jnp.asarray(np.array([[spec.ratio[f] if spec.src[f] == c else 0.0 for f in range(F)] for c in self.cap]).reshape(len(self.cap), F))
        self.width = None if width is None else jnp.asarray(width)
        self.ceiling = None if ceiling is None else jnp.asarray(ceiling)[:, None]   # training only: levels held below it so a run-away stays finite

    def step(self, p: dict, L, ti):
        """L: (S, M) levels; ti: (M,) time indices of the step."""
        seg = self.seg[:, ti]                                         # (F, M)
        C = p["C"][self.fidx[:, None], seg]
        K = p["K"][self.fidx[:, None], seg]                           # (F, M, S)
        r = C + jnp.einsum("fms,sm->fm", K, L)
        r = _floor(r, None if self.width is None else self.width[:, None])
        pi = self.piece[:, ti]
        if p["pieces"].shape[0]:
            pv = jnp.maximum(0.0, p["pieces"][jnp.maximum(pi, 0)])
            r = jnp.where(pi >= 0, pv, r)
        x = jnp.where(self.reads[..., None], L[self.es], 0.0)          # (F, E, M)
        v = _interp(x, self.ex, p["ey"])
        v = _floor(v, None if self.width is None else 1e-3)
        a = r * jnp.prod(jnp.where(self.has_e[..., None], v, 1.0), axis=1)
        per = p["per"]
        for n, c in enumerate(self.cap):
            w = self.src_w[n] + jnp.sum(per * self.use_onehot[:, :, c], axis=1)          # (F,)
            count = (self.src_w[n] > 0).astype(float) + jnp.sum((self.use_onehot[:, :, c] > 0) & (per > 0), axis=1)
            want = jnp.sum(a * w[:, None], axis=0)
            k = jnp.where(want > L[c], jnp.maximum(0.0, L[c]) / jnp.where(want > 0, want, 1.0), 1.0)
            # k to the power count (a flow taking from the stock twice is scaled twice, as in Model);
            # written as products so the gradient is finite at k = 0
            cnt = count[:, None]
            a = a * jnp.where(cnt >= 1, k[None, :], 1.0) * jnp.where(cnt >= 2, k[None, :], 1.0) * jnp.where(cnt >= 3, k[None, :], 1.0)
        D = self.D0 - jnp.einsum("fu,fus->fs", per, self.use_onehot)
        nxt = L + D.T @ a
        nxt = jnp.where(nxt >= 0, nxt, 0.0)
        return nxt if self.ceiling is None else jnp.minimum(nxt, self.ceiling)

    def run(self, p: dict, L, t0, H: int, keep: bool = False):
        """H steps from levels L (S, M) whose first step is time index t0 (M,); with keep, every
        step's levels (H, S, M)."""
        def body(L, k):
            nxt = self.step(p, L, t0 + k)
            return nxt, (nxt if keep else None)
        L, traj = jax.lax.scan(body, L, jnp.arange(H))
        return traj if keep else L


def to_flows(spec: Spec, p: dict, effect_min: float = 0.0, per_min: float = 0.0) -> list[dict]:
    """The flows with the fitted numbers written back in their original forms; candidate effects
    whose table moves less than effect_min from 1, and candidate uses below per_min, are left out."""
    p = {k: np.asarray(v) for k, v in p.items()}
    ids = spec.ids
    out = []
    for i, f in enumerate(spec.flows):
        g = copy.deepcopy(f)
        if spec.inflow[i]:
            vals = p["pieces"][spec.piece_flow == i]
            g["inflow"] = [{**seg, "value": float(v)} for seg, v in zip(g["inflow"], vals)]
        else:
            rates = [_write_rate(r, p["C"][i, j], p["K"][i, j], ids) for j, r in enumerate(spec.groups[i])]
            if g.get("byTime"):
                keys = [json.dumps(s["rate"], sort_keys=True) for s in f["byTime"]]
                uniq = list(dict.fromkeys(keys))
                g["byTime"] = [{**s, "rate": rates[uniq.index(k)]} for s, k in zip(g["byTime"], keys)]
                g["rate"] = g["byTime"][0]["rate"]
            else:
                g["rate"] = rates[0]
        n0 = len(f.get("effects") or [])
        effects = []
        for j in range(spec.es.shape[1]):
            if spec.es[i, j] == -1:
                continue
            n = spec.en[i, j]
            x, y = spec.ex[i, j, :n], p["ey"][i, j, :n]
            if j >= n0 and float(np.max(np.abs(y - 1))) <= effect_min:
                continue
            if spec.es[i, j] == -2:
                effects.append(copy.deepcopy(f["effects"][j]))
                continue
            effects.append({"stock": ids[spec.es[i, j]], "shape": "table", "points": [[float(a), float(b)] for a, b in zip(x, y)]})
        if effects:
            g["effects"] = effects
        uses = [{"stock": ids[spec.uses[i, j]], "per": float(p["per"][i, j])} for j in range(spec.uses.shape[1])
                if spec.uses[i, j] >= 0 and float(p["per"][i, j]) > per_min]
        if uses:
            g["uses"] = uses
        elif "uses" in g:
            del g["uses"]
        out.append(g)
    return out


def _write_rate(r: dict, c: float, k: np.ndarray, ids: list[str]) -> dict:
    form = (r or {}).get("form")
    c = float(c)
    if form == "constant":
        return {"form": "constant", "value": c}
    if form == "proportional" and r.get("stock") in ids:
        return {"form": "proportional", "stock": r["stock"], "k": float(k[ids.index(r["stock"])])}
    if form == "gap" and r.get("stock") in ids:
        kk = float(k[ids.index(r["stock"])])
        if kk < 0:
            return {"form": "gap", "stock": r["stock"], "goal": c / -kk, "time": 1 / -kk}
        return {"form": "linear", "c": c, "terms": [{"stock": r["stock"], "k": kk}]}
    if form == "linear":
        stocks = list(dict.fromkeys(t.get("stock") for t in r.get("terms") or [] if t.get("stock") in ids))
        return {"form": "linear", "c": c, "terms": [{"stock": s, "k": float(k[ids.index(s)])} for s in stocks]}
    return copy.deepcopy(r)
