"""Levels no counters balance, as stocks whose net flow is fitted from the other series.

A measured level that no counters balance (a temperature, a river's flow, a tide, a machine's
load, a backlog nobody counts) may still be a stock: something accumulates in it, and what moves
it can be read off the other series. Its **net flow**, the level's change per unit of time, is
fitted by least squares among these forms, on a grid no finer than any series it reads (each at
its own resolution, ``sd.resolution``: a slow series explains nothing faster than itself):

- ``c``: a constant drift (the reference every other form must beat);
- ``c + b × level``: the level relaxing toward a goal (``b`` below zero) or growing on itself;
- ``c + a × X``: driven by another series X (a stock, or a measured level that is not one);
- ``c + a × X + b × level``: driven by X while relaxing.

Forms are scored by AIC against the constant on the same stretches. A form must earn its place:
``EVENTS_PER_PARAM`` changes of the level per parameter (as a counted flow needs ten events per
parameter); an AIC gain over the constant of ``AIC_MARGIN`` plus ``2 ln m`` for the ``m`` forms
tried (the best of a hundred unrelated series beats a constant by chance by about that much),
counting only the stretches that are independent evidence (residuals that run in long swings are
one piece of evidence per swing); the same gain without the one stretch whose change is furthest
from the usual (a fit resting on one jump explains the jump); for a term in the level itself, a t
statistic past ``DF_T``, the 1% critical value of the Dickey–Fuller test, because a level
regressed on its own value finds a pull toward its mean in a pure random walk far more often than
ordinary statistics allow, while keeping at least half of itself from one stretch to the next
(``FORGETS``: one that loses more holds nothing, and is readings scattered around a mean). A
driver must change both ways in at least ``EVENTS_PER_PARAM`` stretches: one that changed once is
a before and an after, and one that only rises stands in for time.

A form that beats the constant must then survive four refutations; the best-scoring form that
survives all four is the net flow:

- **a steady trend in time** (``c + a × t``, ``t`` each stretch's middle) must not explain the
  level's changes as well: the form must beat it by the same AIC margin it beat the constant by.
  Over a few hours any two smooth series fit each other (a tide and a city's power demand: both
  follow the clock), and a trend is the clock itself;
- **the other half of the window**: fitted on either half, the form must predict the other half
  better than the trend, the constant, and each form with one term fewer. Two unrelated series
  that wander alike for a while fit each other on the whole window; the pairing rarely carries;
- **enough explained**: at least ``MIN_NET_R2`` of the level's changes. Below that, noise moves
  the level more than the form does, and a series that merely tends back to its mean (a count of
  processes, a load average) passes every test above with a tenth of its changes explained;
- **the driver read a quarter of the window away** (both earlier and later) must explain clearly
  less of the changes than the driver in place, beyond what the rest of the form explains: below
  ``SHIFTED`` of it. A cause explains the changes it causes when they happen; a series that only
  moves smoothly explains a smooth level as well an hour off.

A level is never driven by another of its own name (a part of it, its total, or another part),
nor by a series that may be its part or its total under another name: counts in the same unit
(whole numbers, and the same last word of the name, ``processes`` in ``claude_processes``) of
which one never rises above the other and swings no wider. A part's changes are in its total's,
so the total "explains" them by containing them. The rule only keeps a driver out; the unit is
read from the name, so two counts in one unit that are not part and total (a repository's bytes
under the disk's free bytes) are kept apart too. A statistic is never tried: one a source
summarised across reporters (an average, a maximum), and one whose name says it is a statistic
(``sd.properties.statistic``: ``mean``, ``max``, a percentile such as ``p95``), such as a shelf's
mean age: it summarises what is there and holds nothing; its changes follow whatever moves the
things it averages. Nor is a resource a process or host uses (``sd.properties.resource``: CPU,
memory, threads, a load average, a utilisation): its work sets it at each moment, so a fit to the
work's series explains it as well as a stock's and says nothing. What is refuted stays an **input**, with the reason: a level whose net flow
nothing explains better than a constant (a random walk, a steady drift), or whose best form a
refutation struck (the reason names it and the check), and one whose changes move with another
series' changes (``SAME_MOVES``: a second measure of the same thing, or a function of it, such as
a demand computed from a rating, is no store of its own). Of two levels that are each other's copy
(one quantity in two stores), one is tried as the stock (``first``: the finer, then the earlier
written) and the other stays its input; when the first is no stock, the other is tried without it,
so corroboration never deletes the stock.

Every accepted driver is a correlation in the data, not an experiment: nothing here has moved the
driver and watched the level answer.

An accepted stock's net flow becomes an inflow (``c + a × X``, or its negative as an outflow when
it is mostly below zero) and an outflow proportional to the stock (``−b × level``), each with
origin ``fitted`` and method ``least-squares``; growth on itself is an inflow proportional to it.
The flows have no counter and no machine: the environment moves them, or a machine not yet
instrumented (``sd.attribute``)."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

from . import stocktrust
from .drivers import AIC_MARGIN, EVENTS_PER_PARAM
from .model import Equation, Flow, Stock
from .properties import resource, statistic
from .resolution import steps_of
from .series import series_key

DF_T = 3.43           # |t| a term in the level itself must reach: Dickey–Fuller's 1% critical value with a constant
SAME_MOVES = 0.9      # a level whose changes another series' changes explain this well (R²) is that series again, or a function of it
SAME_VALUES = 0.05    # ... or half as well, and whose values stay this close to another's, as a share of its range, is that series again
FORGETS = 0.5         # a level that loses more than this share of itself from one stretch to the next keeps nothing: readings around a mean
ONE_WAY = 0.1         # a driver whose changes go the other way in fewer than this share of stretches only rises (or falls): it stands in for time
MIN_NET_R2 = 0.4      # an accepted net flow explains at least this share of the level's changes: below it, noise moves the level more than the form does
SHIFTED = 0.8         # a driver that, moved a quarter of the window earlier or later, still explains this share of what it explains in place is no cause
NET_FLOW = "no counters balance it"     # the reason conservation gives a level these are tried on


@dataclass
class Driver:
    """A series a net flow may read: its values on the grid, its resolution, and how the model
    refers to it (a stock id, or ``input:<name>``)."""

    ref: str
    values: list[float]
    resolution_s: float | None
    key: str
    name: str = ""


@dataclass
class Fit:
    params: dict[str, float]        # c, and a (on the driver) and b (on the level) when the form has them
    driver: Driver | None
    own: bool
    block_s: float
    blocks: int
    changes: int
    r2: float
    aic: float
    aic_constant: float
    t_own: float | None = None
    tried: int = 0
    mean_in: float = 0.0            # the inflow part's mean (c + a × X) over the stretches
    coef: list[float] = field(default_factory=list)     # the fitted coefficients, in the order of the form's columns
    weight: float = 1.0             # the share of the stretches that count as independent evidence (_independent_share)
    notes: dict = field(default_factory=dict)

    @property
    def form(self) -> str:
        return " + ".join(["c", *(["a × " + self.driver.ref] if self.driver else []), *(["b × level"] if self.own else [])])


def _ols(rows: list[list[float]], y: list[float]) -> tuple[list[float], float, list[float]] | None:
    """Least squares with an intercept column already in ``rows``: coefficients, the residual sum
    of squares, and each coefficient's standard error. None when the columns are degenerate."""
    p, n = len(rows[0]), len(rows)
    g = [[sum(r[i] * r[j] for r in rows) for j in range(p)] for i in range(p)]
    b = [sum(r[i] * v for r, v in zip(rows, y)) for i in range(p)]
    inv = _inverse(g)
    if inv is None:
        return None
    coef = [sum(inv[i][j] * b[j] for j in range(p)) for i in range(p)]
    rss = sum((v - sum(c * x for c, x in zip(coef, r))) ** 2 for r, v in zip(rows, y))
    s2 = rss / max(1, n - p)
    return coef, rss, [math.sqrt(max(0.0, s2 * inv[i][i])) for i in range(p)]


def _inverse(m: list[list[float]]) -> list[list[float]] | None:
    n = len(m)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(a[r][c]))
        if abs(a[piv][c]) < 1e-12 * max(1.0, max(abs(x) for row in m for x in row)):
            return None
        a[c], a[piv] = a[piv], a[c]
        d = a[c][c]
        a[c] = [x / d for x in a[c]]
        for r in range(n):
            if r != c and a[r][c]:
                f = a[r][c]
                a[r] = [x - f * y for x, y in zip(a[r], a[c])]
    return [row[n:] for row in a]


def _independent_share(resid: list[float]) -> float:
    """The share of the stretches that count as independent, from the residuals' correlation with
    the stretch before (``(1 − ρ) / (1 + ρ)``): a smooth series misfitted by a form leaves residuals
    that run in long swings, each swing one piece of evidence however many stretches it spans."""
    mean = sum(resid) / len(resid)
    d = [r - mean for r in resid]
    var = sum(x * x for x in d)
    rho = sum(a * b for a, b in itertools.pairwise(d)) / var if var > 0 else 0.0
    rho = min(0.99, max(0.0, rho))
    return (1 - rho) / (1 + rho)


def _without_largest(rows: list[list[float]], y: list[float], w: float, margin: float) -> bool:
    """Whether the form still beats a constant by the margin without the stretch whose change is
    furthest from the usual one: a fit that rests on one jump (a disk filled when a program
    started, then a steady trickle) explains that jump, not the level."""
    med = sorted(y)[len(y) // 2]
    drop = max(range(len(y)), key=lambda i: abs(y[i] - med))
    keep = [i for i in range(len(y)) if i != drop]
    base, got = _ols([[1.0] for _ in keep], [y[i] for i in keep]), _ols([rows[i] for i in keep], [y[i] for i in keep])
    if base is None or got is None:
        return False
    return w * len(keep) * math.log(max(base[1], 1e-12) / max(got[1], 1e-12)) - 2 * (len(rows[0]) - 1) >= margin


def _aic(rss: float, n: int, p: int) -> float:
    return n * math.log(max(rss, 1e-12) / n) + 2 * p


def _stretches(live: set[int], n: int, k: int) -> list[int]:
    """The starts of the stretches of ``k`` grid steps, from the window's start, whose every step
    is live."""
    return [j * k for j in range(n // k) if all(i in live for i in range(j * k, (j + 1) * k))]


def _mean(values: list[float], a: int, k: int) -> float:
    return sum(values[a:a + k + 1]) / (k + 1)


def _holds_out(rows: list[list[float]], y: list[float], full: list[int], simpler: list[list[int]]) -> bool:
    """Whether a form (``full``: the columns of ``rows`` it reads) fitted on one half of the
    stretches predicts the other half (both ways) better than each simpler form (``simpler``: the
    columns each reads), a steady trend in time among them. Two unrelated series that wander alike
    for a while fit each other on the whole window; the pairing rarely carries from one half to
    the other."""
    h = len(y) // 2
    halves = [(range(h), range(h, len(y))), (range(h, len(y)), range(h))]

    def out_of_sample(cols: list[int]) -> float:
        err = 0.0
        for fit_on, test_on in halves:
            got = _ols([[rows[i][c] for c in cols] for i in fit_on], [y[i] for i in fit_on])
            if got is None:
                return math.inf
            err += sum((y[i] - sum(cf * rows[i][c] for cf, c in zip(got[0], cols))) ** 2 for i in test_on)
        return err
    err = out_of_sample(full)
    return all(err < out_of_sample(cols) for cols in simpler)


def _same(level, d: Driver, starts: list[int], y: list[float], k: int, n: int) -> str:
    """Whether the level is the driver measured again (or a function of it): its changes explained
    by the driver's (``SAME_MOVES``), or half as well with its values within ``SAME_VALUES`` of
    its range of the driver's, with the driver up to two stretches ahead or behind (two collectors of one
    feed, one stamping the feed's own time and the other the time it polled)."""
    lv = [level.values[a] for a in starts]
    span = max(lv) - min(lv)
    for lag in range(-2 * k, 2 * k + 1, max(1, k // 10)):
        at = [(i, a + lag) for i, a in enumerate(starts) if 0 <= a + lag and a + lag + k <= n]
        if len(at) < 3:
            continue
        r2 = _r2_alone([d.values[b + k] - d.values[b] for _, b in at], [y[i] for i, _ in at])
        if r2 >= SAME_MOVES:
            return f"its changes move with (R² {r2:.2f})"
        if r2 >= SAME_MOVES / 2 and span > 0 and sum(abs(lv[i] - d.values[b]) for i, b in at) / len(at) <= SAME_VALUES * span:
            return f"its values and changes (R² {r2:.2f}) are those of"
    return ""


def _eligible(d: Driver, starts: list[int], k: int) -> str:
    """Why a series may not drive a net flow on these stretches, or nothing: it must change in
    ``EVENTS_PER_PARAM`` of them (one that changed once is a before and an after, not a driver),
    and both ways (one that only rises stands in for time)."""
    dx = [d.values[a + k] - d.values[a] for a in starts]
    up, down = sum(1 for v in dx if v > 0), sum(1 for v in dx if v < 0)
    if up + down < EVENTS_PER_PARAM:
        return "changed too seldom"
    if min(up, down) < ONE_WAY * (up + down):
        return "only moves one way"
    return ""


def _unit(name: str) -> str:
    """The unit a series' name ends in (``processes`` in ``claude_processes``)."""
    return name.rsplit("_", 1)[-1]


def _part(level, d: Driver, starts: list[int], k: int) -> str:
    """How the level and the driver may be a part and its total, or nothing: counts in the same
    unit (whole numbers, the same last word in both names), one never above the other and swinging
    no wider. A part's changes are in its total's, so the total explains the part's net flow by
    containing it, and the part the total's."""
    if not d.name or _unit(level.name) != _unit(d.name):
        return ""
    at = sorted({a for a in starts} | {a + k for a in starts})
    lv, dv = [level.values[i] for i in at], [d.values[i] for i in at]
    if not lv or not all(float(v).is_integer() for v in lv + dv):
        return ""

    def inside(p: list[float], t: list[float]) -> bool:
        return all(0 <= a <= b for a, b in zip(p, t)) and max(p) - min(p) <= max(t) - min(t)
    if inside(lv, dv):
        return f"it may be a part of {d.key}"
    return f"{d.key} may be a part of it" if inside(dv, lv) else ""


def _shift_null(d: Driver, own: bool, rows: list[list[float]], y: list[float], starts: list[int], k: int, n: int) -> tuple[float, float, float] | None:
    """What the driver explains of the level's changes beyond the rest of the form (its partial
    R²) in place and moved a quarter of the window earlier or later, whichever explains more, and
    the shift in grid steps. A cause explains the changes it causes when they happen; a series that
    only moves smoothly (a demand that rises all afternoon) explains a smooth level as well an hour
    off. None when too few stretches stay inside the window."""
    shift = max(k, math.ceil(n / 4))
    best: tuple[float, float, float] | None = None
    for sh in (shift, -shift):
        keep = [i for i, a in enumerate(starts) if 0 <= a + sh and a + sh + k <= n]
        if len(keep) < max(2 * EVENTS_PER_PARAM, len(starts) // 2):
            continue
        yy = [y[i] for i in keep]
        rest = _ols([[1.0, *([rows[i][2]] if own else [])] for i in keep], yy)
        here = _ols([rows[i] for i in keep], yy)
        moved = _ols([[1.0, _mean(d.values, starts[i] + sh, k), *([rows[i][2]] if own else [])] for i in keep], yy)
        if rest is None or here is None or moved is None or rest[1] <= 0:
            continue
        got = (1 - here[1] / rest[1], 1 - moved[1] / rest[1], float(sh))
        if best is None or got[1] > best[1]:
            best = got
    return best


def _refuted(f: Fit, rows: list[list[float]], y: list[float], simpler: list[list[int]], starts: list[int], k: int, n: int,
             step: float, margin: float) -> str:
    """Why a form that beat a constant is still refuted, or nothing: a steady trend in time
    explains the level's changes as well (by the AIC margin, and on the held-out half), it explains
    too little of them (``MIN_NET_R2``), or its driver explains as much moved a quarter of the
    window away (``SHIFTED``)."""
    p = len(rows[0])
    t = [(a + k / 2) / n for a in starts]
    trend = _ols([[1.0, v] for v in t], y)
    with_t = [[*r, v] for r, v in zip(rows, t)]
    if trend is not None:
        rss = sum((v - sum(c * x for c, x in zip(f.coef, r))) ** 2 for r, v in zip(rows, y))
        sst = sum((v - sum(y) / len(y)) ** 2 for v in y) or 1e-12
        if f.weight * len(y) * math.log(max(trend[1], 1e-12) / max(rss, 1e-12)) - 2 * (p - 2) < margin:
            what = f"{f.driver.key} stands in for time" if f.driver else "its pull toward a level is a drift in time"
            return f"a steady trend in time explains its changes as well (R² {1 - trend[1] / sst:.2f}): {what}"
    if not _holds_out(with_t, y, list(range(p)), [[0, p]]):
        return "fitted on either half of the window, it predicted the other half no better than a steady trend in time"
    if not _holds_out(with_t, y, list(range(p)), simpler):
        return "fitted on either half of the window, it predicted the other half no better than a form with fewer terms"
    if f.r2 < MIN_NET_R2:
        return f"it explains only {f.r2:.0%} of the level's changes, less than the {MIN_NET_R2:.0%} a net flow must"
    if f.driver is not None and (null := _shift_null(f.driver, f.own, rows, y, starts, k, n)):
        here, moved, sh = null
        if moved >= SHIFTED * here:
            when = f"{abs(sh) * step / 3600:g} h {'later' if sh > 0 else 'earlier'}"
            return (f"{f.driver.key} read {when} explains as much of its changes (R² {moved:.2f} against {here:.2f} in place): "
                    "a series that moves smoothly, not a cause")
    return ""


def fit(level, drivers: list[Driver], step: float, unit_s: float, defer: frozenset | set = frozenset()) -> tuple[Fit | None, str]:
    """The level's net flow, or None and why it stays an input (said after conservation's reason).
    ``defer``: drivers that are the level measured again but give way to it (``stocks``): passed
    over, not a reason to keep the level an input."""
    n = len(level.values) - 1
    live = set(range(n)) if level.live is None else set(level.live)
    k0 = steps_of(level.resolution.seconds if level.resolution else None, step)
    m = 1 + 2 * len(drivers)                         # forms tried beyond the constant: own, and two per driver
    margin = AIC_MARGIN + 2 * math.log(max(1, m))
    cands: list[tuple[Fit, list[list[float]], list[float], list[list[int]], list[int], int]] = []
    same: tuple[str, Driver] | None = None
    parts: list[str] = []
    cache: dict[int, tuple] = {}

    def on(k: int):
        if k not in cache:
            starts = _stretches(live, n, k)
            dt = k * step / unit_s
            y = [(level.values[a + k] - level.values[a]) / dt for a in starts]
            cache[k] = (starts, y, sum(1 for v in y if abs(v) > 1e-12))
        return cache[k]

    def consider(k: int, driver: Driver | None, own: bool) -> None:
        starts, y, changes = on(k)
        p = 1 + (driver is not None) + own
        if changes < EVENTS_PER_PARAM * p or len(y) <= 2 * (p + 1):
            return
        base = _ols([[1.0] for _ in y], y)
        rows = [[1.0, *([_mean(driver.values, a, k)] if driver else []), *([level.values[a]] if own else [])] for a in starts]
        got = _ols(rows, y)
        if base is None or got is None:
            return
        coef, rss, se = got
        aic0, aic = _aic(base[1], len(y), 1), _aic(rss, len(y), p)
        w = _independent_share([v - sum(c * x for c, x in zip(coef, r)) for r, v in zip(rows, y)])
        gain = lambda rss_simple, dp: w * len(y) * math.log(max(rss_simple, 1e-12) / max(rss, 1e-12)) - 2 * dp
        if gain(base[1], p - 1) < margin:
            return
        t_own = coef[-1] / se[-1] * math.sqrt(w) if own and se[-1] > 0 else (math.inf if own else None)
        if own and (abs(t_own) < DF_T or coef[-1] * k * step / unit_s < -FORGETS):
            return
        if driver and own:                      # both terms must earn their place over each alone, the driver as one of many
            for sub, need in (([[1.0, r[1]] for r in rows], AIC_MARGIN), ([[1.0, r[2]] for r in rows], margin)):
                g = _ols(sub, y)
                if g is None or gain(g[1], 1) < need:
                    return
        if not _without_largest(rows, y, w, margin):
            return
        sst = sum((v - sum(y) / len(y)) ** 2 for v in y) or 1e-12
        params = {"c": coef[0], **({"a": coef[1]} if driver else {}), **({"b": coef[-1]} if own else {})}
        inflow = [coef[0] + (coef[1] * r[1] if driver else 0.0) for r in rows]
        simpler = [[0]] + ([[0, 1], [0, 2]] if driver and own else [])
        cands.append((Fit(params, driver, own, k * step, len(y), changes, 1 - rss / sst, aic, aic0, t_own, m,
                          sum(inflow) / len(inflow), coef, w), rows, y, simpler, starts, k))

    _, y0, changes0 = on(k0)
    if changes0 < EVENTS_PER_PARAM * 2:
        return None, (f"and it changed in only {changes0} of its {len(y0)} stretches of {k0 * step:g} s, "
                      "too few to fit a net flow: an input")
    consider(k0, None, True)
    for d in drivers:
        k = max(k0, steps_of(d.resolution_s, step))
        starts, y, changes = on(k)
        if changes < EVENTS_PER_PARAM * 2 or _eligible(d, starts, k):
            continue
        if part := _part(level, d, starts, k):
            parts.append(part)
            continue
        if why := _same(level, d, starts, y, k, n):
            if d.key in defer or statistic(d.name):     # a copy that gives way, or a statistic of it (its maximum): not it again
                continue
            same = (why, d)
            break
        consider(k, d, False)
        consider(k, d, True)
    if same:
        return None, (f"and {same[0]} {same[1].key}: the same quantity measured again, or a function of it, "
                      "so an input, not a stock")
    cands.sort(key=lambda c: c[0].aic - c[0].aic_constant)
    first = ""
    for f, rows, y, simpler, starts, k in cands:
        why = _refuted(f, rows, y, simpler, starts, k, n, step, margin)
        if not why:
            return f, ""
        first = first or f"the best, {f.form} at R² {f.r2:.2f}, refuted: {why}"
    part = f"; {'; '.join(parts)} (counts in one unit, one never above the other and swinging no wider): neither drives the other" if parts else ""
    return None, (f"and no other series explains its changes better than a constant ({first or f'of {m} forms tried'}{part}): "
                  "an input, not a stock")


def _r2_alone(x: list[float], y: list[float]) -> float:
    """How well ``x`` alone, with an intercept, explains ``y``."""
    got = _ols([[1.0, v] for v in x], y)
    if got is None:
        return 0.0
    my = sum(y) / len(y)
    sst = sum((v - my) ** 2 for v in y)
    return 1 - got[1] / sst if sst > 0 else 0.0


def build(f: Fit, sid: str, title: str, writer: str | None, window: tuple[float, float], ref) -> tuple[Stock, list[Flow]]:
    """The stock and its fitted flows. ``ref``: the model's reference to the level's series."""
    p = f.params
    q = {"r2": round(f.r2, 4), "stretches": float(f.blocks), "stretch_s": f.block_s, "aic": round(f.aic, 3),
         "aic_constant": round(f.aic_constant, 3), "forms_tried": float(f.tried), "events": float(f.changes), "changes": float(f.changes)}
    note = {"net_flow_of": sid, "note": f"no counter measures it: fitted from how {title} changed ({f.form})"}
    flows = []
    if f.driver is not None or abs(p["c"]) > 1e-12:
        sign = 1.0 if f.mean_in >= 0 else -1.0
        params = {"c": round(sign * p["c"], 6), **({"k": round(sign * p["a"], 6)} if f.driver else {})}
        eq = Equation("linear" if f.driver else "constant", params, "fitted", "least-squares", window, None, dict(q),
                      [f.driver.ref] if f.driver else [])
        fid, src, dst = (f"{sid}_inflow", None, sid) if sign > 0 else (f"{sid}_loss", sid, None)
        flows.append(Flow(fid, ("into " if sign > 0 else "out of ") + title, src, dst, None, [eq], [], dict(note)))
    if f.own:
        b = p["b"]
        eq = Equation("proportional", {"k": round(abs(b), 6)}, "fitted", "least-squares", window, None, dict(q), [sid])
        fid, src, dst = (f"{sid}_outflow", sid, None) if b < 0 else (f"{sid}_growth", None, sid)
        flows.append(Flow(fid, (f"out of {title}, in proportion to it" if b < 0 else f"into {title}, in proportion to it"),
                          src, dst, None, [eq], [], dict(note)))
    evidence = {"written_by": writer, "net_flow": {"form": f.form, "params": {k: round(v, 6) for k, v in p.items()},
                                                 "driver": f.driver.ref if f.driver else None, "r2": round(f.r2, 4),
                                                 "stretch_s": f.block_s, "stretches": f.blocks, "changes": f.changes,
                                                 "aic": round(f.aic, 3), "aic_constant": round(f.aic_constant, 3),
                                                 "forms_tried": f.tried, **({"t_level": round(f.t_own, 2)} if f.t_own is not None else {})},
                "trust": stocktrust.net_flow(f.notes, f.r2)}
    return Stock(sid, title, "level", ref, evidence), flows


def copy_of(level, stocks: list, k: int):
    """The first of ``stocks`` (levels already stocks by their net flow) that ``level`` is a copy
    of: their changes over stretches of ``k`` steps explain each other at ``SAME_MOVES`` (one lag
    read by group, by topic, and again through a recording rule)."""
    n = len(level.values) - 1
    live = set(range(n)) if level.live is None else set(level.live)
    for other in stocks:
        both = live & (set(range(n)) if other.live is None else set(other.live))
        starts = _stretches(both, n, k)
        if len(starts) >= 3 and _r2_alone([other.values[a + k] - other.values[a] for a in starts],
                                          [level.values[a + k] - level.values[a] for a in starts]) >= SAME_MOVES:
            return other
    return None


def first(s) -> tuple:
    """Which of two copies of one quantity is tried as its stock: the finer resolution, then the one
    written first, then by key."""
    res = s.resolution.seconds if s.resolution and s.resolution.seconds else math.inf
    return (res, s.points[0][0] if s.points else math.inf, s.key)


def stocks(series: list, counted: list, sid_of: dict[str, str], inputs: dict[str, list[float]], input_refs: dict[str, dict],
           left_out: dict[str, str], step: float, unit_s: float, window: tuple[float, float], name_of, ref_of, writer_of,
           measure=None, units: dict[str, str] | None = None) -> list:
    """The levels conservation left out because no counters balance them that are stocks by their
    fitted net flow, as (stock, its flows, the input name it had, its series). The others get their
    reason in ``left_out``. ``counted``: conservation's stocks' series; ``name_of(series)``: a new
    stock's id and title; ``ref_of(series)``: the model's reference to it; ``measure(level, fit,
    drivers, step, unit_s)``: what the stock's trust is computed from (``sd.netnull.measured``);
    ``units``: each series' unit (``sd.units``), by key."""
    key_of = {name: series_key(r["name"], r.get("labels") or {}) for name, r in input_refs.items()}
    drivers = [Driver(sid_of[c.key], c.values, c.resolution.seconds if c.resolution else None, c.key, c.name) for c in counted]
    drivers += [Driver(f"input:{name}", vals, input_refs[name].get("resolution_s"), key_of[name], input_refs[name]["name"])
                for name, vals in inputs.items()]
    accepted = []
    # of two copies of one quantity (two stores' sessions), each moves with the other; the first
    # here is tried as the stock, the other is its copy (``first``: the finer, then the earlier
    # written), and is tried in turn only when the first is no stock
    tried = sorted((s for s in series if not s.counter and left_out.get(s.key, "").startswith(NET_FLOW)), key=first)
    after = {s.key: {t.key for t in tried[i + 1:]} for i, s in enumerate(tried)}
    no_stock: set[str] = set()                   # tried and not a stock: a later copy no longer defers to it
    for s in tried:
        no_stock.add(s.key)
        if statistic(s.name, s.summary):        # sd.discover leaves these out before; a caller's own series may not
            left_out[s.key] += ", and it is a statistic of what it measures (a mean, a maximum, a percentile): a summary, not a store"
            continue
        if resource(s.name, (units or {}).get(s.key)):
            left_out[s.key] += (", and it measures a resource a process or host uses (CPU, memory, threads, a utilisation): a property "
                                "of the running process, set by its work, not an accumulation, so no net flow is fitted to it")
            continue
        mine = [d for d in drivers if d.name != s.name]
        got, why = fit(s, mine, step, unit_s, after[s.key] | no_stock - {s.key})
        if got is not None and (twin := copy_of(s, [lv for lv, _ in accepted], max(1, round(got.block_s / step)))):
            got, why = None, (f"and its changes move with {twin.key}'s, a stock already: the same quantity measured again, "
                              "so an input, not a second stock")
        if got is None:
            left_out[s.key] = f"{left_out[s.key]}, {why}"
        else:
            no_stock.discard(s.key)
            if measure is not None:
                got.notes.update(measure(s, got, mine, step, unit_s))
            accepted.append((s, got))
    named = {s.key: name_of(s) for s, _ in accepted}
    as_input = {f"input:{name}": named[k][0] for name, k in key_of.items() if k in named}
    out = []
    for s, got in accepted:
        if got.driver is not None and got.driver.ref in as_input:      # another level that is a stock now
            got.driver = Driver(as_input[got.driver.ref], got.driver.values, got.driver.resolution_s, got.driver.key, got.driver.name)
        sid, title = named[s.key]
        stock, flows = build(got, sid, title, writer_of(s), window, ref_of(s))
        left_out.pop(s.key, None)
        out.append((stock, flows, next((name for name, k in key_of.items() if k == s.key), None), s))
    return out
