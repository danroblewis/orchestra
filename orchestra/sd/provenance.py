"""Where every series in a model came from, and so every equation fitted on them.

Discovery works on series without asking where they live; afterwards each ``SeriesRef`` in the
model (a stock's series, a flow's counters, a machine's series, the inputs its equations read) is
told its source, final query, kind, origin, resolution and, for counted traffic, the channel
and machine it counts for, from the catalogue's reading
(``orchestra.sources.catalogue``); a series with no record there is the project's own. A stock
bound to a remote count takes its unit (pods, regions). Each equation lists the sources of the
series it was fitted on."""

from __future__ import annotations

from .model import Model, SeriesRef
from .series import series_key

OWN = "own"


def _tell(ref: SeriesRef | None, provenance: dict[str, dict]) -> str | None:
    if ref is None:
        return None
    p = provenance.get(series_key(ref.name, ref.labels))
    if p is None:
        ref.source = OWN
        return OWN
    ref.source, ref.query, ref.kind = p["source"], p.get("query"), p.get("kind")
    ref.origin, ref.unit = list(p.get("origin") or []), p.get("unit")
    if ref.resolution_s is None:              # discovery's measure (sd.resolution) has the source's as its floor
        ref.resolution_s = p.get("resolution_s")
    ref.traffic = p.get("traffic")
    ref.selector, ref.store_query, ref.summed = p.get("selector"), p.get("store_query"), p.get("summed")
    return ref.source


SOURCED = ("source", "selector", "store_query", "kind", "summed", "candidate")   # candidate: what inference read it by (sources.explore)


def sourced(provenance: dict[str, dict]) -> dict[str, dict]:
    """Every series read from another store, by key: its source, its selector as the store spells
    it, the query a view of it starts from, its kind and what was summed over (the pages' view
    links: the Instruments page's source rows, the Dynamics page's left-out list)."""
    return {k: {x: p[x] for x in SOURCED if p.get(x) is not None} for k, p in sorted(provenance.items())
            if p.get("source") and p.get("source") != OWN and "query" in p}


def annotate(model: Model, provenance: dict[str, dict]) -> None:
    if src := sourced(provenance):
        model.discovery["sourced"] = src
    by_stock: dict[str, str | None] = {}
    for s in model.stocks:
        by_stock[s.id] = _tell(s.series, provenance)
        if s.series is not None and s.series.unit and s.unit == "items":
            s.unit = s.series.unit
    inputs = {}
    for name, r in (model.discovery.get("inputs") or {}).items():
        r["source"] = inputs[name] = provenance.get(series_key(r["name"], r.get("labels") or {}), {}).get("source", OWN)
    for f in model.flows:
        got = {_tell(f.counter, provenance)} | {_tell(r, provenance) for r in f.measured_by}
        for eq in f.equations:
            reads = {by_stock.get(x) if not x.startswith("input:") else inputs.get(x[6:], OWN) for x in eq.inputs}
            eq.sources = sorted(x for x in got | reads if x)
    for m in model.machines:
        for r in m.observed_by:
            _tell(r, provenance)
