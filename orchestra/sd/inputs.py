"""The measured levels an SD Lab strategy may read as inputs: gauges that are not stocks (a rating,
a demand, the weather), offered one per machine.

Left out: counters, the stocks' own series and their twins, Orchestra's plumbing, levels that did
not move or are not written on a schedule, and the levels conservation left out as flags (a
level of 0 and 1 that merely moves with the work: a baker is busy or not). A flag as a driver only
restates that work was happening. A gauge written per instance (``bakery_baker_busy{instance="1"}``, and 2 and 3) is
one input per machine, the instances summed (how many bakers are busy): a model is about
machines, not their instances, and one flow per instance is not a model.

**Orchestra's own series are never a system's input.** A series Orchestra's own machinery wrote of
itself (named ``orchestra_*``, or written by an instrument a plugin declared: the workflows
plugin's record, the agents' turns; its ``owner`` in the provenance, ``collect.views.owned``) says
what Orchestra did, as its own series and events do (AGENTS.md rule 7, ``sd.series.PLUMBING``), not
what the system did. It is offered as an input, or read as a driver, only by a flow whose stocks are
all of that same provenance; never by a flow of a source's stock or the project's (bootstrap run 7:
a team's queue drained "0.00 × workflow record bytes"). With no stock of Orchestra's own in the
model, it is no input at all, and the discovery record's ``left_out`` says why (``OWN_REASON``)."""

from __future__ import annotations

import re
from collections import defaultdict

from .capacity import VIEW
from .live import regular
from .series import NOT_NAMED, PLUMBING, Series, series_key


def _group(s: Series) -> tuple[str, tuple]:
    """A gauge's instance-free identity: its name and labels without ``instance`` (and the
    instance part of a ``source``)."""
    labels = {k: v for k, v in s.labels.items() if k != "instance"}
    if "/" in (labels.get("source") or ""):
        labels["source"] = labels["source"].partition("/")[0]
    return s.name, tuple(sorted(labels.items()))


def _name(name: str, labels: dict[str, str]) -> str:
    """An input's name: the series' name and the values of the labels that say which it is (never
    ``series.NOT_NAMED``: a placeholder's input is named as the real series that replaces it)."""
    return "_".join([name, *[re.sub(r"\W+", "_", v) for k, v in sorted(labels.items()) if k not in NOT_NAMED]])


OWN_REASON = ("Orchestra's own ({what}): a measure of Orchestra's own machinery, offered as an input only to flows "
              "of stocks of the same provenance, never to a flow of a source's stock or the project's; no stock here is one")


def orchestras(name: str, labels: dict[str, str], provenance: dict | None) -> str | None:
    """Why a series is Orchestra's own machinery's (see the module), in a few words; None when it
    is not: ``provenance`` is what its source said of it (``sd.discover``'s, by series key)."""
    if PLUMBING.match(name):
        return "named orchestra_*"
    owner = (provenance or {}).get("owner")
    if owner and owner != "project":
        return f"its instrument {(provenance or {}).get('instrument') or labels.get('instrument')} is the {owner} plugin's"
    return None


def own_paths(stocks: dict[str, str], refs: dict[str, dict], provenance: dict) -> set[str]:
    """The paths a rate may read (stock ids; ``input:<name>``) that are Orchestra's own:
    ``stocks`` maps each stock's series key to its id; ``refs`` are ``offered_inputs``'s."""
    out = {sid for key, sid in stocks.items() if orchestras(key, {}, provenance.get(key))}   # a key begins with its name
    return out | {f"input:{k}" for k, r in refs.items() if r.get("orchestra")}


def keep_apart(inputs: dict, refs: dict, own_stock: bool, left_out: dict[str, str] | None = None) -> None:
    """With no stock of Orchestra's own (``own_stock`` false), its own inputs are no input at all:
    removed from ``inputs`` and ``refs``, and said in ``left_out`` (by each member's series key)."""
    if own_stock:
        return
    for k in [k for k, r in refs.items() if r.get("orchestra")]:
        r = refs.pop(k)
        inputs.pop(k, None)
        if left_out is not None:
            for key in r.get("members") or [series_key(r["name"], r.get("labels") or {})]:
                was = left_out.get(key)
                left_out[key] = OWN_REASON.format(what=r["orchestra"]) + (f"; and {was}" if was else "")


def offered_inputs(series: list[Series], stocks: set[str], left_out: dict[str, str], provenance: dict | None = None
                   ) -> tuple[dict[str, list[float]], dict[str, dict]]:
    """``{name: values per step}`` and, per name, the series it came from (``stocks``: the keys of
    the stocks' series; ``left_out``: conservation's, for the flags; ``provenance``: what each
    series' source said of it, by series key). An input of Orchestra's own machinery says why in its
    ref's ``orchestra`` (``orchestras``), and its members' series keys in ``members``."""
    provenance = provenance or {}
    groups: dict[tuple, list[Series]] = defaultdict(list)
    for s in series:
        why = left_out.get(series_key(s.name, s.labels), "")
        if s.counter or s.key in stocks or PLUMBING.match(s.name) or not any(s.deltas) or not regular(s.points) \
                or why.startswith(("a flag", "the same as", VIEW)):
            continue
        groups[_group(s)].append(s)
    inputs, refs = {}, {}
    for (name, labels), members in groups.items():
        labels = dict(labels)
        key = _name(name, labels)
        one = members[0]
        res = [m.resolution for m in members if m.resolution is not None]
        how = {"resolution_s": max((r.seconds for r in res if r.seconds), default=None), "read": res[0].read} if res else {}
        if own := orchestras(name, one.labels, provenance.get(one.key)):
            how |= {"orchestra": own, "members": [m.key for m in members]}
        if len(members) == 1 and "instance" not in one.labels and "/" not in (one.labels.get("source") or ""):
            inputs[key] = one.values
            refs[key] = {"name": name, "labels": one.labels, **how}
            continue
        inputs[key] = [sum(vs) for vs in zip(*[m.values for m in members], strict=True)]
        refs[key] = {"name": name, "labels": labels, "summed": f"summed over {len(members)} instance{'s' if len(members) != 1 else ''}", **how}
    return inputs, refs
