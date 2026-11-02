"""What an instrument says of the series it prints: their views, carried into discovery as provenance.

A source's definitions say which of its series are a count and that count's turnover
(``orchestra.sources.views``); an instrument (``[[collect]]``, ``[[scrape]]``, ``Plugin.collectors``)
may say the same of its own series, because it knows how it made them. A place's level and its own moves
come from one record, so their balance holds by construction and is no evidence
(``orchestra.sd.construction``)::

    [[collect]]
    name = "places"
    command = "python -m places"
    [collect.views]
    items = { view = "count", place = "place", where = { kind = "step" } }
    item_moves_total = { view = "moves", starts = "to", stops = "from" }

or, from a plugin, ``Collector.collect("places", cmd, views={...the same table...})``. Each key is a
series name the instrument prints; its value is one view or a list of them (the first whose
``where`` the series' labels match is taken). The views:

| ``view`` | Fields | Means |
|---|---|---|
| ``count`` | ``place``: the label naming the place | how many things are in each place (a level) |
| ``moves`` | ``starts``, ``stops``: the labels naming the place entered and the place left | things moved from one place to another (a counter) |
| ``starts`` / ``stops`` | ``place`` | things that entered / left the place the label names (a counter) |
| ``aggregate`` | | a level over places that overlap: never a stock |
| ``age`` | | how long something has waited: never a stock |

``where`` (optional) is a table of labels and values a series must carry for the view to be its.
``describes`` (optional, any view) is a sentence about what the matching series measure, kept
beside them and never a label, so editing it never starts a new series: the Dynamics and
Instruments pages show it under the part's name (an instrument may declare one view per series,
each with its ``where`` and its sentence: an instrument's declared views say what each place holds).
A view is a statement about how the series was made, never about a machine or a flow (AGENTS.md
rules 6 and 7): it changes no equation, and the moves' rates are still fitted. Discovery reads
the views of the instruments the host runs (its runtime record, ``instruments``) and of
``orchestra.toml``'s own entries, and gives each matching point of the instrument (its
``instrument`` label) the record ``{"source": "own", "instrument", "view", ...}``."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ..config import ConfigError

FIELDS = {"count": ("place",), "moves": ("starts", "stops"), "starts": ("place",), "stops": ("place",),
          "aggregate": (), "age": ()}
OWN = "own"


@dataclass(frozen=True)
class View:
    series: str
    view: str
    fields: tuple[tuple[str, str], ...] = ()    # place, or starts and stops
    where: tuple[tuple[str, str], ...] = ()
    describes: str = ""

    def matches(self, name: str, labels: dict[str, str]) -> bool:
        return name == self.series and all(labels.get(k) == v for k, v in self.where)

    def record(self, instrument: str) -> dict:
        return {"source": OWN, "instrument": instrument, "view": self.view, **dict(self.fields),
                **({"describes": self.describes} if self.describes else {})}

    def table(self) -> dict:
        """As it is declared, for the runtime record."""
        return {"view": self.view, **dict(self.fields), **({"where": dict(self.where)} if self.where else {}),
                **({"describes": self.describes} if self.describes else {})}


def _label(v, what: str) -> str:
    if not isinstance(v, str) or not v:
        raise ConfigError(f"{what} must name a label, not {v!r}")
    return v


def _one(series: str, t) -> View:
    if isinstance(t, View):
        return t
    if not isinstance(t, dict):
        raise ConfigError(f"views: {series}: must be a table, not {t!r}")
    view = t.get("view")
    if view not in FIELDS:
        raise ConfigError(f"views: {series}: view must be one of {', '.join(FIELDS)}, not {view!r}")
    extra = set(t) - {"view", "where", "describes", *FIELDS[view]}
    if extra:
        raise ConfigError(f"views: {series}: {view} takes no {', '.join(sorted(extra))}")
    fields = tuple((f, _label(t.get(f), f"views: {series}: {f}")) for f in FIELDS[view])
    where = t.get("where") or {}
    if not isinstance(where, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in where.items()):
        raise ConfigError(f"views: {series}: where must be a table of labels and their values, not {where!r}")
    describes = t.get("describes") or ""
    if not isinstance(describes, str):
        raise ConfigError(f"views: {series}: describes must be a sentence, not {describes!r}")
    return View(series, view, fields, tuple(sorted(where.items())), describes)


def parse(views) -> tuple[View, ...]:
    """An instrument's views, from the table it was declared with (or already parsed); raises
    ``ConfigError`` with what is wrong."""
    if not views:
        return ()
    if isinstance(views, tuple) and all(isinstance(v, View) for v in views):
        return views
    if not isinstance(views, dict):
        raise ConfigError(f"views must be a table of series names, not {views!r}")
    out: list[View] = []
    for series, t in views.items():
        for one in t if isinstance(t, list) else [t]:
            out.append(_one(series, one))
    return tuple(out)


def tables(views: Iterable[View]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for v in views:
        out.setdefault(v.series, []).append(v.table())
    return out


def provenance(dump: Iterable, declared: dict[str, tuple[View, ...]], key) -> dict[str, dict]:
    """The provenance of each series in ``dump`` (name, labels, points) an instrument declared a
    view of, by series key (``key(name, labels)``)."""
    out: dict[str, dict] = {}
    for name, labels, _ in dump:
        inst = labels.get("instrument")
        for v in declared.get(inst, ()) if inst else ():
            if v.matches(name, labels):
                out[key(name, labels)] = v.record(inst)
                break
    return out


def declared(project) -> dict[str, tuple[View, ...]]:
    """The views of every instrument, by name: those the host runs (its runtime record, which holds
    the plugins'), then ``orchestra.toml``'s own entries, which win. Either that cannot be read is
    left out."""
    from .. import runtime
    from .spec import from_toml

    out: dict[str, tuple[View, ...]] = {}
    try:
        for name, rec in (runtime.read(project).get("instruments") or {}).items():
            try:
                if views := parse(rec.get("views")):
                    out[name] = views
            except ConfigError:
                continue
    except (OSError, AttributeError, ValueError):
        pass
    try:
        for c in from_toml(project.config.raw)[0]:
            if c.views:
                out[c.name] = c.views
    except (OSError, AttributeError, ValueError, ConfigError):
        pass
    return out
