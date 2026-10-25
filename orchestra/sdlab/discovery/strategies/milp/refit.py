"""The chosen structure's numbers refitted by least squares on every step (the program's misfit is
absolute, reads a sample of the steps, and a MIN's threshold on a grid), and what the refitted model
leaves and moves per step."""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares
from scipy.stats import norm

from . import counter
from .program import Column
from .steps import Steps


class Structure:
    """Parts with one number v: ("term", src, dst, reader) at v x reader; ("neg", src, dst, reader) at
    -v x reader (a goal gap's own level); ("era", src, dst, reader, e) at v x reader in era e only (an
    era's signed change of that term); ("piece", None, dst, None, k) a signed step of an estimated
    inflow's constant from step k on (an unannounced change). And ("min", src, dst, cap) with two (a, b): MIN(a x src, b x cap)."""

    def __init__(self, st: Steps, chosen: list[tuple[Column, float]]):
        self.st = st
        self.parts, theta, lo, hi = [], [], [], []
        for c, v in chosen:
            if c.what[0] == "min":
                self.parts.append(("min", c.src, c.dst, c.what[1]))
                theta += [v, v * c.what[2]]
                lo += [0.0, 0.0]
                hi += [1.0, np.inf]
            else:
                self.parts.append((c.what[0], c.src, c.dst) + tuple(c.what[1:]))
                theta.append(v)
                lo.append(-c.ub if c.signed else 0.0)
                hi.append(c.ub)
        self.theta, self.lo, self.hi = np.array(theta, dtype=float), np.array(lo, dtype=float), np.array(hi, dtype=float)
        self.pos = {s: i for i, s in enumerate(st.ids)}

    def key(self) -> tuple:
        return tuple(sorted(self.parts, key=str))

    def numbers(self) -> list[tuple[tuple, list[float]]]:
        out, o = [], 0
        for p in self.parts:
            k = 2 if p[0] == "min" else 1
            out.append((p, [float(v) for v in self.theta[o:o + k]]))
            o += k
        return out

    def series(self, p: tuple) -> np.ndarray:
        """What a one-number part's number multiplies at every step."""
        x = self.st.series(p[3])
        if p[0] == "neg":
            return -x
        if p[0] == "era":
            return x * (self.st.era == p[4])
        if p[0] == "piece":
            return x * (np.arange(self.st.T) >= p[4])
        return x

    def amounts(self, theta: np.ndarray) -> list[tuple[str | None, str | None, np.ndarray]]:
        out, o = [], 0
        for p in self.parts:
            if p[0] == "min":
                out.append((p[1], p[2], np.minimum(theta[o] * self.st.series(p[1]), theta[o + 1] * self.st.series(p[3]))))
                o += 2
                continue
            out.append((p[1], p[2], theta[o] * self.series(p)))
            o += 1
        return out

    def factors(self, out: list) -> list:
        """Per part, the share of its amount that moves (1 unless counts; see capped)."""
        fs = [None] * len(out)
        if self.st.counts:
            for src in {a[0] for a in out if a[0] in self.pos}:
                idx = [k for k, a in enumerate(out) if a[0] == src]
                D = sum(out[k][2] for k in idx)
                L = self.st.L[self.pos[src]]
                sd = np.sqrt(np.maximum(D, 1e-9))
                z = (L - D) / sd
                loss = sd * norm.pdf(z) - (L - D) * norm.sf(z)          # E[(N - L)+]
                f = np.where(D > 1e-9, np.clip((D - loss) / np.maximum(D, 1e-9), 0.0, 1.0), 1.0)
                for k in idx:
                    fs[k] = f
        return fs

    def capped(self, theta: np.ndarray) -> list[tuple[str | None, str | None, np.ndarray]]:
        """The amounts, for counts data as the expected amounts when whole things move: a stock's
        outflows drawn Poisson around their rates share what it holds (nothing leaves a stock that is not
        there), so a stock drained near its level loses on average E[min(N, level)] with N ~ Poisson(the
        total rate), less than the total rate (normal approximation of the Poisson tail)."""
        out = self.amounts(theta)
        return [(a[0], a[1], a[2] if f is None else a[2] * f) for a, f in zip(out, self.factors(out))]

    def jac(self, theta: np.ndarray, scale: np.ndarray) -> np.ndarray:
        """d residual / d numbers ((stocks x steps) x numbers), the counts share held fixed."""
        out = self.amounts(theta)
        fs = self.factors(out)
        J = np.zeros((self.st.dy.size, len(theta)))
        T = self.st.T
        o = 0
        for p, f in zip(self.parts, fs):
            cols = []
            if p[0] == "min":
                x, y = self.st.series(p[1]), self.st.series(p[3])
                own = theta[o] * x <= theta[o + 1] * y
                cols = [np.where(own, x, 0.0), np.where(own, 0.0, y)]
            else:
                cols = [self.series(p)]
            for g in cols:
                g = g if f is None else g * f
                for end, sign in ((p[1], 1.0), (p[2], -1.0)):        # residual = dy - change: a source's change is -amount
                    if end in self.pos:
                        i = self.pos[end]
                        J[i * T:(i + 1) * T, o] += sign * g / scale[i]
                o += 1
        for i, sd in self.st.level_rows.items():                       # a level row: the cumulative change, its start profiled
            blk = np.cumsum(J[i * T:(i + 1) * T] * scale[i][:, None], axis=0)
            w = 1.0 / sd ** 2
            blk -= (w @ blk) / w.sum()
            J[i * T:(i + 1) * T] = blk / sd[:, None]
        return J

    def resid(self, theta: np.ndarray | None, scale: np.ndarray) -> np.ndarray:
        """Per stock and step, the weighted misfit: of the one-step change (per scale), or for a stock with a
        level row (Steps.level_rows: a counter whose levels carry measurement error) of its level less a
        free start (per the level's noise sd), the start profiled out (weighted mean)."""
        e = (self.st.dy - self.change(theta)) / scale
        for i, sd in self.st.level_rows.items():
            r = np.cumsum(e[i] * scale[i])
            w = 1.0 / sd ** 2
            e[i] = (r - (w @ r) / w.sum()) / sd
        return e

    def row_scale(self, scale: np.ndarray) -> np.ndarray:
        """The noise scale each row is weighed by (a level row's own sd)."""
        if not self.st.level_rows:
            return scale
        sc = np.array(scale, dtype=float, copy=True)
        for i, sd in self.st.level_rows.items():
            sc[i] = sd
        return sc

    def change(self, theta: np.ndarray | None = None) -> np.ndarray:
        d = np.zeros_like(self.st.dy)
        for src, dst, amt in self.capped(self.theta if theta is None else theta):
            if src in self.pos:
                d[self.pos[src]] -= amt
            if dst in self.pos:
                d[self.pos[dst]] += amt
        return d

    def gross(self) -> np.ndarray:
        """Per stock and step, the amount moved in or out of it (a count's scatter grows with it). (k8s-315,
        net-gross) A flow's amount is the sum of its parts before its size is taken: two terms of one flow
        that cancel (+0.008 x one counter - 0.016 x another, each ~1800 a step) move next to nothing, and
        counting each one's size made the stock's scatter flat and huge, so its own weights favoured them."""
        g = np.zeros_like(self.st.dy)
        net: dict = {}
        for src, dst, amt in self.amounts(self.theta):
            net[(src, dst)] = net.get((src, dst), 0.0) + amt
        for (src, dst), amt in net.items():
            for e in (src, dst):
                if e in self.pos:
                    g[self.pos[e]] += np.abs(amt)
        return g

    def thetas(self) -> dict:
        """Each MIN's refitted threshold b / a, keyed (src, dst, cap)."""
        return {(p[1], p[2], p[3]): v[1] / v[0] for p, v in self.numbers() if p[0] == "min" and v[0] > 0}

    def _drains(self) -> list[list[int]]:
        """Per stock, the positions of the numbers of its drains proportional to itself."""
        out, o = {}, 0
        for p in self.parts:
            if p[0] == "term" and p[1] is not None and p[3] == p[1]:
                out.setdefault(p[1], []).append(o)
            o += 2 if p[0] == "min" else 1
        return [v for v in out.values() if len(v) > 1]

    def blocks(self) -> list[tuple[list[int], list[int]]]:
        """(k8s-317, block refit) The structure's independent blocks: (part positions, stock rows). Parts
        that share a measured stock (an end) are in one block; a reader is data and couples nothing. Every
        residual row, its counts share (a source's outflows: one row), its level row and its drain penalty
        (one stock) lie inside one block, so the least squares separates exactly into them."""
        parent = list(range(len(self.parts)))

        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        at: dict = {}
        for i, p in enumerate(self.parts):
            for end in (p[1], p[2]):
                if end in self.pos:
                    if end in at:
                        parent[root(i)] = root(at[end])
                    else:
                        at[end] = i
        out: dict = {}
        for i in range(len(self.parts)):
            out.setdefault(root(i), []).append(i)
        res = []
        for ix in out.values():
            rows = sorted({self.pos[e] for i in ix for e in self.parts[i][1:3] if e in self.pos})
            res.append((ix, rows))
        return res

    def subset(self, ix: list[int]) -> "Structure":
        """A copy with only the parts at positions ix (their numbers kept)."""
        out = Structure(self.st, [])
        offs = np.cumsum([0] + [2 if p[0] == "min" else 1 for p in self.parts])
        out.parts = [self.parts[j] for j in ix]
        idx = [k for j in ix for k in range(offs[j], offs[j + 1])]
        out.theta, out.lo, out.hi = self.theta[idx].copy(), self.lo[idx].copy(), self.hi[idx].copy()
        out._idx = idx
        return out

    def refit(self, scale: np.ndarray, evals: int = 200) -> np.ndarray:
        """(k8s-317, block refit) The least squares of _refit, solved block by block (blocks()): the same
        problem, separable, so each block's SVD is its own small one (36 stocks: one joint fit of ~80
        numbers on 10,764 rows took 29 s, most of it the SVD)."""
        if not len(self.theta):
            return self.theta
        bl = self.blocks() if BLOCKS else []
        if len(bl) <= 1:
            return self._refit(scale, evals)
        theta = self.theta.copy()
        for ix, rows in bl:
            sub = self.subset(ix)
            sub._rows = rows
            sub._refit(scale, evals)
            theta[sub._idx] = sub.theta
        self.theta = theta
        return self.theta

    def _refit(self, scale: np.ndarray, evals: int = 200) -> np.ndarray:
        """Least squares on every step; a stock's proportional drains together take at most all of it
        in a step (sum of their numbers <= 1, a penalty row): with counts the expected amount saturates
        at the level, so without it their total is not identified, only their shares. (k8s-317) A block
        (refit) reads only its own rows (self._rows); a stock no part touches has a residual that no
        number moves."""
        if not len(self.theta):
            return self.theta
        rows = getattr(self, "_rows", None)
        if rows is not None:
            T = self.st.T
            sel = np.concatenate([np.arange(i * T, (i + 1) * T) for i in rows])
            full_res, full_jac = self.resid, self.jac
            self.resid = lambda th, sc: full_res(th, sc)[rows]              # noqa: E731
            self.jac = lambda th, sc: full_jac(th, sc)[sel]                  # noqa: E731
            try:
                return self._refit_rows(scale, evals)
            finally:
                del self.resid, self.jac
        return self._refit_rows(scale, evals)

    def _refit_rows(self, scale: np.ndarray, evals: int = 200) -> np.ndarray:
        x0 = np.clip(self.theta, self.lo, self.hi)
        groups = self._drains()

        def res(th):
            r = self.resid(th, scale).ravel()
            return np.concatenate([r, [PENALTY * max(0.0, th[g].sum() - 1.0) for g in groups]]) if groups else r

        def jac(th):
            J = self.jac(th, scale)
            if not groups:
                return J
            P = np.zeros((len(groups), len(th)))
            for k, g in enumerate(groups):
                if th[g].sum() > 1.0:
                    P[k, g] = PENALTY
            return np.vstack([J, P])
        try:
            r = least_squares(res, x0, jac=jac, bounds=(self.lo, self.hi), method="trf", x_scale="jac", max_nfev=evals)
            if np.sum(r.fun ** 2) <= np.sum(res(x0) ** 2):
                self.theta = r.x
        except (ValueError, np.linalg.LinAlgError):
            pass
        return self.theta

    def without(self, i: int) -> "Structure":
        """A copy without part i."""
        out = Structure(self.st, [])
        offs = np.cumsum([0] + [2 if p[0] == "min" else 1 for p in self.parts])
        keep = [j for j in range(len(self.parts)) if j != i]
        out.parts = [self.parts[j] for j in keep]
        idx = [k for j in keep for k in range(offs[j], offs[j + 1])]
        out.theta, out.lo, out.hi = self.theta[idx].copy(), self.lo[idx].copy(), self.hi[idx].copy()
        return out

    def simplified(self, i: int) -> "Structure | None":
        """A copy with MIN part i read as its demand alone (a x src): the nested model with one number fewer."""
        p = self.parts[i]
        if p[0] != "min":
            return None
        out = self.without(i)
        offs = np.cumsum([0] + [2 if q[0] == "min" else 1 for q in self.parts])
        out.parts.append(("term", p[1], p[2], p[1]))
        out.theta = np.append(out.theta, self.theta[offs[i]])
        out.lo, out.hi = np.append(out.lo, 0.0), np.append(out.hi, 1.0)
        return out

    def rerouted(self, i: int, dst) -> "Structure":
        """A copy with part i's flow sent to another stock (or outside), its numbers kept."""
        out = self.without(len(self.parts))           # a copy
        p = self.parts[i]
        out.parts[i] = (p[0], p[1], dst) + tuple(p[3:])
        return out

    def with_piece(self, dst: str, k: int, v: float = 0.0) -> "Structure":
        """A copy with a step of dst's estimated inflow constant from step k on."""
        out = self.without(len(self.parts))
        out.parts.append(("piece", None, dst, None, int(k)))
        out.theta, out.lo, out.hi = np.append(out.theta, v), np.append(out.lo, -np.inf), np.append(out.hi, np.inf)
        return out

    def bic(self, scale: np.ndarray, floor: np.ndarray, extra: float = 0.0) -> float:
        """Gaussian BIC on every step, each step's variance a stock's (profiled) times scale^2: per stock
        T log(mean squared weighted misfit) + 2 sum log scale, + log T per number."""
        e = self.resid(None, scale)
        rs = self.row_scale(scale)
        msq = np.maximum(np.mean(e ** 2, axis=1), (floor[:, None] / rs).mean(axis=1) ** 2)
        n = len(self.theta) + (PIECE_PRICE - 1.0) * sum(p[0] == "piece" for p in self.parts)
        return float(self.st.T * np.sum(np.log(msq)) + 2.0 * np.sum(np.log(rs)) + np.log(max(self.st.T, 2)) * n + extra)


BLOCKS = True         # (k8s-317) refit block by block (Structure.blocks): the same least squares, separated
PIECE_PRICE = 2.0     # an inflow step pays this many log T (its size and its place), as in the program
PENALTY = 1e4         # weight of a drain total beyond 1 (per unit, against misfits per noise scale)
PRUNE_EVALS = 30      # function evaluations of each refit while pruning (started from the numbers already fitted)
PRUNE_WORK = 1.5e10   # a prune stops (keeping what it has) after refits costing this much: sum of steps x stocks x numbers^2
                      # (a refit's SVD; k8s-310: a start with ~120 numbers on 2000 steps took 0.47 s a refit, 100-230 s a
                      # prune; this is ~25 s of it; deterministic, unlike a clock)


def drop_tiny(s: Structure, rel: float = 1e-6) -> Structure:
    """Without the parts that move next to nothing (below rel of the changes of the stocks they touch):
    the program may switch a column on at a number of 0."""
    scale = {x: float(np.mean(np.abs(s.st.dy[i]))) + 1e-12 for i, x in enumerate(s.st.ids)}
    for i in reversed(range(len(s.parts))):
        src, dst, amt = s.amounts(s.theta)[i]
        ref = max(scale.get(src, 0.0), scale.get(dst, 0.0))
        if float(np.mean(np.abs(amt))) <= rel * ref:
            s = s.without(i)
    return s


def keeps(s: Structure, forced: list) -> bool:
    """Every declared outside flow still has a plain part."""
    have = {(p[1], p[2]) for p in s.parts if p[0] in ("term", "neg", "min")}
    return all(k in have for k in forced)


def pair_drops(s: Structure) -> list[Structure]:
    """(k8s-315, pair-drop) Copies without two plain terms of one flow at once. Two readers that cancel
    (+a x one counter - b x another: together a slow wander, each alone a huge drift) are kept by a
    one-at-a-time search, because dropping either alone leaves the other's drift unexplained."""
    out = []
    by: dict = {}
    for i, p in enumerate(s.parts):
        if p[0] in ("term", "neg"):
            by.setdefault((p[1], p[2]), []).append(i)
    for ix in by.values():
        for a in range(len(ix)):
            for b in range(a + 1, len(ix)):
                out.append(s.without(ix[b]).without(ix[a]))
    return out


def prune(s: Structure, scale: np.ndarray, floor: np.ndarray, price, targets, forced: list = (), places=None,
          shape=None) -> Structure:
    """Drop a part, read a MIN as its demand alone, or send a flow from a stock to another of the
    targets(src) the boundary allows, one change at a time while the refitted BIC (with price(structure):
    its boundary claims) improves: a local search around the program's answer, whose absolute misfit on a
    sample of the steps and limited search can keep a part, or a destination, the full least squares does
    not prefer."""
    own = (lambda x: shape(x)) if shape else (lambda x: scale)     # counts: each structure weighs steps by what it moves
    cur = s.bic(own(s), floor, price(s))
    work = 0.0
    while s.parts and work < PRUNE_WORK:
        best = None
        moves = [s.without(i) for i in range(len(s.parts))] + [x for x in (s.simplified(i) for i in range(len(s.parts))) if x]
        moves += pair_drops(s)
        moves += [s.rerouted(i, d) for i, p in enumerate(s.parts) if p[1] is not None and p[0] in ("term", "min")
                  for d in targets(p[1]) if d != p[2] and not any(q[1:3] == (p[1], d) and q[0] == p[0] and q[3:] == p[3:] for q in s.parts)]
        if places:                                   # an inflow step: move it a little
            o = 0
            have = {(p[2], p[4]) for p in s.parts if p[0] == "piece"}
            for i, p in enumerate(s.parts):
                if p[0] == "piece":
                    for dk in (-4, -2, -1, 1, 2, 4):
                        k = p[4] + dk
                        if 0 < k < s.st.T and (p[2], k) not in have:
                            moves.append(s.without(i).with_piece(p[2], k, float(s.theta[o])))
                o += 2 if p[0] == "min" else 1
        moves += counter.adds(s)                     # a move into a counter fitted in level space
        for c in [m for m in moves if keeps(m, forced)]:
            if work >= PRUNE_WORK:
                break
            sc = own(c)
            c.refit(sc, PRUNE_EVALS)
            work += float(c.st.T) * len(c.st.ids) * max(1, len(c.theta)) ** 2
            b = c.bic(sc, floor, price(c))
            if b < cur:                              # first improvement (the moves are cheap to try, not to refit)
                best = (b, c)
                break
        if best is None:
            break
        cur, s = best
    return s
