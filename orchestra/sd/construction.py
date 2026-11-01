"""Balances that hold by construction: a count of reporters and its own turnover.

A source that reads another store counts, for a family with an identity label, how many of them
report (``…_pods``: the pods reporting ``http_requests_total``), and that count's turnover (``…_pods_started_total``,
``…_pods_stopped_total``: reporters that appeared and disappeared, ``orchestra.sources.views``). The
turnover is the count's changes, taken apart: the balance is exact whatever the count means, so its
R² of 1.000 is no evidence of anything. Such a level is still a count of things (pods come and go),
and it is kept as a stock only when it counts reporters in a place pods are held (a deployment, a
node, a phase), recorded as ``by_construction`` with no R², its trust nil; split by what happened
to a request (an HTTP status code, a method, an outcome), it counts the pods that happened to
report one lately, which no system holds, and it is left out.

Which series are counts of reporters and their turnover is the source's to say: its definitions'
views (``count``, ``starts``, ``stops``), passed to discovery as the reading's provenance.

**Piles** are the other construction: an instrument that counts the items in each pile and every
move between piles from one record (``items{place}`` and
``item_moves_total{from, to}``, from one record) says so with its views
(``orchestra.collect.views``): the level's ``count`` names its ``place`` label, a move's ``moves``
names the labels of the place it ``starts`` (enters) and ``stops`` (leaves), or a counter is the
``starts`` or ``stops`` of one place. The level and its own moves are then one construction: every
move into the pile adds one, every move out takes one, and the balance is recorded as it was
declared (``terms``), never searched for and never fitted, its R² no evidence. The pile is kept as a
stock ``by_construction`` (an instrument's count names its place, so it is never left out for one),
its moves are its flows, and the evidence about it is elsewhere: the fitted rates of its moves, the
loops they make, and agreement with an outside measurement of the same quantity."""

from __future__ import annotations

COUNT_VIEW = "count"
MOVES_VIEW = "moves"
TURNOVER_VIEWS = {"starts", "stops", MOVES_VIEW}
# labels that say where reporters or items are held: a count of them split by these is a count of things in a place
PLACES = {"deployment", "statefulset", "daemonset", "replicaset", "node", "namespace", "service", "job", "app", "phase",
          "condition", "cluster", "zone", "region", "container", "workload", "pile"}
WRITERS = {"instrument", "machine", "source", "project", "instance"}


def _view(provenance: dict, key: str) -> str | None:
    return (provenance.get(key) or {}).get("view")


def _place(provenance: dict, level) -> str | None:
    """The place label an instrument declared for a count it prints, when the level carries it."""
    place = (provenance.get(level.key) or {}).get("place")
    return place if place and place in level.labels else None


def sign_of(level, counter, provenance: dict) -> int:
    """How a counter moves a pile's level by construction: +1 a move into it, −1 a move out of it,
    0 none of its own (another pile's, another workflow's, or no move at all)."""
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
    """A pile's balance as its instrument declared it: its own moves, each with its sign; none for
    a level that is no instrument's count of a place."""
    if _view(provenance, level.key) != COUNT_VIEW or _place(provenance, level) is None:
        return []
    return [(c, sg) for c in counters if (sg := sign_of(level, c, provenance))]


def constructed(level, terms: list, provenance: dict) -> bool:
    """Whether a level's balance is a count and its own turnover only: a count of reporters and the
    reporters that started and stopped, or a pile and its own moves."""
    if not terms or _view(provenance, level.key) != COUNT_VIEW:
        return False
    if _place(provenance, level) is not None:
        return all(sign_of(level, c, provenance) == sg for c, sg in terms)
    return all(_view(provenance, c.key) in TURNOVER_VIEWS for c, _ in terms)


def no_place(level, provenance: dict | None = None) -> str:
    """The label a count is split by that is no place things are held, or nothing; an
    instrument's count names its place, so it has none."""
    if provenance is not None and _place(provenance, level) is not None:
        return ""
    return next((k for k in sorted(level.labels) if k not in WRITERS and k not in PLACES), "")


def apart(a, b, provenance: dict) -> bool:
    """Whether two counters are an instrument's two moves (or two places' turnover): told apart by
    construction, so never one flow counted twice however alike they move."""
    ra, rb = provenance.get(a.key) or {}, provenance.get(b.key) or {}
    return a.key != b.key and all(r.get("instrument") and r.get("view") in TURNOVER_VIEWS for r in (ra, rb))


# an instrument's views of a level that is no candidate for a stock, and why
NO_LEVEL = {"aggregate": "its instrument says it is an aggregate (piles that overlap): never a stock",
            "age": "its instrument says it is an age (how long the oldest has waited): never a stock"}


def no_level(provenance: dict, key: str) -> str:
    """Why an instrument's view keeps a level out of the candidates for a stock, or nothing."""
    return NO_LEVEL.get(_view(provenance, key) or "", "")
