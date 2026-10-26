"""Discovery v1: build the model from the metrics store, without being told what anything is.

Given every series of a project over a window, it finds stocks, the flows between them, the
equation of each flow, and the machine behind each flow:

1. **Sample** every series onto a grid of steps (the last value at or before each step).
2. **Find stocks by conservation.** A level whose changes are explained by counters, added or
   subtracted, is a stock, and those counters are its inflows and outflows:
   ``Δlevel ≈ Σ inflows − Σ outflows`` in every step. The counters (each with a coefficient of +1
   or −1) are found by a local search that keeps a counter only if it explains a real share
   (``sd.balance``). A level is kept only if the balance fits (R² ≥ ``MIN_R2``); everything else is
   left out, with the reason. Two levels that change alike in nearly every step, or that the same
   counters balance, are one stock measured twice: the machine whose counters make the balance
   keeps it, the other is recorded as its twin.
3. **Connect flows.** A counter that is an outflow of one stock and an inflow of another is a flow
   between them; otherwise it comes from or goes to outside (``sd.ends``: when two stocks claim the
   same end, the one the counter explains most keeps it and the other claim is evidence; stocks of
   different machines claiming one counter make it a co-flow, one flow per machine).
4. **Fit each flow's equation** by maximum likelihood, choosing by AIC among:
   - ``constant``: rate = c;
   - ``proportional``: rate = k × the source stock (its exact time-average over the step);
   - ``linear``: rate = c + k × X, for X any stock found. When X is not the flow's own source,
     that is an **influence**: one stock changing the rate of another's flow, the link that
     closes feedback loops.

   Forms are scored with the exact point-process likelihood (each event against the levels just
   before it), not counts per step, which favour spurious forms (see ``fit_flow``). A flow with
   fewer than ``MIN_EVENTS`` events in the window gets the constant form only: an influence fitted
   on one event is noise.
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
from dataclasses import dataclass, field
from itertools import pairwise

from ..metrics import step_sample
from .balance import LeastSquares, balance
from .ends import claims, moves
from .model import Equation, Flow, Machine, Model, SeriesRef, Stock

MIN_R2 = 0.9            # how well a balance must fit for a level to count as a stock
FLAG_EXACT = 0.97         # a two-valued level is a stock only if its balance is exact in this share of steps
SAME_STEPS = 0.03          # counters that differ in no more than this share of steps are one
TWIN_STEPS = 0.97          # levels whose changes are equal in this share of steps are one stock measured twice
MIN_EVENTS = 5             # a flow with fewer events than this in the window gets the constant form only
EVENT_COUNTER = "orchestra_events_total"   # Orchestra's own count of each event type
UNITS = {"second": 1.0, "minute": 60.0, "hour": 3600.0}


def series_key(name: str, labels: dict[str, str]) -> str:
    """A series' identity in a discovery: its name and every label but the project (the machine
    included: two machines' series of one name are two series)."""
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()) if k != "project")
    return f"{name}{{{inner}}}" if inner else name


@dataclass
class Series:
    name: str
    labels: dict[str, str]
    points: list[tuple[float, float]]
    values: list[float]                     # at each grid time
    counter: bool
    members: list = field(default_factory=list)   # the instances' series, when this one sums them (sum_instances)

    @property
    def key(self) -> str:
        return series_key(self.name, self.labels)

    @property
    def deltas(self) -> list[float]:
        """Change per step; for a counter, a drop is a reset (as in Prometheus): the new value is
        what was counted since."""
        if self.counter:
            return [(b - a) if b >= a else b for a, b in pairwise(self.values)]
        return [b - a for a, b in pairwise(self.values)]


def sum_instances(series: list[Series]) -> tuple[list[Series], dict[str, str]]:
    """Counters that differ only by instance, summed into one per machine.

    A model is about machines, not their instances: six workers' counts of one event are one flow.
    Counting each instance apart multiplies the candidates a balance is chosen from (on a busy
    system, past the number of steps, where least squares can no longer tell them apart). An
    instance is an ``instance`` label, or the instance part of a ``source`` (``worker/3``).
    Increments are summed, so one instance's reset does not read as the total going back.
    Returns the series, and what each summed series was made from (for the record)."""
    groups: dict[tuple, list[Series]] = defaultdict(list)
    out: list[Series] = []
    for ser in series:
        src = ser.labels.get("source") or ""
        if not ser.counter or ("instance" not in ser.labels and "/" not in src):
            out.append(ser)
            continue
        labels = {k: v for k, v in ser.labels.items() if k != "instance"}
        if "/" in src:
            labels["source"] = src.partition("/")[0]
        groups[(ser.name, tuple(sorted(labels.items())))].append(ser)
    made: dict[str, str] = {}
    for (name, labels), members in groups.items():
        if len(members) == 1 and "/" not in (members[0].labels.get("source") or "") and "instance" not in members[0].labels:
            out.append(members[0])
            continue
        n = len(members[0].values)
        steps = [sum((b - a) if b >= a else b for a, b in ((m.values[i], m.values[i + 1]) for m in members)) for i in range(n - 1)]
        values, total = [0.0], 0.0
        for d in steps:
            total += d
            values.append(total)
        incs = []                                        # every instance's increments, in time order
        for m in members:
            for (t0, a), (t1, b) in pairwise(m.points):
                incs.append((t1, (b - a) if b >= a else b))
        incs.sort()
        points, total = [], 0.0
        if members[0].points:
            points.append((min(m.points[0][0] for m in members if m.points), 0.0))
        for t, d in incs:
            total += d
            points.append((t, total))
        merged = Series(name, dict(labels), points, values, True, members)
        out.append(merged)
        made[merged.key] = f"summed over {len(members)} instance{'s' if len(members) != 1 else ''}"
    return out, made


def _slug(s: Series) -> str:
    extra = [v for k, v in sorted(s.labels.items()) if k not in ("project", "machine")]
    return "_".join([s.name, *[re.sub(r"\W+", "_", v) for v in extra]])


def _title(s: Series) -> str:
    base = re.sub(r"_total$", "", s.name).replace("_", " ")
    extra = [v for k, v in sorted(s.labels.items()) if k not in ("project", "machine")]
    return base + (f" ({', '.join(extra)})" if extra else "")


def same_flow(a: Series, b: Series, n: int) -> bool:
    """Two counters that count the same events: equal in all but a few steps, or the same events
    stamped a moment apart, so some fall in the next step: one counter's running total is always
    between the other's at the step before and at this step (never more than a step behind). The
    same activity is often measured twice: Orchestra counts every event (orchestra_events_total)
    and the machine counts what it did (a ticket's transitions, an agent's turns); they are one flow,
    not two that share a balance. The lag is allowed only to Orchestra's own count, which is
    stamped after the machine's: two machines' counters a step apart may be a quick buffer's
    inflow and outflow (put on a shelf and taken within seconds), which are not one flow."""
    da, db = a.deltas, b.deltas
    total_a, total_b = sum(da), sum(db)
    if not total_a or abs(total_a - total_b) > max(1.0, SAME_STEPS * total_b):
        return False
    # Orchestra's count of a machine's events can only be a copy of a counter that machine writes:
    # a few rare events (a host restart, an operator's note) otherwise match anything as rare
    if EVENT_COUNTER in (a.name, b.name) and (machine_of(a) is None or machine_of(a) != machine_of(b)):
        return False
    moved = sum(1 for x, y in zip(da, db) if x or y)                   # steps where either counted something
    if sum(1 for x, y in zip(da, db) if x != y) <= SAME_STEPS * moved:  # (of all steps, two rare counters always "agree")
        return True

    def behind(lead: list[float], lag: list[float]) -> bool:
        cl = cg = before = 0.0
        for x, y in zip(lead, lag):
            cl, cg = cl + x, cg + y
            if not before - 1e-9 <= cg <= cl + 1e-9:
                return False
            before = cl
        return True
    return (b.name == EVENT_COUNTER and a.name != EVENT_COUNTER and behind(da, db)) or \
        (a.name == EVENT_COUNTER and b.name != EVENT_COUNTER and behind(db, da))


def machine_of(s: Series) -> str | None:
    """The machine a series belongs to: its ``machine`` label, or, for Orchestra's event counters,
    the ``source`` that emitted the events (``unknown`` is no machine)."""
    who = s.labels.get("machine") or (s.labels.get("source") or "").partition("/")[0]   # baker/2 is the machine baker
    return who if who and who != "unknown" else None


def _is_counter(name: str, values: list[float]) -> bool:
    """Named like a counter, and never falls except for the odd reset (a machine restarting)."""
    drops = sum(1 for a, b in pairwise(values) if b < a)
    return name.endswith("_total") and drops <= max(2, len(values) // 100)


GAP_FACTOR, MIN_GAP_S = 10.0, 60.0


def live_intervals(points: list[tuple[float, float]], start: float, end: float) -> list[tuple[float, float]]:
    """When a series written on a schedule was being written: between consecutive points no further
    apart than ten times its usual interval (at least a minute). A longer silence is missing data (its machine was down
    or cut off), not a measurement: carrying the last value through it would read as "nothing
    happened at this level", which is false."""
    ts = [t for t, _ in points if start - 3600 <= t <= end]
    if len(ts) < 2:
        return []
    gaps = sorted(b - a for a, b in pairwise(ts))
    limit = max(MIN_GAP_S, GAP_FACTOR * gaps[len(gaps) // 2])
    out: list[tuple[float, float]] = []
    for a, b in pairwise(ts):
        if b - a > limit:
            continue
        a, b = max(a, start), min(b, end)
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    if out and ts[-1] >= end - limit:                 # still being written at the end of the window
        out[-1] = (out[-1][0], end)
    return out


def regular(points: list[tuple[float, float]]) -> bool:
    """Written on a schedule (most intervals near the usual one), as a machine's own metrics are.
    A series written only when something happens (Orchestra's event counters) is not: its
    silences mean nothing happened, so they say nothing about whether anything was running."""
    ts = [t for t, _ in points[-2000:]]
    if len(ts) < 10:
        return False
    gaps = sorted(b - a for a, b in pairwise(ts))
    med = gaps[len(gaps) // 2]
    return med > 0 and sum(1 for g in gaps if g <= 3 * med) >= 0.8 * len(gaps)


def intersect(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if lo < hi:
            out.append((lo, hi))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def _within(t: float, live: list[tuple[float, float]]) -> bool:
    i = bisect_right([a for a, _ in live], t) - 1
    return i >= 0 and live[i][0] < t <= live[i][1]


def sample(dump, start: float, step: float, n: int) -> list[Series]:
    """Every series on the grid; leading steps before its first point take its first value."""
    out = []
    times = [start + i * step for i in range(n + 1)]
    for name, labels, pts in dump:
        if not pts:
            continue
        got = dict(step_sample(pts, start, times[-1], step))
        first = next((v for t, v in pts if t >= start), pts[-1][1])
        vals, last = [], None
        for t in times:
            last = got.get(t, last)
            vals.append(first if last is None else last)
        out.append(Series(name, dict(labels), pts, vals, _is_counter(name, vals)))
    return out


def _average(points: list[tuple[float, float]], a: float, b: float) -> float:
    """Time-average of a step-function series over [a, b)."""
    before = [v for t, v in points if t <= a]
    level = before[-1] if before else (points[0][1] if points else 0.0)
    total, t0 = 0.0, a
    for t, v in points:
        if t <= a:
            continue
        if t >= b:
            break
        total += level * (t - t0)
        t0, level = t, v
    total += level * (b - t0)
    return total / (b - a)


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
        return cls(times, values, dict(time_at))

    def before(self, t: float) -> float:
        """The level just before ``t``: what an event at ``t`` saw."""
        i = bisect_left(self.times, t) - 1
        return self.values[i] if i >= 0 else (self.values[0] if self.values else 0.0)

    def integral(self, c: float, k: float) -> float:
        """∫ max(0, c + k × level) dt over the window."""
        return sum(d * max(0.0, c + k * x) for x, d in self.time_at.items())


def events_of(points: list[tuple[float, float]], live: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """A counter's increments inside the live time, as (time, count); a drop is a reset."""
    out, prev = [], None
    for t, v in points:
        if prev is not None and _within(t, live):
            d = v - prev if v >= prev else v
            if d > 0:
                out.append((t, d))
        prev = v
    return out


def fit_flow(events: list[tuple[float, float]], window: float, paths: dict[str, Path], src: str | None,
             drivers: set[str] | None = None) -> list[dict]:
    """Every candidate form for one flow, best (lowest AIC) first, scored with the exact
    point-process likelihood: each event against the rate just before it, the rate integrated
    over the stocks' actual paths:

        log L = Σ count × log rate(t⁻)  −  ∫ rate dt        (rate = c + k × X, never below zero)

    Scoring counts per step instead is biased for outflows: a step's average level is lowered by
    the very outflow being counted, which makes the rate look higher at low levels and favours a
    spurious intercept. The estimates of the constant and proportional forms are the same either
    way (events ÷ time, events ÷ level × time)."""
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
    if src in paths:
        expo = paths[src].integral(0.0, 1.0)
        if expo > 0:
            k = total / expo
            cands.append({"form": "proportional", "params": {"k": k}, "inputs": [src], "loglik": ll(0.0, k, src), "k": 1})
    for sid, p in paths.items():
        xs = list(p.time_at)
        if not xs or max(xs) - min(xs) < 1e-9 or (drivers is not None and sid not in drivers and sid != src):
            continue
        span = max(xs) - min(xs)

        def nll(q, sid=sid):
            v = ll(q[0], q[1], sid)
            return -v if math.isfinite(v) else 1e18
        cc, kk = _nelder_mead(nll, [c0, 0.0], [max(c0, 1e-3) * 0.5, max(c0, 1e-3) / span])
        cands.append({"form": "linear", "params": {"c": cc, "k": kk}, "inputs": [sid], "loglik": ll(cc, kk, sid), "k": 2})
    for cand in cands:
        cand["aic"] = 2 * cand["k"] - 2 * cand["loglik"] if math.isfinite(cand["loglik"]) else math.inf
    return sorted(cands, key=lambda c: c["aic"])


def dispersion(y: list[float], dt: float, form: dict, levels: dict[str, list[float]]) -> float:
    """Pearson χ² per degree of freedom of the counts per step against the chosen form: near 1
    when the form explains the variation, well above 1 when something it lacks drives the flow."""
    p, xs = form["params"], (levels[form["inputs"][0]] if form["inputs"] else [0.0] * len(y))
    mu = [max(1e-9, (p.get("c", 0.0) + p.get("k", 0.0) * x) * dt) for x in xs]
    return sum((v - m) ** 2 / m for v, m in zip(y, mu)) / max(1, len(y) - form["k"])


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
    """The share of steps in which two levels changed by the same amount."""
    da, db = a.deltas, b.deltas
    return sum(1 for x, y in zip(da, db) if abs(x - y) <= 1e-6) / max(1, len(da))


def _owns(s: Series, terms: list) -> int:
    """How many of the balance's counters the level's own machine writes: that machine owns the
    transitions, and the level is its record of them."""
    return sum(1 for c, _ in terms if machine_of(c) is not None and machine_of(c) == machine_of(s))


def twin_levels(found: list, left_out: dict[str, str]) -> tuple[list, dict[str, list[dict]]]:
    """One stock measured twice (a shelf counted by the shelf and by the board): two levels that
    change alike in at least ``TWIN_STEPS`` of the steps, or that the same counters balance. The
    one kept is the machine's whose counters make the balance, then the better balance; the other
    is left out and recorded as its twin, in the kept stock's evidence."""
    kept: list = []
    twins: dict[str, list[dict]] = defaultdict(list)
    for s, terms, r2, exact in found:
        bal = {(c.key, sign) for c, sign in terms}
        other = next((k for k in kept if _equal_steps(s, k[0]) >= TWIN_STEPS or {(c.key, sg) for c, sg in k[1]} == bal), None)
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
        share = _equal_steps(win, lose)
        twins[win.key].append({"series": lose.key, "machine": machine_of(lose), "equal_steps": round(share, 4)})
        for rec in twins[win.key]:
            left_out[rec["series"]] = (f"the same as {win.key} (one stock measured twice: their changes are equal in "
                                       f"{rec['equal_steps']:.0%} of steps)")
    return kept, dict(twins)


def discover(dump, *, start: float, end: float, step: float, time_unit: str = "minute") -> Model:
    """The model the metrics imply over [start, end], with how it was found in ``model.discovery``."""
    n = max(2, int((end - start) // step))
    dt = step / UNITS[time_unit]
    series, summed = sum_instances(sample(dump, start, step, n))
    left_out: dict[str, str] = {}
    # a series written on a schedule that is no longer written at the end of the window (its
    # machine is gone, or was replaced) is not measured now: left out, or its silence would leave no
    # time when every series involved was being written, and nothing could be fitted
    current = []
    for ser in series:
        ivs = live_intervals(ser.points, start, end) if regular(ser.points) else [(start, end)]
        if ivs and ivs[-1][1] >= start + n * step:
            current.append(ser)
        else:
            last = max((t for t, _ in ser.points), default=start)
            left_out[ser.key] = f"no longer written: its last point is {round((end - last) / 60)} min before the end of the window"
    series = current
    counters = [s for s in series if s.counter and any(s.deltas)]
    # counters that moved together in (almost) every step measure the same thing (a machine's own
    # count and Orchestra's count of the event it publishes for it; they may differ by a step at the
    # edge, where one was collected later): balances could not tell them apart, and two stocks
    # choosing different ones would lose the flow that joins them. One is kept: the machine's own,
    # then the shortest name.
    counters.sort(key=lambda c: (c.name.startswith(EVENT_COUNTER), len(c.key), c.key))
    kept_counters: list[Series] = []
    for c in counters:
        twin = next((k for k in kept_counters if same_flow(c, k, n)), None)
        if twin is None:
            kept_counters.append(c)
        else:
            left_out[c.key] = f"the same as {twin.key} (counts the same events)"
    counters = kept_counters
    for s in series:
        if s.counter and not any(s.deltas):
            left_out[s.key] = "a counter that did not move in the window"
    found: list[tuple[Series, list[tuple[Series, int]], float, float]] = []
    ls = LeastSquares([c.deltas for c in counters]) if counters else None
    for s in series:
        if s.counter:
            continue
        if not any(s.deltas):
            left_out[s.key] = "a level that did not change in the window"
            continue
        terms, r2, exact = balance(s, counters, ls)
        # a level that only ever takes two values is usually a flag (a baker is busy or not), and
        # least squares will balance a flag with counters that merely move with it; it is a stock
        # only when counters balance it exactly (a shelf that holds nothing or one item)
        if len({v for _, v in s.points}) <= 2 and not (terms and r2 >= MIN_R2 and exact >= FLAG_EXACT):
            left_out[s.key] = "a flag (it only ever takes two values, and no counters balance it exactly), not a quantity that accumulates"
            continue
        if terms and r2 >= MIN_R2:
            found.append((s, terms, r2, exact))
        else:
            why = f"no counters balance it (best R² {r2:.2f}" + (f" with {', '.join(c.key for c, _ in terms)}" if terms else "") + ")"
            left_out[s.key] = why

    # An accumulator (a stock whose balance only adds) may only be balanced by counters no ordinary
    # stock uses: otherwise it borrows the system's flows as stand-ins for what it really counts.
    ordinary = [x for x in found if not all(sign > 0 for _, sign in x[1])]
    taken = {c.key for _, terms, _, _ in ordinary for c, _ in terms}
    free = [c for c in counters if c.key not in taken]
    kept = list(ordinary)
    for s, terms, r2, exact in found:
        if not all(sign > 0 for _, sign in terms):
            continue
        if not any(c.key in taken for c, _ in terms):
            kept.append((s, terms, r2, exact))
            continue
        terms2, r2b, exact2 = balance(s, free, LeastSquares([c.deltas for c in free]) if free else None)
        if terms2 and r2b >= MIN_R2:
            kept.append((s, terms2, r2b, exact2))
        else:
            left_out[s.key] = f"only an accumulator of other stocks' flows (R² {r2b:.2f} with counters of its own)"
    found, twins = twin_levels(kept, left_out)
    stocks, sid_of, ids = [], {}, set()
    for s, terms, r2, exact in found:
        sid = unique_id(_slug(s), machine_of(s), ids)
        sid_of[s.key] = sid
        stocks.append(Stock(sid, _title(s), "items", SeriesRef(s.name, s.labels),
                            {"balance_r2": round(r2, 4), "exact_steps": round(exact, 4), "steps": n,
                             "machine": machine_of(s), "accumulator": all(sign > 0 for _, sign in terms),
                             "balance": [{"series": c.key, "sign": sign} for c, sign in terms],
                             **({"twins": twins[s.key]} if s.key in twins else {})}))
    # a counter in two balances connects those stocks (sd.ends: contested ends and co-flows)
    fid_of = {c.key: unique_id(_slug(c), machine_of(c), ids) for c in counters}
    by_counter = claims(found, sid_of, machine_of)
    flow_moves = moves(counters, by_counter, fid_of, machine_of)
    for c in counters:
        if c.key not in by_counter:
            left_out[c.key] = "a counter no stock's balance needed"

    end = start + n * step
    unit_s = UNITS[time_unit]
    # fit only over the time every series involved was being written: before a machine started,
    # or while it was down, its silence is not a rate of zero
    live = [(start, end)]
    for ser in [s for s, _, _, _ in found] + [c for c in counters if c.key in by_counter]:
        if regular(ser.points):           # only a scheduled series' silence means its machine was down
            live = intersect(live, live_intervals(ser.points, start, end))
    live_s = sum(b - a for a, b in live)
    steps_live = [i for i in range(n) if any(a <= start + i * step and start + (i + 1) * step <= b for a, b in live)]
    fit_start = live[0][0] if live else end
    levels = {sid_of[s.key]: [_average(s.points, start + i * step, start + (i + 1) * step) for i in steps_live]
              for s, _, _, _ in found}
    paths = {sid_of[s.key]: Path.of(s.points, live, unit_s) for s, _, _, _ in found}
    # A stock that only fills (no outflow in its balance) grows with time whatever else happens,
    # so as a driver of another flow's rate it stands in for time itself and finds spurious
    # influences. It stays a stock; it just may not explain other flows.
    accumulators = {sid_of[s.key] for s, terms, _, _ in found if all(sign > 0 for _, sign in terms)}
    drivers = set(paths) - accumulators
    flows, by_machine = [], defaultdict(list)
    for mv in flow_moves:
        c = mv.counter
        if live_s <= 0:
            continue
        dl = c.deltas
        y = [dl[i] for i in steps_live]
        best, *rest = fit_flow(events_of(c.points, live), live_s / unit_s, paths, mv.src, drivers)
        best["dispersion"] = dispersion(y, dt, best, levels)
        alt = {f"aic_{x['form']}" + (f"_{x['inputs'][0]}" if x["form"] == "linear" else ""): round(x["aic"], 2) for x in rest[:4]}
        alt.update({f"{x['form']}_k": round(x["params"]["k"], 6) for x in [best, *rest] if x["form"] == "proportional"})
        q = {"events": float(sum(y)), "loglik": round(best["loglik"], 3), "aic": round(best["aic"], 3),
             "dispersion": round(best["dispersion"], 3), "steps": float(len(steps_live)), "live_minutes": round(live_s / 60, 2), **alt}
        # a counter summed over instances is not a series in the store: the flow is measured by each of them
        flows.append(Flow(mv.id, _title(c), mv.src, mv.dst, None if c.members else SeriesRef(c.name, c.labels),
                          [Equation(best["form"], {k: round(v, 6) for k, v in best["params"].items()}, "fitted", "poisson-mle",
                                    (fit_start, end), None, q, best["inputs"])],
                          [SeriesRef(m.name, m.labels) for m in c.members], mv.evidence))
        who = machine_of(c)
        if who:
            by_machine[who].append(mv.id)
    owners = {st.evidence.get("machine") for st in stocks} - {None}
    machines = [Machine(m, m, "program", "Seen in the metrics store: it writes the series these flows are bound to.",
                        sorted(by_machine.get(m, [])), [SeriesRef(s.name, s.labels) for s in series if machine_of(s) == m])
                for m in sorted(set(by_machine) | owners)]
    model = Model("system", "The system",
                  "Discovered from the metrics store: stocks are levels that counters balance; flows are those "
                  "counters, with equations fitted by Poisson maximum likelihood.",
                  time_unit, stocks, flows, machines)
    model.discovery = {"summed": summed, "start": start, "end": end, "fit_start": fit_start, "live_minutes": round(live_s / 60, 2) if found else 0,
                       "gaps": [[a, b] for (_, a), (b, _) in pairwise(live)] if found else [],
                       "step": step, "series": len(series),
                       "stocks": len(stocks), "flows": len(flows), "min_r2": MIN_R2,
                       "left_out": dict(sorted(left_out.items()))}
    return model


def structure(model: Model) -> list:
    """What a discovery found, without its numbers: stocks, and each flow's ends, form and inputs.
    A new model version is worth saving only when this changes."""
    return [sorted(s.id for s in model.stocks),
            sorted((f.id, f.src or "", f.dst or "", f.current().form if f.current() else "",
                    tuple(f.current().inputs) if f.current() else ()) for f in model.flows)]
