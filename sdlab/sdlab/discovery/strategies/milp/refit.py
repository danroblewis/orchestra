"""The chosen structure's numbers refitted by least squares on every step (the program's misfit is
absolute, reads a sample of the steps, and a MIN's threshold on a grid), and what the refitted model
leaves and moves per step."""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares
from scipy.stats import norm

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
        return J

    def change(self, theta: np.ndarray | None = None) -> np.ndarray:
        d = np.zeros_like(self.st.dy)
        for src, dst, amt in self.capped(self.theta if theta is None else theta):
            if src in self.pos:
                d[self.pos[src]] -= amt
            if dst in self.pos:
                d[self.pos[dst]] += amt
        return d

    def gross(self) -> np.ndarray:
        """Per stock and step, the amount moved in or out of it (a count's scatter grows with it)."""
        g = np.zeros_like(self.st.dy)
        for src, dst, amt in self.amounts(self.theta):
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

    def refit(self, scale: np.ndarray, evals: int = 200) -> np.ndarray:
        """Least squares on every step; a stock's proportional drains together take at most all of it
        in a step (sum of their numbers <= 1, a penalty row): with counts the expected amount saturates
        at the level, so without it their total is not identified, only their shares."""
        if not len(self.theta):
            return self.theta
        x0 = np.clip(self.theta, self.lo, self.hi)
        groups = self._drains()

        def res(th):
            r = ((self.st.dy - self.change(th)) / scale).ravel()
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
        e = (self.st.dy - self.change()) / scale
        msq = np.maximum(np.mean(e ** 2, axis=1), (floor[:, None] / scale).mean(axis=1) ** 2)
        n = len(self.theta) + (PIECE_PRICE - 1.0) * sum(p[0] == "piece" for p in self.parts)
        return float(self.st.T * np.sum(np.log(msq)) + 2.0 * np.sum(np.log(scale)) + np.log(max(self.st.T, 2)) * n + extra)


PIECE_PRICE = 2.0     # an inflow step pays this many log T (its size and its place), as in the program
PENALTY = 1e4         # weight of a drain total beyond 1 (per unit, against misfits per noise scale)
PRUNE_EVALS = 30      # function evaluations of each refit while pruning (started from the numbers already fitted)


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


def prune(s: Structure, scale: np.ndarray, floor: np.ndarray, price, targets, forced: list = (), places=None,
          shape=None) -> Structure:
    """Drop a part, read a MIN as its demand alone, or send a flow from a stock to another of the
    targets(src) the boundary allows, one change at a time while the refitted BIC (with price(structure):
    its boundary claims) improves: a local search around the program's answer, whose absolute misfit on a
    sample of the steps and limited search can keep a part, or a destination, the full least squares does
    not prefer."""
    own = (lambda x: shape(x)) if shape else (lambda x: scale)     # counts: each structure weighs steps by what it moves
    cur = s.bic(own(s), floor, price(s))
    while s.parts:
        best = None
        moves = [s.without(i) for i in range(len(s.parts))] + [x for x in (s.simplified(i) for i in range(len(s.parts))) if x]
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
        for c in [m for m in moves if keeps(m, forced)]:
            sc = own(c)
            c.refit(sc, PRUNE_EVALS)
            b = c.bic(sc, floor, price(c))
            if b < cur:                              # first improvement (the moves are cheap to try, not to refit)
                best = (b, c)
                break
        if best is None:
            break
        cur, s = best
    return s
