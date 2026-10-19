# Vendored for combined2 from sdlab/discovery/strategies/structures/fit.py at commit 7e0a2bf (HEAD 05ae898); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""Fitting terms' numbers (theta >= 0, the outside inflow floored at 0 as the engine floors it) and
choosing which terms stay, by BIC.

The mean change is linear in theta, so a set of terms is fitted by non-negative weighted least
squares, with an active set for the floor: steps where a stock's outside inflow (its constant,
links and gaps) comes out below 0 get none of it, and the fit is repeated until those steps stop
changing. The likelihood the search compares models by depends on the data:

- counts: each change Gaussian with the variance counting noise gives it (each term's amount
  through the stock, the outside inflow as one draw), held fixed during a search at a reference
  model's, so models are compared by their weighted squared error;
- anything else (noise-free runs): each stock's own variance concentrated out, floored at the
  quantum the levels are written in (0.5 T log(rss / T) per stock).

The search is stepwise: each round screens every term not in the model by how much it would lower
the weighted error alone (a projection), fits the few best exactly, adds the one that lowers BIC
most, then drops any term whose removal lowers BIC; it stops when nothing added lowers BIC.
"""

from __future__ import annotations

import math
import time

import numpy as np
from scipy.optimize import nnls

from .terms import Rows, Term, inits

SCREEN = 8           # terms fitted exactly per round, the best by the projection


class OutOfTime(Exception):
    pass


class Problem:
    def __init__(self, rows: Rows, dy: np.ndarray, counts: bool, quantum: float, deadline: float | None = None, price: float = 1.0):
        self.rows, self.dy = rows, dy
        self.S, self.T = dy.shape
        self.counts = counts
        self.eps = max(quantum ** 2 / 6.0, 1e-12)
        self.delta = 1.0 / 6.0 if counts else self.eps
        self.var = np.tile(np.maximum(dy.var(axis=1), 1.0 if counts else self.eps)[:, None], (1, self.T))
        self.deadline = deadline
        self.price = price
        self.log_t = math.log(max(2, self.T))

    def check(self):
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise OutOfTime()


class Fit:
    def __init__(self, terms: list[Term], theta: np.ndarray, resid: np.ndarray, nll: float, numbers: float, price: float, log_t: float):
        self.terms, self.theta, self.resid, self.nll = terms, theta, resid, nll
        self.numbers = numbers
        self.bic = nll + 0.5 * price * log_t * numbers

    def live(self) -> list[tuple[Term, float]]:
        return [(t, th) for t, th in zip(self.terms, self.theta) if th > 0]


PRODUCT = 4.0        # numbers a bilinear term costs: its rate and a linear effect (3), as combined's judge prices it


def numbers(terms: list[Term]) -> float:
    """What the terms write down, priced as combined's judge prices the flows they become: one per
    term, a bilinear term PRODUCT, an inflow piece 2 (its value and its place), and a hidden chain its n stage rates (one delay, but n flows)."""
    chains = {t.chain_key() for t in terms if t.kind == "chain"}
    return sum(PRODUCT if len(t.x) == 2 else 2.0 if t.span is not None else 1.0 for t in terms) + sum(c[2] for c in chains)


def _solve(A: np.ndarray, b: np.ndarray) -> np.ndarray:
    sc = np.linalg.norm(A, axis=0)
    sc = np.where(sc > 0, sc, 1.0)
    try:
        x, _ = nnls(A / sc, b, maxiter=50 * A.shape[1] + 200)
    except RuntimeError:
        x = np.maximum(0.0, np.linalg.lstsq(A / sc, b, rcond=None)[0])
    return x / sc


def fit(p: Problem, terms: list[Term], weights: np.ndarray | None = None) -> Fit:
    """The terms' numbers by weighted NNLS with the outside inflow's floor; noise-free data are
    reweighted by each stock's residual variance (twice)."""
    p.check()
    terms = list(dict.fromkeys(terms))
    J = len(terms)
    if J == 0:
        r = p.dy.copy()
        return Fit([], np.zeros(0), r, _nll(p, r), 0, p.price, p.log_t)
    C = np.array([p.rows.column(t) for t in terms])                    # J x S x T
    w = (1.0 / p.var) if weights is None else weights
    pools = sorted({t.dst for t in terms if t.kind in ("gap", "goal")})
    mask = {b: np.ones(p.T, bool) for b in pools}
    theta = np.zeros(J)
    for it in range(6):
        Ce = C
        if pools:
            Ce = C.copy()
            for j, t in enumerate(terms):
                if t.pooled and t.dst in mask:
                    Ce[j, t.dst] = Ce[j, t.dst] * mask[t.dst]
        sw = np.sqrt(w)
        A = (Ce * sw[None]).reshape(J, -1).T
        theta = _solve(A, (p.dy * sw).reshape(-1))
        r = p.dy - np.tensordot(theta, Ce, axes=1)
        settled = p.counts or it >= 2
        if not p.counts:
            w = np.tile((1.0 / np.maximum((r ** 2).mean(axis=1), p.eps))[:, None], (1, p.T))
        if pools:
            new = {b: p.rows.pool_rate(terms, theta, b) > 0 for b in pools}
            settled = settled and all(np.array_equal(new[b], mask[b]) for b in pools)
            mask = new
        if settled:
            break
    return Fit(terms, theta, r, _nll(p, r), numbers(terms), p.price, p.log_t)


def _nll(p: Problem, r: np.ndarray) -> float:
    if p.counts:
        return float(0.5 * ((r ** 2) / p.var + np.log(p.var)).sum())
    return float(0.5 * p.T * np.log(np.maximum((r ** 2).mean(axis=1), p.eps)).sum())


def variance(p: Problem, f: Fit) -> np.ndarray:
    """Counting noise's variance of each stock's change under a fitted model: every term's amount
    through the stock, a stock's outside inflow as one draw, plus the rounding."""
    v = np.zeros((p.S, p.T))
    pool = np.zeros((p.S, p.T))
    for t, th in f.live():
        if t.pooled:
            pool[t.dst] += th * p.rows.signed(t)
        else:
            v += th * np.abs(p.rows.column(t))
    return v + np.maximum(np.abs(pool), 0.05) + p.delta


def _with(terms: list[Term], t: Term) -> list[Term]:
    out = list(terms) + [t]
    if t.kind == "chain":
        out += [i for i in inits(t) if i not in terms]
    return out


def _without(terms: list[Term], t: Term) -> list[Term]:
    out = [u for u in terms if u != t]
    if t.kind == "chain" and not any(u.kind == "chain" and u.chain_key() == t.chain_key() for u in out):
        out = [u for u in out if u.chain_key() != t.chain_key()]
    return out


def screen(p: Problem, cur: Fit, cands: list[Term], w: np.ndarray, k: int = SCREEN) -> list[Term]:
    """The k candidates that would lower the weighted error most on their own (a projection on
    the current model's columns), with a positive number."""
    sw = np.sqrt(w).reshape(-1)
    r = cur.resid.reshape(-1) * sw
    X = np.array([p.rows.column(t).reshape(-1) for t in cands]).T * sw[:, None]      # N x L
    if cur.terms:
        A = np.array([p.rows.column(t).reshape(-1) for t in cur.terms]).T * sw[:, None]
        Q, _ = np.linalg.qr(A)
        X = X - Q @ (Q.T @ X)
    nn = (X ** 2).sum(axis=0)
    dot = r @ X
    ok = (nn > 1e-12 * max(1e-300, nn.max())) & (dot > 0)
    beta = np.where(ok, dot / np.where(nn > 0, nn, 1), 0.0)
    if p.counts:
        gain = beta * dot
    else:
        # noise-free: the drop in 0.5 T sum log(rss_s / T), each stock's rss floored at the quantum
        # (a term that only fits a stock's rounding gains nothing)
        S, T = p.S, p.T
        rw = r.reshape(S, T)
        ws = w.reshape(S, T)[:, 0]
        before = (rw ** 2).sum(axis=1) / ws
        gain = np.zeros(len(cands))
        for s in range(S):
            Xs = X.reshape(S, T, -1)[s]
            after = ((rw[s][:, None] - Xs * beta[None, :]) ** 2).sum(axis=0) / ws[s]
            gain += 0.5 * T * (np.log(max(before[s] / T, p.eps)) - np.log(np.maximum(after / T, p.eps)))
        gain = np.where(ok, gain, 0.0)
    order = np.argsort(-gain)
    return [cands[i] for i in order[:k] if gain[i] > 0]


def _signs(t: Term) -> dict[int, float]:
    out = {}
    if t.src is not None:
        out[t.src] = -1.0
    if t.dst is not None:
        out[t.dst] = -1.0 if (t.kind == "gap" or t.sign < 0) else 1.0
    return out


def aliases(t: Term, lib: list[Term]) -> list[Term]:
    """Terms reading the same thing that change one of the same stocks the same way (an outflow and
    a gap, a drain and a gap, a move and an outflow): what a swap may replace t with."""
    if t.kind == "init" or t.span is not None:
        return []
    st = _signs(t)
    same_x = [a for a in lib if a != t and a.span is None and a.x == t.x and a.chain == t.chain and any(st.get(s) == v for s, v in _signs(a).items())]
    # the same flow reading something else: a plain outflow for a bilinear one, and back
    same_ends = [a for a in lib if a != t and a.kind == t.kind and a.src == t.src and a.dst == t.dst and a.chain == t.chain and a.sign == t.sign and a.x != t.x]
    return same_x + same_ends


def merges(terms: list[Term], lib: list[Term]) -> list[tuple[Term, Term, Term]]:
    """(t1, t2, move): an outflow of a and a link into b at the same driver that are one move a -> b
    (one draw, half the numbers), or the outflow and an outside-fed chain into b, a's loss passing
    through the chain."""
    have = set(lib)
    out = []
    for t1 in terms:
        if t1.kind != "out":
            continue
        for t2 in terms:
            if t2.x != t1.x or t2.dst is None or t2.dst == t1.src and t2.kind != "chain":
                continue
            if t2.kind in ("link", "plink"):
                m = Term("move", src=t1.src, dst=t2.dst, x=t1.x)
            elif t2.kind == "chain" and t2.src is None and t2.sign > 0:
                m = Term("chain", src=t1.src, dst=t2.dst, x=t1.x, chain=t2.chain)
            else:
                continue
            if m in have and m not in terms:
                out.append((t1, t2, m))
    return out


def _weights(p: Problem, cur: Fit) -> np.ndarray:
    if p.counts:
        return 1.0 / p.var
    return np.tile((1.0 / np.maximum((cur.resid ** 2).mean(axis=1), p.eps))[:, None], (1, p.T))


def search(p: Problem, lib: list[Term], start: list[Term] | None = None, steps: int = 40) -> Fit:
    """Stepwise selection by BIC (see the module's docstring), with swaps of a term for an alias
    when nothing added helps."""
    terms = list(start or [])
    for t in list(terms):
        if t.kind == "chain":
            terms += [i for i in inits(t) if i not in terms]
    cur = fit(p, terms)
    cur = backward(p, cur)
    for _ in range(steps):
        p.check()
        w = _weights(p, cur)
        cands = [t for t in lib if t not in cur.terms]
        best = None
        for t in screen(p, cur, cands, w) if cands else []:
            g = fit(p, _with(cur.terms, t), w)
            if best is None or g.bic < best.bic:
                best = g
        if best is None or best.bic >= cur.bic - 1e-9:
            best = None
            for t in [u for u in cur.terms if u.kind != "init" and u.span is None]:
                for a in aliases(t, lib):
                    if a in cur.terms:
                        continue
                    g = fit(p, _with(_without(cur.terms, t), a), w)
                    if best is None or g.bic < best.bic:
                        best = g
            for t1, t2, mv in merges(cur.terms, lib):
                terms = [u for u in cur.terms if u not in (t1, t2)]
                if t2.kind == "chain":
                    terms = [u for u in terms if not (u.kind == "init" and u.chain_key() == t2.chain_key())]
                g = fit(p, _with(terms, mv), w)
                if best is None or g.bic < best.bic:
                    best = g
            if best is None or best.bic >= cur.bic - 1e-9:
                break
        cur = backward(p, best)
    return cur


def backward(p: Problem, cur: Fit) -> Fit:
    """Drop terms (zeros first, then whichever removal lowers BIC most) while BIC falls."""
    while True:
        w = _weights(p, cur)
        zero = [t for t, th in zip(cur.terms, cur.theta) if th <= 0 and t.kind != "init"]
        if zero:
            terms = cur.terms
            for t in zero:
                terms = _without(terms, t)
            g = fit(p, terms, w)
            if g.bic <= cur.bic + 1e-9:
                cur = g
                continue
        best = None
        for t in [u for u in cur.terms if u.kind != "init"]:
            g = fit(p, _without(cur.terms, t), w)
            if best is None or g.bic < best.bic:
                best = g
        if best is None or best.bic >= cur.bic - 1e-9:
            return cur
        cur = best


def conventions(p: Problem, cur: Fit, lib: list[Term]) -> Fit:
    """A link into b reading a, beside an outflow of a at the same driver at least as large, is
    written as the move it equals on average (the outflow keeps the rest): the same means and the
    same count of numbers, kept unless the likelihood says otherwise (with counts, the move's
    draw leaves a as it arrives in b)."""
    have = set(lib)
    for _ in range(len(cur.terms)):
        th = dict(zip(cur.terms, cur.theta))
        done = False
        for t2 in cur.terms:
            if t2.kind not in ("link", "plink") or th[t2] <= 0:
                continue
            for a in dict.fromkeys(i for i in t2.x if i < p.S):
                t1 = Term("out", src=a, x=t2.x)
                mv = Term("move", src=a, dst=t2.dst, x=t2.x)
                if t1 not in th or mv not in have or mv in th or th[t1] < th[t2] * 0.999:
                    continue
                if len(t2.x) == 2 and th[t1] > th[t2] * 1.05:
                    continue           # at a product, only a whole move: predation removing X at one rate
                                       # and breeding Y at another is two flows, not a move and an outflow (127)
                g = fit(p, [u for u in cur.terms if u != t2] + [mv])
                if g.bic <= cur.bic + 1e-6 * max(1.0, abs(cur.bic)):
                    cur, done = g, True
                    break
            if done:
                break
        if not done:
            return cur
    return cur
