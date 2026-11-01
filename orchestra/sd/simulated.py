"""Simulated and draft series (docs/proposals/intended-model.md §6.3), selected for discovery in one
place (``discovered``, used by ``sd.rediscover`` and by the judge's split halves, ``sd.judge``).

A placeholder instrument's entry (a ``[[collect]]`` or ``[[scrape]]``, or a plugin's collector)
carries ``simulated = true``, and the instrument labels every point ``simulated="true"``
(``collect.round``). Discovery reads such a series as any other, but only while an entry with
``simulated = true`` names its instrument; once the entry is gone its points stay in the store and
the series is left out ("simulated, expired"), so the simulated parts leave the next version.

Every stock and flow fitted from a simulated series (its own series or counter, an end, or a
measured input its equation reads), and every machine hypothesis on such a flow, is marked
``simulated: true`` in the saved version (in its ``evidence``), from the label, so the mark lives
in ``vN``. A prediction verdict never counts a simulated part as an unpredicted change
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


def plugin_collectors(project) -> list:
    """The plugins' collectors, each with its owner, loaded now: only for a caller that runs none
    (the CLI); the host and the web server pass theirs (``collectors``)."""
    from .. import plugins

    try:
        loaded = plugins.load(project)
    except Exception:  # noqa: BLE001 - no plugin collectors: only the project's entries name instruments
        return []
    return [replace(c, owner=p.name) for p in loaded.plugins for c in p.collectors]


def configured(project, collectors: list | None = None) -> set[str]:
    """The instruments whose entries say ``simulated = true``: the project's ``[[collect]]`` and
    ``[[scrape]]`` and the plugins' collectors (``collectors``, or loaded now)."""
    from ..collect.spec import from_toml

    plugin = plugin_collectors(project) if collectors is None else collectors
    found, _ = from_toml(getattr(project.config, "raw", None) or {}, plugin)
    return {c.name for c in found if c.simulated}


def select(dump: list, others: dict, allowed) -> tuple[list, dict[str, str]]:
    """The dump without the own draft series and the own simulated ones no entry names any more,
    and why each was left out. ``others``: the keys of series another store serves (the
    reading's provenance); ``allowed``: a callable giving the simulated instruments' names, asked
    only when an own simulated series is there."""
    from .series import series_key

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
                left[key] = EXPIRED
        else:
            kept.append((name, labels, pts))
    return kept, left


def discovered(project, reading, *, collectors: list | None = None, **kw):
    """The model ``sd.strategies.discover_with`` finds in a catalogue reading, the draft and
    expired simulated series left out (in ``left_out``), the simulated parts marked.
    ``collectors``: the plugins' collectors the caller runs (or has loaded); None loads them,
    only if a simulated series is there."""
    from .strategies import discover_with

    dump, left = select(reading.dump, reading.provenance, lambda: configured(project, collectors))
    m = discover_with(dump, kinds=reading.kinds, **kw)
    mark(m, reading.provenance)
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

    sim_stocks = {s.id for s in model.stocks if s.series and sim(s.series.name, s.series.labels)}
    sim_inputs = {f"input:{n}" for n, ref in ((model.discovery or {}).get("inputs") or {}).items()
                  if isinstance(ref, dict) and sim(ref.get("name") or "", ref.get("labels"))}
    for s in model.stocks:
        if s.id in sim_stocks:
            s.evidence["simulated"] = True
    for f in model.flows:
        refs = [r for r in [f.counter, *(f.measured_by or [])] if r is not None]
        inputs = {i for e in f.equations for i in e.inputs}
        if any(sim(r.name, r.labels) for r in refs) or {f.src, f.dst} & sim_stocks or inputs & (sim_stocks | sim_inputs):
            f.evidence["simulated"] = True
            for h in ((f.evidence.get("machines") or {}).get("hypotheses") or []):
                h["simulated"] = True
