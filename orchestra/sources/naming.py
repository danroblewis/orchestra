"""What a series read from a source is called: ``names`` on a ``[[sources]]`` entry
(``{"gcp_pubsub_subscription_num_undelivered_messages" = "{subscription_id} messages waiting"}``),
a fact about how to read the store, like ``kinds``: it binds no series to a stock and never makes
one; it only says what the stock or flow a series becomes is called.

A key is a metric name or a glob, matched as ``kinds``' are (``kinds.entry``: an exact name over a
pattern, a longer pattern over a shorter) against the store's metrics a definition reads: those
its query selects (a recording rule's ``x:count``, a counter's ``x_total``), or, for an occupancy
view (calls in progress, ``views.py``), its busy time (``x:sum``), which then names that view
alone, not the sum's own. A value is a template: ``{label}`` is the series' label (its canonical
name or the store's spelling), ``{metric}`` the metric matched (as the store spells it, so without
the source's prefix); a label the series lacks is left out, and the brackets and spaces around it
with it ("{method} calls ({status})" with no status: "Get calls").

The result is the base name ``sd.titles`` gives the series (``sourced``: ``named_as`` in its
provenance, ``named_by`` the entry); its tags are as before, and a name the owner declares
(``declared_name``, the intended model) still wins over it on every page. It is applied at each
read, not at inference: a change to ``names`` needs no new round (``infer.settings_key`` leaves it
out)."""

from __future__ import annotations

import re
from fnmatch import fnmatchcase

from .kinds import entry

FIELD = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
SELECTED = re.compile(r"([a-zA-Z_:][a-zA-Z0-9_:]*)\s*[\[{]")     # a metric a query selects: followed by a range or matchers


def metrics_read(d) -> list[str]:
    """The store's metric names a definition reads: an occupancy view's busy time; else the names
    its query selects; else its family."""
    if d.occupancy:
        return [d.occupancy["busy"]]
    found = [m for m in SELECTED.findall(d.query or "") if m not in ("by", "without")]
    return list(dict.fromkeys(found)) or [d.family]


def render(template: str, metric: str, labels: dict, rename: dict | None = None) -> str:
    """The template filled from ``labels`` (canonical or the store's spelling, through ``rename``:
    real -> canonical); a label it lacks left out, with the empty brackets and extra spaces."""
    def one(m: re.Match) -> str:
        k = m[1]
        if k == "metric":
            return metric
        return str(labels.get(k) or labels.get((rename or {}).get(k, k)) or "")
    out = FIELD.sub(one, template)
    out = re.sub(r"\(\s*[,;]?\s*\)|\[\s*\]", "", out)
    out = re.sub(r"\(\s*[,;]\s*|\s*[,;]\s*\)", lambda m: "(" if "(" in m[0] else ")", out)
    return re.sub(r"\s+", " ", out).strip(" ,;:-") or metric


def name_of(names: dict[str, str], d, labels: dict, busy: set[str] = frozenset()) -> tuple[str, str] | None:
    """(the name, the entry that gave it) for one series of ``d``, or None when no entry names it.
    ``busy``: the busy-time metrics of the source's occupancy views, which name those views only."""
    if not names:
        return None
    metrics = metrics_read(d) if d.occupancy else [m for m in metrics_read(d) if m not in busy]
    k = entry(metrics, names)
    if k is None:
        return None
    metric = next(m for m in sorted(set(metrics)) if m == k or fnmatchcase(m, k))
    return render(names[k], metric, labels, getattr(d, "rename", None)), k
