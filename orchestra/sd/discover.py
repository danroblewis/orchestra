"""Discovery v1: build the model from the metrics store, without being told what anything is.

Given every series of a project over a window, it finds stocks, the flows between them, the
equation of each flow, and the machine behind each flow:

1. **Sample** every series onto a grid of steps (the last value at or before each step), and mark
   when each was live (``sd.series``, ``sd.live``): liveness is the machine's, so a gauge not
   re-written because nothing changed holds its value while its machine is alive, and a
   machine's silence is it down or not yet started, not a measurement of the silence. Orchestra's
   own series (``PLUMBING``: the host's, the Core page's probes) are no candidates.
2. **Find stocks by conservation.** A level whose changes are explained by counters, added or
   subtracted, is a stock, and those counters are its inflows and outflows:
   ``Δlevel ≈ Σ inflows − Σ outflows`` in every step the level and the counters were live in.
   The counters (each with a coefficient of +1 or −1) are found by a local search from many
   starts that keeps a counter only if it explains a real share, searching only counters that
   counted enough events, for a level that changed in enough steps (``sd.balance``: fewer
   coincide by chance). The level's own machine's counters come first (its record of its
   transitions): when they balance it within the tolerance, another machine's counter never
   replaces one of them, and enters only to explain the residual they leave; every counter is
   searched only when the machine's own do not balance it. A level is kept only if the balance
   fits (R² ≥ ``MIN_R2``); everything else is left out, with the reason. With every balance
   known, a counter that stands in for others gives way to them (``sd.restate``: Orchestra's
   event counter to the machine counters it sums, another machine's copy to the machine's own,
   two machines' counts of one flow to one). Two levels that change alike in nearly every step,
   or that the same counters balance, are one stock measured twice: the machine whose counters
   make the balance keeps it, the other is recorded as its twin.
3. **Connect flows.** A counter that is an outflow of one stock and an inflow of another is a flow
   between them; otherwise it comes from or goes to outside (``sd.ends``: when two stocks claim the
   same end, the one the counter explains most keeps it and the other claim is evidence; stocks of
   different machines claiming one counter make it a co-flow, one flow per machine). A state each
   item leaves within a step is empty at almost every step, so the chain through it runs past it
   or splits through outside; it is joined through again (``sd.hops``, ``sd.passing``), on the
   measured level whose raw points show it (``sd.between``) or on a hidden stock.
4. **Fit each flow's equation** by maximum likelihood, choosing by AIC among:
   - ``constant``: rate = c;
   - ``proportional``: rate = k × X, for X the source stock (its exact time-average over the
     step) or another stock that held something whenever the flow's events came;
   - ``linear``: rate = c + k × X, for X any stock found, or any measured gauge that is not a
     stock (``sd.inputs``: a rating, a demand; recorded as ``input:<name>``).

   When X is a stock other than the flow's own source, that is an **influence**: one stock
   changing the rate of another's flow, the link that closes feedback loops. Forms are scored
   with the exact point-process likelihood (each event against the levels just before it), not
   counts per step, which favour spurious forms; a second parameter must beat the best
   one-parameter form by ``AIC_MARGIN``, and a line below zero where the data had no chance to
   show the floor is rejected (see ``fit_flow``). A flow with fewer than ``MIN_EVENTS`` events
   in the window gets the constant form only: an influence fitted on one event is noise; one
   that reads another stock or an input needs ``EVENTS_PER_PARAM`` events per parameter.
5. **Attribute** each flow to the machine named by its counter's ``machine`` label, and each stock
   to the machine that writes it.

Structure is discovered and parameters are fitted, so equations record ``origin: fitted`` with
``method: poisson-mle`` and the model records how it was found (``Model.discovery``).

What this cannot do yet: stocks no series measures (hidden stocks), delays, non-linear forms,
eras. Those are the SD Lab strategies' job, and they are still unproven on real data."""

from __future__ import annotations

import math
import re
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from itertools import accumulate, pairwise

from .balance import MIN_EVENTS, MIN_GAIN, LeastSquares, balance, fit_of
from .drivers import behind, co_counting
from .ends import claims, moves
from .hops import split_hops
from .inputs import offered_inputs
from .live import balance_steps, held_for, intersect, within
from .model import Equation, Flow, Machine, Model, SeriesRef, Stock
from .parsimony import fewer_counters
from .passing import passages
from .restate import split_event_counters, split_foreign_counters, unify_same_flows
from .series import (
    EVENT_COUNTER,
    PLUMBING,
    Series,
    machine_of,
    plumbing_reason,
    sample,
    sum_instances,
)

MIN_R2 = 0.9            # how well a balance must fit for a level to count as a stock
FLAG_EXACT = 0.97         # a two-valued level is a stock only if its balance is exact in this share of steps
SAME_STEPS = 0.03          # counters that differ in no more than this share of steps are one
TWIN_STEPS = 0.97          # levels whose changes are equal in this share of steps are one stock measured twice
TWIN_CORR = 0.9            # ... or whose changes correlate this well (one a moment behind the other)
MIN_STEPS = 5              # a level live in fewer steps than this (while every counter was) cannot be balanced
AIC_MARGIN = 2.0           # a two-parameter form must beat the best one-parameter form by this much AIC to be chosen
EVENTS_PER_PARAM = 10      # a form that reads another stock or an input needs this many events per parameter
UNITS = {"second": 1.0, "minute": 60.0, "hour": 3600.0}


def _slug(s: Series) -> str:
    extra = [v for k, v in sorted(s.labels.items()) if k not in ("project", "machine")]
    return "_".join([s.name, *[re.sub(r"\W+", "_", v) for v in extra]])


def _title(s: Series) -> str:
    base = re.sub(r"_total$", "", s.name).replace("_", " ")
    extra = [v for k, v in sorted(s.labels.items()) if k not in ("project", "machine")]
    return base + (f" ({', '.join(extra)})" if extra else "")


def _same_total(a: Series, b: Series) -> bool:
    """Whether two counters could count the same events: their totals agree, and Orchestra's count
    of a machine's events is only compared with a counter that machine writes (a few rare events,
    a host restart or an operator's note, otherwise match anything as rare)."""
    total_a, total_b = sum(a.deltas), sum(b.deltas)
    if not total_a or abs(total_a - total_b) > max(1.0, SAME_STEPS * total_b):
        return False
    return not (EVENT_COUNTER in (a.name, b.name) and (machine_of(a) is None or machine_of(a) != machine_of(b)))


def same_flow(a: Series, b: Series, n: int) -> bool:
    """Two counters that count the same events: equal in all but a few steps, or the same events
    stamped a moment apart, so some fall in the next step: one counter's running total is always
    between the other's at the step before and at this step (never more than a step behind). The
    same activity is often measured twice: Orchestra counts every event (orchestra_events_total)
    and the machine counts what it did (an order's moves, a run's turns); they are one flow,
    not two that share a balance. Here the lag is allowed only to Orchestra's own count, which is
    stamped after the machine's: two other counters a step apart may be a quick buffer's inflow
    and outflow (put on a shelf and taken within seconds), which are one flow only when nothing
    measured lies between them; that is known once the balances are (``lagged_flow``,
    ``restate.unify_same_flows``)."""
    if not _same_total(a, b):
        return False
    da, db = a.deltas, b.deltas
    moved = sum(1 for x, y in zip(da, db) if x or y)                   # steps where either counted something
    if sum(1 for x, y in zip(da, db) if x != y) <= SAME_STEPS * moved:  # (of all steps, two rare counters always "agree")
        return True
    return (b.name == EVENT_COUNTER and a.name != EVENT_COUNTER and behind(da, db)) or \
        (a.name == EVENT_COUNTER and b.name != EVENT_COUNTER and behind(db, da))


def lagged_flow(a: Series, b: Series) -> bool:
    """Two counters of the same events stamped up to a step apart, either way (``drivers.behind``):
    a transition recorded in two hops through a state the grid never sees held."""
    return _same_total(a, b) and (behind(a.deltas, b.deltas) or behind(b.deltas, a.deltas))


EVER = [(-math.inf, math.inf)]


def first_stamped(a: Series, b: Series) -> bool:
    """Whether ``a``'s events are stamped before ``b``'s, for two counters of the same events (the
    i-th increment of each is the i-th event): more of ``a``'s stamps come earlier than later. On
    the grid both land in the same step; only the raw stamps say which was recorded first."""
    ta = [t for t, _ in events_of(a.points, EVER)]
    tb = [t for t, _ in events_of(b.points, EVER)]
    return sum(1 for x, y in zip(ta, tb) if x < y) > sum(1 for x, y in zip(ta, tb) if x > y)


def _loglik(y: list[float], mu: list[float]) -> float:
    ll = 0.0
    for c, m in zip(y, mu):
        if m <= 1e-12:
            if c > 0:
                return -math.inf
            continue
        ll += c * math.log(m) - m - math.lgamma(c + 1)
    return ll


def _nelder_mead(f, x0: list[float], scale: list[float], iters: int = 400) -> list[float]:
    """Minimise f over a few parameters; small and dependency-free."""
    n = len(x0)
    pts = [list(x0)] + [[x0[i] + (scale[i] if i == j else 0.0) for i in range(n)] for j in range(n)]
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = sorted(range(n + 1), key=lambda i: vals[i])
        pts, vals = [pts[i] for i in order], [vals[i] for i in order]
        cen = [sum(p[i] for p in pts[:-1]) / n for i in range(n)]
        ref = [cen[i] + (cen[i] - pts[-1][i]) for i in range(n)]
        fr = f(ref)
        if fr < vals[0]:
            exp = [cen[i] + 2 * (cen[i] - pts[-1][i]) for i in range(n)]
            fe = f(exp)
            pts[-1], vals[-1] = (exp, fe) if fe < fr else (ref, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = ref, fr
        else:
            con = [cen[i] + 0.5 * (pts[-1][i] - cen[i]) for i in range(n)]
            fc = f(con)
            if fc < vals[-1]:
                pts[-1], vals[-1] = con, fc
            else:
                pts = [pts[0]] + [[pts[0][i] + 0.5 * (p[i] - pts[0][i]) for i in range(n)] for p in pts[1:]]
                vals = [vals[0]] + [f(p) for p in pts[1:]]
        if max(vals) - min(vals) < 1e-9:
            break
    return pts[min(range(n + 1), key=lambda i: vals[i])]


@dataclass
class Path:
    """A stock's level over the window, as the fitter needs it: the level just before any instant,
    and how long it spent at each level (in the model's time unit)."""

    times: list[float]
    values: list[float]
    time_at: dict[float, float]
    live: list[tuple[float, float]]
    unit_s: float

    @classmethod
    def of(cls, points: list[tuple[float, float]], live: list[tuple[float, float]], unit_s: float) -> Path:
        """The path, counting time only inside ``live`` (when every series involved was written)."""
        times, values = [p[0] for p in points], [p[1] for p in points]
        time_at: dict[float, float] = defaultdict(float)
        for start, end in live:
            i = bisect_right(times, start) - 1
            level = values[i] if i >= 0 else (values[0] if values else 0.0)
            t0 = start
            for t, v in points[max(0, i + 1):]:
                if t >= end:
                    break
                time_at[level] += (t - t0) / unit_s
                t0, level = t, v
            time_at[level] += (end - t0) / unit_s
        return cls(times, values, dict(time_at), list(live), unit_s)

    def before(self, t: float) -> float:
        """The level just before ``t``: what an event at ``t`` saw."""
        i = bisect_left(self.times, t) - 1
        return self.values[i] if i >= 0 else (self.values[0] if self.values else 0.0)

    def integral(self, c: float, k: float) -> float:
        """∫ max(0, c + k × level) dt over the window: a rate stops at zero (``fit_flow`` says
        when the data have shown that floor and when they have not)."""
        return sum(d * max(0.0, c + k * x) for x, d in self.time_at.items())

    def expected(self, a: float, b: float, c: float, k: float) -> float:
        """∫ max(0, c + k × level) dt over [a, b) within the live time: the events due between two
        instants, following the level between them."""
        total = 0.0
        for start, end in self.live:
            lo, hi = max(a, start), min(b, end)
            if hi <= lo:
                continue
            i = bisect_right(self.times, lo) - 1
            level, t0 = (self.values[i] if i >= 0 else (self.values[0] if self.values else 0.0)), lo
            for t, v in zip(self.times[i + 1:], self.values[i + 1:]):
                if t >= hi:
                    break
                total += (t - t0) * max(0.0, c + k * level)
                t0, level = t, v
            total += (hi - t0) * max(0.0, c + k * level)
        return total / self.unit_s

    def below_zero(self, c: float, k: float) -> tuple[float | None, float]:
        """The lowest level the stock held at which c + k × level is below zero, and how long it
        held all such levels (in the model's time unit)."""
        neg = [x for x in self.time_at if c + k * x < -1e-9]
        return (min(neg) if neg else None), sum(self.time_at[x] for x in neg)


def events_of(points: list[tuple[float, float]], live: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """A counter's increments inside the live time, as (time, count); a drop is a reset. Before
    a counter's first point nothing had been counted (``sample``), so that point is its first
    events."""
    out, prev = [], 0.0
    for t, v in points:
        if within(t, live):
            d = v - prev if v >= prev else v
            if d > 0:
                out.append((t, d))
        prev = v
    return out


def fit_flow(events: list[tuple[float, float]], window: float, paths: dict[str, Path], src: str | None,
             drivers: set[str] | None = None) -> list[dict]:
    """Every candidate form for one flow, the chosen one first, scored with the exact
    point-process likelihood: each event against the rate just before it, the rate integrated
    over the stocks' actual paths:

        log L = Σ count × log rate(t⁻)  −  ∫ rate dt        (rate = c + k × X)

    Scoring counts per step instead is biased for outflows: a step's average level is lowered by
    the very outflow being counted, which makes the rate look higher at low levels and favours a
    spurious intercept. The estimates of the constant and proportional forms are the same either
    way (events ÷ time, events ÷ level × time).

    A form must have the events to be told from chance: ``EVENTS_PER_PARAM`` per parameter for
    one that reads another stock or an input (on eight events a level that happened to be high
    beats the constant on likelihood alone), twice that for a line ``c + k × X``; below that, the
    constant and the form proportional to the flow's own source are all it is offered.

    The chosen form is the plain one (constant, or proportional to the flow's own source) with the
    lowest AIC, unless another beats it by at least ``AIC_MARGIN``: a second parameter, or a
    reading of another stock, must earn its place, and a tie goes to the plain form. A line's rate stops
    at zero, and the line may go below it only where the data have shown that nothing flows: at
    levels the stock held long enough for ``MIN_EVENTS`` events to be due at the flow's mean rate
    (a shelf kept full for an hour, with no order placed). Where it held them too briefly for
    that, the zero is a rate the data never saw, and the form is rejected whatever its AIC (a
    twelfth of an hour of a baker at the oven, during which nothing happened to arrive); it stays
    in the list, marked ``rejected`` with the reason."""
    total = sum(d for _, d in events)
    if total < MIN_EVENTS:                 # too few events to tell a form from noise: the rate alone
        paths, src = {}, None
    at = {sid: [p.before(t) for t, _ in events] for sid, p in paths.items()}

    def ll(c: float, k: float, sid: str | None) -> float:
        xs = at[sid] if sid else [0.0] * len(events)
        out = 0.0
        for (_, d), x in zip(events, xs):
            r = c + k * x
            if r <= 1e-12:
                return -math.inf
            out += d * math.log(r)
        return out - (paths[sid].integral(c, k) if sid else max(0.0, c) * window)

    cands = []
    c0 = total / window
    cands.append({"form": "constant", "params": {"c": c0}, "inputs": [], "loglik": ll(c0, 0.0, None), "k": 1})
    for sid, p in paths.items():
        xs = list(p.time_at)
        if not xs or max(xs) - min(xs) < 1e-9 or (drivers is not None and sid not in drivers and sid != src):
            continue
        # proportional to the flow's own source, or to another stock when every event came while
        # that stock held something (what waits is taken: the rate is nothing when nothing waits)
        expo = p.integral(0.0, 1.0)
        if expo > 0 and (sid == src or total >= EVENTS_PER_PARAM):
            k = total / expo
            cands.append({"form": "proportional", "params": {"k": k}, "inputs": [sid], "loglik": ll(0.0, k, sid), "k": 1})
        if total < 2 * EVENTS_PER_PARAM:
            continue
        span = max(xs) - min(xs)

        def nll(q, sid=sid):
            v = ll(q[0], q[1], sid)
            return -v if math.isfinite(v) else 1e18
        cc, kk = _nelder_mead(nll, [c0, 0.0], [max(c0, 1e-3) * 0.5, max(c0, 1e-3) / span])
        cand = {"form": "linear", "params": {"c": cc, "k": kk}, "inputs": [sid], "loglik": ll(cc, kk, sid), "k": 2}
        level, held = p.below_zero(cc, kk)
        if level is not None and c0 * held < MIN_EVENTS:
            cand["rejected"] = (f"its rate is below zero from level {level:g} of {sid}, which the stock held only long enough for "
                                f"{c0 * held:.1f} events at this flow's mean rate: too few to have seen that nothing flows there")
        cands.append(cand)
    for cand in cands:
        cand["aic"] = 2 * cand["k"] - 2 * cand["loglik"] if math.isfinite(cand["loglik"]) else math.inf
    plain = min((c for c in cands if c["k"] == 1 and c["inputs"] in ([], [src])), key=lambda c: c["aic"])
    best = min((c for c in cands if "rejected" not in c), key=lambda c: c["aic"])
    if best is not plain and best["aic"] > plain["aic"] - AIC_MARGIN:
        best = plain
    return [best, *sorted((c for c in cands if c is not best), key=lambda c: ("rejected" in c, c["aic"]))]


def dispersion(events: list[tuple[float, float]], live: list[tuple[float, float]], form: dict, paths: dict[str, Path], unit_s: float) -> float:
    """How far the events are from a Poisson process at the chosen form's rate: the rate
    integrated from each event to the next (``Path.expected``: the events the form expected in
    between) is, for a Poisson process, exponential with mean 1, so the variance of those
    intervals over their mean squared is near 1 when the form explains the variation, well above
    1 when events bunch where the form expected few (something it lacks drives the flow), and
    well below 1 when they come more regularly than chance (a machine's fixed service time). Judged
    between events rather than on counts per step, which for a rate tied to the stock's own
    changes (a start that ends the idle time it depends on) is wrong at every step's edge."""
    p, x = form["params"], (form["inputs"][0] if form["inputs"] else None)
    c, k = p.get("c", 0.0), p.get("k", 0.0)
    times = [t for t, d in events for _ in range(int(d))]
    if len(times) < 2:
        return 1.0
    between = lambda a, b: paths[x].expected(a, b, c, k) if x else max(0.0, c) * sum(max(0.0, min(b, hi) - max(a, lo)) for lo, hi in live) / unit_s
    gaps = [between(a, b) for a, b in pairwise(times)]
    mean = sum(gaps) / len(gaps)
    return sum((g - mean) ** 2 for g in gaps) / max(1, len(gaps) - 1) / max(mean * mean, 1e-12)


def unique_id(slug: str, machine: str | None, taken: set[str]) -> str:
    """``slug``, or with the machine's name when another series already has it (two machines'
    series of one name): everything keyed by id needs each id once."""
    sid, i = slug, 1
    while sid in taken:
        i += 1
        sid = f"{slug}_{machine or 'other'}" + (f"_{i}" if i > 2 else "")
    taken.add(sid)
    return sid


def _equal_steps(a: Series, b: Series) -> float:
    """The share of the steps in which either level changed where both changed by the same
    amount. Steps where neither moved say nothing: over a long window every quiet level would
    be every other's twin."""
    moved = [(x, y) for x, y in zip(a.deltas, b.deltas) if abs(x) > 1e-6 or abs(y) > 1e-6]
    return sum(1 for x, y in moved if abs(x - y) <= 1e-6) / max(1, len(moved))


def _alike(a: Series, b: Series) -> dict[str, float]:
    """How alike two levels are, on the steps both were live in: the correlation of their
    changes, and the share of the steps in which either held something where both held the same."""
    steps = [i for i in range(min(len(a.deltas), len(b.deltas))) if (a.live is None or i in a.live) and (b.live is None or i in b.live)]
    da, db = [a.deltas[i] for i in steps], [b.deltas[i] for i in steps]
    n = max(1, len(steps))
    ma, mb = sum(da) / n, sum(db) / n
    va, vb = sum((x - ma) ** 2 for x in da), sum((y - mb) ** 2 for y in db)
    corr = sum((x - ma) * (y - mb) for x, y in zip(da, db)) / math.sqrt(va * vb) if va > 0 and vb > 0 else 0.0
    held = [i for i in steps if a.values[i + 1] or b.values[i + 1]]
    same = sum(1 for i in held if abs(a.values[i + 1] - b.values[i + 1]) <= 1e-6) / len(held) if len(held) >= MIN_EVENTS else 0.0
    return {"change_correlation": corr, "equal_values": same}


def _twins(a: Series, b: Series, a_terms: list, b_terms: list, same_flow) -> bool:
    if _equal_steps(a, b) >= TWIN_STEPS or _same_balance(a_terms, b_terms, same_flow):
        return True
    alike = _alike(a, b)
    return alike["change_correlation"] >= TWIN_CORR or alike["equal_values"] >= TWIN_STEPS


def _owns(s: Series, terms: list) -> int:
    """How many of the balance's counters the level's own machine writes: that machine owns the
    transitions, and the level is its record of them."""
    return sum(1 for c, _ in terms if machine_of(c) is not None and machine_of(c) == machine_of(s))


def own_balance(s: Series, counters: list[Series], steps: list[int], fits) -> tuple[list | None, float, float]:
    """The level's balance made of its own machine's counters (its record of its transitions, and
    Orchestra's counts of its events), when they balance it within the tolerance: that is its
    balance, whatever another machine's counts of the same events would say in fewer terms or a
    step more exactly (one machine's turns are not another's moves). Another machine's
    counter enters only to explain the residual the machine's own leave, when there is one. None
    when the machine's own do not balance it: then every counter is searched."""
    own = [c for c in counters if machine_of(s) is not None and machine_of(c) == machine_of(s)]
    terms, r2, exact = balance(s, own, None, steps) if own else ([], 0.0, 0.0)
    if not (terms and fits(s, r2, exact)):
        return None, 0.0, 0.0
    foreign = [c for c in counters if not any(c is o for o in own)]
    if exact >= FLAG_EXACT or not foreign:
        return terms, r2, exact
    left = [d - sum(sign * c.deltas[i] for c, sign in terms) for i, d in enumerate(s.deltas)]
    residual = Series(s.name, s.labels, [], [0.0, *accumulate(left)], False)
    more, _, _ = balance(residual, foreign, None, steps)
    if more:
        r2b, exact2 = fit_of(s, terms + more, steps)
        if r2b > r2 + MIN_GAIN:
            return terms + more, r2b, exact2
    return terms, r2, exact


def _same_balance(a: list, b: list, same_flow) -> bool:
    """Whether two balances are the same counters with the same signs, a counter of the same
    events (``same_flow``: the board's rejected, the customers' returns) counting as the same."""
    return len(a) == len(b) and all(any(sa == sb and (ca is cb or same_flow(ca, cb)) for cb, sb in b) for ca, sa in a)


def twin_levels(found: list, left_out: dict[str, str], same_flow) -> tuple[list, dict[str, list[dict]]]:
    """One stock measured twice (a shelf counted by the shelf and by the board): two levels that
    change alike in at least ``TWIN_STEPS`` of the steps, or that the same counters balance (two
    machines' counts of the same events being the same counter), or, judged on the levels
    themselves, whose changes correlate by ``TWIN_CORR`` or whose values are equal in
    ``TWIN_STEPS`` of the steps either held something (the expo's view of the board's queue, a
    moment behind it, whose balance takes the expo's own counters). The one kept is the machine's
    whose counters make the balance, then the better balance; the other is left out and recorded
    as its twin, in the kept stock's evidence."""
    kept: list = []
    twins: dict[str, list[dict]] = defaultdict(list)
    for s, terms, r2, exact in found:
        other = next((k for k in kept if _twins(s, k[0], terms, k[1], same_flow)), None)
        if other is None:
            kept.append((s, terms, r2, exact))
            continue
        o, oterms, or2, oexact = other
        if (_owns(s, terms), exact, r2) > (_owns(o, oterms), oexact, or2):
            kept[kept.index(other)] = (s, terms, r2, exact)
            win, lose = s, o
            twins[s.key] = twins.pop(o.key, [])
        else:
            win, lose = o, s
        share, alike = _equal_steps(win, lose), _alike(win, lose)
        twins[win.key].append({"series": lose.key, "machine": machine_of(lose), "equal_steps": round(share, 4),
                               **{k: round(v, 4) for k, v in alike.items()}})
        for rec in twins[win.key]:
            left_out[rec["series"]] = (f"the same as {win.key} (one stock measured twice: their changes are equal in "
                                       f"{rec['equal_steps']:.0%} of steps and correlate by {rec['change_correlation']:.2f}; "
                                       f"their values are equal in {rec['equal_values']:.0%} of the steps either held something)")
    return kept, dict(twins)


def discover(dump, *, start: float, end: float, step: float, time_unit: str = "minute", kinds: dict | None = None) -> Model:
    """The model the metrics imply over [start, end], with how it was found in ``model.discovery``."""
    n = max(2, int((end - start) // step))
    series, summed = sum_instances(sample(dump, start, step, n, kinds))
    sampled = len(series)          # every series looked at (a machine's instances summed into one)
    left_out: dict[str, str] = {}
    end = start + n * step
    # Orchestra's own series are plumbing, not a measure of the system; and a series not live at the
    # end of the window (its machine silent past its live limit: gone, or replaced) is not measured
    # now: left out, or its silence would leave no time when every series involved was live, and
    # nothing could be fitted
    current = []
    for ser in series:
        ivs = ser.intervals if ser.intervals is not None else [(start, end)]
        if PLUMBING.match(ser.name):
            left_out[ser.key] = plumbing_reason(ser.name)
        elif ivs and ivs[-1][1] >= end:
            current.append(ser)
        else:
            since = round((end - (ivs[-1][1] if ivs else max((t for t, _ in ser.points), default=start))) / 60)
            who = f"its machine {machine_of(ser)} has been silent" if machine_of(ser) else "its last point is"
            left_out[ser.key] = f"no longer written: {who} {since} min before the end of the window"
    series = current
    counters = [s for s in series if s.counter and any(s.deltas)]
    # counters that moved together in (almost) every step measure the same thing (a machine's own
    # count and Orchestra's count of the event it publishes for it; they may differ by a step at the
    # edge, where one was collected later): balances could not tell them apart, and two stocks
    # choosing different ones would lose the flow that joins them. One is kept: the machine's own,
    # then, of a machine's two counts of one move made in two hops (an item approved and at the
    # same instant moved on), the hop stamped first: a flow's events are judged against the levels
    # just before them, and the level the first hop drained is already one lower at the second;
    # then the shortest name. Two machines' counts of the same events both stay: each machine's
    # stocks take their own, and the balances say which fits (restate.unify_same_flows).
    counters.sort(key=lambda c: (c.name.startswith(EVENT_COUNTER), len(c.key), c.key))
    kept_counters: list[Series] = []
    same_as: dict[str, list[dict]] = defaultdict(list)     # kept counter key -> the counters it stands for
    copies: dict[str, list[Series]] = defaultdict(list)    # ... as series (sd.hops may bring one back)
    for c in counters:
        twin = next((k for k in kept_counters if same_flow(c, k, n)
                     and (EVENT_COUNTER in (c.name, k.name) or machine_of(c) == machine_of(k))), None)
        if twin is None:
            kept_counters.append(c)
            continue
        if EVENT_COUNTER not in (c.name, twin.name) and first_stamped(c, twin):
            kept_counters[kept_counters.index(twin)] = c
            same_as[c.key] = same_as.pop(twin.key, [])
            copies[c.key] = copies.pop(twin.key, [])
            c, twin = twin, c
        left_out[c.key] = f"the same as {twin.key} (counts the same events)"
        same_as[twin.key].append({"name": c.name, "labels": c.labels})
        copies[twin.key].append(c)
    counters = kept_counters
    for s in series:
        if s.counter and not any(s.deltas):
            left_out[s.key] = "a counter that did not move in the window"
    found: list[tuple[Series, list[tuple[Series, int]], float, float]] = []
    masks: dict[str, list[int]] = {}              # the steps each level's balance was found on
    solvers: dict[tuple, LeastSquares] = {}       # least squares over all counters, per set of steps

    def fits(s: Series, r2: float, exact: float) -> bool:
        """A balance a level may be a stock on: a level that only ever takes two values is usually
        a flag (a baker is busy or not), and least squares will balance a flag with counters that
        merely move with it; it is a stock only when counters balance it exactly (a shelf that
        holds nothing or one item)."""
        return r2 >= MIN_R2 and (exact >= FLAG_EXACT or len({v for _, v in s.points}) > 2)
    for s in series:
        if s.counter:
            continue
        # only the steps when the level and every counter were live: a level's stale value from
        # before a silence (its machine was down, then restarted with a cleared state) is not a
        # change any counter explains, and the fit below cuts the same time
        steps = balance_steps(s, counters)
        if len(steps) < MIN_STEPS:
            left_out[s.key] = f"live in only {len(steps)} of {n} steps while every counter was: too few to balance"
            continue
        moved = sum(1 for i in steps if s.deltas[i])
        if not moved:
            left_out[s.key] = "a level that did not change in the window" + (" while it was live" if len(steps) < n else "")
            continue
        if moved < MIN_EVENTS:
            left_out[s.key] = (f"a level that changed in only {moved} step{'s' if moved != 1 else ''}: fewer than {MIN_EVENTS}, "
                               "too few to tell a balance from coincidence")
            continue
        masks[s.key] = steps
        terms, r2, exact = own_balance(s, counters, steps, fits)
        if terms is None:
            key = tuple(steps)
            if key not in solvers and counters:
                solvers[key] = LeastSquares([[c.deltas[i] for i in steps] for c in counters])
            terms, r2, exact = balance(s, counters, solvers.get(key), steps)
        if len({v for _, v in s.points}) <= 2 and not (terms and fits(s, r2, exact)):
            left_out[s.key] = "a flag (it only ever takes two values, and no counters balance it exactly), not a quantity that accumulates"
            continue
        if terms and r2 >= MIN_R2:
            found.append((s, terms, r2, exact))
        else:
            why = f"no counters balance it (best R² {r2:.2f}" + (f" with {', '.join(c.key for c, _ in terms)}" if terms else "") + ")"
            left_out[s.key] = why
    # with every balance known, the stand-ins give way (sd.restate); a counter no balance keeps
    # is recorded with why, below
    notes: dict[str, str] = {}
    for pass_ in (split_event_counters, split_foreign_counters):
        found, made = pass_(found, counters, masks, machine_of, fits, MIN_EVENTS)
        notes.update(made)
    found, made, joined = unify_same_flows(found, masks, lambda a, b: same_flow(a, b, n) or lagged_flow(a, b),
                                           first_stamped, machine_of, fits)
    notes.update(made)
    for keep, drop in joined:              # a counter joined to another stands for nothing on its own
        same_as[keep.key] += [{"name": drop.name, "labels": drop.labels}, *same_as.pop(drop.key, [])]
        copies[keep.key] += [drop, *copies.pop(drop.key, [])]
        left_out[drop.key] = made[drop.key]
    dropped = {drop.key for _, drop in joined}
    counters = [c for c in counters if c.key not in dropped]
    # a set of a balance's counters that one unused counter counts at once gives way to it
    # (sd.parsimony: the customers' orders less the app's are the takers' own orders taken)
    found, made = fewer_counters(found, counters, masks, fits, set(notes), machine_of)
    notes.update(made)

    # A level that only fills (its balance only adds) is a stock when its balance is exact,
    # whatever feeds it: a terminal state, where other stocks' outflows end (the orders delivered).
    # One the system's flows explain only roughly is more likely a tally of activity (a log's
    # length) than a stock of the material those flows move: it may only be balanced by counters
    # no ordinary stock uses, or it borrows the system's flows as stand-ins for what it counts.
    ordinary = [x for x in found if not all(sign > 0 for _, sign in x[1])]
    taken = {c.key for _, terms, _, _ in ordinary for c, _ in terms}
    free = [c for c in counters if c.key not in taken]
    kept = list(ordinary)
    for s, terms, r2, exact in found:
        if not all(sign > 0 for _, sign in terms):
            continue
        if exact >= FLAG_EXACT or not any(c.key in taken for c, _ in terms):
            kept.append((s, terms, r2, exact))
            continue
        terms2, r2b, exact2 = balance(s, free, None, masks[s.key])
        if terms2 and r2b >= MIN_R2:
            kept.append((s, terms2, r2b, exact2))
        else:
            left_out[s.key] = f"only an accumulator of other stocks' flows (R² {r2b:.2f} with counters of its own)"
    found, twins = twin_levels(kept, left_out, lambda a, b: same_flow(a, b, n))
    # a state each item leaves within a step is empty at almost every step of the grid, so the
    # chain through it runs past it (sd.hops) or ends at outside and begins again there
    # (sd.passing); joined through it
    where = {"start": start, "end": end, "step": step, "machine_of": machine_of}
    stock_keys = {s.key for s, _, _, _ in found}
    levels = [s for s in series if not s.counter and s.key not in stock_keys and not left_out.get(s.key, "").startswith("the same as")]
    found, hopped, revived = split_hops(found, counters, copies, levels, first_stamped=first_stamped, **where)
    for d in revived:                      # a copy that came back as a hop of its own stands for itself
        counters.append(d)
        left_out.pop(d.key, None)
        for k, recs in same_as.items():
            same_as[k] = [x for x in recs if (x["name"], x["labels"]) != (d.name, d.labels)]
    levels = [s for s in levels if all(s is not h.level for h in hopped)]
    passed = {}
    for p in hopped + passages(found + [(h.level, h.terms, 1.0, 1.0) for h in hopped], counters, levels, copies=copies, **where):
        masks[p.level.key] = balance_steps(p.level, [c for c, _ in p.terms])
        r2, exact = fit_of(p.level, p.terms, masks[p.level.key]) if p.measured else (1.0, 1.0)
        found.append((p.level, p.terms, max(0.0, r2), exact))
        left_out.pop(p.level.key, None)
        passed[p.level.key] = p
    stocks, sid_of, ids = [], {}, set()
    held: dict[str, dict] = {}       # the levels whose value was carried on their machine's word, and for how long
    for s, terms, r2, exact in found:
        sid = unique_id(_slug(s), machine_of(s), ids)
        sid_of[s.key] = sid
        carried, at_end = held_for(s.points, s.intervals if s.intervals is not None else [(start, end)])
        if carried:
            held[sid] = {"minutes": round(carried / 60, 2), "at_end_minutes": round(at_end / 60, 2)}
        p = passed.get(s.key)
        stocks.append(Stock(sid, _title(s), "items", SeriesRef(s.name, s.labels) if not p or p.measured else None,
                            {"balance_r2": round(r2, 4), "exact_steps": round(exact, 4), "steps": n, "balance_steps": len(masks[s.key]),
                             "machine": machine_of(s), "accumulator": all(sign > 0 for _, sign in terms),
                             "balance": [{"series": c.key, "sign": sign} for c, sign in terms],
                             "held_minutes": round(carried / 60, 2),
                             **({"twins": twins[s.key]} if s.key in twins else {}), **(p.evidence() if p else {})}))
    # a counter in two balances connects those stocks (sd.ends: contested ends and co-flows)
    fid_of = {c.key: unique_id(_slug(c), machine_of(c), ids) for c in counters}
    by_counter = claims(found, sid_of, machine_of)
    flow_moves = moves(counters, by_counter, fid_of, machine_of)
    through = {sid_of[k]: p for k, p in passed.items()}
    for mv in flow_moves:
        if mv.src in through or mv.dst in through:
            mv.evidence["through"] = [x for x in (mv.src, mv.dst) if x in through]
    for c in counters:
        if c.key in by_counter:
            continue
        events = sum(c.deltas)
        rare = f"a counter of only {events:g} event{'s' if events != 1 else ''}: fewer than {MIN_EVENTS}, too few to carry a balance; it completed none"
        left_out[c.key] = notes.get(c.key, rare if events < MIN_EVENTS else "a counter no stock's balance needed")

    unit_s = UNITS[time_unit]
    # fit only over the time every series involved was live: before a machine started, or while it
    # was down, its silence is not a rate of zero
    live = [(start, end)]
    for ser in [s for s, _, _, _ in found] + [c for c in counters if c.key in by_counter]:
        if ser.intervals is not None:
            live = intersect(live, ser.intervals)
    live_s = sum(b - a for a, b in live)
    steps_live = [i for i in range(n) if any(a <= start + i * step and start + (i + 1) * step <= b for a, b in live)]
    fit_start = live[0][0] if live else end
    paths = {sid_of[s.key]: Path.of(s.points, live, unit_s) for s, _, _, _ in found}
    # the measured gauges that are not stocks (a rating, a demand; sd.inputs) may drive a flow's
    # rate like a stock may, as input:<name>
    inputs, input_refs = offered_inputs(series, {s.key for s, _, _, _ in found}, left_out)
    for name, vals in inputs.items():
        paths[f"input:{name}"] = Path.of([(start + i * step, v) for i, v in enumerate(vals)], live, unit_s)
    # A stock that only fills (no outflow in its balance) grows with time whatever else happens,
    # so as a driver of another flow's rate it stands in for time itself and finds spurious
    # influences. It stays a stock; it just may not explain other flows. Nor may a stock whose
    # balance counts the flow's own events, one off just before each of them (sd.drivers).
    accumulators = {sid_of[s.key] for s, terms, _, _ in found if all(sign > 0 for _, sign in terms)}
    flows, by_machine = [], defaultdict(list)
    grouped: dict[str, list] = defaultdict(list)       # per counter: its flow, then its co-flows (ends.moves's order)
    for mv in flow_moves:
        grouped[mv.counter.key].append(mv)
    for mvs in grouped.values():
        c = mvs[0].counter
        if live_s <= 0:
            continue
        dl = c.deltas
        y = [dl[i] for i in steps_live]
        # one event has one rate: a counter is fitted once, against its flow's source, and its
        # co-flows (the same events moving another machine's stock) get the same equation; no end
        # of any of them is kept from driving it
        ends = {e for mv in mvs for e in (mv.src, mv.dst) if e}
        barred = co_counting(c, ends, found, sid_of, steps_live, lambda a, b: same_flow(a, b, n))
        events = events_of(c.points, live)
        src = mvs[0].src
        best, *rest = fit_flow(events, live_s / unit_s, paths, src, set(paths) - accumulators - set(barred))
        best["dispersion"] = dispersion(events, live, best, paths, unit_s)
        other = lambda x, src=src: f"_{x['inputs'][0]}" if x["inputs"] and x["inputs"] != [src] else ""   # a form in another stock says which
        alt = {f"aic_{x['form']}{other(x)}": round(x["aic"], 2) for x in rest[:4]}
        alt.update({f"proportional_k{other(x)}": round(x["params"]["k"], 6) for x in [best, *rest] if x["form"] == "proportional"})
        if rejected := {f"linear_{x['inputs'][0]}": x["rejected"] for x in rest if "rejected" in x}:
            alt["rejected"] = rejected
        q = {"events": float(sum(y)), "loglik": round(best["loglik"], 3), "aic": round(best["aic"], 3),
             "dispersion": round(best["dispersion"], 3), "steps": float(len(steps_live)), "live_minutes": round(live_s / 60, 2), **alt}
        for mv in mvs:
            if barred:
                mv.evidence["not_drivers"] = barred
            if c.key in same_as:             # the counters of the same events this one stands for (one flow, measured twice)
                mv.evidence["same_as"] = same_as[c.key]
            # a counter summed over instances is not a series in the store: the flow is measured by each of them
            flows.append(Flow(mv.id, _title(c), mv.src, mv.dst, None if c.members else SeriesRef(c.name, c.labels),
                              [Equation(best["form"], {k: round(v, 6) for k, v in best["params"].items()}, "fitted", "poisson-mle",
                                        (fit_start, end), None, dict(q), list(best["inputs"]))],
                              [SeriesRef(m.name, m.labels) for m in c.members], mv.evidence))
            who = machine_of(c)
            if who:
                by_machine[who].append(mv.id)
    owners = {st.evidence.get("machine") for st in stocks} - {None}
    # what a machine is (a program, an AI agent) is not in the metrics: the model says "machine"
    machines = [Machine(m, m, "machine", "Seen in the metrics store: it writes the series these flows are bound to.",
                        sorted(by_machine.get(m, [])), [SeriesRef(s.name, s.labels) for s in series if machine_of(s) == m])
                for m in sorted(set(by_machine) | owners)]
    model = Model("system", "The system",
                  "Discovered from the metrics store: stocks are levels that counters balance; flows are those "
                  "counters, with equations fitted by Poisson maximum likelihood.",
                  time_unit, stocks, flows, machines)
    model.discovery = {"summed": summed, "start": start, "end": end, "fit_start": fit_start, "live_minutes": round(live_s / 60, 2) if found else 0,
                       "gaps": [[a, b] for (_, a), (b, _) in pairwise(live)] if found else [],
                       "step": step, "sampled": sampled, "series": len(series), "inputs": input_refs, "held": held,
                       "stocks": len(stocks), "flows": len(flows), "min_r2": MIN_R2,
                       "left_out": dict(sorted(left_out.items()))}
    return model


def structure(model: Model) -> list:
    """What a discovery found, without its numbers: stocks, and each flow's ends, form and inputs.
    A new model version is worth saving only when this changes."""
    return [sorted(s.id for s in model.stocks),
            sorted((f.id, f.src or "", f.dst or "", f.current().form if f.current() else "",
                    tuple(f.current().inputs) if f.current() else ()) for f in model.flows)]
