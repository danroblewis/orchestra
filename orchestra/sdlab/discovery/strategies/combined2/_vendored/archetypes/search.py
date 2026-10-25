# Vendored for combined2 from sdlab/discovery/strategies/archetypes/search.py at commit 3c3e009 (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""The search over term sets: every model fitted by its free run and priced by AICc.

- One stock: every subset of its five terms (a constant inflow, growth, a drain, crowding as a gain
  or as a loss) is fitted.
- More stocks: forward selection from the empty model (each round screens every library term by
  how much of the one-step residual it explains, fits the best few exactly by their free run and
  keeps the best AICc), with backward elimination after each addition; and backward elimination
  from a signed Lotka-Volterra start (each stock's per-capita change regressed on 1 and every level,
  each monomial routed as a gain or a loss by its sign), because a forward search is myopic when
  two terms only help together (a predator's gain and the prey's loss).
"""

from __future__ import annotations

import itertools
import math
import time

import numpy as np
from scipy.optimize import nnls

from .fit import Data, Fit, fit
from .families import families
from .terms import Term, effect_on, features, library


def onestep(D: Data, Z: np.ndarray | None = None):
    """(levels before each step after injections, the measured stocks' changes): what one-step
    regressions read. Z: every stock's levels (the hidden ones from a fit), else the measured ones."""
    Z = D.Y if Z is None else Z
    prev = Z[:, :-1] + D.inj[1:, : Z.shape[0]].T
    return prev, D.Y[:, 1:] - prev[: D.m]


def levels(D: Data, warm: Fit | None) -> np.ndarray:
    """The measured levels, with the hidden stocks' levels from a fit below them."""
    if D.hidden == 0:
        return D.Y
    return np.vstack([D.Y, warm.X[D.m:]])


def init_theta(terms: list[Term], D: Data, fixed: np.ndarray | None = None, Z: np.ndarray | None = None) -> np.ndarray:
    """theta >= 0 by non-negative least squares of the measured stocks' one-step changes (weighted by
    the errors' sizes); the first len(fixed) numbers are held."""
    if not terms:
        return np.zeros(0)
    prev, dy = onestep(D, Z)
    E = effect_on(terms, D.m + D.hidden)[: D.m]
    F = features(terms, prev)
    w = (D.W[:, 1:] * D.scale[:, None])
    A = np.concatenate([(E[i][:, None] * F / w[i]).T for i in range(D.m)])
    y = np.concatenate([dy[i] / w[i] for i in range(D.m)])
    k = 0 if fixed is None else len(fixed)
    if k:
        y = y - A[:, :k] @ fixed
    if k == len(terms):
        return np.asarray(fixed, dtype=float)
    th, _ = nnls(A[:, k:], y, maxiter=2000)
    return np.concatenate([fixed, th]) if k else th


def fit_set(terms: list[Term], D: Data, cache: dict, warm: Fit | None = None) -> Fit:
    """terms fitted by their free run: from the warm fit's numbers (its terms that are kept; new ones
    by least squares of what it leaves of the one-step changes) and, without hidden stocks, also from
    a plain one-step start; the better is kept."""
    key = frozenset(terms)
    if key in cache:
        return cache[key]
    tries = []
    if warm is not None:
        kept = [t for t in warm.terms if t in terms]
        order = kept + [t for t in terms if t not in kept]
        fixed = np.array([warm.theta[warm.terms.index(t)] for t in kept])
        tries.append(fit(order, D, init_theta(order, D, fixed=fixed, Z=levels(D, warm)), warm.x0.copy()))
    if D.hidden == 0 or warm is None:
        x0 = np.concatenate([D.Y[:, 0], np.zeros(D.hidden)]) if warm is None else warm.x0.copy()
        tries.append(fit(terms, D, init_theta(terms, D) if D.hidden == 0 else np.full(len(terms), 0.1), x0))
    f = min(tries, key=lambda g: (g.aicc, g.nll))
    cache[key] = f
    return f


def screen(model: Fit, cands: list[Term], D: Data, top: int) -> list[Term]:
    """The candidates that explain most of the model's one-step residual (by projection)."""
    prev, dy = onestep(D, levels(D, model))
    E = effect_on(model.terms, D.m + D.hidden)[: D.m]
    F = features(model.terms, prev)
    res = dy - E @ (model.theta[:, None] * F) if model.terms else dy
    w = D.W[:, 1:] * D.scale[:, None]
    gains = []
    Fc = features(cands, prev)
    Ec = effect_on(cands, D.m + D.hidden)[: D.m]
    for q, t in enumerate(cands):
        col = Ec[:, q][:, None] * Fc[q][None, :] / w
        r = res / w
        den = float(np.sum(col * col))
        num = float(np.sum(col * r))
        gains.append(num * num / den if den > 0 and num > 0 else 0.0)
    order = np.argsort(gains)[::-1]
    return [cands[i] for i in order[:top]]


def stepwise(D: Data, lib: list[Term], start: list[Term] | Fit, cache: dict, deadline: float, top: int = 6,
             locked: frozenset = frozenset()) -> Fit:
    cur = start if isinstance(start, Fit) else fit_set(start, D, cache)
    max_terms = len(lib) + len(locked)
    improved = True
    while improved and time.perf_counter() < deadline:
        improved = False
        if cur.size < max_terms:
            cands = [t for t in lib if t not in cur.terms]
            best = cur
            for t in screen(cur, cands, D, top) if cands else []:
                f = fit_set(cur.terms + [t], D, cache, warm=cur)
                if f.aicc < best.aicc - 1e-9:
                    best = f
                if time.perf_counter() > deadline:
                    break
            if best is not cur:
                cur, improved = best, True
        cur, dropped = backward(cur, D, cache, deadline, locked)
        improved = improved or dropped
    return cur


def backward(cur: Fit, D: Data, cache: dict, deadline: float, locked: frozenset = frozenset()) -> tuple[Fit, bool]:
    changed = False
    while cur.terms and time.perf_counter() < deadline:
        best = cur
        for t in cur.terms:
            if t in locked:
                continue
            rest = [u for u in cur.terms if u != t]
            f = fit_set(rest, D, cache, warm=cur)
            if f.aicc < best.aicc - 1e-9:
                best = f
        if best is cur:
            break
        cur, changed = best, True
    return cur, changed


def glv_start(D: Data) -> list[Term]:
    """Each stock's per-capita change regressed (signs free) on 1 and every level; each monomial
    routed as a gain (in) or a loss (out) by its sign."""
    prev, dy = onestep(D)
    out = []
    for i in range(D.m):
        ok = prev[i] > 1e-9
        if ok.sum() < D.m + 2:
            continue
        A = np.vstack([np.ones(ok.sum())] + [prev[j][ok] for j in range(D.m)]).T
        y = dy[i][ok] / prev[i][ok]
        w = prev[i][ok] / (D.W[i, 1:][ok])                   # back to the changes' own error scale
        coef, *_ = np.linalg.lstsq(A * w[:, None], y * w, rcond=None)
        out.append(Term(None, i, (i,)) if coef[0] >= 0 else Term(i, None, (i,)))
        for j in range(D.m):
            mono = tuple(sorted((i, j)))
            out.append(Term(None, i, mono) if coef[1 + j] >= 0 else Term(i, None, mono))
    return out


def signed(D: Data, terms: list[Term], cache: dict) -> Fit:
    """A structure whose monomials each may be a gain or a loss: every monomial fitted as both (two
    numbers >= 0 whose difference is the net), then each written as its net's direction and refitted
    from there; the pair's twin number is not counted (the result is cached as its plain terms)."""
    flip = lambda t: Term(None, t.src, t.mono) if t.dst is None else Term(t.dst, None, t.mono)  # noqa: E731
    both = list(dict.fromkeys([u for t in terms for u in (t, flip(t))]))
    f = fit_set(both, D, cache)
    net: dict[tuple, float] = {}
    for t, th in zip(f.terms, f.theta):
        i = t.dst if t.src is None else t.src
        net[(i, t.mono)] = net.get((i, t.mono), 0.0) + (th if t.src is None else -th)
    out = [Term(None, i, mono) if v >= 0 else Term(i, None, mono) for (i, mono), v in net.items() if v != 0]
    key = frozenset(out)
    if key in cache:
        return cache[key]
    order = [t for t in out]
    th0 = np.array([abs(net[(t.dst if t.src is None else t.src, t.mono)]) for t in order])
    g = fit(order, D, th0, f.x0.copy())
    cache[key] = g
    return g


def conserved(Y: np.ndarray) -> bool:
    """The measured stocks' total stays the same at every sample (to the data's rounding): nothing
    enters or leaves, so every flow is a move between them (shares of one population)."""
    if Y.shape[0] < 2:
        return False
    tot = Y.sum(axis=0)
    return float(np.ptp(tot)) <= 1e-6 * max(1.0, float(np.mean(np.abs(tot)))) + 1e-3


def search(D: Data, seconds: float, moves: bool = True, price: bool = True) -> Fit:
    """The best structure by AICc, a structure the search composed paying `extra` per term (the
    risk-inflation price of choosing among the library's terms, 2 log(library size) - 2 more than
    AICc's 2) unless it is one of the archetypes (families.py) or a subset of the one-stock library
    as small as the archetype it extends."""
    deadline = time.perf_counter() + seconds
    cache: dict = {}
    lib = library(D.m, moves=moves)
    prev, dy = onestep(D)
    glv = glv_start(D)
    fams = families(D.m, dy.mean(axis=1), glv)
    if D.allow is not None:                               # (boundary: docs/research/declared-boundary.md): outside terms only on declared sides
        lib = [t for t in lib if D.allow(t)]
        glv = [t for t in glv if D.allow(t)]
        fams = {k: [t for t in v if D.allow(t)] for k, v in fams.items()}
        fams = {k: v for k, v in fams.items() if v}
    if conserved(D.Y):                                    # a closed total: only moves between the stocks
        lib = [t for t in lib if t.kind == "move"]
        fams = {k: v for k, v in fams.items() if v and all(t.kind == "move" for t in v)}
        fams["linear moves"] = [t for t in lib if len(t.mono) == 1]
        glv = []
    extra = max(0.0, 2 * math.log(len(lib)) - 2) if price else 0.0
    named = {frozenset(v): k for k, v in fams.items()}
    found: list[Fit] = [fit_set([], D, cache)]
    for k, v in fams.items():                                 # every archetype, whatever the time: they are few
        g = signed(D, v, cache) if k == "generalised Lotka-Volterra" else fit_set(v, D, cache)
        named.setdefault(frozenset(g.terms), k)
        found.append(g)
        # an archetype with terms the data do not need is that archetype's simpler form (no search price)
        h, _ = backward(g, D, cache, math.inf)
        named.setdefault(frozenset(h.terms), k)
        found.append(h)
    if D.m == 1:
        for r in range(len(lib) + 1):
            for sub in itertools.combinations(lib, r):
                found.append(fit_set(list(sub), D, cache))
    else:
        found.append(stepwise(D, lib, [], cache, deadline))
        if glv and time.perf_counter() < deadline:
            f0, _ = backward(fit_set(glv, D, cache), D, cache, deadline)
            found.append(stepwise(D, lib, f0.terms, cache, deadline))
    for f in found:
        key = frozenset(f.terms)
        f.family = named.get(key, "none" if not f.terms else "search")
        f.score = f.aicc + (extra * f.size if f.family == "search" else 0.0)
    return min(found, key=lambda f: f.score if math.isfinite(f.score) else math.inf)
