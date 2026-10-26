"""A level's balance: the counters, each added or subtracted, that explain its changes.

``Δlevel ≈ Σ inflows − Σ outflows`` in every step. The counters are found by a local search on an
objective of squared error plus a penalty per counter used, so a counter must explain a real share
to be kept: at least ``MIN_GAIN`` of the level's variance, and at least one event's worth of
squared change (``EVENT_FLOOR``), because on a level that barely moves one per cent of its variance
is less than the noise of a single step at the edge of the window."""

from __future__ import annotations

import math
from itertools import combinations

MIN_GAIN = 0.01         # each counter must explain at least this share of the level's variance
EVENT_FLOOR = 1.0       # ... and at least one event's worth of squared change
MAX_TERMS = 8
CANCEL_SIZE = 4         # a cancelling set is at most this many counters
CANCEL_STEPS = 0.1      # ... whose signed sum is non-zero in at most this share of the steps it moved in
CANCEL_SHARE = 0.05     # ... and whose removal costs less than this share of the level's variance (or its penalty)


class LeastSquares:
    """Ordinary least squares of any level's changes on every counter's changes at once. The
    normal matrix is the same for every level, so it is factored once (Cholesky, lightly
    regularised so collinear counters don't break it)."""

    def __init__(self, xs: list[list[float]]):
        self.xs = xs
        m = len(xs)
        g = [[sum(a * b for a, b in zip(xs[i], xs[j])) for j in range(m)] for i in range(m)]
        ridge = 1e-6 * (sum(g[i][i] for i in range(m)) / max(1, m)) + 1e-12
        for i in range(m):
            g[i][i] += ridge
        self.L = [[0.0] * m for _ in range(m)]
        for i in range(m):
            for j in range(i + 1):
                v = g[i][j] - sum(self.L[i][k] * self.L[j][k] for k in range(j))
                self.L[i][j] = math.sqrt(max(v, 1e-18)) if i == j else v / self.L[j][j]

    def solve(self, y: list[float]) -> list[float]:
        m, L = len(self.xs), self.L
        b = [sum(a * v for a, v in zip(x, y)) for x in self.xs]
        z = [0.0] * m
        for i in range(m):
            z[i] = (b[i] - sum(L[i][k] * z[k] for k in range(i))) / L[i][i]
        c = [0.0] * m
        for i in reversed(range(m)):
            c[i] = (z[i] - sum(L[k][i] * c[k] for k in range(i + 1, m))) / L[i][i]
        return c


def penalty(sst: float) -> float:
    """What one counter in a balance costs, for a level with this variance of its changes."""
    return max(MIN_GAIN * sst, EVENT_FLOOR)


def balance(level, counters: list, ls: LeastSquares | None = None) -> tuple[list[tuple], float, float]:
    """The counters (each +1 or −1) that best explain the level's changes; and the balance's R²
    and the share of steps it explains exactly.

    The search starts from least squares on all counters, each coefficient rounded to +1, −1 or
    0, and then repeatedly applies the change that lowers the objective most (any counter to +1,
    −1 or 0, or one chosen counter swapped for another), until none does. Starting from least
    squares matters: one term of a balance alone often makes the fit worse (inflow without its
    outflows), so a search that adds terms one at a time misses it. Last, any small set of chosen
    counters that cancels to nothing is dropped (``cancel``)."""
    y = level.deltas
    mean = sum(y) / len(y)
    sst = sum((v - mean) ** 2 for v in y) or 1e-12
    pen = penalty(sst)
    # a machine's own measurement (labelled machine=…) is preferred over Orchestra's generic event
    # count of the same thing when the two fit about equally: it costs a little less to use
    cost = [pen * (1.0 if c.labels.get("machine") else 1.1) for c in counters]
    xs = [c.deltas for c in counters]
    live = [j for j, x in enumerate(xs) if any(x)]
    coef: dict[int, int] = {}
    if ls is not None:
        for j, v in enumerate(ls.solve(y)):
            if abs(v) >= 0.5 and j in live:
                coef[j] = 1 if v > 0 else -1
        if len(coef) > MAX_TERMS:
            coef = {}
    resid = [v - sum(sign * xs[j][i] for j, sign in coef.items()) for i, v in enumerate(y)]
    sse = sum(r * r for r in resid)
    for _ in range(4 * MAX_TERMS):
        best = None                                   # (gain, changes {j: new coefficient}, sse after)
        for j in live:                                # change one counter's coefficient
            old = coef.get(j, 0)
            for new in (-1, 0, 1):
                if new == old or (new and not old and len(coef) >= MAX_TERMS):
                    continue
                d = new - old
                e = sum((r - d * v) ** 2 for r, v in zip(resid, xs[j]))
                gain = (sse - e) - cost[j] * ((new != 0) - (old != 0))
                if gain > 1e-9 and (best is None or gain > best[0]):
                    best = (gain, {j: new}, e)
        for j, sign in list(coef.items()):            # swap a chosen counter for another, same sign:
            for k in live:                            # near-identical counters can't be swapped one step at a time
                if k in coef:
                    continue
                e = sum((r + sign * a - sign * b) ** 2 for r, a, b in zip(resid, xs[j], xs[k]))
                gain = (sse - e) - (cost[k] - cost[j])
                if gain > 1e-9 and (best is None or gain > best[0]):
                    best = (gain, {j: 0, k: sign}, e)
        if best is None:
            break
        _, changes, e = best
        for j, new in changes.items():
            d = new - coef.get(j, 0)
            resid = [r - d * v for r, v in zip(resid, xs[j])]
            if new:
                coef[j] = new
            else:
                coef.pop(j, None)
        sse = e
    coef, resid, sse = cancel(coef, resid, sse, xs, pen, sst)
    chosen = [(counters[j], sign) for j, sign in sorted(coef.items())]
    exact = sum(1 for r in resid if abs(r) <= 0.5) / len(resid)
    return chosen, 1 - sse / sst, exact


def cancel(coef: dict[int, int], resid: list[float], sse: float, xs: list[list[float]], pen: float, sst: float
           ) -> tuple[dict[int, int], list[float], float]:
    """Drop any small set of the chosen counters whose signed sum is about zero in every step: two
    near-identical counters with opposite signs, or a triple like ``+made −baked −late`` that is
    identically zero. Such a set explains nothing and only soaks up noise, and the search cannot
    remove it one counter at a time (each alone is a big change). It goes when removing it costs
    less than it is charged (its size × the penalty) or less than ``CANCEL_SHARE`` of the variance."""
    changed = True
    while changed and len(coef) >= 2:
        changed = False
        n = len(resid)
        for size in range(2, min(CANCEL_SIZE, len(coef)) + 1):
            for sub in combinations(sorted(coef), size):
                s = [sum(coef[j] * xs[j][i] for j in sub) for i in range(n)]
                moved = sum(1 for i in range(n) if any(xs[j][i] for j in sub))
                if not moved or sum(1 for v in s if abs(v) > 0.5) > CANCEL_STEPS * moved:
                    continue
                r2 = [r + v for r, v in zip(resid, s)]
                e = sum(r * r for r in r2)
                if e - sse < max(CANCEL_SHARE * sst, size * pen):
                    resid, sse = r2, e
                    for j in sub:
                        coef.pop(j)
                    changed = True
                    break
            if changed:
                break
    return coef, resid, sse


def explained_share(level, terms: list[tuple], counter) -> float:
    """How much of the level's variance this counter of its balance explains: the rise in the
    balance's squared error when the counter is taken out, as a share of the variance."""
    y = level.deltas
    mean = sum(y) / len(y)
    sst = sum((v - mean) ** 2 for v in y) or 1e-12
    resid = [v - sum(sign * c.deltas[i] for c, sign in terms) for i, v in enumerate(y)]
    sign = next((sg for c, sg in terms if c is counter), 0)
    without = [r + sign * x for r, x in zip(resid, counter.deltas)]
    return (sum(r * r for r in without) - sum(r * r for r in resid)) / sst
