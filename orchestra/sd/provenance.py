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
    ref.origin, ref.resolution_s, ref.unit = list(p.get("origin") or []), p.get("resolution_s"), p.get("unit")
    ref.traffic = p.get("traffic")
    return ref.source


def annotate(model: Model, provenance: dict[str, dict]) -> None:
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
