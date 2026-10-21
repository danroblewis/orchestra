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
    era's signed change of that term). And ("min", src, dst, cap) with two (a, b): MIN(a x src, b x cap)."""

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

    def amounts(self, theta: np.ndarray) -> list[tuple[str | None, str | None, np.ndarray]]:
        out, o = [], 0
        for p in self.parts:
            if p[0] == "min":
                out.append((p[1], p[2], np.minimum(theta[o] * self.st.series(p[1]), theta[o + 1] * self.st.series(p[3]))))
                o += 2
                continue
            x = self.st.series(p[3])
            if p[0] == "neg":
                x = -x
            elif p[0] == "era":
                x = x * (self.st.era == p[4])
            out.append((p[1], p[2], theta[o] * x))
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
                x = self.st.series(p[3])
                x = -x if p[0] == "neg" else x * (self.st.era == p[4]) if p[0] == "era" else x
                cols = [x]
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

    def refit(self, scale: np.ndarray, evals: int = 200) -> np.ndarray:
        if not len(self.theta):
            return self.theta
        x0 = np.clip(self.theta, self.lo, self.hi)
        res = lambda th: ((self.st.dy - self.change(th)) / scale).ravel()  # noqa: E731
        try:
            r = least_squares(res, x0, jac=lambda th: self.jac(th, scale), bounds=(self.lo, self.hi), method="trf",
                              x_scale="jac", max_nfev=evals)
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

    def bic(self, scale: np.ndarray, floor: np.ndarray, extra: float = 0.0) -> float:
        """Gaussian BIC on every step: per stock T log(mean squared weighted misfit) + log T per number."""
        e = (self.st.dy - self.change()) / scale
        msq = np.maximum(np.mean(e ** 2, axis=1), (floor[:, None] / scale).mean(axis=1) ** 2)
        return float(self.st.T * np.sum(np.log(msq)) + np.log(max(self.st.T, 2)) * len(self.theta) + extra)


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


def prune(s: Structure, scale: np.ndarray, floor: np.ndarray, price) -> Structure:
    """Drop parts, or read a MIN as its demand alone, one at a time while the refitted BIC (with
    price(structure): its boundary claims) improves: the program's absolute misfit on a sample can keep a
    part the full least squares does not need."""
    cur = s.bic(scale, floor, price(s))
    while s.parts:
        best = None
        for c in [s.without(i) for i in range(len(s.parts))] + [x for x in (s.simplified(i) for i in range(len(s.parts))) if x]:
            c.refit(scale, PRUNE_EVALS)
            b = c.bic(scale, floor, price(c))
            if b < cur and (best is None or b < best[0]):
                best = (b, c)
        if best is None:
            break
        cur, s = best
    return s
