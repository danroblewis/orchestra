"""Balances that hold by construction: a count of reporters and its own turnover.

A source that reads another store counts, for a family with an identity label, how many of them
report (``…_pods``: the pods reporting ``http_requests_total``), and that count's turnover (``…_pods_started_total``,
``…_pods_stopped_total``: reporters that appeared and disappeared, ``orchestra.sources.views``). The
turnover is the count's changes, taken apart: the balance is exact whatever the count means, so its
R² of 1.000 is no evidence of anything. Such a level is still a count of things (pods come and go),
and it is kept as a stock only when it counts reporters in a place pods are held (a deployment, a
node, a phase), recorded as ``by_construction`` with no R², its trust nil; split by what happened
to a request (an HTTP status code, a method, an outcome), it counts the pods that happened to
report one lately, which no system holds, and it is left out. A count of reporters split by a
state each reporter has one of at a time (a pod's ``phase``, kube-state-metrics' one-hot 0/1 gauge)
would count every pod in every phase: the source reads such an **indicator** as the sum per state
instead (view ``count``, ``sum by``), and its turnover as the series that turned 1 and turned 0
(``orchestra.sources.views``), so the pods in each phase are a place's level and its own moves.

Which series are counts of reporters and their turnover is the source's to say: its definitions'
views (``count``, ``starts``, ``stops``), passed to discovery as the reading's provenance.

**Places** are the other construction: an instrument that counts the things in each place and every
move between places from one record (``items{place}`` and
``item_moves_total{from, to}``, from one record) says so with its views
(``orchestra.collect.views``): the level's ``count`` names its ``place`` label, a move's ``moves``
names the labels of the place it ``starts`` (enters) and ``stops`` (leaves), or a counter is the
``starts`` or ``stops`` of one place. The level and its own moves are then one construction: every
move into the place adds one, every move out takes one, and the balance is recorded as it was
declared (``terms``), never searched for and never fitted, its R² no evidence. The place is kept as a
stock ``by_construction`` (an instrument's count names its place, so it is never left out for one),
its moves are its flows, and the evidence about it is elsewhere: the fitted rates of its moves, the
loops they make, and agreement with an outside measurement of the same quantity.

**Occupancy** is the third: a latency family with a sum and a count (``orchestra.sources.views``,
view ``occupancy``) gives the calls in progress, its busy time over the interval (Little's law),
and its source records its moves, the family's completions (its count view's counters, by outcome:
passed and failed drain it) and its driver, the same count's rate. What fills it, the arrivals, is
read by no series: by Little's law they are the completions plus the level's change, so they are
derived here (``arrivals``, the series ``…_arrived_total``, its provenance view ``arrivals``) and
the balance, the arrivals in and the completions out, is exact by definition, its R² no evidence.
The level is kept as a stock ``by_construction`` whatever it is split by (a method is where calls
are in progress), its completions are its outflows and the arrivals its inflow, whose rate is
fitted like any flow's."""

from __future__ import annotations

COUNT_VIEW = "count"
OCCUPANCY_VIEW = "occupancy"
ARRIVALS_VIEW = "arrivals"
MOVES_VIEW = "moves"
TURNOVER_VIEWS = {"starts", "stops", MOVES_VIEW}
# labels that say where reporters or items are held: a count of them split by these is a count of things in a place
PLACES = {"deployment", "statefulset", "daemonset", "replicaset", "node", "namespace", "service", "job", "app", "phase",
          "condition", "cluster", "zone", "region", "container", "workload"}
WRITERS = {"instrument", "machine", "source", "project", "instance"}


def _view(provenance: dict, key: str) -> str | None:
    return (provenance.get(key) or {}).get("view")


def _place(provenance: dict, level) -> str | None:
    """The place label an instrument declared for a count it prints, when the level carries it."""
    place = (provenance.get(level.key) or {}).get("place")
    return place if place and place in level.labels else None


def sign_of(level, counter, provenance: dict) -> int:
    """How a counter moves a place's level by construction: +1 a move into it, −1 a move out of it,
    0 none of its own (another place's, or no move at all)."""
    place, rec = _place(provenance, level), provenance.get(counter.key) or {}
    if place is None:
        return 0
    view = rec.get("view")
    into, out_of = (rec.get("starts"), rec.get("stops")) if view == MOVES_VIEW else \
        ((rec.get("place"), None) if view == "starts" else (None, rec.get("place")) if view == "stops" else (None, None))
    shared = [k for k in level.labels if k != place and k not in WRITERS and k in counter.labels and k not in (into, out_of)]
    if any(counter.labels[k] != level.labels[k] for k in shared):
        return 0
    here = level.labels[place]
    if into and counter.labels.get(into) == here:
        return 0 if out_of and counter.labels.get(out_of) == here else 1
    if out_of and counter.labels.get(out_of) == here:
        return -1
    return 0


def terms(level, counters: list, provenance: dict) -> list:
    """A place's balance as its instrument declared it: its own moves, each with its sign; none for
    a level that is no instrument's count of a place."""
    if _view(provenance, level.key) != COUNT_VIEW or _place(provenance, level) is None:
        return []
    return [(c, sg) for c in counters if (sg := sign_of(level, c, provenance))]


def completions(level, counters: list, provenance: dict) -> list:
    """An occupancy level's moves as its source recorded them: the counters of its family's count
    view with the level's own labels, split by the outcome label when its source read them so
    (passed and failed), else not split; none for any other level."""
    rec = (provenance.get(level.key) or {}).get("occupancy")
    if _view(provenance, level.key) != OCCUPANCY_VIEW or not rec:
        return []
    family, by = (provenance.get(level.key) or {}).get("family"), rec.get("by")
    mine = [c for c in counters if c.name.split(":", 1)[-1] == rec.get("completions")
            and (provenance.get(c.key) or {}).get("family") == family and all(c.labels.get(k) == v for k, v in level.labels.items())]
    split = [c for c in mine if by and set(c.labels) - set(level.labels) == {by}]
    return split or [c for c in mine if set(c.labels) == set(level.labels)]


def arrivals(level, outs: list, start: float, step: float):
    """What filled an occupancy level, by Little's law: each step's completions plus the level's
    change (never below none), as a counter on the grid with the level's labels."""
    from .series import Series
    vals = [0.0]
    for i, d in enumerate(level.deltas):
        vals.append(vals[-1] + max(0.0, d + sum(c.deltas[i] for c in outs)))
    return Series(f"{level.name.removesuffix('_in_progress')}_arrived_total", dict(level.labels),
                  [(start + i * step, v) for i, v in enumerate(vals)], vals, True,
                  intervals=level.intervals, live=level.live, resolution=level.resolution)


def arrivals_record(level, outs: list, provenance: dict) -> dict:
    """The provenance of the arrivals derived for an occupancy level: derived, never read."""
    rec = provenance.get(level.key) or {}
    return {"view": ARRIVALS_VIEW, "family": rec.get("family"), "unit": "calls", "of": level.key,
            "derived": "the completions plus the change in the calls in progress (Little's law)",
            "completions": [c.key for c in outs], "driver": (rec.get("occupancy") or {}).get("driver")}


def constructed(level, terms: list, provenance: dict) -> bool:
    """Whether a level's balance is a count and its own turnover only: a count of reporters and the
    reporters that started and stopped, a place's level and its own moves, or the calls in
    progress and their arrivals and completions."""
    if terms and _view(provenance, level.key) == OCCUPANCY_VIEW:
        outs = {c.key for c in completions(level, [c for c, _ in terms], provenance)}
        return (any(_view(provenance, c.key) == ARRIVALS_VIEW for c, _ in terms)
                and all(_view(provenance, c.key) == ARRIVALS_VIEW or c.key in outs for c, _ in terms))
    if not terms or _view(provenance, level.key) != COUNT_VIEW:
        return False
    if _place(provenance, level) is not None:
        return all(sign_of(level, c, provenance) == sg for c, sg in terms)
    return all(_view(provenance, c.key) in TURNOVER_VIEWS for c, _ in terms)


def no_place(level, provenance: dict | None = None) -> str:
    """The label a count is split by that is no place things are held, or nothing; an
    instrument's count names its place, so it has none."""
    if provenance is not None and (_place(provenance, level) is not None or _view(provenance, level.key) == OCCUPANCY_VIEW):
        return ""          # an occupancy's method (or service) is where its calls are in progress
    return next((k for k in sorted(level.labels) if k not in WRITERS and k not in PLACES), "")


def apart(a, b, provenance: dict) -> bool:
    """Whether two counters are an instrument's two moves (or two places' turnover): told apart by
    construction, so never one flow counted twice however alike they move."""
    ra, rb = provenance.get(a.key) or {}, provenance.get(b.key) or {}
    return a.key != b.key and all(r.get("instrument") and r.get("view") in TURNOVER_VIEWS for r in (ra, rb))


# an instrument's views of a level that is no candidate for a stock, and why
NO_LEVEL = {"aggregate": "its instrument says it is an aggregate (places that overlap): never a stock",
            "age": "its instrument says it is an age (how long the oldest has waited): never a stock"}


def no_level(provenance: dict, key: str) -> str:
    """Why an instrument's view keeps a level out of the candidates for a stock, or nothing."""
    return NO_LEVEL.get(_view(provenance, key) or "", "")
