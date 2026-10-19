# Vendored for combined2 from sdlab/discovery/strategies/structures/terms.py at commit 7e0a2bf (HEAD 05ae898); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""Terms: the smallest parts a model is built of, each with one number theta >= 0, and the change
each makes to every measured stock per unit of theta (a column of the regression).

Drivers are rows of R = [measured levels at each step's start; measured inputs during the step]; a
term reads one row, a product of two rows (a bilinear term: S x I, P x A, X x X), or nothing (a
constant). Kinds:

    in     outside -> b         theta                    (b's outside inflow; floored with the rest of it)
    link   outside -> b         theta x x                (x a stock, b itself (births) or an input)
    gap    outside -> b         -theta x x               (a goal gap: b's inflow falls as x rises)
    out    a -> outside         theta x a  or  theta x a x c
    drain  a -> outside         theta x x                (x another stock or an input)
    move   a -> b               theta x a  or  theta x a x c
    plink  outside -> b         theta x i x j            (a link scaled by a product)
    chain  a -> (hidden) -> b   a loses theta x x now; b gets theta x x through an n-stage Erlang
                                chain of mean delay tau (a None: fed from outside, x may be 1, a
                                stock or an input, sign -1 for a gap)
    init   (hidden) -> b        the chain's stage `stage` holding theta at the start
    in + span                   one piece of b's outside inflow (steps a..b-1), its places taken
                                from the base model's pieces (an unannounced schedule)
    goal   outside -> b         theta x (u - sum of stocks x[1:])   (a goal gap closed over 1 / theta
                                steps, the goal an input u = x[0]: one shared time for every stock)

`in`, `link` and `gap` into one stock are one flow (its outside inflow), floored at 0 as a whole.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Term:
    kind: str
    src: int | None = None
    dst: int | None = None
    x: tuple = ()                      # driver rows (empty: a constant)
    chain: tuple | None = None         # (n, tau) for chain / init
    stage: int = 0                     # init: the stage that holds theta at the start
    sign: float = 1.0
    span: tuple | None = None          # in: steps a..b-1 only (a piece of an outside inflow)

    @property
    def pooled(self) -> bool:
        return self.kind in ("in", "link", "gap", "goal")

    def chain_key(self) -> tuple | None:
        """Which hidden chain a chain or init term belongs to: (src, dst, n, tau)."""
        if self.kind not in ("chain", "init"):
            return None
        return (self.src, self.dst) + tuple(self.chain)


def erlang(z: np.ndarray, n: int, tau: float) -> np.ndarray:
    """What an n-stage chain (each stage drained at n / tau per step, one Euler step per step) fed
    z[k] in step k delivers in each step: delivery[k] = r x H_n[k], H's contents at step k's start."""
    from scipy.signal import lfilter
    r = min(1.0, n / tau)
    x = np.asarray(z, dtype=float)
    for _ in range(n):
        h = lfilter([0.0, 1.0], [1.0, -(1.0 - r)], x)
        x = r * h
    return x


def init_response(T: int, n: int, tau: float, stage: int) -> np.ndarray:
    """The delivery per step from one unit held in stage `stage` (0-based) at the first step's start."""
    r = min(1.0, n / tau)
    H = np.zeros(n)
    H[stage] = 1.0
    out = np.zeros(T)
    for k in range(T):
        o = r * H
        out[k] = o[-1]
        H = H - o
        H[1:] += o[:-1]
    return out


def stage_contents(inflow: np.ndarray, init: np.ndarray, n: int, tau: float) -> np.ndarray:
    """Each stage's contents at every step's start and after the last step (n x (T + 1))."""
    r = min(1.0, n / tau)
    T = len(inflow)
    H = np.array(init, dtype=float)
    out = np.zeros((n, T + 1))
    for k in range(T):
        out[:, k] = H
        o = r * H
        H = H - o
        H[1:] += o[:-1]
        H[0] += inflow[k]
    out[:, T] = H
    return out


class Rows:
    """The driver rows and the columns of terms (cached)."""

    def __init__(self, prev: np.ndarray, inputs: np.ndarray):
        self.S, self.T = prev.shape
        self.R = np.vstack([np.maximum(prev, 0.0), inputs]) if inputs.size else np.maximum(prev, 0.0)
        self._z: dict = {}
        self._c: dict = {}

    def goal(self, x: tuple) -> np.ndarray:
        return self.R[x[0]] - self.R[list(x[1:])].sum(axis=0)

    def signed(self, t: "Term") -> np.ndarray:
        """A pooled term's part of its stock's outside inflow per unit theta."""
        if t.kind == "goal":
            return self.goal(t.x)
        if t.span is not None:
            return self.piece(t.span)
        return -self.z(t.x) if t.kind == "gap" else self.z(t.x)

    def piece(self, span: tuple) -> np.ndarray:
        v = np.zeros(self.T)
        v[span[0]:span[1]] = 1.0
        return v

    def z(self, x: tuple) -> np.ndarray:
        if x not in self._z:
            v = np.ones(self.T)
            for i in x:
                v = v * self.R[i]
            self._z[x] = v
        return self._z[x]

    def column(self, t: Term) -> np.ndarray:
        """The term's change to every measured stock per unit of theta (S x T)."""
        if t in self._c:
            return self._c[t]
        C = np.zeros((self.S, self.T))
        if t.kind == "init":
            C[t.dst] += init_response(self.T, t.chain[0], t.chain[1], t.stage)
        elif t.kind == "goal":
            C[t.dst] += self.goal(t.x)
        elif t.span is not None:
            C[t.dst] += self.piece(t.span)
        else:
            z = self.z(t.x)
            if t.src is not None:
                C[t.src] -= z
            if t.dst is not None:
                if t.kind == "chain":
                    C[t.dst] += t.sign * erlang(z, *t.chain)
                else:
                    C[t.dst] += -z if t.kind == "gap" else z
        self._c[t] = C
        return C

    def pool_rate(self, terms: list[Term], theta: np.ndarray, b: int) -> np.ndarray:
        """b's outside inflow (its in, link and gap terms) per step, before the floor."""
        rate = np.zeros(self.T)
        for t, th in zip(terms, theta):
            if t.pooled and t.dst == b:
                rate += th * self.signed(t)
        return rate


def library(S: int, m: int, unit: list[str], final: set[int], group: list, products: bool = True) -> list[Term]:
    """Every plain and bilinear term between S stocks and m inputs that the page allows (moves
    between stocks of one unit; nothing leaves a final stock; a stock reads another only in its
    own group, or when either has none)."""
    def may(j, s):
        return j >= S or j == s or not group[j] or not group[s] or group[j] == group[s]

    out: list[Term] = []
    for b in range(S):
        out.append(Term("in", dst=b))
        for j in range(S + m):
            if may(j, b):
                out.append(Term("link", dst=b, x=(j,)))
                if j < S:
                    out.append(Term("gap", dst=b, x=(j,)))
    for a in range(S):
        if a in final:
            continue
        out.append(Term("out", src=a, x=(a,)))
        for j in range(S + m):
            if j != a and may(j, a):
                out.append(Term("drain", src=a, x=(j,)))
        for b in range(S):
            if b != a and unit[a] == unit[b] and may(a, b):
                out.append(Term("move", src=a, dst=b, x=(a,)))
    if products:
        for i in range(S):
            for j in range(i, S):
                if not may(i, j):
                    continue
                x = (i, j)
                for a in {i, j}:
                    if a in final:
                        continue
                    out.append(Term("out", src=a, x=x))
                    for b in range(S):
                        if b != a and unit[a] == unit[b]:
                            out.append(Term("move", src=a, dst=b, x=x))
                for b in range(S):
                    out.append(Term("plink", dst=b, x=x))
    return list(dict.fromkeys(out))


def chain_terms(S: int, m: int, n: int, tau: float, unit: list[str], final: set[int]) -> list[Term]:
    """The chain terms for one (n, tau): a stock's loss delivered to a stock of its unit (itself
    too: a loop through a hidden stock, as rework), and an outside-fed chain into each stock whose
    feed is a constant, a stock (either sign) or an input."""
    out = []
    ch = (n, float(tau))
    for b in range(S):
        for a in range(S):
            if a not in final and unit[a] == unit[b]:
                out.append(Term("chain", src=a, dst=b, x=(a,), chain=ch))
        out.append(Term("chain", dst=b, x=(), chain=ch))
        for j in range(S + m):
            if j in final:
                continue
            out.append(Term("chain", dst=b, x=(j,), chain=ch))
            if j < S:
                out.append(Term("chain", dst=b, x=(j,), chain=ch, sign=-1.0))
    return out


def inits(t: Term) -> list[Term]:
    """The start-of-run contents of a chain term's stages."""
    n = t.chain[0]
    return [Term("init", src=t.src, dst=t.dst, chain=t.chain, stage=s) for s in range(n)]
