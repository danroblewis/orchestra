"""Every instrument's name and kind, in one place: the Instruments page lists them
(``web/instruments.py``) and an attachment may name only one of them (``sd.intended.instruments``),
so the two never disagree.

- the runtime record's (``orchestra.collect.runner``, written by the host that launches): a
  ``script``, a ``URL``, or a plugin's ``collector`` (its kind not recorded);
- the configuration's ``[[collect]]`` (``script``) and ``[[scrape]]`` (``URL``)
  (``collect.spec.from_toml``);
- ``[[sources]]`` (``source``)."""

from __future__ import annotations

from collections.abc import Iterable

OWN_KINDS = ("script", "URL", "collector")


def instrument_kinds(record: dict, declared: Iterable = (), sources: Iterable = ()) -> dict[str, str]:
    """``record``: the runtime record's ``instruments``; ``declared``: the configuration's
    collectors (each with ``name`` and ``what``); ``sources``: the ``[[sources]]`` specs."""
    out = {n: r.get("kind") if r.get("kind") in OWN_KINDS else "collector" for n, r in record.items()}
    out |= {c.name: c.what for c in declared}
    out |= {s.name: "source" for s in sources}
    return out
