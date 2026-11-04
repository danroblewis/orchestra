"""Discovery v1: build the model from the metrics store, without being told what anything is.

Given every series of a project over a window, it finds stocks, the flows between them, the
equation of each flow, and the machine behind each flow:

1. **Sample** every series onto a grid of steps (the last value at or before each step), and mark
   when each was live (``sd.series``, ``sd.live``): liveness is the machine's, so a gauge not
   re-written because nothing changed holds its value while its machine is alive, and a
   machine's silence is it down or not yet started, not a measurement of the silence. Orchestra's
   own series (``PLUMBING``: the host's, the Core page's probes) are no candidates, nor is a level
   live for less than ``MIN_COVER`` of the window's data (``too_short``): it stays an input.
2. **Find stocks by conservation.** A level whose changes are explained by counters, added or
   subtracted, is a stock, and those counters are its inflows and outflows:
   ``Δlevel ≈ Σ inflows − Σ outflows`` in every step the level and the counters were live in.
   The counters (each with a coefficient of +1 or −1) are found by a local search from many
   starts that keeps a counter only if it explains a real share, searching only counters that
   counted enough events, for a level that changed in enough steps (``sd.balance``: fewer
   coincide by chance). The level's own machine's counters come first (its record of its
   transitions): when they balance it within the tolerance, another machine's counter never
   replaces one of them, and enters only to explain the residual they leave; every counter is
   searched only when the machine's own do not balance it. A channel's backlog (counted traffic,
   ``orchestra.sources.traffic``) is first balanced by its own traffic: what was produced into the
   channel, less what its own consumer took (``channel_balance``). Only counters in the level's own
   unit are searched (``sd.units``: seconds never balance a queue). A level is kept only if the
   balance fits (R² ≥ ``MIN_R2``) and, once every balance is restated and twins are joined, on
   evidence that holds (``sd.accept``, ``sd.identify``): its counters chosen again on each half of
   the window, and, short of exact, its choice on one half predicting the other, its running residual
   reproducing the level, and a shift null of the same search priced against it. A count of reporters
   balanced by its own turnover is a balance by construction (``sd.construction``), and so is a place's level
   balanced by its own moves, as its instrument declared them (``collect.views``): taken as declared,
   never searched for. Every stock records
   how far to trust it (``sd.stocktrust``); everything else is left out, with the reason. With every balance
   known, a counter that stands in for others gives way to them (``sd.restate``: Orchestra's
   event counter to the machine counters it sums, another machine's copy to the machine's own,
   two machines' counts of one flow to one). Two levels that change alike in nearly every step,
   or that the same counters balance, are one stock measured twice: the machine whose counters
   make the balance keeps it, the other is recorded as its twin. A level that counts a stock's
   servers busy is its capacity, shown in that stock's evidence (``sd.capacity``). Two levels of one name that
   differ in what they measure (pods by region, and pods) are never twins, and a level is never
   balanced by the counters of another level of its name (``barred_counters``).
3. **Connect flows.** A counter that is an outflow of one stock and an inflow of another is a flow
   between them; otherwise it comes from or goes to outside (``sd.ends``: when two stocks claim the
   same end, the one the counter explains most keeps it and the other claim is evidence; stocks of
   different machines claiming one counter make it a co-flow, one flow per machine). A state each
   item leaves within a step is empty at almost every step, so the chain through it runs past it
   or splits through outside; it is joined through again (``sd.hops``, ``sd.passing``), on the
   measured level whose raw points show it (``sd.between``) or on a hidden stock.
4. **Fit each flow's equation** on its own window (``flow_window``: when its counter and its
   stocks were live) by maximum likelihood, choosing by AIC among:
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
5. **Associate machines** with flows, only as hypotheses with their evidence (``sd.attribute``):
   the machines whose own events on the bus (``orchestra_events_total``, per type and source)
   match a counter's increments; several may match one flow, and a machine may match none. Who
   wrote a series (its ``instrument`` or ``machine`` label) is never read for this, and nothing
   declares it: a measurement is not a machine (AGENTS.md rule 7). A flow with none says no machine
   is associated yet. The hypotheses change no equation and no structure.
6. **Levels no counters balance** may still be stocks: their net flow is fitted from the other
   series (``sd.netflow``), with origin ``fitted``; those it refutes stay inputs, with the reason.

Structure is discovered and parameters are fitted, so equations record ``origin: fitted`` with
``method: poisson-mle`` and the model records how it was found (``Model.discovery``).

What this cannot do yet: stocks no series measures (hidden stocks), delays, non-linear forms,
eras. Those are the SD Lab strategies' job, and they are still unproven on real data."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from itertools import accumulate, pairwise

from . import construction
from . import explain as explained
from .accept import accepted, stock_trust
from .attribute import associate, candidates
from .balance import MIN_EVENTS, MIN_GAIN, LeastSquares, balance, columns, fit_of, parsimonious
from .capacity import capacity_views
from .coarse import coarse, on_writes, slowest
from .driverchoice import adjacency, choose
from .drivers import AIC_MARGIN, EVENTS_PER_PARAM, behind, co_counting
from .ends import claims, moves
from .hops import split_hops
from .identify import timing_limited, two_clocks
from .inputs import input_name, keep_apart, offered_inputs, own_paths
from .live import (
    arrived,
    balance_steps,
    gone,
    held_for,
    intersect,
    length,
    level_steps,
    live_span,
    observed,
    observed_from,
    union,
    within,
)
from .model import Equation, Flow, Machine, Model, SeriesRef, Stock
from .netflow import stocks as net_flow_stocks
from .netnull import measured as net_evidence
from .parsimony import fewer_counters
from .passing import passages, unread
from .path import Path
from .path import by_level as _by_level
from .path import nelder_mead as _nelder_mead
from .pins import declared as declared_stocks
from .properties import statistic
from .resolution import LINEAR, intervals_with, real_points, steps_of
from .restate import (
    buffers,
    bus_copies,
    own_counters_back,
    split_event_counters,
    split_foreign_counters,
    unify_same_flows,
)
from .series import (
    EVENT_COUNTER,
    NOT_NAMED,
    ORCHESTRA_EVENTS_REASON,
    PLUMBING,
    Series,
    not_current_reason,
    orchestra_events,
    plumbing_reason,
    sample,
    sum_instances,
    writer_of,
)
from .titles import Places, plural
from .units import unit_of

MIN_R2 = 0.9            # how well a balance must fit for a level to count as a stock
FLAG_EXACT = 0.97         # a two-valued level is a stock only if its balance is exact in this share of steps
SAME_STEPS = 0.03          # counters that differ in no more than this share of steps are one
TWIN_STEPS = 0.97          # levels whose changes are equal in this share of steps are one stock measured twice
TWIN_CORR = 0.9            # ... or whose changes correlate this well (one a moment behind the other)
TWIN_SCALE = 0.2           # ... and only when the levels themselves match: their spreads within this share of each other
TWIN_OFFSET = 0.5          # ... and their difference, usually, within this share of the level's own spread (or a step's change)
TWIN_SIZE = 0.1            # ... or of its size (three orphan files beside a shelf of forty)
MIN_STEPS = 5              # a level live in fewer steps than this (while its counters were) cannot be balanced
MIN_COVER = 0.5            # a level live for less than this share of the window's data is too new (or too broken) to be a stock yet
DRIVER_COVER = 0.95        # a stock may drive a flow only if it was live for this share of the time the flow is fitted on
SHORT = "written for only"  # the start of the reason a level too new to be a stock is left out (it stays an input)
UNITS = {"second": 1.0, "minute": 60.0, "hour": 3600.0}
LEAD_S = 60.0              # a driver's level is compared this long before and after a flow's events (_follows)
NOT_IDENTITY = {"instrument", "machine", "source", "project", "instance"}   # who wrote a series, not which thing it measures


def _said(s: Series) -> list[str]:
    """The label values that say which series it is: not the project's or its writer's, not a value
    with nothing to say (RabbitMQ's vhost ``/``, which would end an id in ``__``), and not one
    another value already says (a queue ``analytics.clicks`` says its consumer ``analytics`` and its
    exchange ``clicks``: the id is ``…_analytics_clicks``, not ``…_analytics_clicks_analytics_clicks``)."""
    vals = [v for k, v in sorted(s.labels.items()) if k not in NOT_NAMED and re.sub(r"\W+", "", v)]
    words = [set(filter(None, re.split(r"\W+", v))) for v in vals]
    return [v for i, v in enumerate(vals)
            if not any(j != i and (words[i] < words[j] or (words[i] == words[j] and j < i)) for j in range(len(vals)))]


def _slug(s: Series) -> str:
    return "_".join([s.name, *[re.sub(r"\W+", "_", v) for v in _said(s)]])


def _in_words(s: Series) -> str | None:
    """A series said in words by how its name and labels read, not by a place: Orchestra's own count
    of the bus by its event type and source ("item.closed events (supervisor)"); a series whose one
    label is a word of its name, with a plural noun after it, is what those words count on that
    label's value (``git_branch_commits{branch="main"}``: "commits on main")."""
    own = {k: v for k, v in s.labels.items() if k not in NOT_NAMED}
    if s.name == EVENT_COUNTER and own.get("type"):
        return f"{own['type']} events" + (f" ({own['source']})" if own.get("source") else "")
    words = [w for w in re.sub(r"_total$", "", s.name).split("_") if w]
    if len(own) == 1:
        [(k, v)] = own.items()
        rest = words[words.index(k) + 1:] if k in words[:-1] else []
        if rest and len(rest) == 1 and plural(rest[0]) and re.search(r"[^\W\d_]", v):
            return " ".join(rest) + f" on {v}"
    return None


def _title(s: Series, places: Places | None = None) -> str:
    """What the model calls a part: what sits in a place its instrument's count spells, the age of
    them, or a move between places, in words (``sd.titles``); a series its name and labels say in
    words (``_in_words``); otherwise its series' name and the label values that say which one. The
    pages show this title (sd-graph.js)."""
    if places is not None and (t := places.level(s.labels, s.key, s.name) if not s.counter else places.move(s.labels, s.key)):
        return t
    if places is not None and (t := places.sourced(s.name, s.labels, s.key)):
        return t
    if t := _in_words(s):
        return t
    base = re.sub(r"_total$", "", s.name).replace("_", " ")
    extra = _said(s)
    return base + (f" ({', '.join(extra)})" if extra else "")


def _named(s: Series, places: Places | None) -> dict:
    """The record that a part's title is its instrument's places' or its words' (the pages show it
    as it is), with its tags (``sd.titles``: the labels its place does not spell, its view's noun)."""
    if places is not None and (places.move(s.labels, s.key) if s.counter else places.level(s.labels, s.key, s.name)):
        noun = None if s.counter else (places.provenance.get(s.key) or {}).get("noun")
        tags = places.move_tags(s.labels, s.key) if s.counter else places.level_tags(s.labels, s.key, s.name)
        return {"named": "places", **({"noun": noun} if noun else {}), **({"tags": tags} if tags else {})}
    if places is not None and places.sourced(s.name, s.labels, s.key):
        return {"named": "words", "tags": places.sourced_tags(s.name, s.labels, s.key)}
    return {"named": "words"} if _in_words(s) else {}


def _never_falls(s: Series) -> bool:
    """Whether a level never went down in the window: an accumulator only fills (its balance's
    terms all add, and its level never fell: a repository's commits, unless force-pushed back)."""
    return all(b >= a for (_, a), (_, b) in zip(s.points, s.points[1:]))


def _words(v: str) -> list[str]:
    return [w for w in re.split(r"[\W_]+", v.lower()) if w]


def _between_titles(found: list, passed: dict, places: Places | None = None) -> tuple[dict[str, str], dict[str, dict]]:
    """A state no series measures (an unmeasured passage, ``sd.passing``) is named by the places
    its moves name, when every one names one (``sd.titles``: "deliveries between write and
    sail_check", with the places it spans and its tags);
    otherwise by its neighbours: "between <what its ins drain> and <what its outs fill>", never
    after the counter that fills it (the owner, 2026-11-01: "after work item moves (write.held,
    open_pr.waiting, delivery_sail)" read as three things in one stock). Its id keeps the level
    the counters imply. Returns the titles, and, of those named by places, the record of each
    (``spans``: the places it spans; ``tags``)."""
    out, named = {}, {}
    for key, p in passed.items():
        if p.measured:
            continue
        if places is not None and (t := places.between(p.ins, p.outs)):
            out[key] = t
            named[key] = {k: v for k, v in (("spans", places.spans(p.ins, p.outs)), ("tags", places.between_tags(p.ins, p.outs))) if v}
            continue
        ins, outs = {c.key for c in p.ins}, {c.key for c in p.outs}
        side = lambda keys, sign, key=key: list(dict.fromkeys(
            _title(s, places) for s, terms, _, _ in found if s.key != key and any(c.key in keys and g == sign for c, g in terms)))
        src, dst = side(ins, -1) or ["outside"], side(outs, 1) or ["outside"]
        out[key] = f"between {' or '.join(src)} and {' or '.join(dst)}"
    return out, named


def _same_total(a: Series, b: Series) -> bool:
    """Whether two counters could count the same events: their totals agree, and Orchestra's count
    of a machine's events is only compared with a counter that machine writes (a few rare events,
    a host restart or an operator's note, otherwise match anything as rare)."""
    total_a, total_b = sum(a.deltas), sum(b.deltas)
    if not total_a or abs(total_a - total_b) > max(1.0, SAME_STEPS * total_b):
        return False
    return not (EVENT_COUNTER in (a.name, b.name) and (writer_of(a) is None or writer_of(a) != writer_of(b)))


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


def named_apart(levels: list[Series]) -> dict[str, set[str]]:
    """Per label, the values that tell measured levels apart (the regions pods are counted in)."""
    out: dict[str, set[str]] = defaultdict(set)
    for s in levels:
        for k, v in _identity(s.labels).items():
            out[k].add(v)
    return out


def counts_apart(a: Series, b: Series, named: dict[str, set[str]]) -> bool:
    """Two counters that count different things: they differ in a label whose values tell measured
    levels apart (``named_apart``: pods started in us-east, and pods started or stopped in us-west).
    However often their events coincide (rolling deploys that reach every region in the same
    minutes), each is its own level's turnover, never the same events. A machine's two counts of
    one move made in two hops (``to`` one state, ``from`` it) differ in labels no level has, and may
    still be one."""
    ia, ib = _identity(a.labels), _identity(b.labels)
    return any(k in ib and ib[k] != v and {v, ib[k]} <= named.get(k, set()) for k, v in ia.items())


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
             drivers: set[str] | None = None, slow: dict[str, float] | None = None, start: float = 0.0,
             fills: set[str] | None = None, near: dict[str, int] | None = None) -> list[dict]:
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
    constant and the form proportional to the flow's own source are all it is offered. A driver
    slower than the grid (``slow``: its resolution in seconds, by path) is known only once per
    interval of its resolution, so the events within one such interval (from ``start``) are one
    observation of it: it needs as many intervals holding the flow's events as a form needs events
    (``sd.resolution.intervals_with``). A space-weather index that changes every few minutes does
    not drive a machine's jobs because the machine happened to be busy while it was high.

    A stock the flow fills (``fills``: its destination, and every backlog a copy of it fills) may
    drive it only the other way: the fuller, the slower (a capacity: free bakers freed more slowly
    the fewer are busy). It is higher after a burst of the flow's own events, so a rate rising
    with it reads the flow's effect as its cause (a publisher fitted as publishing faster the
    fuller a queue its own messages fill); such a form is rejected.

    The flow's own form is the plain one (constant, or proportional to the flow's own source) with
    the lowest AIC, unless a line in its source beats it by at least ``AIC_MARGIN`` (in
    quasi-likelihood: the events' bursts discount it) and survives the refutations of
    ``sd.driverchoice``: a second parameter must earn its place, and a tie goes to the plain form.
    A form that reads another series (a driver) is chosen over it only when it also pays for the
    search and survives the same refutations (a trend in time, the other half of the window, the
    driver read away from the events); ties among survivors go to the series nearest the flow by
    name and labels (``near``). The chosen form's ``driver`` says what was tried and why. A line's rate stops
    at zero, and the line may go below it only where the data have shown that nothing flows: at
    levels the stock held long enough for ``MIN_EVENTS`` events to be due at the flow's mean rate
    (a shelf kept full for an hour, with no order placed). Where it held them too briefly for
    that, the zero is a rate the data never saw, and the form is rejected whatever its AIC (a
    twelfth of an hour of a baker at the oven, during which nothing happened to arrive); it stays
    in the list, marked ``rejected`` with the reason."""
    total = sum(d for _, d in events)
    if total < MIN_EVENTS:                 # too few events to tell a form from noise: the rate alone
        paths, src = {}, None
    at = {sid: _by_level(events, [p.before(t) for t, _ in events]) for sid, p in paths.items()}
    flat = _by_level(events, [0.0] * len(events))

    def ll(c: float, k: float, sid: str | None) -> float:
        out = 0.0
        for x, d in at[sid] if sid else flat:
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
        seen = intervals_with(events, start, slow[sid]) if slow and sid in slow else total   # observations of this driver
        filled = bool(fills) and sid in fills and sid != src        # the flow's own events raise it
        span = max(xs) - min(xs)
        follows = (lambda sid=sid, p=p, span=span: _follows(events, p, c0, span)) if sid != src and not filled else (lambda: "")
        if expo > 0 and (sid == src or seen >= EVENTS_PER_PARAM) and not filled:
            k = total / expo
            cand = {"form": "proportional", "params": {"k": k}, "inputs": [sid], "loglik": ll(0.0, k, sid), "k": 1}
            if sid != src and (why := follows()):
                cand["rejected"] = why
            cands.append(cand)
        if seen < 2 * EVENTS_PER_PARAM:
            continue

        def nll(q, sid=sid):
            v = ll(q[0], q[1], sid)
            return -v if math.isfinite(v) else 1e18
        cc, kk = _nelder_mead(nll, [c0, 0.0], [max(c0, 1e-3) * 0.5, max(c0, 1e-3) / span])
        cand = {"form": "linear", "params": {"c": cc, "k": kk}, "inputs": [sid], "loglik": ll(cc, kk, sid), "k": 2}
        if sid != src and not filled and (why := follows()):           # the flow's own ends move at its events
            cand["rejected"] = why
        if filled and kk > 0:
            cand["rejected"] = (f"its rate rises with {sid}, which its own events fill: higher after a burst of them, so the "
                                "form reads the flow's effect as its cause")
        level, held = p.below_zero(cc, kk)
        if level is not None and c0 * held < MIN_EVENTS:
            cand["rejected"] = (f"its rate is below zero from level {level:g} of {sid}, which the stock held only long enough for "
                                f"{c0 * held:.1f} events at this flow's mean rate: too few to have seen that nothing flows there")
        cands.append(cand)
    for cand in cands:
        cand["aic"] = 2 * cand["k"] - 2 * cand["loglik"] if math.isfinite(cand["loglik"]) else math.inf
        if not math.isfinite(cand["aic"]) and "rejected" not in cand:
            # an event came where the form's rate is nothing (a stock read empty): it cannot have
            # produced the data, so it is not fitted, and says why rather than carrying an infinite AIC
            on = cand["inputs"][0] if cand["inputs"] else "time"
            cand["rejected"] = f"not fitted: an event came while its rate in {on} was zero, so the form cannot produce the data"
    plain = min((c for c in cands if c["k"] == 1 and c["inputs"] in ([], [src])), key=lambda c: c["aic"])
    # a line in the source, or another series, must earn its place (another series against the size
    # of the search too) and survive the refutations (sd.driverchoice); what was found is kept either way
    best, evidence = choose(cands, plain, src, paths, events, next(iter(paths.values())).unit_s, near) if paths else (plain, {})
    best["driver"] = evidence
    return [best, *sorted((c for c in cands if c is not best), key=lambda c: ("rejected" in c, c["aic"]))]


def _follows(events: list[tuple[float, float]], p: Path, c0: float, span: float) -> str:
    """Why a level read by a flow's rate follows the flow rather than leading it, or nothing: the
    rate fitted on the level ``LEAD_S`` later explains the events better, by ``AIC_MARGIN``, than
    on the level at the time. A cause comes first: a level that drives the rate is best read as it
    was when the events came. A count of the last two minutes' orders, high after each rush began,
    fits the orders as a cause would, until it is read a minute later and fits them better."""
    def best(shift: float) -> float:
        xs = _by_level(events, [p.before(t + shift) for t, _ in events])

        def nll(q):
            out = 0.0
            for x, d in xs:
                r = q[0] + q[1] * x
                if r <= 1e-12:
                    return 1e18
                out += d * math.log(r)
            return -(out - p.integral(q[0], q[1]))
        return -nll(_nelder_mead(nll, [c0, 0.0], [max(c0, 1e-3) * 0.5, max(c0, 1e-3) / span]))
    later, now = best(LEAD_S), best(0.0)
    if later > now + AIC_MARGIN:
        return (f"the level a minute after each event explains the flow better than the level at the time "
                f"(log-likelihood {later:.1f} against {now:.1f}): it follows what drives the flow, it does not drive it")
    return ""


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
    at = [(t, int(d)) for t, d in events if int(d) > 0]
    n = sum(d for _, d in at)                       # the events, one by one
    if n < 2:
        return 1.0
    between = lambda a, b: paths[x].expected(a, b, c, k) if x else max(0.0, c) * sum(max(0.0, min(b, hi) - max(a, lo)) for lo, hi in live) / unit_s
    # events at one instant are apart by nothing: of the n − 1 gaps, all but those between
    # instants are 0, so they are counted, not listed (a counter of bytes counts millions a step)
    gaps = [between(a, b) for (a, _), (b, _) in pairwise(at)]
    zeros = (n - 1) - len(gaps)
    mean = sum(gaps) / (n - 1)
    return (sum((g - mean) ** 2 for g in gaps) + zeros * mean * mean) / max(1, n - 2) / max(mean * mean, 1e-12)


def too_short(s: Series, since: float, end: float, awake: list[tuple[float, float]]) -> str:
    """Why a level is too new to be a stock yet, or nothing: it was live for less than
    ``MIN_COVER`` of the window's data (from ``since``, when the first series was live in the
    window, and while anything was written: ``awake``, sd.live.observed). A collector started ten minutes ago has ten minutes of a level: balanced on those, a
    weather series fits whatever counters moved in them, and fitted with the rest it would cut every
    other flow's window to its own. It stays an input until it covers enough. Its changes are also
    counted by each layer's own minimum (``MIN_EVENTS`` for a balance, ``EVENTS_PER_PARAM`` per
    parameter for a net flow), over the time it covers."""
    watched = intersect(awake, [(since, end)])
    span = length(watched)
    got = length(intersect(live_span(s, end), watched))
    if span <= 0 or got >= MIN_COVER * span:
        return ""
    return (f"{SHORT} {got / 60:.0f} min of the {span / 60:.0f} min the window holds data for ({got / span:.0%}, less than "
            f"the {MIN_COVER:.0%} a stock must cover): too new to be a stock yet, an input until it covers enough")


def flow_window(own: list[Series], sources: dict[str, tuple[list, list | None]], start: float, end: float, unit_s: float,
                cache: dict) -> tuple[list[tuple[float, float]], dict[str, Path]]:
    """The time a flow is fitted on, and the paths its rate may read over it. The time is when the
    flow's own series (its counter, its stocks) were live, cut further only by the stocks live for
    at least ``DRIVER_COVER`` of it, which may drive it; a stock live for less of it (a machine
    started later, or down for a while) is not offered as a driver, and does not cut the flow's
    window. ``sources``: each path's points and when it was live (None: always)."""
    live = [(start, end)]
    for ser in own:
        if ser.intervals is not None:
            live = intersect(live, ser.intervals)
    total = length(live)
    usable = {pid: iv for pid, (_, iv) in sources.items()
              if iv is None or (total > 0 and length(intersect(live, iv)) >= DRIVER_COVER * total)}
    for iv in usable.values():
        if iv is not None:
            live = intersect(live, iv)
    key = (tuple(live), tuple(sorted(usable)))
    if key not in cache:
        cache[key] = {pid: Path.of(sources[pid][0], live, unit_s) for pid in usable}
    return live, cache[key]


def ref(s: Series) -> SeriesRef:
    """The model's reference to a series, with its resolution and how it was read (``sd.resolution``)."""
    r = s.resolution
    return SeriesRef(s.name, s.labels, resolution_s=None if r is None or r.seconds is None else round(r.seconds, 3),
                     read=r.read if r else None)


def unique_id(slug: str, machine: str | None, taken: set[str]) -> str:
    """``slug``, or with the machine's name when another series already has it (two machines'
    series of one name): everything keyed by id needs each id once."""
    sid, i = slug, 1
    while sid in taken:
        i += 1
        sid = f"{slug}_{machine or 'other'}" + (f"_{i}" if i > 2 else "")
    taken.add(sid)
    return sid


def _live_in(s: Series, n: int) -> list[bool]:
    live = set(s.live) if s.live is not None else None
    return [live is None or i in live for i in range(n)]


def _equal_steps(a: Series, b: Series) -> float:
    """The share of the steps in which either level changed where both changed by the same
    amount. Steps where neither moved say nothing: over a long window every quiet level would
    be every other's twin. A step in which one was live and the other not is a disagreement: a
    level absent while the other moved is no evidence that they are one."""
    n = min(len(a.deltas), len(b.deltas))
    la, lb = _live_in(a, n), _live_in(b, n)
    agree = moved = 0
    for i in range(n):
        if la[i] != lb[i]:
            moved += 1
        elif la[i] and (abs(a.deltas[i]) > 1e-6 or abs(b.deltas[i]) > 1e-6):
            moved += 1
            agree += abs(a.deltas[i] - b.deltas[i]) <= 1e-6
    return agree / max(1, moved)


def _alike(a: Series, b: Series) -> dict[str, float]:
    """How alike two levels are: the correlation of their changes on the steps both were live in,
    scaled by the share of the steps either was live in that both were (a step one was absent in
    is a disagreement); and the share of the steps in which either held something where both held
    the same, a step only one was live in counting as unequal."""
    n = min(len(a.deltas), len(b.deltas))
    la, lb = _live_in(a, n), _live_in(b, n)
    steps = [i for i in range(n) if la[i] and lb[i]]
    either = sum(1 for i in range(n) if la[i] or lb[i])
    da, db = [a.deltas[i] for i in steps], [b.deltas[i] for i in steps]
    k = max(1, len(steps))
    ma, mb = sum(da) / k, sum(db) / k
    va, vb = sum((x - ma) ** 2 for x in da), sum((y - mb) ** 2 for y in db)
    corr = sum((x - ma) * (y - mb) for x, y in zip(da, db)) / math.sqrt(va * vb) if va > 0 and vb > 0 else 0.0
    corr *= len(steps) / max(1, either)
    held = [i for i in range(n) if (la[i] or lb[i]) and (a.values[i + 1] or b.values[i + 1])]
    same = (sum(1 for i in held if la[i] and lb[i] and abs(a.values[i + 1] - b.values[i + 1]) <= 1e-6) / len(held)
            if len(held) >= MIN_EVENTS else 0.0)
    return {"change_correlation": corr, "equal_values": same}


def _identity(labels: dict[str, str]) -> dict[str, str]:
    """The labels that say which thing a series measures (not who wrote it)."""
    return {k: v for k, v in labels.items() if k not in NOT_IDENTITY}


def _parts_of_one(a: Series, b: Series) -> bool:
    """Two levels of one name that measure different things of it: one a finer grouping of the
    other (a part and its total: pods by region and pods), or two parts (another region). A part
    is not its sum, nor another part, however alike they move."""
    if a.name != b.name:
        return False
    ia, ib = set(_identity(a.labels).items()), set(_identity(b.labels).items())
    return ia != ib


def _one_reading(a: Series, b: Series) -> bool:
    """Two levels of one name grouped by different labels that read the same at every step and
    were live alike: one split by a label that has a single value here, and its total (the lag of
    the one group that reads a topic, by group and by topic). Two parts of one grouping (two
    regions) are never this, however equal: they differ in a value, not in what they are grouped by."""
    if a.name != b.name or set(_identity(a.labels)) == set(_identity(b.labels)) or a.live != b.live:
        return False
    n = min(len(a.values), len(b.values))
    return any(a.deltas) and all(abs(a.values[i] - b.values[i]) <= 1e-9 * max(1.0, abs(a.values[i])) for i in range(n))


def barred_counters(levels: list[Series], counters: list[Series]) -> dict[str, set[str]]:
    """For each level, the counters that belong to another level of the same name: a counter that
    has a different value of a label the level also has (``region="us-west"`` for the eu-west
    pods), where another level of that name agrees with the counter on every label they share.
    Those count that level's things, never this one's, however well they would balance it."""
    by_name: dict[str, list[Series]] = defaultdict(list)
    for s in levels:
        by_name[s.name].append(s)
    out: dict[str, set[str]] = {}
    for s in levels:
        sibs = [o for o in by_name[s.name] if o is not s]
        if not sibs:
            continue
        mine = _identity(s.labels)
        for c in counters:
            theirs = _identity(c.labels)
            differ = {k for k in theirs if k in mine and theirs[k] != mine[k]}
            if differ and any(all(o.labels.get(k) == theirs[k] for k in differ)
                              and all(o.labels[k] == v for k, v in theirs.items() if k in _identity(o.labels)) for o in sibs):
                out.setdefault(s.key, set()).add(c.key)
    return out


def _apart(a_terms: list, b_terms: list, a_exact: float, b_exact: float, same_flow) -> bool:
    """Two levels each balanced exactly by counters of which none counts the other's events: each
    is explained, step by step, by what happened to its own things. However alike their values
    (two services' pods in one region, both two pods most of the time and both none while the
    region is down), they are two stocks."""
    return a_exact >= FLAG_EXACT and b_exact >= FLAG_EXACT and \
        not any(ca is cb or same_flow(ca, cb) or lagged_flow(ca, cb) for ca, _ in a_terms for cb, _ in b_terms)


def _bare(name: str) -> str:
    """A series' name without the prefix of the source it was read from (``shop:queue`` is ``queue``)."""
    return name.rpartition(":")[2]


def _same_series(a: Series, b: Series) -> bool:
    """The same series by identity, read twice: one name (a source's prefix aside) and the same
    labels of what it measures (two stores that both hold it, two addresses of one store)."""
    return a.key != b.key and _bare(a.name) == _bare(b.name) and _identity(a.labels) == _identity(b.labels)


def levels_match(a: Series, b: Series) -> bool:
    """Whether two levels read alike as levels, not only as changes: on the steps both were live,
    they spread alike over the window (within ``TWIN_SCALE``: a copy written every other step, or
    a moment behind, spreads as the level does, where the spread of its changes would not), and
    their difference is usually (in half the steps) within ``TWIN_OFFSET`` of the larger spread,
    ``TWIN_SIZE`` of the larger level, or a step's change of either (a copy a moment behind). Two
    warehouses drained in proportion to one order stream change in step (correlation 1.00) and are
    two stocks: one holds 1.25 M units and loses 0.6 of the picks, the other 0.8 M and 0.4."""
    n = min(len(a.values), len(b.values))
    la, lb = _live_in(a, n - 1), _live_in(b, n - 1)
    both = [i for i in range(n - 1) if la[i] and lb[i]]
    if not both:
        return False
    va, vb = [a.values[i + 1] for i in both], [b.values[i + 1] for i in both]
    sa, sb = _spread(va), _spread(vb)
    if max(sa, sb) > 0 and abs(sa - sb) > TWIN_SCALE * max(sa, sb):
        return False
    size = max(abs(sorted(va)[len(va) // 2]), abs(sorted(vb)[len(vb) // 2]))
    room = max(max(sa, sb) * TWIN_OFFSET, TWIN_SIZE * size)
    near = sum(1 for k, i in enumerate(both)
               if abs(va[k] - vb[k]) <= max(0.5, room, abs(a.deltas[i]), abs(b.deltas[i]),
                                            abs(a.deltas[i - 1]) if i else 0.0, abs(b.deltas[i - 1]) if i else 0.0))
    return near >= 0.5 * len(both)


def _spread(xs: list[float]) -> float:
    m = sum(xs) / max(1, len(xs))
    return math.sqrt(sum((x - m) ** 2 for x in xs) / max(1, len(xs)))


def _twins(a: Series, b: Series, a_terms: list, b_terms: list, same_flow, a_exact: float = 0.0, b_exact: float = 0.0,
           unit: dict[str, str] | None = None) -> bool:
    if a.traffic and b.traffic and a.traffic[0] == b.traffic[0] == "backlog":
        return False            # two queues a source declared: never one stock measured twice, however alike (one consumer acks both at once)
    if unit and unit.get(a.key) != unit.get(b.key):
        return False            # bytes and messages are never one stock measured twice, however alike they move (sd.units)
    if _one_reading(a, b):
        return True
    if _parts_of_one(a, b):
        return False
    if not (_same_series(a, b) or levels_match(a, b)):
        return False            # alike in their changes, but two levels apart: two stocks (two warehouses, one order stream)
    if _equal_steps(a, b) >= TWIN_STEPS or _same_balance(a_terms, b_terms, same_flow):
        return True
    if _apart(a_terms, b_terms, a_exact, b_exact, same_flow):
        return False
    alike = _alike(a, b)
    return alike["change_correlation"] >= TWIN_CORR or alike["equal_values"] >= TWIN_STEPS


def _owns(s: Series, terms: list) -> int:
    """How many of the balance's counters the level's own machine writes: that machine owns the
    transitions, and the level is its record of them."""
    return sum(1 for c, _ in terms if writer_of(c) is not None and writer_of(c) == writer_of(s))


def own_balance(s: Series, counters: list[Series], steps: list[int], fits) -> tuple[list | None, float, float]:
    """The level's balance made of its own machine's counters (its record of its transitions, and
    Orchestra's counts of its events), when they balance it within the tolerance: that is its
    balance, whatever another machine's counts of the same events would say in fewer terms or a
    step more exactly (one machine's turns are not another's moves). Another machine's
    counter enters only to explain the residual the machine's own leave, when there is one. None
    when the machine's own do not balance it: then every counter is searched."""
    own = [c for c in counters if writer_of(s) is not None and writer_of(c) == writer_of(s)]
    terms, r2, exact = balance(s, own, None, steps) if own else ([], 0.0, 0.0)
    if not (terms and fits(s, r2, exact)):
        return None, 0.0, 0.0
    foreign = [c for c in counters if not any(c is o for o in own)]
    if exact >= FLAG_EXACT or not foreign:
        return terms, r2, exact
    left = [d - sum(sign * c.deltas[i] for c, sign in terms) for i, d in enumerate(s.deltas)]
    residual = Series(s.name, s.labels, [], [0.0, *accumulate(left)], False, blocks=s.blocks)
    more, _, _ = balance(residual, foreign, None, steps)
    # each search was held to its own limit (sd.balance.supported); the whole is held to the
    # level's, by shedding only the other machine's counters: the machine's own are its record
    if more:
        more = [t for t in parsimonious(s, terms + more, steps) if not any(t[0] is c for c, _ in terms)]
    if more:
        r2b, exact2 = fit_of(s, terms + more, steps)
        if r2b > r2 + MIN_GAIN:
            return terms + more, r2b, exact2
    return terms, r2, exact


def channel_balance(s: Series, counters: list[Series], steps: list[int], fits) -> tuple[list | None, float, float]:
    """A channel's backlog balanced by its own traffic, when the source's definitions said what
    each count is (``orchestra.sources.traffic``): what was produced into the channel, less what
    the backlog's own consumer (its machine) took from it. Searched first, as a level's own
    machine's counters are, and kept only when it balances within the tolerance: a prior the data
    must bear out (decision D4). Otherwise another consumer that keeps up, whose acks run a moment
    behind the publishes, is as good a stand-in for the channel's inflow as the publishes
    themselves. A backlog its consumer keeps near empty barely moves; it is kept when its traffic,
    as declared (everything produced into the channel, less its own consumer's acks), accounts for
    what went in (``through_r2``), and its R² is then that one. None when the level is no backlog,
    or its traffic does not balance it."""
    if not s.traffic or s.traffic[0] != "backlog":
        return None, 0.0, 0.0
    channel = s.traffic[1]
    mates = [c for c in counters if c.traffic and c.traffic[1] == channel
             and (c.traffic[0] == "out" or (c.traffic[0] == "in" and writer_of(c) == writer_of(s)))]
    terms, r2, exact = balance(s, mates, None, steps) if mates else ([], 0.0, 0.0)
    if terms and fits(s, r2, exact):
        return terms, r2, exact
    prior = [(c, 1) for c in mates if c.traffic[0] == "out"] + [(c, -1) for c in mates if c.traffic[0] == "in"]
    if any(sg > 0 for _, sg in prior) and any(sg < 0 for _, sg in prior) and (through := through_r2(s, prior, steps)) >= MIN_R2:
        return prior, through, fit_of(s, prior, steps)[1]
    return None, 0.0, 0.0


def through_r2(s: Series, terms: list, steps: list[int]) -> float:
    """How much of what went into a backlog its balance accounts for: one less the balance's squared
    error over the variance of the inflow. A consumer that keeps up holds its backlog near empty,
    so the level's own changes are a step's timing jitter and an R² on them says nothing; what was
    published, less what was acknowledged, still accounts for every message within that jitter."""
    y = [s.deltas[i] for i in steps]
    inflow = [sum(c.deltas[i] for c, sign in terms if sign > 0) for i in steps]
    sse = sum((v - sum(sign * c.deltas[i] for c, sign in terms)) ** 2 for v, i in zip(y, steps))
    mean = sum(inflow) / max(1, len(inflow))
    var = sum((v - mean) ** 2 for v in inflow)
    return 1 - sse / var if var > 0 else 0.0


def _same_balance(a: list, b: list, same_flow) -> bool:
    """Whether two balances are the same counters with the same signs, a counter of the same
    events (``same_flow``: the board's rejected, the customers' returns) counting as the same."""
    return len(a) == len(b) and all(any(sa == sb and (ca is cb or same_flow(ca, cb)) for cb, sb in b) for ca, sa in a)


def twin_levels(found: list, left_out: dict[str, str], same_flow, declared: frozenset | set = frozenset(),
                unit: dict[str, str] | None = None) -> tuple[list, dict[str, list[dict]]]:
    """One stock measured twice (a shelf counted by the shelf and by the board): two levels that
    read alike as levels (``levels_match``: the same scale, and apart by no more than their spread)
    or are the same series read twice (``_same_series``), and that change alike in at least
    ``TWIN_STEPS`` of the steps, or that the same counters balance (two
    machines' counts of the same events being the same counter), or, judged on the levels
    themselves, whose changes correlate by ``TWIN_CORR`` or whose values are equal in
    ``TWIN_STEPS`` of the steps either held something (the expo's view of the board's queue, a
    moment behind it, whose balance takes the expo's own counters). The one kept is the one the
    operator declared a stock (``declared``, sd.pins), then the machine's whose counters make the
    balance, then the better balance, then the one more labels say (a queue that reads the same as
    the total of all queues is that queue); the other is left out and recorded as its twin, in the
    kept stock's evidence. Two levels in different units (``unit``, by key) are never twins."""
    kept: list = []
    twins: dict[str, list[dict]] = defaultdict(list)
    for s, terms, r2, exact in found:
        other = next((k for k in kept if _twins(s, k[0], terms, k[1], same_flow, exact, k[3], unit)), None)
        if other is None:
            kept.append((s, terms, r2, exact))
            continue
        o, oterms, or2, oexact = other
        # ... then the more specific level: a split that reads the same as its total names the thing
        if ((s.key in declared, _owns(s, terms), exact, r2, len(_identity(s.labels)))
                > (o.key in declared, _owns(o, oterms), oexact, or2, len(_identity(o.labels)))):
            kept[kept.index(other)] = (s, terms, r2, exact)
            win, lose = s, o
            twins[s.key] = twins.pop(o.key, [])
        else:
            win, lose = o, s
        share, alike = _equal_steps(win, lose), _alike(win, lose)
        twins[win.key].append({"series": lose.key, "written_by": writer_of(lose), "equal_steps": round(share, 4),
                               **{k: round(v, 4) for k, v in alike.items()}})
        for rec in twins[win.key]:
            left_out[rec["series"]] = (f"the same as {win.key} (one stock measured twice: their changes are equal in "
                                       f"{rec['equal_steps']:.0%} of steps and correlate by {rec['change_correlation']:.2f}; "
                                       f"their values are equal in {rec['equal_values']:.0%} of the steps either held something)")
    return kept, dict(twins)


def discover(dump, *, start: float, end: float, step: float, time_unit: str = "minute", kinds: dict | None = None,
             provenance: dict | None = None) -> Model:
    """The model the metrics imply over [start, end], with how it was found in ``model.discovery``.
    ``provenance`` (by series key): what each series' source said of it (its unit, its view), when
    another store was read (``orchestra.sources``)."""
    provenance = provenance or {}
    n = max(2, int((end - start) // step))
    series, summed = sum_instances(sample(dump, start, step, n, kinds))
    on_bus = candidates(series)    # each machine's event counts: what a flow may be associated with (sd.attribute)
    sampled = len(series)          # every series looked at (a machine's instances summed into one)
    left_out: dict[str, str] = {}
    end = start + n * step
    # Orchestra's own series are plumbing, not a measure of the system, and so are its own events
    # (an orchestra.* type, or anything the host published: orchestra_events); and a series whose machine
    # has been silent at the end of the window for longer than a restart takes (gone, or replaced)
    # is not measured now: left out (sd.live.gone)
    awake = observed(series, start, end)
    current = []
    for ser in series:
        ivs = ser.intervals if ser.intervals is not None else [(start, end)]
        if PLUMBING.match(ser.name):
            left_out[ser.key] = plumbing_reason(ser.name)
        elif orchestra_events(ser):
            left_out[ser.key] = ORCHESTRA_EVENTS_REASON
        elif ivs and not gone(ivs[-1][1], end, awake):
            current.append(ser)
        else:
            left_out[ser.key] = not_current_reason(ser, end)
    series = current
    # the window's data begin when the first series was live in it; a level is judged on how much
    # of that it covers (MIN_COVER), so a collector started a few minutes ago is an input, not a
    # stock fitted on its few minutes
    since = observed_from(series, start, end)
    counters_read = sum(1 for s in series if s.counter)    # still written, moved or not: a wider window may see them move (sd.rediscover.widen)
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
    named = named_apart([s for s in series if not s.counter])
    for c in counters:
        twin = next((k for k in kept_counters if same_flow(c, k, n) and not counts_apart(c, k, named)
                     and not construction.apart(c, k, provenance)
                     and (EVENT_COUNTER in (c.name, k.name) or writer_of(c) == writer_of(k))), None)
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
    moved_events = [sum(c.deltas) for c in counters if any(c.deltas)]   # each moving counter's events: why there may be no model (sd.no_model)
    for s in series:
        if s.counter and not any(s.deltas):
            left_out[s.key] = "a counter that did not move in the window"
    found: list[tuple[Series, list[tuple[Series, int]], float, float]] = []
    masks: dict[str, list[int]] = {}              # the steps each level's balance was found on
    solvers: dict[tuple, LeastSquares] = {}       # least squares over the counters a level may use, per set of steps
    barred = barred_counters([s for s in series if not s.counter], counters)
    # a balance adds counters with coefficients of ±1, so only counters in the level's own unit may
    # be its terms: seconds never balance a queue, nor bytes a count (sd.units)
    unit = {s.key: unit_of(s.name, s.labels, (provenance.get(s.key) or {}).get("unit")) for s in series}
    places = Places([(s.name, s.labels, s.key) for s in series], provenance)   # what its instruments' places spell (sd.titles)
    for s in series:
        if not s.counter and (other := {c.key for c in counters if unit[c.key] != unit[s.key]}):
            barred[s.key] = barred.get(s.key, set()) | other

    # the stocks the operator declared ([[series]] stock and role): tried first, judged like any (sd.pins)
    pins, pin_problems = declared_stocks(series, provenance)
    # a place's level and its own moves, as their instrument declared them: one construction, recorded (sd.construction)
    built = {s.key: t for s in series if not s.counter and s.key not in pins and (t := construction.terms(s, counters, provenance))}
    pinned: list = []                             # declared balances that fit: kept out of the restatements below
    pin_tried: dict[str, str] = {}                # a declared balance that did not fit, and how well it did
    balances: dict[str, dict] = {}                # each level's balance attempt, as tried (sd.explain)

    def tried_balance(s: Series, mine: list[Series], unlive: list[Series], steps: list[int], terms, r2, exact, fit: bool) -> None:
        other_unit = {c.key for c in counters if unit[c.key] != unit[s.key]}
        not_live = {c.key for c in unlive} - other_unit
        apart = set(barred.get(s.key, ())) - other_unit - not_live
        balances[s.key] = {"in_window": len(counters), "counters_all": [c.key for c in mine],
                           "counters": explained._few(c.key for c in mine),
                           "kept_apart": {k: v for k, v in (("in another unit", len(other_unit)), ("not live in its steps", len(not_live)),
                                                            ("counting another level of its name, or its own twin", len(apart))) if v},
                           "steps": len(steps), "terms": [{"series": c.key, "sign": sg} for c, sg in terms or []],
                           "r2": None if r2 is None else round(max(r2, 0.0), 4), "exact": None if exact is None else round(exact, 4),
                           "outcome": "fits" if fit else "no balance fits",
                           **({"declared": pin_tried[s.key]} if s.key in pin_tried else {})}

    def fits(s: Series, r2: float, exact: float, terms: list | None = None, steps: list[int] | None = None) -> bool:
        """A balance a level may be a stock on: a level that only ever takes two values is usually
        a flag (a baker is busy or not: 0 and 1) or changed too seldom to tell (a day's length,
        612 then 613 minutes), and least squares will balance it with counters that merely move
        with it; it is a stock only when counters balance it exactly (a shelf that holds nothing
        or one item). With its ``terms`` and ``steps``, a balance judged on a slow counter's writes
        whose misses are timing fits at a lower R² (``sd.identify.two_clocks``, ``timing_limited``)."""
        good = r2 >= MIN_R2 or (terms is not None and steps is not None and two_clocks(s, terms)
                                and timing_limited(s, terms, steps, r2))
        return good and (exact >= FLAG_EXACT or len({v for _, v in s.points}) > 2)
    set_aside: dict[str, list[str]] = defaultdict(list)   # a counter -> the levels it was live in too few steps of
    sparse: dict[str, int] = {}                  # a level left out for too few live steps it moved in -> how many it had
    enough_steps = 0                             # levels with enough of them (sd.rediscover.sparse_window)
    never_level: set[str] = set()                # an age, an aggregate or a statistic: no stock, nor a state between moves
    for s in series:
        if s.counter:
            continue
        if why := construction.no_level(provenance, s.key):
            left_out[s.key] = why
            never_level.add(s.key)
            continue
        if statistic(s.name, s.summary):
            never_level.add(s.key)
            # a maximum over partitions jumps from one to another with no flow: never conserved (sd.properties)
            left_out[s.key] = ("a statistic of what it measures (a maximum, a mean, a percentile, or one its source summarised "
                               "across reporters): a summary, not a store, so never a stock")
            continue
        if why := too_short(s, since, end, awake):
            left_out[s.key] = why
            continue
        # only the steps when the level and the counters it may be balanced with were live: a
        # level's stale value from before a silence (its machine was down, then restarted with a
        # cleared state) is not a change any counter explains, and the fit below cuts the same
        # time; a counter live in too few of the level's steps is set aside for it (sd.live.level_steps)
        steps, unlive = level_steps(s, counters, MIN_STEPS)
        if unlive:
            barred[s.key] = barred.get(s.key, set()) | {c.key for c in unlive}
            for c in unlive:
                set_aside[c.key].append(s.key)
        if len(steps) < MIN_STEPS:
            sparse[s.key] = sum(1 for i in steps if s.deltas[i])
            live_s = round(len(s.live if s.live is not None else range(n)) * step)
            left_out[s.key] = (f"live in only {len(steps)} of the {n} steps in the window while its counters were "
                               f"(written over {live_s} s so far): too new, or too broken, to balance")
            continue
        moved = sum(1 for i in steps if s.deltas[i])
        if moved < MIN_STEPS:
            sparse[s.key] = moved
        else:
            enough_steps += 1
        if not moved:
            left_out[s.key] = "a level that did not change in the window" + (" while it was live" if len(steps) < n else "")
            continue
        if moved < MIN_EVENTS:
            left_out[s.key] = (f"a level that changed in only {moved} step{'s' if moved != 1 else ''}: fewer than {MIN_EVENTS}, "
                               "too few to tell a balance from coincidence")
            continue
        masks[s.key] = steps
        if given := (pins[s.key].terms if s.key in pins else built.get(s.key)):
            # the declared counters (or the place's own moves), on the slowest one's writes when it
            # is slower than the level, where all of them have data
            view = on_writes(s, blocks) if s.blocks is None and (blocks := slowest(given)) else s
            given_steps = sorted(set(steps).intersection(balance_steps(s, [c for c, _ in given])))
            mine_steps = arrived(given_steps, [s, *(c for c, _ in given)], start, step)
            r2, exact = fit_of(view, given, mine_steps)
            if fits(view, r2, exact, given, mine_steps):
                s.blocks = view.blocks
                masks[s.key] = mine_steps
                pinned.append((s, list(given), r2, exact))
                tried_balance(s, [c for c, _ in given], unlive, mine_steps, given, r2, exact, True)
                continue
            shown = " ".join(f"{'+' if sg > 0 else '−'}{c.key}" for c, sg in given)
            pin_tried[s.key] = (f"the balance declared for stock {pins[s.key].name} ({shown}) fits at R² {r2:.2f}" if s.key in pins
                                else f"its construction by its instrument ({shown}) fits at R² {r2:.2f}: the moves miss some of its changes")
        mine = [c for c in counters if c.key not in barred.get(s.key, ())]
        terms, r2, exact = channel_balance(s, mine, steps, fits)
        backlog = terms is not None                # a declared backlog its own traffic balances: never a flag
        if terms is None:
            terms, r2, exact = own_balance(s, mine, steps, fits)
        if terms is None:
            key = (tuple(steps), tuple(sorted(barred.get(s.key, ()))), tuple(s.blocks or ()))
            if key not in solvers and mine:
                solvers[key] = LeastSquares(columns(s, mine, steps))
            terms, r2, exact = balance(s, mine, solvers.get(key), steps)
            # counters another store reports more seldom than the grid: also on their writes (sd.coarse)
            if mine:
                terms, r2, exact = coarse(s, mine, steps, (terms, r2, exact), fits, solvers, key)
        # judged only where the level and its balance's counters all have data (sd.live.arrived)
        if terms and (mine_steps := arrived(steps, [s, *(c for c, _ in terms)], start, step)) != steps:
            masks[s.key] = steps = mine_steps
            r2, exact = fit_of(s, terms, steps)
            if backlog:                            # a backlog its traffic accounts for is judged on that traffic
                r2 = max(r2, through_r2(s, terms, steps))
        tried_balance(s, mine, unlive, steps, terms, r2, exact, bool(terms and fits(s, r2, exact)))
        values = {v for _, v in s.points}
        if len(values) <= 2 and not backlog and not (terms and fits(s, r2, exact)):
            if values == {0.0, 1.0}:
                left_out[s.key] = "a flag (it only ever takes 0 and 1, and no counters balance it exactly), not a quantity that accumulates"
            else:
                times = len(real_points(s.points, LINEAR)) - 1
                left_out[s.key] = (f"a level that changed only {times} time{'s' if times != 1 else ''}, between two values "
                                   f"({', '.join(f'{v:g}' for v in sorted(values))}): too few to tell a balance from coincidence, "
                                   "and no counters balance it exactly")
            continue
        if terms and (r2 >= MIN_R2 or (two_clocks(s, terms) and timing_limited(s, terms, steps, r2))):
            found.append((s, terms, r2, exact))
        else:
            why = f"no counters balance it (best R² {r2:.2f}" + (f" with {', '.join(c.key for c, _ in terms)}" if terms else "") + ")"
            left_out[s.key] = why + (f"; {pin_tried[s.key]}" if s.key in pin_tried else "")
    # with every balance known, the stand-ins give way (sd.restate); a counter no balance keeps
    # is recorded with why, below
    notes: dict[str, str] = {}
    for pass_ in (split_event_counters, split_foreign_counters):
        found, made = pass_(found, counters, masks, writer_of, fits, MIN_EVENTS)
        notes.update(made)
    found, made, joined = unify_same_flows(found, masks, lambda a, b: (same_flow(a, b, n) or lagged_flow(a, b)) and not counts_apart(a, b, named),
                                           first_stamped, writer_of, fits, buffers(series, unit))
    notes.update(made)
    for keep, drop in joined:              # a counter joined to another stands for nothing on its own
        same_as[keep.key] += [{"name": drop.name, "labels": drop.labels}, *same_as.pop(drop.key, [])]
        copies[keep.key] += [drop, *copies.pop(drop.key, [])]
        left_out[drop.key] = made[drop.key]
    dropped = {drop.key for _, drop in joined}
    counters = [c for c in counters if c.key not in dropped]
    # each stock judged on its own writer's count of events joined to another writer's, before
    # anything weighs its balance: judged on the other's, a stock its own counters balance exactly
    # may fail identification on the other's lag (sd.restate.own_counters_back, again below)
    found, own_back = own_counters_back(found, joined, masks, writer_of, fits)
    # a set of a balance's counters that one unused counter counts at once gives way to it
    # (sd.parsimony: the customers' orders less the app's are the takers' own orders taken)
    found, made = fewer_counters(found, counters, masks, fits, set(notes), writer_of)
    notes.update(made)
    # a restated balance may have taken another level's counters: balanced again without them
    rebalanced = []
    for s, terms, r2, exact in found:
        if any(c.key in barred.get(s.key, ()) for c, _ in terms):
            mine = [c for c in counters if c.key not in barred[s.key]]
            terms, r2, exact = balance(s, mine, None, masks[s.key])
            if not (terms and fits(s, r2, exact)):
                left_out[s.key] = f"no counters of its own balance it (best R² {r2:.2f}); the others count another {s.name}"
                continue
        rebalanced.append((s, terms, r2, exact))
    found = rebalanced

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
        terms2, r2b, exact2 = balance(s, [c for c in free if c.key not in barred.get(s.key, ())], None, masks[s.key])
        if terms2 and r2b >= MIN_R2:
            kept.append((s, terms2, r2b, exact2))
        else:
            left_out[s.key] = f"only an accumulator of other stocks' flows (R² {r2b:.2f} with counters of its own)"
    declared_keys = {s.key for s, _, _, _ in pinned if s.key in pins}
    # a balance is identified only by evidence that holds out of sample and beats chance (sd.identify);
    # a count of reporters and its own turnover is a balance by construction, no evidence at all
    given = list({drop.key: drop for _, drop in own_back.values()}.values())
    found, identified, constructed_, refused = accepted(pinned + kept, counters + given, barred, masks, provenance, left_out,
                                                         lambda a, b: same_flow(a, b, n) or lagged_flow(a, b), declared_keys)
    # twins are joined among the identified only: a copy that loses to a level identification then
    # refuses would leave neither (the order backlog and a per-partition maximum)
    found, twins = twin_levels(found, left_out, lambda a, b: same_flow(a, b, n), declared_keys | constructed_, unit)
    # a state each item leaves within a step is empty at almost every step of the grid, so the
    # chain through it runs past it (sd.hops) or ends at outside and begins again there
    # (sd.passing); joined through it
    where = {"start": start, "end": end, "step": step, "writer_of": writer_of}
    stock_keys = {s.key for s, _, _, _ in found}
    # a state between moves holds the moves' items: never an age, an aggregate or a statistic of
    # them, nor a level in a unit no counter is in (the oldest item's seconds)
    counted_in = {unit[c.key] for c in counters}
    levels = [s for s in series if not s.counter and s.key not in stock_keys and s.key not in never_level
              and unit[s.key] in counted_in and not left_out.get(s.key, "").startswith(("the same as", SHORT))]
    found, hopped, revived = split_hops(found, counters, copies, levels, first_stamped=first_stamped, **where)
    for d in revived:                      # a copy that came back as a hop of its own stands for itself
        counters.append(d)
        left_out.pop(d.key, None)
        for k, recs in same_as.items():
            same_as[k] = [x for x in recs if (x["name"], x["labels"]) != (d.name, d.labels)]
    levels = [s for s in levels if all(s is not h.level for h in hopped)]
    passed = {}
    joined_through = passages(found + [(h.level, h.terms, 1.0, 1.0) for h in hopped], counters, levels, copies=copies,
                              apart=lambda a, b: counts_apart(a, b, named) or unit[a.key] != unit[b.key], **where)
    for p in hopped + joined_through:
        masks[p.level.key] = balance_steps(p.level, [c for c, _ in p.terms])
        r2, exact = fit_of(p.level, p.terms, masks[p.level.key]) if p.measured else (None, None)   # an unmeasured state has no fit to report
        found.append((p.level, p.terms, None if r2 is None else max(0.0, r2), exact))
        left_out.pop(p.level.key, None)
        passed[p.level.key] = p
    # a level that counts a stock's servers busy (the head chef, inside the orders inspecting) is
    # that stock's capacity: shown in its evidence, not a second stock (sd.capacity); judged on the
    # final stocks, so the stock it is shown in is one
    found, views, made = capacity_views(found, left_out, since, end, declared_keys | constructed_ | set(passed), set(passed),
                                        lambda a, b: counts_apart(a, b, named))
    notes.update(made)
    # each stock balanced by its own writer's count of events joined to another writer's (sd.restate):
    # it measures that stock's co-flow, so it is no longer left out, nor one the kept counter stands for
    found, late = own_counters_back(found, [(k, d) for k, d in joined if d.key not in {c.key for c in counters}],
                                    masks, writer_of, fits)
    own_back |= late
    # Orchestra's count of an event type is filed under its machine's counter of the same moments
    # where one is a flow: never a flow of its own (AGENTS.md rule 7, sd.restate.bus_copies)
    own_back = bus_copies(found, own_back, copies, lambda a, b: counts_apart(a, b, named))
    for keep, drop in own_back.values():
        left_out.pop(drop.key, None)
        same_as[keep.key] = [x for x in same_as[keep.key] if (x["name"], x["labels"]) != (drop.name, drop.labels)]
    stocks, sid_of, ids = [], {}, set()
    held: dict[str, dict] = {}       # the levels whose value was carried on their machine's word, and for how long
    between, between_named = _between_titles(found, passed, places)
    # a level's age (an instrument's ``age`` view of the same place, its labels the same): pointed to
    # from the stock, so a page can show how long the oldest has waited there. A measurement beside the
    # stock, never a binding, never read by the fit (rule 7)
    age_of = {tuple(sorted(x.labels.items())): x for x in series if (provenance.get(x.key) or {}).get("view") == "age"}
    # a hidden state whose place has a count of its own that never read anything there: said, not "no series"
    by_key = {x.key: x for x in series}
    unread_of = {k: unread(lv, _left_title(lv, places)) for k, p in passed.items() if not p.measured
                 and (lk := places.level_series(p.ins, p.outs)) and (lv := by_key.get(lk))}
    for s, terms, r2, exact in found:
        sid = unique_id(_slug(s), writer_of(s), ids)
        sid_of[s.key] = sid
        carried, at_end = held_for(s.points, s.intervals if s.intervals is not None else [(start, end)])
        if carried:
            held[sid] = {"minutes": round(carried / 60, 2), "at_end_minutes": round(at_end / 60, 2)}
        p = passed.get(s.key)
        by_cons = s.key in constructed_
        unfit = by_cons or r2 is None           # no R² that is evidence: a balance by construction, or no series measures the level
        stocks.append(Stock(sid, between.get(s.key) or _title(s, places), "items", ref(s) if not p or p.measured else None,
                            {**({"named": "places", **between_named[s.key]}
                                if s.key in between_named else {} if s.key in between else _named(s, places)),
                             "balance_r2": None if unfit else round(r2, 4), "exact_steps": None if unfit else round(exact, 4),
                             "steps": n, "balance_steps": len(masks[s.key]),
                             **({"by_construction": True} if by_cons else {}),
                             **({"measured": False, "level": {"name": s.name, "labels": dict(s.labels)}}   # the level the counters imply: its name holds
                                if p and not p.measured else {}),
                             **({"identification": identified[s.key].record()} if s.key in identified else {}),
                             "trust": stock_trust(s, exact, identified, by_cons, p, unread_of.get(s.key)),
                             "written_by": writer_of(s), "accumulator": all(sign > 0 for _, sign in terms) and _never_falls(s),
                             "balance": [{"series": c.key, "sign": sign} for c, sign in terms],
                             "held_minutes": round(carried / 60, 2),
                             **({"balance_r2_level": round(fit_of(s, terms, masks[s.key])[0], 4),
                                 "balance_on": "traffic: the balance's error against what went in"}
                                if not unfit and s.traffic and s.traffic[0] == "backlog" and r2 > fit_of(s, terms, masks[s.key])[0] + 1e-6 else {}),
                             **({"twins": twins[s.key]} if s.key in twins else {}), **(p.evidence(unread_of.get(s.key)) if p else {}),
                             **({"age_series": {"name": a.name, "labels": dict(a.labels)}}
                                if (not p or p.measured) and (a := age_of.get(tuple(sorted(s.labels.items())))) else {}),
                             **({"capacity_of": views[s.key]} if s.key in views else {}),
                             **({"declared": pins[s.key].record()} if s.key in declared_keys else {}),
                             **({"balance_on": f"the stretches between the writes of its slowest series ({len(s.blocks)} in the window)"}
                                if s.blocks and any(c.blocks for c, _ in terms) else {})}))
    # a counter in two balances connects those stocks (sd.ends: contested ends and co-flows)
    fid_of = {c.key: unique_id(_slug(c), writer_of(c), ids) for c in counters}
    by_counter = claims(found, sid_of, writer_of, {k: keep for k, (keep, _) in own_back.items()})
    flow_moves = moves(counters, by_counter, fid_of, writer_of)
    # a move between places is a flow by construction: its ends are its instrument's; its rate is still fitted
    built_moves = {c.key for s, terms, _, _ in found if s.key in constructed_ for c, _ in terms}
    through = {sid_of[k]: p for k, p in passed.items()}
    for mv in flow_moves:
        if mv.counter.key in built_moves:
            mv.evidence["by_construction"] = True
        if mv.src in through or mv.dst in through:
            mv.evidence["through"] = [x for x in (mv.src, mv.dst) if x in through]
    for c in counters:
        if c.key in by_counter:
            continue
        events = sum(c.deltas)
        rare = f"a counter of only {events:g} event{'s' if events != 1 else ''}: fewer than {MIN_EVENTS}, too few to carry a balance; it completed none"
        unlive = (f"{c.key}: live in fewer than {MIN_STEPS} of the steps of {len(set_aside[c.key])} level"
                  f"{'s' if len(set_aside[c.key]) != 1 else ''} (live only from its first write, or seldom), so set aside "
                  "from their balances; the other counters balance them without it") if c.key in set_aside else None
        left_out[c.key] = notes.get(c.key, unlive or (rare if events < MIN_EVENTS else "a counter no stock's balance needed"))

    unit_s = UNITS[time_unit]
    # what a flow's rate may read, by path id: each stock's points and when it was live, and the
    # measured gauges that are not stocks (a rating, a demand; sd.inputs) as input:<name>, read on
    # the grid; each flow is fitted on its own window (flow_window)
    grid = lambda vals: [(start + i * step, v) for i, v in enumerate(vals)]
    sources: dict[str, tuple[list, list | None]] = {sid_of[s.key]: (s.points, s.intervals) for s, _, _, _ in found}
    inputs, input_refs = offered_inputs(series, {s.key for s, _, _, _ in found}, left_out, provenance)
    # Orchestra's own series drive only flows of Orchestra's own stocks (sd.inputs): with none, they are no input
    keep_apart(inputs, input_refs, bool(own_paths({s.key: sid_of[s.key] for s, _, _, _ in found}, {}, provenance)), left_out)
    found_net: list[Series] = []
    input_of = {s.key: nm for s in series if not s.counter and (nm := input_name(s)) in input_refs}
    net_trace: dict[str, dict] = {}               # each level's net flow as tried (sd.netflow, sd.explain)
    for name, vals in inputs.items():
        sources[f"input:{name}"] = (grid(vals), None)
    # a level no counters balance may still be a stock, its net flow fitted from the other series (sd.netflow)
    net_flows: list[Flow] = []
    for st, made, was_input, lv in net_flow_stocks(series, [s for s, _, _, _ in found], sid_of, inputs, input_refs, left_out, step,
                                                   unit_s, (since, end), lambda x: (unique_id(_slug(x), writer_of(x), ids), _title(x, places)),
                                                   ref, writer_of, measure=net_evidence, units=unit, counters=counters,
                                                   explain=net_trace):
        st.evidence.update(_named(lv, places))
        stocks.append(st)
        net_flows += made
        sources.pop(f"input:{was_input}", None)
        inputs.pop(was_input, None)
        input_refs.pop(was_input, None)
        sources[st.id] = (grid(lv.values), lv.intervals)
        sid_of[lv.key] = st.id
        found_net.append(lv)
    # a driver slower than the grid explains nothing faster than its own resolution (sd.resolution)
    slow = {sid_of[s.key]: s.resolution.seconds for s in [x for x, _, _, _ in found] + found_net
            if s.resolution and steps_of(s.resolution.seconds, step) > 1}
    slow.update({f"input:{k}": r["resolution_s"] for k, r in input_refs.items() if steps_of(r.get("resolution_s"), step) > 1})
    # A stock that only fills (no outflow in its balance) grows with time whatever else happens,
    # so as a driver of another flow's rate it stands in for time itself and finds spurious
    # influences. It stays a stock; it just may not explain other flows. Nor may a stock whose
    # balance counts the flow's own events, one off just before each of them (sd.drivers).
    accumulators = {sid_of[s.key] for s, terms, _, _ in found if all(sign > 0 for _, sign in terms)}
    flows, measured = [], {}
    offered: dict[str, list[dict]] = defaultdict(list)    # a path a rate may read -> the flows it was offered to (sd.explain)
    grouped: dict[str, list] = defaultdict(list)       # per counter: its flow, then its co-flows (ends.moves's order)
    for mv in flow_moves:                              # a co-flow its own writer counted is still the flow's events
        grouped[mv.evidence.get("co_flow_of") or mv.evidence.get("copy_of") or mv.id].append(mv)
    series_of = {sid_of[s.key]: s for s, _, _, _ in found}
    # what each series a rate may read says of itself (name, labels, unit): a tie-break between drivers (sd.driverchoice)
    described = {sid_of[s.key]: (s.name, s.labels, unit.get(s.key)) for s in [*series_of.values(), *found_net]}
    described.update({f"input:{k}": (r["name"], r.get("labels") or {}, unit_of(r["name"], r.get("labels") or {}))
                      for k, r in input_refs.items()})
    own_ = own_paths({**{s.key: sid_of[s.key] for s, _, _, _ in found}, **{s.key: sid_of[s.key] for s in found_net}}, input_refs, provenance)
    windows: list[tuple[float, float]] = []
    path_cache: dict = {}
    for mvs in grouped.values():
        c = mvs[0].counter
        # fit only over the time the flow's counter and its stocks were live: before a machine
        # started, or while it was down, its silence is not a rate of zero. Another series' short
        # history or silence cuts only its own flows, never everyone's (flow_window)
        own = [c, *(series_of[e] for mv in mvs for e in (mv.src, mv.dst) if e in series_of)]
        live, paths = flow_window(own, sources, start, end, unit_s, path_cache)
        live_s = length(live)
        if live_s <= 0:
            continue
        windows += live
        steps_live = [i for i in range(n) if any(a <= start + i * step and start + (i + 1) * step <= b for a, b in live)]
        dl = c.deltas
        y = [dl[i] for i in steps_live]
        # one event has one rate: a counter is fitted once, against its flow's source, and its
        # co-flows (the same events moving another machine's stock) get the same equation; no end
        # of any of them is kept from driving it
        ends = {e for mv in mvs for e in (mv.src, mv.dst) if e}
        barred = co_counting(c, ends, found, sid_of, steps_live, lambda a, b: same_flow(a, b, n))
        events = events_of(c.points, live)
        src = mvs[0].src
        near = {pid: adjacency(c.name, c.labels, *described[pid][:2], described[pid][2] == unit.get(c.key))
                for pid in paths if pid in described}
        # Orchestra's own series drive a flow only when every stock it moves is Orchestra's own too (sd.inputs)
        apart = set() if ends and ends <= own_ else own_
        best, *rest = fit_flow(events, live_s / unit_s, paths, src, set(paths) - accumulators - set(barred) - apart, slow, start,
                               {mv.dst for mv in mvs if mv.dst}, near)
        best["dispersion"] = dispersion(events, live, best, paths, unit_s)
        for pid in set(paths) - accumulators - set(barred) - apart:
            offered[pid].append({"flow": mvs[0].id, "chosen": pid in best["inputs"]})
        other = lambda x, src=src: f"_{x['inputs'][0]}" if x["inputs"] and x["inputs"] != [src] else ""   # a form in another stock says which
        # a form that could not be fitted (no finite AIC) is named only among the rejected, with its reason
        alt = {f"aic_{x['form']}{other(x)}": round(x["aic"], 2) for x in rest[:4] if math.isfinite(x["aic"])}
        alt.update({f"proportional_k{other(x)}": round(x["params"]["k"], 6) for x in [best, *rest]
                    if x["form"] == "proportional" and math.isfinite(x["aic"])})
        if rejected := {f"{x['form']}_{x['inputs'][0]}": x["rejected"] for x in rest if "rejected" in x}:
            alt["rejected"] = rejected
        q = {"events": float(sum(y)), "loglik": round(best["loglik"], 3), "aic": round(best["aic"], 3),
             "dispersion": round(best["dispersion"], 3), "steps": float(len(steps_live)), "live_minutes": round(live_s / 60, 2), **alt}
        for mv in mvs:
            if best.get("driver"):
                mv.evidence["driver"] = best["driver"]
            if barred:
                mv.evidence["not_drivers"] = barred
            # a co-flow its own writer counted is measured by that count, at the flow's one rate (sd.ends)
            by = mv.counter
            if same_as.get(by.key):          # the counters of the same events this one stands for (one flow, measured twice)
                mv.evidence["same_as"] = same_as[by.key]
            # a counter summed over instances is not a series in the store: the flow is measured by each of them
            if named := _named(c, places):
                mv.evidence.update(named)
            flows.append(Flow(mv.id, _title(c, places), mv.src, mv.dst, None if by.members else ref(by),
                              [Equation(best["form"], {k: round(v, 6) for k, v in best["params"].items()}, "fitted", "poisson-mle",
                                        (live[0][0], end), None, dict(q), list(best["inputs"]))],
                              [ref(m) for m in by.members], mv.evidence))
            measured[mv.id] = by
    flows += net_flows
    # which machines may be associated with each flow: hypotheses from the bus, never from who
    # wrote the counter; they change no equation and no structure (sd.attribute)
    by_machine: dict[str, list[str]] = defaultdict(list)
    events_of_machine: dict[str, list] = defaultdict(list)
    for fl in flows:
        # the other ways out of the same stock: one event type may end a subject either way (sd.attribute)
        exits = [measured[g.id] for g in flows if g is not fl and fl.src and g.src == fl.src and g.id in measured and measured[g.id] is not measured.get(fl.id)]
        fl.evidence["machines"] = assoc = associate(measured.get(fl.id), on_bus, exits)
        for h in assoc["hypotheses"]:
            by_machine[h["machine"]].append(fl.id)
            if ev := h.get("events"):
                events_of_machine[h["machine"]].append(ev)
    # the time any flow was fitted on; with no flow, the window's data
    live = union(windows) if windows else [(since, end)]
    live_s = length(live)
    fit_start = live[0][0] if live else end
    for st in stocks:
        ser = series_of.get(st.id) or next((x for x in found_net if sid_of.get(x.key) == st.id), None)
        span = live_span(ser, end) if ser is not None else []
        st.evidence["live_from"] = max(since, span[0][0]) if span else since
    # what a machine is (a program, a service, a person) is not in the metrics: the model says "machine"
    machines = [Machine(m, m, "machine", "Seen on the bus. Guessed from timing on these flows (sd.attribute): "
                        + "; ".join(sorted({h["by"] for f in flows for h in f.evidence["machines"]["hypotheses"] if h["machine"] == m})) + ".",
                        sorted(set(by_machine[m])), [ref(e) for e in on_bus if writer_of(e) == m
                                                and {"type": e.labels.get("type"), "source": m} in events_of_machine[m]])
                for m in sorted(by_machine)]
    model = Model("system", "The system",
                  "Discovered from the metrics store: stocks are levels that counters balance, with those counters "
                  "as flows fitted by Poisson maximum likelihood, and levels no counters balance whose net flow "
                  "the other series explain, fitted by least squares.",
                  time_unit, stocks, flows, machines)
    explain = explained.record(series, left_out=left_out, stocks=stocks, sid_of=sid_of, kinds=kinds, provenance=provenance,
                               start=start, end=end, step=step, balances=balances, net=net_trace, input_of=input_of,
                               offered=offered, flow_of={by.key: fid for fid, by in measured.items()}, min_r2=MIN_R2)
    model.discovery = {"summed": summed, "start": start, "end": end, "fit_start": fit_start, "live_minutes": round(live_s / 60, 2) if found else 0,
                       "gaps": [[a, b] for (_, a), (b, _) in pairwise(live)] if found else [],
                       "step": step, "sampled": sampled, "series": len(series), "inputs": input_refs, "held": held,
                       "resolution": {x.key: x.resolution.record() for x in series if x.resolution},
                       "stocks": sum(1 for st in stocks if not st.evidence.get("by_construction")), "flows": len(flows), "min_r2": MIN_R2,
                       "by_construction": sorted(sid_of[k] for k in constructed_ if k in sid_of),
                       "refused": refused,
                       "counters_read": counters_read,
                       # the levels whose live steps held fewer than MIN_STEPS moves, by how many: when every level is
                       # one, a window over longer own data is widened (sd.rediscover.sparse_window)
                       "level_steps": {"levels": len(sparse) + enough_steps, "sparse": dict(sorted(sparse.items())), "needed": MIN_STEPS},
                       "counter_events": {"counters": len(moved_events), "most": round(max(moved_events, default=0.0), 3), "needed": MIN_EVENTS},
                       **({"declared": {"stocks": {p.name: {"level": p.level, **p.record(),
                                                            "outcome": "a stock" if p.level in declared_keys and p.level in sid_of
                                                            else left_out.get(p.level) or pin_tried.get(p.level) or "not a stock"}
                                                   for p in pins.values()},
                                        **({"problems": pin_problems} if pin_problems else {})}}
                          if pins or pin_problems else {}),
                       "left_out": dict(sorted(left_out.items())),
                       # what the pages call a left-out series its instrument's places or its words name
                       # (sd.titles): "items waiting at ci", never its raw key
                       "titles": {x.key: t for x in series if x.key in left_out and (t := _left_title(x, places))},
                       "title_tags": {x.key: t for x in series if x.key in left_out and (t := _left_tags(x, places))},
                       # a left-out count of a place that holds items now: its level and its place, so a page
                       # draws or captions it (never a count that silently leaves something out)
                       "held_levels": _held_levels(series, left_out, provenance),
                       # what discovery read and tried for each series it considered, stock or left out (sd.explain)
                       "explain": explain}
    return model


def _held_levels(series: list[Series], left_out: dict, provenance: dict) -> dict:
    """The left-out counts of things in a place (an instrument's ``count`` view) that hold items at
    the end of the window: by key, their last value and the place value they count."""
    out = {}
    for x in series:
        rec = provenance.get(x.key) or {}
        if x.counter or x.key not in left_out or rec.get("view") != "count" or not x.points:
            continue
        v, at = x.points[-1][1], x.labels.get(rec.get("place") or "")
        if v and v > 0 and at:
            out[x.key] = {"level": v, "place": at}
    return out


def _left_tags(s: Series, places: Places) -> list[str]:
    """A left-out series' tags, when its instrument's places name it (``sd.titles``)."""
    if tags := (places.move_tags(s.labels, s.key) if s.counter else places.level_tags(s.labels, s.key, s.name)):
        return tags
    return places.sourced_tags(s.name, s.labels, s.key)


def _left_title(s: Series, places: Places) -> str | None:
    """A left-out series' title when its instrument's places or its own words give one, else None."""
    if t := (places.move(s.labels, s.key) if s.counter else places.level(s.labels, s.key, s.name)):
        return t
    return places.sourced(s.name, s.labels, s.key) or _in_words(s)


def structure(model: Model) -> list:
    """What a discovery found, without its numbers: stocks, and each flow's ends, form and inputs.
    A new model version is worth saving only when this changes."""
    return [sorted(s.id for s in model.stocks),
            sorted((f.id, f.src or "", f.dst or "", f.current().form if f.current() else "",
                    tuple(f.current().inputs) if f.current() else ()) for f in model.flows)]
