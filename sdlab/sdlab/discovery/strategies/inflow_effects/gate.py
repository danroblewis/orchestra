"""Outside inflows that carry an effect: an inflow into a stock R that is a base B(t) times a table
f(C) of a stock's level (C may be R itself), optionally using up another stock U as it arrives.

The base B(t) is either a measured input (arrivals x a gate of the queue it fills) or a schedule of
a few values the data does not announce (a planted base 10 / 20 x a table of nitrogen). Both are
bilinear in (B, f); they are fitted by alternating least squares:

- with B fixed, the table's weights (tents over C, basis.py), the numbers of the other flows that
  touch R or U (each a scale on what it moves now), R's drain, U's inflow (c + d x U) and the
  co-flow's per unit are least squares (per unit alternately with the rest);
- with f fixed, a scheduled base is re-cut: every step assigned to one of L values (Viterbi; a change
  costs `change` x log T in the rows' noise) and the values refitted, for L = 1..`levels`.

A hypothesis replaces R's (and U's) outside inflows that carry no effect (constants, pieces, links to
inputs) and keeps every other flow of the base model, rescaled. It is priced (one-step BIC; a table
costs a number per point, a schedule a number per value and per change) against the base, and taken
only if it prices better and behaves no worse than `margin` x the base on the multi-step judge.
"""

from __future__ import annotations

import math
import os
import time

import numpy as np

from ...simulate import Model, behaviour_error, levels_array
from .basis import hats, knots
from .inputs import model_inputs
from ...changes import pelt
from .pieces import _kmeans, _segments

DEFAULTS = {"gate": True, "gate_knots": [3, 4, 5, 6], "gate_levels": 4, "gate_change": 2.0, "gate_iter": 40,
            "gate_top": 8, "gate_rounds": 3, "gate_margin": 1.0, "gate_budget": 60.0, "gate_gain": 10.0, "gate_vary": 0.05}


def size(flows: list[dict]) -> int:
    """Numbers in a model: a rate's numbers, a schedule's values and changes, a table's points, a
    linear effect's one, a co-flow's per unit."""
    p = 0
    for f in flows:
        if f.get("inflow"):
            vals = {round(float(g["value"]), 9) for g in f["inflow"]}
            p += len(vals) + len(f["inflow"]) - 1
        elif f.get("byTime"):
            p += len({repr(g.get("rate")) for g in f["byTime"]}) * 1
        else:
            r = f.get("rate") or {}
            form = r.get("form")
            if form == "linear":
                p += len(r.get("terms") or []) + (1 if r.get("c") else 0)
            elif form == "gap":
                p += 2
            else:
                p += 1
        for e in f.get("effects") or []:
            p += len(e.get("points") or []) if e.get("shape") == "table" else 1
        p += len(f.get("uses") or [])
    return p


def onestep_rss(flows, ids, A, tt, mi, injections=None):
    prev = A[:, :-1]
    if injections is not None:
        prev = prev + injections
    with np.errstate(all="ignore"):
        nxt = Model(flows, ids, inputs=mi).step(prev, tt)
    nxt = np.nan_to_num(nxt, nan=1e12, posinf=1e12, neginf=-1e12)
    return ((nxt - A[:, 1:]) ** 2).sum(axis=1)


def resolution(A: np.ndarray) -> np.ndarray:
    """Each stock's reporting step: the largest 10^-d (d = 0..8) its levels are whole multiples of
    (0 if none): noise-free levels are rounded, and a fit closer than that is fitting the rounding."""
    out = np.zeros(A.shape[0])
    for i, x in enumerate(A):
        for d in range(9):
            y = x * 10.0 ** d
            if np.all(np.abs(y - np.round(y)) < 1e-6 * np.maximum(1.0, np.abs(y)) + 1e-9):
                out[i] = 10.0 ** -d
                break
    return out


def price(flows, ids, A, tt, mi, injections=None, res=None) -> float:
    """One-step BIC; a row's error is never taken below its levels' rounding (res: per stock, a
    rounded step's change errs by about res^2 / 6)."""
    T = A.shape[1] - 1
    rss = onestep_rss(flows, ids, A, tt, mi, injections)
    floor = np.full(len(rss), 1e-9) if res is None else np.maximum(1e-9, T * np.asarray(res) ** 2 / 6.0)
    return float(sum(T * math.log(max(r, fl) / T) for r, fl in zip(rss, floor)) + size(flows) * math.log(T))


def _carries_effect(f: dict) -> bool:
    return bool(f.get("effects") or f.get("uses") or f.get("byTime"))


def replaceable(f: dict, row: str, inputs: set) -> bool:
    """An outside inflow into `row` with no effect: a constant, pieces, or a link to inputs only."""
    if f.get("from") is not None or f.get("to") != row or _carries_effect(f):
        return False
    if f.get("inflow"):
        return True
    r = f.get("rate") or {}
    if r.get("form") == "constant":
        return True
    if r.get("form") == "linear":
        terms = r.get("terms") or []
        return bool(terms) and all(x.get("stock") in inputs for x in terms)
    if r.get("form") == "proportional":
        return r.get("stock") in inputs
    return False


def own_inflow(f: dict, row: str) -> bool:
    """An outside inflow into `row` reading nothing but `row` itself (and a constant): a gap."""
    if f.get("from") is not None or f.get("to") != row or _carries_effect(f) or f.get("inflow"):
        return False
    r = f.get("rate") or {}
    if r.get("form") == "gap":
        return r.get("stock") == row
    if r.get("form") == "linear":
        return all(x.get("stock") == row for x in r.get("terms") or [])
    return False


def _schedule_out(f: dict, row: str) -> bool:
    """An outflow of `row` to outside at a constant or in pieces (what a move out of it replaces)."""
    if f.get("from") != row or f.get("to") is not None or _carries_effect(f):
        return False
    return bool(f.get("inflow")) or (f.get("rate") or {}).get("form") == "constant"


def _own_drain(f: dict, row: str) -> bool:
    r = f.get("rate") or {}
    return (f.get("from") == row and f.get("to") is None and not _carries_effect(f) and not f.get("inflow")
            and r.get("form") == "proportional" and r.get("stock") == row)


def deltas(f, ids, prev, tt, mi):
    with np.errstate(all="ignore"):
        d = Model([f], ids, inputs=mi).step(prev, tt) - prev
    return np.nan_to_num(d)


def _viterbi_w(y: np.ndarray, g: np.ndarray, levels: np.ndarray, change: float) -> np.ndarray:
    """State of each step: sum over rows of (y - level x g)^2 (y, g: rows x T, already weighted)
    plus `change` per switch."""
    T, m = y.shape[1], len(levels)
    cost = ((y[:, :, None] - g[:, :, None] * levels[None, None, :]) ** 2).sum(axis=0)
    acc = cost[0].copy()
    back = np.zeros((T, m), dtype=np.int32)
    ar = np.arange(m)
    for t in range(1, T):
        best = int(np.argmin(acc))
        move = acc[best] + change
        back[t] = np.where(acc <= move, ar, best)
        acc = np.minimum(acc, move) + cost[t]
    path = np.zeros(T, dtype=np.int32)
    path[-1] = int(np.argmin(acc))
    for t in range(T - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return path


class Hypothesis:
    """One (R, C, base, U) fitted by alternating least squares."""

    def __init__(self, ids, prev, dy, tt, mi, xin_names, xin, base_flows, r, c, kind, u, o, sigma, move=False):
        self.ids, self.prev, self.dy, self.tt, self.mi = ids, prev, dy, tt, mi
        self.idx = {s: i for i, s in enumerate(ids)}
        self.r, self.c, self.kind, self.u, self.o = r, c, kind, u, o
        self.move = bool(move and u)          # the flow runs from U (per unit 1), not from outside
        self.base_flows = base_flows
        inputs = set(xin_names)
        # R's inflows without effects; for a used stock, its schedule-like inflows (constants, pieces)
        # and its gap, which c + d x U stands in for (its links to inputs stay)
        self.removed = [f for f in base_flows if replaceable(f, r, inputs)
                        or (u is not None and not self.move and (replaceable(f, u, set()) or own_inflow(f, u)))
                        or (self.move and _schedule_out(f, u))]
        rem = {id(f) for f in self.removed}
        rows = {r} | ({u} if u else set())
        between = {r, u} if u else set()
        # moves between R and U (the co-flow's stand-ins) and U's own drain (one with U's new inflow
        # c + d x U) go
        self.dropped = [f for f in base_flows if id(f) not in rem and between and o.get("gate_drop_between", True)
                        and ({f.get("from"), f.get("to")} == between or (not self.move and _own_drain(f, u)))]
        rem |= {id(f) for f in self.dropped}
        self.kept = [f for f in base_flows if id(f) not in rem and (f.get("from") in rows or f.get("to") in rows
                                                                   or any(x.get("stock") in rows for x in f.get("uses") or []))]
        self.rest = [f for f in base_flows if id(f) not in rem and not any(f is k for k in self.kept)]
        self.rows = [r] + ([u] if u else [])
        ri = [self.idx[x] for x in self.rows]
        self.ri = ri
        self.Y = dy[ri]                                            # rows x T
        self.W = np.array([1.0 / max(1e-9, sigma[i]) for i in ri])  # row weights
        self.D = [deltas(f, ids, prev, tt, mi)[ri] for f in self.kept]   # each rows x T
        T = prev.shape[1]
        self.T = T
        # R's drain unless a kept flow already drains R in proportion to it
        has_drain = any(f.get("from") == r and f.get("to") is None and (f.get("rate") or {}).get("form") == "proportional"
                        and (f.get("rate") or {}).get("stock") == r and not f.get("effects") for f in self.kept)
        self.extra = []                                             # (name, rows x T column)
        if not has_drain:
            col = np.zeros((len(ri), T))
            col[0] = -prev[self.idx[r]]
            self.extra.append(("drain", col))
        # U's inflow c + d x U stands in for the outside inflows into U it replaces (none: none)
        if u and any(f.get("to") == u for f in self.removed):
            one = np.zeros((len(ri), T))
            one[1] = 1.0
            lvl = np.zeros((len(ri), T))
            lvl[1] = prev[self.idx[u]]
            self.extra += [("u_c", one), ("u_k", lvl)]
        self.base = xin[xin_names.index(kind)] if kind != "pieces" else None
        self.ok = True

    def start_B(self) -> np.ndarray:
        """What flows into R in the base model (outside inflows and moves into it, effects aside),
        re-cut into a few values: the schedule as if the curve were flat."""
        g = np.zeros(self.T)
        for f in self.base_flows:
            if f.get("to") == self.r and not f.get("effects"):
                g += deltas(f, self.ids, self.prev, self.tt, self.mi)[self.idx[self.r]]
        g = np.maximum(g, 0.0)
        if g.max() <= 1e-12:
            return np.ones(self.T)
        s2 = max(1e-12, float(np.var(np.diff(g))) / 2)
        best = None
        for nl in range(1, self.o["gate_levels"] + 1):
            lv = _kmeans(g, np.ones(self.T), nl)
            pth = _viterbi_w(g[None, :], np.ones((1, self.T)), lv, self.o["gate_change"] * s2 * math.log(self.T))
            used = np.unique(pth)
            pth = np.searchsorted(used, pth)
            lv = np.array([float(g[pth == m].mean()) for m in range(len(used))])
            r2 = float(((g - lv[pth]) ** 2).sum())
            nch = int(np.sum(pth[1:] != pth[:-1]))
            bic = self.T * math.log(max(r2, 1e-12) / self.T) + (len(lv) + nch) * math.log(self.T) * self.o["gate_change"]
            if best is None or bic < best[0]:
                best = (bic, lv[pth])
        return best[1]

    def _fit_linear(self, B, kn, p):
        """Least squares of every number but the base's schedule and the per unit, given them."""
        H = hats(self.prev[self.idx[self.c]], kn)                   # K x T
        K = len(kn)
        sgn = np.array([1.0] + ([-p] if self.u else []))
        cols = [sgn[:, None] * (B * H[j])[None, :] for j in range(K)]
        cols += self.D + [col for _, col in self.extra]
        X = np.stack([(self.W[:, None] * c).ravel() for c in cols], axis=1)
        y = (self.W[:, None] * self.Y).ravel()
        theta = np.linalg.lstsq(X, y, rcond=None)[0]
        return theta, H

    def _parts(self, theta, B, H, p):
        """(the effect's series V, everything else per row) for these numbers."""
        K = H.shape[0]
        V = B * (theta[:K] @ H)
        others = np.zeros_like(self.Y)
        for j, D in enumerate(self.D):
            others += theta[K + j] * D
        for j, (_, col) in enumerate(self.extra):
            others += theta[K + len(self.D) + j] * col
        return V, others

    def _rss(self, V, others, p) -> float:
        pred = others + np.vstack([V] + ([-p * V] if self.u else []))
        return float((((self.Y - pred) * self.W[:, None]) ** 2).sum())

    def _alternate(self, kn, B, p, labels=None, iters=None):
        """Alternating least squares from (B, p): the linear numbers, then the per unit, then (with
        `labels`, a value index per step) the schedule's values. The best numbers seen."""
        best = None
        for it in range(iters or self.o["gate_iter"]):
            try:
                theta, H = self._fit_linear(B, kn, p)
            except np.linalg.LinAlgError:
                return best
            V, others = self._parts(theta, B, H, p)
            rss = self._rss(V, others, p)
            improved = best is None or rss < best["rss"] * (1 - 1e-7)
            if best is None or rss < best["rss"]:
                best = {"rss": rss, "theta": theta.copy(), "p": p, "B": np.array(B, dtype=float), "kn": kn,
                        "labels": None if labels is None else labels.copy()}
            if not improved and it > 1:
                break
            if self.u and not self.move:
                vv = float(V @ V)
                p = max(0.0, float(-((self.Y[1] - others[1]) @ V) / vv)) if vv > 1e-12 else 0.0
            if labels is None:
                if not self.u or self.move:
                    break
                continue
            f = theta[: H.shape[0]] @ H
            y = (self.Y - others) * self.W[:, None]
            g = np.vstack([f] + ([-p * f] if self.u else [])) * self.W[:, None]
            num = (y * g).sum(axis=0)
            den = (g ** 2).sum(axis=0)
            m = int(labels.max()) + 1
            lv = np.bincount(labels, num, m) / np.maximum(1e-12, np.bincount(labels, den, m))
            lv = lv / max(1e-12, float(np.mean(np.abs(lv[labels]))))
            B = lv[labels]
        return best

    def fit(self, kn, init_B=None, init_p=None):
        """The hypothesis fitted: a measured base as it is; a schedule first as free values between
        the changes PELT finds in R's row (from `init_B` or the base's inflows into R), then pooled
        into 1..`gate_levels` values, the count by BIC."""
        _o, _T = self.o, self.T
        init_p = (1.0 if self.move else 0.0) if init_p is None else init_p
        if self.kind != "pieces":
            r = self._alternate(kn, self.base, float(init_p))
            self.result = self.polish(r) if r is not None else r
            return self.result
        B0 = self.start_B() if init_B is None else np.asarray(init_B, dtype=float)
        B0 = B0 / max(1e-12, float(np.mean(np.abs(B0))))
        best = self._fit_cuts(kn, B0, float(init_p), self.cuts())
        if best is None:
            self.result = None
            return None
        r = best[1]
        lab = r["labels"]
        lv = np.array([float(r["B"][lab == m][0]) for m in range(int(lab.max()) + 1)])
        r["path"], r["levels"] = lab, lv
        self.result = r
        return r

    def _fit_cuts(self, kn, B0, p0, cuts):
        """(BIC, fit) with the schedule changing only at `cuts`: free values between them first, then
        pooled into 1..`gate_levels` values, the count by BIC."""
        o, T = self.o, self.T
        seg = np.zeros(T, dtype=np.int64)
        for q, (a, b) in enumerate(zip(cuts[:-1], cuts[1:])):
            seg[a:b] = q
        first = self._alternate(kn, B0, p0, labels=seg)
        if first is None:
            return None
        vals = np.array([float(first["B"][seg == q].mean()) for q in range(int(seg.max()) + 1)])
        lens = np.bincount(seg).astype(float)
        best = None
        log_t = math.log(T)
        for nl in range(1, o["gate_levels"] + 1):
            lv = _kmeans(vals, lens, nl)
            lab = np.argmin(np.abs(vals[:, None] - lv[None, :]), axis=1)
            used = np.unique(lab)
            lab = np.searchsorted(used, lab)
            labels = lab[seg]
            B = lv[used][lab][seg]
            r = self._alternate(kn, B, first["p"], labels=labels)
            if r is None:
                continue
            r = self.polish(r)
            nch = int(np.sum(labels[1:] != labels[:-1]))
            bic = T * math.log(max(r["rss"], 1e-12) / T) + (len(used) + nch) * log_t
            if best is None or bic < best[0]:
                best = (bic, r)
        return best

    def polish(self, r: dict) -> dict:
        """Every number at once (the schedule's values but the first, the table, the other flows'
        scales, the per unit) by nonlinear least squares from the alternating fit: alternation
        crawls along the ridge where the schedule and the curve trade."""
        from scipy.optimize import least_squares

        kn = r["kn"]
        H = hats(self.prev[self.idx[self.c]], kn)
        K = len(kn)
        lab = r.get("labels")
        if lab is None:
            lv0 = np.zeros(0)
        else:
            lv0 = np.array([float(r["B"][lab == m][0]) for m in range(int(lab.max()) + 1)])
        nth = len(r["theta"])
        Ds = np.stack(self.D + [c for _, c in self.extra]) if (self.D or self.extra) else np.zeros((0,) + self.Y.shape)

        def unpack(x):
            lv = np.concatenate([lv0[:1], x[: max(0, len(lv0) - 1)]]) if len(lv0) else lv0
            o = max(0, len(lv0) - 1)
            th = x[o:o + nth]
            p = (1.0 if self.move else x[o + nth]) if self.u else 0.0
            return lv, th, p

        def resid(x):
            lv, th, p = unpack(x)
            B = lv[lab] if lab is not None else self.base
            V = B * (th[:K] @ H)
            pred = np.tensordot(th[K:], Ds, axes=1) if len(Ds) else np.zeros_like(self.Y)
            pred = pred + np.vstack([V] + ([-p * V] if self.u else []))
            return ((self.Y - pred) * self.W[:, None]).ravel()

        nrow = self.Y.shape[0]
        sg = np.array([1.0] + ([-1.0] if self.u else []))
        if lab is not None:
            onehot = (lab[None, :] == np.arange(1, len(lv0))[:, None]).astype(float)   # (L-1) x T

        def jac(x):
            lv, th, p = unpack(x)
            B = lv[lab] if lab is not None else self.base
            f = th[:K] @ H
            mult = np.array([1.0] + ([-p] if self.u else []))           # per row
            cols = []
            if lab is not None:
                for m in range(len(lv0) - 1):
                    cols.append(mult[:, None] * (onehot[m] * f)[None, :])
            for j in range(K):
                cols.append(mult[:, None] * (B * H[j])[None, :])
            for i in range(len(Ds)):
                cols.append(Ds[i])
            if self.u and not self.move:
                c = np.zeros_like(self.Y)
                c[1] = -(B * f)
                cols.append(c)
            Jm = np.stack([(-(self.W[:, None]) * c).ravel() for c in cols], axis=1)
            return Jm

        x0 = np.concatenate([lv0[1:], r["theta"], [r["p"]] if (self.u and not self.move) else []])
        del sg, nrow
        try:
            sol = least_squares(resid, x0, jac=jac, method="lm", max_nfev=100)
        except Exception:                                          # noqa: BLE001
            return r
        rss = float(sol.fun @ sol.fun)
        if not rss < r["rss"]:
            return r
        lv, th, p = unpack(sol.x)
        out = {**r, "rss": rss, "theta": np.asarray(th), "p": float(max(0.0, p))}
        if self.move:
            out["p"] = 1.0
        if lab is not None:
            out["B"], out["levels"], out["path"] = lv[lab], lv, lab
        return out

    def recut(self) -> list[int] | None:
        """The cuts again from the fitted schedule read off both rows (the curve divided out): a
        step's value is clean once the curve is known. None if they are the same."""
        r = self.result
        if r is None or r.get("labels") is None:
            return None
        kn = r["kn"]
        H = hats(self.prev[self.idx[self.c]], kn)
        _, others = self._parts(r["theta"], r["B"], H, r["p"])
        f = r["theta"][: len(kn)] @ H
        g = np.vstack([f] + ([-r["p"] * f] if self.u else [])) * self.W[:, None]
        yy = (self.Y - others) * self.W[:, None]
        den = (g ** 2).sum(axis=0)
        z = np.where(den > 1e-12, (yy * g).sum(axis=0) / np.where(den > 1e-12, den, 1.0), 0.0)
        c2 = pelt(z, 5, self.o["gate_change"])
        return None if c2 == self.cuts() else c2

    def cuts(self) -> list[int]:
        """Where R's inflow changes before the curve is known: R's row with a drain at rate k added
        back (dy + k x R, the inflow if k is R's drain), for k on a grid; PELT on each, and the k
        whose pieces cost least. A stock that settles fast after a change shows it in its level, not
        its change, so the drain must be added back first."""
        if getattr(self, "_cuts", None) is not None:
            return self._cuts
        y, x = self.Y[0], self.prev[self.idx[self.r]]
        best = None
        T = len(y)
        seen = set()
        for k in [0.0] + list(np.geomspace(0.003, 1.0, 24)):
            c = pelt(y + k * x, 5, self.o["gate_change"])
            if tuple(c) in seen:
                continue
            seen.add(tuple(c))
            # judged on R's own row: its change on its level and a value per piece
            X = np.zeros((T, len(c)))
            X[:, 0] = x
            for q, (a, b) in enumerate(zip(c[:-1], c[1:])):
                X[a:b, q + 1] = 1.0
            res = y - X @ np.linalg.lstsq(X, y, rcond=None)[0]
            cost = T * math.log(max(float(res @ res), 1e-12) / T) + (2 * (len(c) - 2) + 1) * math.log(T)
            if best is None or cost < best[0]:
                best = (cost, c)
        self._cuts = best[1]
        return self._cuts

    def flows(self) -> list[dict] | None:
        b = self.result
        if b is None:
            return None
        kn = b["kn"]
        K = len(kn)
        th = b["theta"]
        w = th[:K]
        cl = self.prev[self.idx[self.c]]
        ref = float(np.interp(float(np.mean(cl)), kn, w))
        if not np.isfinite(ref) or ref <= 1e-9:
            return None
        wn = w / ref
        fv = wn @ hats(cl, kn)
        if np.mean(fv > -1e-6) < 0.95:
            return None                                             # a rate cannot be negative
        lo, hi = np.percentile(fv, [2, 98])
        if hi - lo < self.o["gate_vary"]:
            return None                                             # a flat curve is no effect
        eff = {"stock": self.c, "shape": "table", "points": [[float(x), float(max(0.0, y))] for x, y in zip(kn, wn)]}
        new = {"from": None, "to": self.r, "ratio": 1, "driver": self.c, "effects": [eff]}
        if self.kind == "pieces":
            levels = b["levels"] * ref
            if np.any(levels < -1e-9):
                return None
            segs = _segments(b["path"], self.tt, np.maximum(0.0, levels))
            for g in segs:
                g.pop("pool", None)
            mean = float(np.mean(levels[b["path"]]))
            new.update(rate={"form": "constant", "value": mean}, inflow=segs)
            new["rates"] = [new["rate"]]
        else:
            rate = {"form": "linear", "c": 0, "terms": [{"stock": self.kind, "k": float(ref)}]}
            new.update(rate=rate, rates=[rate], input=self.kind)
        if self.move:
            new["from"] = self.u
        elif self.u and b["p"] > 1e-9:
            new["uses"] = [{"stock": self.u, "per": float(b["p"])}]
        out = list(self.rest)
        for j, f in enumerate(self.kept):
            s = float(th[K + j])
            if s <= 1e-6:
                continue
            g = _scaled(f, s)
            if g is not None:
                out.append(g)
        names = [n for n, _ in self.extra]
        vals = th[K + len(self.D):]
        ex = dict(zip(names, vals))
        if ex.get("drain", 0) > 1e-9:
            out.append({"from": self.r, "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": self.r, "k": float(ex["drain"])}})
        if self.u and ("u_c" in ex):
            cc, kk = float(ex["u_c"]), float(ex["u_k"])
            if abs(cc) > 1e-9 or abs(kk) > 1e-9:
                rate = {"form": "linear", "c": cc, "terms": [{"stock": self.u, "k": kk}]} if abs(kk) > 1e-12 else {"form": "constant", "value": cc}
                out.append({"from": None, "to": self.u, "ratio": 1, "rate": rate, "rates": [rate]})
        out.append(new)
        return out


def _negative(flows, ids, prev, tt, mi) -> bool:
    """A flow (without effects) that runs backwards on more than 5% of the steps: an outside inflow
    c + d x U that turns negative, a link with a negative number."""
    idx = {s: i for i, s in enumerate(ids)}
    for f in flows:
        row = f.get("to") if f.get("to") is not None else f.get("from")
        if row not in idx or f.get("inflow"):
            continue
        d = deltas(f, ids, prev, tt, mi)[idx[row]]
        if f.get("to") is None:
            d = -d
        scale = max(1e-9, float(np.mean(np.abs(d))))
        if np.mean(d < -1e-6 * scale) > 0.05:
            return True
    return False


def _assign(y, g, levels):
    cost = ((y[:, :, None] - g[:, :, None] * levels[None, None, :]) ** 2).sum(axis=0)
    return np.argmin(cost, axis=1)


def _scaled(f: dict, s: float) -> dict | None:
    """A flow with what it moves scaled by s."""
    g = dict(f)
    if f.get("inflow"):
        g["inflow"] = [{**x, "value": float(x["value"]) * s} for x in f["inflow"]]
        return g
    if f.get("byTime"):
        return None if abs(s - 1) > 1e-6 else g

    def sc(r):
        r = dict(r)
        form = r.get("form")
        if form == "constant":
            r["value"] = float(r["value"]) * s
        elif form == "proportional":
            r["k"] = float(r["k"]) * s
        elif form == "linear":
            r["c"] = float(r.get("c") or 0) * s
            r["terms"] = [{**x, "k": float(x["k"]) * s} for x in r.get("terms") or []]
        else:
            return None
        return r
    r = sc(f.get("rate") or {})
    if r is None:
        return None if abs(s - 1) > 1e-6 else g
    g["rate"], g["rates"] = r, [r]
    return g


def search(flows: list[dict], stocks: list[dict], run: dict, opts: dict, o: dict) -> tuple[list[dict], list[str]]:
    """The base flows, or a better-priced model with outside inflows that carry effects."""
    o = {**DEFAULTS, **o}
    notes: list[str] = []
    if not o["gate"] or not flows:
        return flows, notes
    t0 = time.perf_counter()
    ids = [s["id"] for s in stocks]
    A = levels_array(run["levels"], ids)
    tt = np.asarray(run["t"], dtype=float)[1:]
    T = A.shape[1] - 1
    if T < 60:
        return flows, notes
    inj = None
    if opts.get("injections"):
        from ...matrix import injected
        inj = injected(opts["injections"], ids, run["t"])[:, 1:]
    prev = A[:, :-1] + (inj if inj is not None else 0)
    dy = A[:, 1:] - prev
    mi = model_inputs(opts.get("inputs"), ids, run["t"])
    res = resolution(A)
    from .inputs import rows as input_rows
    xin_names, xin = input_rows(opts.get("inputs"), ids, T)
    final = {s["id"] for s in stocks if s.get("final")}
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    moving = [s for s in ids if np.ptp(prev[ids.index(s)]) > 1e-9 * max(1.0, float(np.max(np.abs(prev[ids.index(s)]))))]

    def judge(fl):
        hs = [h for h in (5, 20, 100) if h < len(run["t"]) / 4]
        try:
            return sum(behaviour_error(fl, ids, run["t"], run["levels"], horizon=h, injections=opts.get("injections"),
                                       inputs=opts.get("inputs") or None) for h in hs) / len(hs)
        except Exception:                                          # noqa: BLE001
            return float("inf")

    cur = flows
    cur_p = price(cur, ids, A, tt, mi, inj, res)
    base_e = judge(cur)
    chain: list = []
    log_t = math.log(T)
    done_rows: set = set()
    for _round in range(o["gate_rounds"]):
        rss = onestep_rss(cur, ids, A, tt, mi, inj)
        sigma = np.sqrt(np.maximum(rss / T, 1e-12))
        # stage 1: (R, C, base) without a used stock, ranked by the price of R's row
        set(xin_names)
        scored = []
        # the screen: one knot count, knots where they fall, a few rounds
        quick = {**o, "gate_knots": [o["gate_knots"][len(o["gate_knots"]) // 2]], "gate_refine": False, "gate_iter": 15}
        for r in ids:
            if r not in moving:
                continue
            if r in done_rows:
                continue
            # a schedule may stand where the base has outside inflows or moves into R
            kinds = ["pieces"] if any(f.get("to") == r and not f.get("effects") for f in cur) else []
            kinds += list(xin_names)
            for kind in kinds:
                for c in moving:
                    if time.perf_counter() - t0 > o["gate_budget"]:
                        break
                    h = Hypothesis(ids, prev, dy, tt, mi, xin_names, xin, cur, r, c, kind, None, quick, sigma)
                    fit = _best_knots(h, quick)
                    if fit is None:
                        continue
                    # R's row against the base's (weighted by the base's noise: T per row)
                    sc = _bic(h, fit)
                    scored.append((sc, r, c, kind, None))
                    if os.environ.get("SDLAB_GATE_DEBUG"):
                        print(f"gate screen: {kind} x f({c}) -> {r}: {sc:.0f}")
        scored.sort(key=lambda x: x[0])
        # the best two of each row, best first
        per_row: dict = {}
        top = []
        for x in scored:
            if per_row.get(x[1], 0) < 2:
                per_row[x[1]] = per_row.get(x[1], 0) + 1
                top.append(x)
        best = None
        for _sc, r, c, kind, _fl in top[: o["gate_top"]]:
            cands = []
            for u, move in [(None, False)] + [(u, m) for u in ids for m in (False, True)]:
                if u is not None and (u == r or u not in moving or (u in final and not move)):
                    continue
                if move and unit.get(u) != unit.get(r):
                    continue
                if time.perf_counter() - t0 > o["gate_budget"]:
                    break
                h = Hypothesis(ids, prev, dy, tt, mi, xin_names, xin, cur, r, c, kind, u, o, sigma, move=move)
                if _best_knots(h, o) is None:
                    continue
                fu = h.flows()
                if fu is None or _negative(fu, ids, prev, tt, mi):
                    continue
                fu = _prune(fu, ids, A, tt, mi, inj, res)
                how = (f" from {u}" if move else f" using {u}") if u else ""
                cands.append((price(fu, ids, A, tt, mi, inj, res), fu, how))
            if os.environ.get("SDLAB_GATE_DEBUG"):
                for pc, fc, how in cands:
                    print(f"gate: {kind} x f({c}) -> {r}{how}: price {pc:.0f} (base {cur_p:.0f})")
            for pc, fc, how in cands:
                if best is None or pc < best[0]:
                    best = (pc, fc, f"{kind} x f({c}) -> {r}{how}", r)
        if best is None or not best[0] < cur_p - o["gate_gain"] * log_t:
            break
        fl = best[1]
        e = judge(fl)
        notes.append(f"{best[2]}: price {best[0]:.0f} vs {cur_p:.0f}, judge {e:.3g} vs {base_e:.3g}")
        # rounds go on by price (one effect may only behave once the next is in); the model returned
        # is the round that behaves best, if no worse than `gate_margin` x the base
        cur, cur_p = fl, price(fl, ids, A, tt, mi, inj, res)
        chain.append((e, cur))
        done_rows.add(best[3])
    ok = [(e, fl) for e, fl in chain if e <= o["gate_margin"] * base_e]
    if not ok:
        return flows, notes
    return min(ok, key=lambda x: x[0])[1], notes


def _rss_linear(h: Hypothesis, B, kn, p) -> float:
    try:
        theta, H = h._fit_linear(B, kn, p)
    except np.linalg.LinAlgError:
        return float("inf")
    K = len(kn)
    V = B * (theta[:K] @ H)
    pred = np.vstack([V] + ([-p * V] if h.u else []))
    for j, D in enumerate(h.D):
        pred = pred + theta[K + j] * D
    for j, (_, col) in enumerate(h.extra):
        pred = pred + theta[K + len(h.D) + j] * col
    return float((((h.Y - pred) * h.W[:, None]) ** 2).sum())


def refine_knots(h: Hypothesis, o: dict):
    """The table's inner knots moved where the curve bends (each over a grid between its
    neighbours, the base and per unit held), then the whole hypothesis refitted from there."""
    b = h.result
    if b is None:
        return None
    kn = np.array(b["kn"], dtype=float)
    B, p = b["B"], b["p"]
    best = _rss_linear(h, B, kn, p)
    for _ in range(2):
        for j in range(1, len(kn) - 1):
            lo, hi = kn[j - 1], kn[j + 1]
            for x in np.linspace(lo, hi, 17)[1:-1]:
                trial = kn.copy()
                trial[j] = x
                r = _rss_linear(h, B, trial, p)
                if r < best:
                    best, kn = r, trial
    keep = h.result
    nb = h.fit(kn, init_B=B if h.kind == "pieces" else None)
    if nb is None or nb["rss"] > keep["rss"] * (1 + 1e-9) and nb["rss"] > best * (1 + 1e-6):
        h.result = keep
    return h.result


def _knots_fit(h: Hypothesis, o: dict):
    best = None
    for k in o["gate_knots"]:
        kn = knots(h.prev[h.idx[h.c]], k)
        b = h.fit(kn)
        if b is None:
            continue
        nb = _bic(h, b)
        if best is None or nb < best[0]:
            best = (nb, b)
    if best is None:
        return None
    h.result = best[1]
    if o.get("gate_refine", True) and len(best[1]["kn"]) > 2:
        refine_knots(h, o)
    return h.result


def _bic(h: Hypothesis, b: dict) -> float:
    T = h.T
    n = len(b["theta"]) + (1 if (h.u and not h.move) else 0)
    if b.get("labels") is not None:
        lab = b["labels"]
        n += int(lab.max()) + 1 + int(np.sum(lab[1:] != lab[:-1]))
    return T * math.log(max(b["rss"], 1e-12) / T) + n * math.log(T)


def _best_knots(h: Hypothesis, o: dict):
    """The knot count by BIC (inner knots then moved where the curve bends); for a schedule, again
    with the cuts read off that fit, the better kept."""
    r = _knots_fit(h, o)
    if r is None or h.kind != "pieces":
        return r
    for _ in range(2):
        c2 = h.recut()
        if c2 is None:
            break
        old_cuts, old = h._cuts, h.result
        h._cuts = c2
        r2 = _knots_fit(h, o)
        if r2 is None or not _bic(h, r2) < _bic(h, old):
            h._cuts, h.result = old_cuts, old
            break
    return h.result


def _prune(flows, ids, A, tt, mi, inj, res=None):
    """Flows dropped one at a time while the price falls (numbers not refitted: a flow the new
    inflow made redundant has a small scale)."""
    cur = flows
    p = price(cur, ids, A, tt, mi, inj, res)
    while len(cur) > 1:
        trial = None
        for i in range(len(cur)):
            if cur[i].get("effects") and cur[i].get("driver"):
                continue
            fl = cur[:i] + cur[i + 1:]
            q = price(fl, ids, A, tt, mi, inj, res)
            if q < p and (trial is None or q < trial[0]):
                trial = (q, fl)
        if trial is None:
            break
        p, cur = trial
    return cur
