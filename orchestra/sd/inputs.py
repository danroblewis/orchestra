"""The measured levels an SD Lab strategy may read as inputs: gauges that are not stocks (a rating,
a demand, the weather), offered one per machine.

Left out: counters, the stocks' own series and their twins, Orchestra's plumbing, levels that did
not move or are not written on a schedule, and the levels conservation left out as flags (a
two-valued level that merely moves with the work: a baker is busy or not). A flag as a driver only
restates that work was happening. A gauge written per instance (``bakery_baker_busy{instance="1"}``, and 2 and 3) is
one input per machine, the instances summed (how many bakers are busy): a model is about
machines, not their instances, and one flow per instance is not a model."""

from __future__ import annotations

import re
from collections import defaultdict

from .live import regular
from .series import PLUMBING, Series, series_key


def _group(s: Series) -> tuple[str, tuple]:
    """A gauge's instance-free identity: its name and labels without ``instance`` (and the
    instance part of a ``source``)."""
    labels = {k: v for k, v in s.labels.items() if k != "instance"}
    if "/" in (labels.get("source") or ""):
        labels["source"] = labels["source"].partition("/")[0]
    return s.name, tuple(sorted(labels.items()))


def _name(name: str, labels: dict[str, str]) -> str:
    return "_".join([name, *[re.sub(r"\W+", "_", v) for k, v in sorted(labels.items()) if k not in ("project", "machine")]])


def offered_inputs(series: list[Series], stocks: set[str], left_out: dict[str, str]
                   ) -> tuple[dict[str, list[float]], dict[str, dict]]:
    """``{name: values per step}`` and, per name, the series it came from (``stocks``: the keys of
    the stocks' series; ``left_out``: conservation's, for the flags)."""
    groups: dict[tuple, list[Series]] = defaultdict(list)
    for s in series:
        why = left_out.get(series_key(s.name, s.labels), "")
        if s.counter or s.key in stocks or PLUMBING.match(s.name) or not any(s.deltas) or not regular(s.points) \
                or why.startswith(("a flag", "the same as")):
            continue
        groups[_group(s)].append(s)
    inputs, refs = {}, {}
    for (name, labels), members in groups.items():
        labels = dict(labels)
        key = _name(name, labels)
        one = members[0]
        res = [m.resolution for m in members if m.resolution is not None]
        how = {"resolution_s": max((r.seconds for r in res if r.seconds), default=None), "read": res[0].read} if res else {}
        if len(members) == 1 and "instance" not in one.labels and "/" not in (one.labels.get("source") or ""):
            inputs[key] = one.values
            refs[key] = {"name": name, "labels": one.labels, **how}
            continue
        inputs[key] = [sum(vs) for vs in zip(*[m.values for m in members], strict=True)]
        refs[key] = {"name": name, "labels": labels, "summed": f"summed over {len(members)} instance{'s' if len(members) != 1 else ''}", **how}
    return inputs, refs
