"""The chosen structure's numbers refitted by least squares on every step (the program's misfit is
absolute, reads a sample of the steps, and a MIN's threshold on a grid), and what the refitted model
leaves and moves per step."""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

from .program import Column
from .steps import Steps


class Structure:
    """Parts: ("term", src, dst, reader) with one number v, or ("min", src, dst, cap) with two (a, b):
    MIN(a x src, b x cap)."""

    def __init__(self, st: Steps, chosen: list[tuple[Column, float]]):
        self.st = st
        self.parts, theta, hi = [], [], []
        for c, v in chosen:
            if c.what[0] == "term":
                self.parts.append(("term", c.src, c.dst, c.what[1]))
                theta.append(v)
                hi.append(c.ub)
            else:
                self.parts.append(("min", c.src, c.dst, c.what[1]))
                theta += [v, v * c.what[2]]
                hi += [1.0, np.inf]
        self.theta, self.hi = np.array(theta, dtype=float), np.array(hi, dtype=float)
        self.pos = {s: i for i, s in enumerate(st.ids)}

    def key(self) -> tuple:
        return tuple(sorted(self.parts, key=str))

    def numbers(self) -> list[tuple[tuple, list[float]]]:
        out, o = [], 0
        for p in self.parts:
            k = 1 if p[0] == "term" else 2
            out.append((p, [float(v) for v in self.theta[o:o + k]]))
            o += k
        return out

    def amounts(self, theta: np.ndarray) -> list[tuple[str | None, str | None, np.ndarray]]:
        out, o = [], 0
        for p in self.parts:
            if p[0] == "term":
                out.append((p[1], p[2], theta[o] * self.st.series(p[3])))
                o += 1
            else:
                out.append((p[1], p[2], np.minimum(theta[o] * self.st.series(p[1]), theta[o + 1] * self.st.series(p[3]))))
                o += 2
        return out

    def change(self, theta: np.ndarray | None = None) -> np.ndarray:
        d = np.zeros_like(self.st.dy)
        for src, dst, amt in self.amounts(self.theta if theta is None else theta):
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

    def refit(self, scale: np.ndarray) -> np.ndarray:
        if not len(self.theta):
            return self.theta
        x0 = np.clip(self.theta, 0.0, self.hi)
        res = lambda th: ((self.st.dy - self.change(th)) / scale).ravel()  # noqa: E731
        try:
            r = least_squares(res, x0, bounds=(np.zeros_like(x0), self.hi), method="trf", x_scale="jac", max_nfev=200)
            if np.sum(r.fun ** 2) <= np.sum(res(x0) ** 2):
                self.theta = r.x
        except (ValueError, np.linalg.LinAlgError):
            pass
        return self.theta

    def without(self, i: int) -> "Structure":
        """A copy without part i."""
        out = Structure(self.st, [])
        offs = np.cumsum([0] + [1 if p[0] == "term" else 2 for p in self.parts])
        keep = [j for j in range(len(self.parts)) if j != i]
        out.parts = [self.parts[j] for j in keep]
        idx = [k for j in keep for k in range(offs[j], offs[j + 1])]
        out.theta, out.hi = self.theta[idx].copy(), self.hi[idx].copy()
        return out

    def bic(self, scale: np.ndarray, floor: np.ndarray, extra: float = 0.0) -> float:
        """Gaussian BIC on every step: per stock T log(mean squared weighted misfit) + log T per number."""
        e = (self.st.dy - self.change()) / scale
        msq = np.maximum(np.mean(e ** 2, axis=1), (floor[:, None] / scale).mean(axis=1) ** 2)
        return float(self.st.T * np.sum(np.log(msq)) + np.log(max(self.st.T, 2)) * len(self.theta) + extra)


def prune(s: Structure, scale: np.ndarray, floor: np.ndarray, price) -> Structure:
    """Drop parts one at a time while the refitted BIC (with price(structure): its boundary claims)
    improves: the program's absolute misfit on a sample can keep a part the full least squares does not need."""
    cur = s.bic(scale, floor, price(s))
    while s.parts:
        best = None
        for i in range(len(s.parts)):
            c = s.without(i)
            c.refit(scale)
            b = c.bic(scale, floor, price(c))
            if b < cur and (best is None or b < best[0]):
                best = (b, c)
        if best is None:
            break
        cur, s = best
    return s
