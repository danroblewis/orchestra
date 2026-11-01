"""Simulated and draft series (docs/proposals/intended-model.md §6.3), selected for discovery in one
place (``discovered``, used by ``sd.rediscover`` and by the judge's split halves, ``sd.judge``).

A placeholder instrument's entry (a ``[[collect]]`` or ``[[scrape]]``, or a plugin's collector)
carries ``simulated = true``, and the instrument labels every point ``simulated="true"``
(``collect.round``). Discovery reads such a series as any other, but only while an entry with
``simulated = true`` names its instrument; once the entry is gone its points stay in the store and
the series is left out ("simulated, expired"), so the simulated parts leave the next version. When
the plugins could not be loaded (the CLI loads them itself), whether one of theirs names it is not
known: the series is left out as unknown, never as expired, and no version is saved from that
discovery (``discovery["plugins_error"]``).

Every stock and flow fitted from a simulated series (its own series or counter, an end, or a
measured input its equation reads), and every machine hypothesis on such a flow, is marked
``simulated: true`` in the saved version (in its ``evidence``), from the label, so the mark lives
in ``vN``, with the series that caused it (``evidence["simulated_from"]``: ``{series, as}``, ``as``
one of ``series`` for a stock, ``counter``, ``end`` or ``input`` for a flow). Every equation fitted
from one is marked too (``quality["simulated"] = 1``): one that reads a simulated stock or input,
one fitted on a simulated counter, and a net flow's fitted on a simulated end's level. A prediction verdict never counts a simulated part as an unpredicted change
(``sd.verdict``) and a target backed only by simulated parts is never met (``sd.intended``). This
is a flag, not a rule change: the parts are discovered as any other.

A **draft** instrument (``draft = true``, with ``expires``: an option being tried, P4's need 2)
labels its points ``draft="true"``; discovery leaves every such series out of its candidates
("draft"), while the entry exists and after it is gone. The core honours the flag and nothing
more: the plugin sets it, removes the entry at ``expires`` or clears the flag when the option is
chosen. Points written after that are unlabelled and join the same stock, since the key leaves
``draft`` out (``sd.intended.keys``).

Both flags are Orchestra's own labels, so they are read only on series from Orchestra's own
metrics store: a series another store serves (``[[sources]]``, in the reading's provenance) keeps
its labels as its own, a ``draft="true"`` of its own included."""

from __future__ import annotations

from dataclasses import replace

LABEL = "simulated"
DRAFT = "draft"
DRAFTED = "draft: recorded for an option being tried, left out of discovery"
EXPIRED = "simulated, expired: no [[collect]] entry with simulated = true names its instrument any more"


def is_simulated(labels: dict | None) -> bool:
    return (labels or {}).get(LABEL) == "true"


def unknown(error: str) -> str:
    """Why a simulated series is left out when the plugins could not be loaded: not that it
    expired, which nobody knows."""
    return f"simulated, its instrument unknown: plugins failed to load ({error}), so whether one names it is unknown"


class PluginsUnknown(Exception):
    """Not every plugin could be loaded: their collectors, and so which of their instruments are
    simulated, are unknown. ``collectors``: those of the plugins that did load."""

    def __init__(self, error: str, collectors: list):
        super().__init__(error)
        self.error, self.collectors = error, collectors


def plugin_collectors(project) -> list:
    """The plugins' collectors, each with its owner, loaded now: only for a caller that runs none
    (the CLI); the host and the web server pass theirs (``collectors``). Raises ``PluginsUnknown``
    when a plugin, or the loading, failed."""
    from .. import plugins

    try:
        loaded = plugins.load(project)
    except Exception as e:                 # said, never taken for 'no plugin collectors'
        raise PluginsUnknown(f"{type(e).__name__}: {e}", []) from e
    found = [replace(c, owner=p.name) for p in loaded.plugins for c in p.collectors]
    if loaded.errors:
        raise PluginsUnknown("; ".join(f"{e['plugin']}: {e['error']}" for e in loaded.errors), found)
    return found


def configured(project, collectors: list | None = None) -> set[str]:
    """The instruments whose entries say ``simulated = true``: the project's ``[[collect]]`` and
    ``[[scrape]]`` (the configuration read again if it changed, ``config.fresh_config``) and the
    plugins' collectors (``collectors``, or loaded now)."""
    return configured_or_why(project, collectors)[0]


def configured_or_why(project, collectors: list | None = None) -> tuple[set[str], str | None]:
    """``configured``, and why it may be incomplete: the plugins' loading error, when they were
    loaded now and failed (None otherwise)."""
    from ..collect.spec import from_toml
    from ..config import fresh_config

    fresh_config(project)
    error = None
    if collectors is None:
        try:
            collectors = plugin_collectors(project)
        except PluginsUnknown as e:
            collectors, error = e.collectors, e.error
    found, _ = from_toml(getattr(project.config, "raw", None) or {}, collectors)
    return {c.name for c in found if c.simulated}, error


def select(dump: list, others: dict, allowed, why: dict | None = None) -> tuple[list, dict[str, str]]:
    """The dump without the own draft series and the own simulated ones no entry names any more,
    and why each was left out. ``others``: the keys of series another store serves (the
    reading's provenance); ``allowed``: a callable giving the simulated instruments' names, asked
    only when an own simulated series is there; ``why``: filled by ``allowed`` with ``error``
    when those names may be incomplete (plugins that failed to load), so an unnamed series is
    left out as unknown, never as expired."""
    from .series import series_key

    why = why if why is not None else {}
    kept, left, names = [], {}, None
    for name, labels, pts in dump:
        key = series_key(name, labels)
        if key in others:
            kept.append((name, labels, pts))
        elif (labels or {}).get(DRAFT) == "true":
            left[key] = DRAFTED
        elif is_simulated(labels):
            names = allowed() if names is None else names
            if labels.get("instrument") in names:
                kept.append((name, labels, pts))
            else:
                left[key] = unknown(why["error"]) if why.get("error") else EXPIRED
        else:
            kept.append((name, labels, pts))
    return kept, left


def discovered(project, reading, *, collectors: list | None = None, **kw):
    """The model ``sd.strategies.discover_with`` finds in a catalogue reading, the draft and
    expired simulated series left out (in ``left_out``), the simulated parts marked.
    ``collectors``: the plugins' collectors the caller runs (or has loaded); None loads them,
    only if a simulated series is there."""
    from .strategies import discover_with

    why: dict = {}

    def allowed() -> set[str]:
        names, why["error"] = configured_or_why(project, collectors)
        return names
    dump, left = select(reading.dump, reading.provenance, allowed, why)
    m = discover_with(dump, kinds=reading.kinds, **kw)
    mark(m, reading.provenance)
    if why.get("error") and unknown(why["error"]) in left.values():
        m.discovery["plugins_error"] = why["error"]          # a series was left out unknown: rediscover saves no version
    if left:
        m.discovery["left_out"] = dict(sorted({**(m.discovery.get("left_out") or {}), **left}.items()))
    return m


def mark(model, others: dict | None = None) -> None:
    """Mark the parts fitted from a simulated series, in place. ``others``: the keys of series
    another store serves (the reading's provenance), whose labels are their own and never read
    as the flag."""
    from .series import series_key

    others = others or {}

    def sim(name: str, labels: dict | None) -> bool:
        return is_simulated(labels) and series_key(name, labels or {}) not in others

    sim_stocks = {s.id: series_key(s.series.name, s.series.labels or {}) for s in model.stocks
                  if s.series and sim(s.series.name, s.series.labels)}
    sim_inputs = {f"input:{n}": series_key(ref.get("name") or "", ref.get("labels") or {})
                  for n, ref in ((model.discovery or {}).get("inputs") or {}).items()
                  if isinstance(ref, dict) and sim(ref.get("name") or "", ref.get("labels"))}
    read = {**sim_stocks, **sim_inputs}
    for s in model.stocks:
        if s.id in sim_stocks:
            s.evidence.update(simulated=True, simulated_from=[{"series": sim_stocks[s.id], "as": "series"}])
    for f in model.flows:
        refs = [r for r in [f.counter, *(f.measured_by or [])] if r is not None]
        counters = [series_key(r.name, r.labels or {}) for r in refs if sim(r.name, r.labels)]
        ends = [sim_stocks[e] for e in dict.fromkeys((f.src, f.dst)) if e in sim_stocks]
        inputs = [read[i] for i in dict.fromkeys(i for e in f.equations for i in e.inputs) if i in read]
        why = [{"series": k, "as": a} for a, keys in (("counter", counters), ("end", ends), ("input", inputs)) for k in keys]
        if not why:
            continue
        f.evidence.update(simulated=True, simulated_from=why)
        for h in ((f.evidence.get("machines") or {}).get("hypotheses") or []):
            h["simulated"] = True
        for e in f.equations:
            if counters or (ends and not refs) or set(e.inputs) & set(read):
                e.quality["simulated"] = 1
