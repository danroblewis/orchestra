"""A level balanced by counters slower than the grid: judged on the stretches between their writes.

Discovery reads every series on one grid of steps. A counter another store reports once a minute
(or scrapes once a minute and is read every 30 s) moves only in the steps its counts arrive in:
two minutes' worth in one step and none in the next. On single steps it never balances a level
read every 15 s, however exactly it counts the level's outflow: the level changed in both steps,
the counter in one (the metrics lab: a queue read at 15 s from one store, its inflow from the same
store, its outflow from a second store at 60 s; R² −0.98 on steps, where published − sent matched
the level's change to 0.7% over the hour).

So a level's balance is also searched on the stretches between a slow counter's writes
(``sd.resolution.Block``): there every series is read at the same two instants from its own points
(a counter are compared on a common grid, the slower one's. A level whose balance on steps is exact
needs no other grid. The coarse balance is kept when it uses a slow counter and fits where the
balance on steps does not, or is exact where the balance on steps fits only roughly (a lag read
every 30 s beside its topic's offsets read every minute: on steps, CPU periods and orders placed
"fit" the incident's rise at R² 0.98; on the minutes, produced less consumed is exact); the level is then
judged on those stretches throughout (``Series.blocks``), its identification included. The steps after the slow counter's last write
are no stretch: what it counted there has not arrived (``sd.series.arrived_until``)."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from .balance import LeastSquares, balance, columns
from .identify import FLAG_EXACT

PATTERNS = 2            # the most common write patterns among the slow counters tried (one per store and phase, as a rule)


def patterns(counters: list) -> list[list[tuple[int, float]]]:
    """The slow counters' write patterns (the steps their counts arrive in), most common first."""
    seen = Counter(tuple(c.blocks) for c in counters if c.blocks)
    return [list(p) for p, _ in seen.most_common(PATTERNS)]


def on_writes(level, blocks: list[tuple[int, float]]):
    """The level read on another series' writes: a copy judged on the stretches between them."""
    view = replace(level, blocks=blocks)
    view.__dict__.pop("_deltas", None)
    return view


def slowest(terms: list) -> list[tuple[int, float]] | None:
    """The write pattern of a balance's slowest counter (fewest writes), or None when none is slow."""
    slow = [c for c, _ in terms if c.blocks]
    return min(slow, key=lambda c: len(c.blocks)).blocks if slow else None


def coarse(level, counters: list, steps: list[int], got: tuple, fits, solvers: dict, key: tuple) -> tuple:
    """The level's balance on the stretches between slow counters' writes, when ``got`` (its balance
    on steps: terms, R², exact share) does not fit and the coarse one does, with a slow counter; the level then
    takes those stretches as its units (``level.blocks``). ``solvers`` caches the counters' least
    squares by ``key`` and pattern."""
    terms, r2, exact = got
    on_steps = bool(terms) and fits(level, r2, exact, terms, steps)
    if level.blocks is not None or (on_steps and exact >= FLAG_EXACT):
        return got
    best = None
    for pattern in patterns(counters):
        view = on_writes(level, pattern)
        k = (*key, tuple(pattern))
        if k not in solvers:
            solvers[k] = LeastSquares(columns(view, counters, steps))
        t, r, e = balance(view, counters, solvers[k], steps)
        if any(c.blocks for c, _ in t) and fits(view, r, e, t, steps) and (best is None or r > best[2]):
            best = (pattern, t, r, e)
    if best is None or (on_steps and best[3] < FLAG_EXACT):
        return got
    level.blocks = best[0]
    return best[1], best[2], best[3]
