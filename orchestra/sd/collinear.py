"""Sets of counters that are one: a small set of a balance's counters whose signed sum is nothing
(``cancel``), or is exactly another counter (``merge``), and an event counter that is the sum of
the machine counters that count the same events apart (``decompose``).

The balance search changes one counter at a time, so it cannot leave such a set by itself: each
member alone is a big change for the worse. Here the set is traded as a whole, when the objective
(squared error plus a penalty per counter) falls. A set counts as equal to its stand-in when the
two differ in at most ``CANCEL_STEPS`` of the steps either moved in: counters stamped a moment
apart put the odd event in the next step."""

from __future__ import annotations

from itertools import combinations

CANCEL_SIZE = 4         # a cancelling or collinear set is at most this many counters
CANCEL_STEPS = 0.1      # ... whose signed sum differs from its stand-in in at most this share of the steps it moved in
CANCEL_SHARE = 0.05     # ... and (for cancel) whose removal costs less than this share of the level's variance (or its penalty)


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


def merge(coef: dict[int, int], resid: list[float], sse: float, xs: list[list[float]], g: list[list[float]],
          cost: list[float], objective) -> tuple[dict[int, int], list[float], float]:
    """Replace a small set of the chosen counters by the one unchosen counter that equals their
    signed sum (``order.queued − app_orders − returns − failed`` is ``orders_taken``), when the
    objective falls: the one counter costs one penalty where the set cost several. The mirror of
    ``cancel``. ``g`` is the counters' Gram matrix, which says cheaply whether a counter is near a
    sum before the steps are compared; ``objective(sse, charge)`` is the search's, ``charge`` the
    chosen counters' ``cost`` summed."""
    n, m = len(resid), len(xs)
    changed = True
    while changed and len(coef) >= 2:
        changed = False
        free = [k for k in range(m) if k not in coef and any(xs[k])]
        for size in range(2, min(CANCEL_SIZE, len(coef)) + 1):
            for sub in combinations(sorted(coef), size):
                norm = sum(coef[j] * coef[l] * g[j][l] for j in sub for l in sub)
                if norm <= 0:
                    continue
                s = None
                for k in free:
                    for t in (1, -1):
                        if norm - 2 * t * sum(coef[j] * g[j][k] for j in sub) + g[k][k] > 0.5 * norm:
                            continue
                        if s is None:
                            s = [sum(coef[j] * xs[j][i] for j in sub) for i in range(n)]
                        moved = sum(1 for i in range(n) if s[i] or xs[k][i])
                        if not moved or sum(1 for i in range(n) if abs(s[i] - t * xs[k][i]) > 0.5) > CANCEL_STEPS * moved:
                            continue
                        r2 = [r + a - t * b for r, a, b in zip(resid, s, xs[k])]
                        e = sum(r * r for r in r2)
                        after = {j: v for j, v in coef.items() if j not in sub} | {k: t}
                        if objective(e, sum(cost[j] for j in after)) < objective(sse, sum(cost[j] for j in coef)) - 1e-9:
                            coef, resid, sse, changed = after, r2, e, True
                            break
                    if changed:
                        break
                if changed:
                    break
            if changed:
                break
    return coef, resid, sse


def decompose(counter, candidates: list, steps: list[int], *, sizes=(2, 3), required: set[str] | None = None,
              floor: float = 0.0, own: set[str] | None = None) -> list | None:
    """The one to three ``candidates`` whose sum is this counter in all but ``CANCEL_STEPS`` of the
    steps either moved in: the counters that count the same events apart (Orchestra's
    ``order.rejected`` is the machines' returns plus refunds; yelp's reviews are the customers
    served plus those who gave up). One such counter is cheaper for a balance than the parts, and a
    part with a single event can never pay its way alone; but with the parts each flow is drawn
    between the stocks that exchange it, where the one counter goes through outside. ``required``:
    at least one of the parts must be among these keys (a counter another stock's balance claims:
    evidence that the parts are flows of their own); ``floor``: a sum of several parts needs at
    least this many events, a coincidence of rare counters being cheap. Among sets that differ in
    equally few steps, the one with the fewest parts another machine wrote wins (``own``: the keys
    of the level's own machine's counters; a board's count of its events is its own transitions
    counted apart, which another machine's copy of one of them only mirrors), then the smallest.
    None when no set fits."""
    y = [counter.deltas[i] for i in steps]
    total = sum(y)
    if total <= 0:
        return None
    pool = [c for c in candidates if c is not counter]
    xs = [[c.deltas[i] for i in steps] for c in pool]
    wanted = [required is None or c.key in required for c in pool]
    foreign = [own is not None and c.key not in own for c in pool]
    sums = [sum(x) for x in xs]
    best = None                                   # (steps that differ, parts another machine wrote, size, parts)
    for size in sizes:
        if size > 1 and total < floor:
            continue
        for sub in combinations(range(len(pool)), size):
            if not any(wanted[j] for j in sub) or abs(sum(sums[j] for j in sub) - total) > max(1.0, 0.03 * total):
                continue
            s = [sum(xs[j][i] for j in sub) for i in range(len(y))]
            moved = sum(1 for a, b in zip(s, y) if a or b)
            differ = sum(1 for a, b in zip(s, y) if abs(a - b) > 0.5)
            key = (differ, sum(1 for j in sub if foreign[j]), size)
            if moved and differ <= CANCEL_STEPS * moved and (best is None or key < best[:3]):
                best = (*key, [pool[j] for j in sub])
                if key[:2] == (0, 0):
                    return best[3]
    return best[3] if best else None
