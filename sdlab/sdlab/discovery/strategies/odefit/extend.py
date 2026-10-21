"""Terms beyond the linear ones, each kept only when BIC says the data earn it.

  products  every product of two levels (a square too: crowding, a concave or convex drain) as a
            column of every row, fitted with the linear terms by output error, then pruned
  hinges    for one stock, sign x max(0, h . [levels, inputs, 1]): a linear rate whose floor at 0
            binds (a switch, a controller that shuts off); started from the one-step fit of
            max(0, o (x_j - q)) over each level and input j, both directions o and three knots q
"""

from __future__ import annotations

import numpy as np

from . import fit as F


FAMILIES = {"products": lambda a, b: True, "squares": lambda a, b: a == b, "cross products": lambda a, b: a != b}


def with_products(spec: F.Spec, W: np.ndarray, family: str = "products") -> tuple[F.Spec, np.ndarray]:
    """spec with the products of the family (all; squares only; cross products only) on every row."""
    S = spec.S
    keep = FAMILIES[family]
    prods = [(a, b) for a in range(S) for b in range(a, S) if keep(a, b)]
    sp = F.Spec(S, spec.m, prods, hinges=spec.hinges, roots=spec.roots, region=spec.region)
    sp.mask[:, : spec.S + spec.m + 1] = spec.mask[:, : spec.S + spec.m + 1]
    W2 = np.zeros((S, sp.P))
    W2[:, : spec.S + spec.m + 1] = W[:, : spec.S + spec.m + 1]
    return sp, W2


def with_roots(spec: F.Spec, W: np.ndarray) -> tuple[F.Spec, np.ndarray]:
    """spec (linear) with the square root of every level on every row: a flow through a hole (the
    outflow of a tank, k sqrt(level)) and what it delivers downstream."""
    S = spec.S
    sp = F.Spec(S, spec.m, hinges=spec.hinges, roots=list(range(S)), region=spec.region)
    sp.mask[:, : spec.S + spec.m + 1] = spec.mask[:, : spec.S + spec.m + 1]
    W2 = np.zeros((S, sp.P))
    W2[:, : spec.S + spec.m + 1] = W[:, : spec.S + spec.m + 1]
    return sp, W2


def hinge_starts(spec: F.Spec, d: F.Data, W: np.ndarray, stock: int) -> list[tuple[float, int, np.ndarray]]:
    """(one-step rss, sign, h) for single-variable hinges on `stock`, best first."""
    X = (d.Y[:-1] + d.J[1:]).T
    U = d.U[1:].T
    Z = np.vstack([X, U, np.ones((1, X.shape[1]))])          # (S + m + 1) x (n - 1)
    C = F.columns(X, U, spec)
    dy = d.Y[1:, stock] - X[stock]
    cols = np.flatnonzero(spec.mask[stock])
    base = C[cols].T
    out = []
    for j in range(spec.S + spec.m):
        v = Z[j]
        if np.ptp(v) <= 0:
            continue
        for q in np.quantile(v, [0.25, 0.5, 0.75]):
            for o in (1.0, -1.0):
                f = np.maximum(0.0, o * (v - q))
                M = np.column_stack([base, f])
                sc = np.maximum(np.abs(M).max(axis=0), 1e-12)
                coef = np.linalg.lstsq(M / sc, dy, rcond=None)[0] / sc
                rss = float(((M @ coef - dy) ** 2).sum())
                a = coef[-1]
                if a == 0:
                    continue
                h = np.zeros(spec.H)
                h[j] = abs(a) * o
                h[-1] = -abs(a) * o * q
                out.append((rss, int(np.sign(a)), h, coef[:-1]))
    out.sort(key=lambda x: x[0])
    return out


def with_hinge(spec: F.Spec, d: F.Data, W: np.ndarray, stock: int, tries: int = 3) -> list[tuple[F.Spec, np.ndarray]]:
    """Specs with one hinge on `stock` (spec has none yet) and their starting numbers (the best few
    one-step starts, one per variable and direction)."""
    out = []
    seen = set()
    for rss, g, h, coef in hinge_starts(spec, d, W, stock):
        key = (g, int(np.argmax(np.abs(h[:-1]))), float(np.sign(h[np.argmax(np.abs(h[:-1]))])))
        if key in seen:
            continue
        seen.add(key)
        sp = F.Spec(spec.S, spec.m, spec.products, spec.mask, spec.hinges + [(stock, g)], region=spec.region)
        W0 = W.copy()
        W0[stock, np.flatnonzero(spec.mask[stock])] = coef
        theta = np.concatenate([W0[sp.mask], h])
        out.append((sp, theta))
        if len(out) >= tries:
            break
    return out


RUN = 2000           # steps of the runaway check
WIDER = 0.5          # inputs held this share of their range beyond the values seen (both sides)
AWAY = 20.0          # a run that leaves the levels seen by this many ranges has run away


def runs_away(spec: F.Spec, theta: np.ndarray, d: F.Data) -> bool:
    """True when the model, run free for RUN steps from the run's first and last states, with the
    measured inputs repeated or held beyond the values seen (above, and below down to 0), leaves the
    levels seen far behind: a nonlinear term that only fits inside the range seen (a square that
    turns a drain into growth past its top)."""
    lo, hi = d.Y.min(axis=0), d.Y.max(axis=0)
    span = np.maximum(hi - lo, 1e-9)
    n = RUN
    settings = [np.resize(d.U, (n, d.m))]
    if d.m:
        ulo, uhi = d.U.min(axis=0), d.U.max(axis=0)
        uspan = uhi - ulo
        settings += [np.tile(uhi + WIDER * uspan, (n, 1)), np.tile(np.maximum(0.0, ulo - WIDER * uspan), (n, 1))]
    W, Hs = spec.unpack(theta)
    Z = np.array([[d.Y[0]], [d.Y[-1]]])                                               # 2 x 1 x S
    for U in settings:
        dd = F.Data(np.zeros((n, d.S)), U, np.zeros((n, d.S)))
        with np.errstate(all="ignore"):
            X = F.simulate_batch(np.repeat(W[None], 2, 0), np.repeat(Hs[None], 2, 0), Z, spec, dd, [(0, n)])
        if not np.all(np.isfinite(X)) or np.any(X > hi + AWAY * span) or np.any(X < lo - AWAY * span):
            return True
    return False
