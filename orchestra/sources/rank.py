"""Which candidates go to discovery: families × statistics × groupings × views explode, so each
candidate is scored and the best are kept, up to ``max_series`` series per source and
``max_per_family`` definitions per family.

A higher score: it **moves** within the window (measured by a read of it, ``infer.probe``); its
grouping labels are **stable** (low churn); it is **small** (few series); its grouping is
**coarse**; its view is one discovery uses most (counts and counters first, a minimum last).
Candidates are taken round-robin across families, best family first, so one family cannot take
the cap. A count and its two turnover counters are one unit, taken or left out together and sized
as their sum: a count kept without them cannot balance. A script's ``pin`` bypasses the ranking,
not the cap. What is left out is kept with its score and the reason."""

from __future__ import annotations

from dataclasses import replace
from math import log10

from .spec import SourceSpec
from .views import WEIGHT, Definition


def score(d: Definition, probe: dict | None) -> tuple[float, str]:
    churn = max([float(d.labels_info.get(c, {}).get("churn", 0.0)) for c in d.group_by] or [0.0])
    n = (probe or {}).get("series", d.est_series)
    moves = 1.5 if probe is None else (3.0 if probe.get("moves") else 0.0)
    parts = {"moves": moves, "stable": 1.0 - churn, "small": 1.0 / (1.0 + log10(max(1, n))),
             "coarse": 1.0 / (1.0 + len(d.group_by)), "view": WEIGHT.get(d.view, 0.5)}
    return round(sum(parts.values()), 3), ", ".join(f"{k} {v:.2f}" for k, v in parts.items())


def _unit(d: Definition) -> tuple | None:
    """A count and its two turnover counters (the same thing counted, the same grouping) are one
    unit: the count balances only with both, so they are kept or left out together."""
    return (d.counts, tuple(d.group_by)) if d.view in ("count", "starts", "stops") and d.counts and not d.pin else None


def rank(defs: list[Definition], spec: SourceSpec, probes: dict[str, dict]) -> tuple[list[Definition], list[Definition]]:
    """(kept, left out), each with its score and why."""
    scored = []
    for d in defs:
        s, why = score(d, probes.get(d.id))
        scored.append(replace(d, score=s, why=why))
    left: list[Definition] = []
    live = []
    for d in scored:
        p = probes.get(d.id)
        if p is not None and not p.get("series"):
            left.append(replace(d, why=f"returned nothing in the window ({p.get('error') or 'no series'})"))
        elif p is not None and not p.get("moves") and not d.pin:
            left.append(replace(d, why=f"did not move in the window (score {d.score})"))
        else:
            live.append(d)
    gone = {_unit(d) for d in left} - {None}
    for d in [d for d in live if _unit(d) in gone]:      # a count without its turnover, or the reverse, cannot balance
        live.remove(d)
        left.append(replace(d, why=f"the rest of its count and turnover was left out (score {d.score})"))
    size = lambda d: int((probes.get(d.id) or {}).get("series", d.est_series)) or 1
    kept: list[Definition] = []
    total = 0
    per_family: dict[str, int] = {}

    def take(unit: list[Definition]) -> None:
        nonlocal total
        n, fam, pinned = sum(size(d) for d in unit), unit[0].family, all(d.pin for d in unit)
        if total + n > spec.max_series:
            left.extend(replace(d, why=f"over the cap of {spec.max_series} series (score {d.score}: {d.why})") for d in unit)
        elif per_family.get(fam, 0) + len(unit) > spec.max_per_family and not pinned:
            left.extend(replace(d, why=f"its family already has {spec.max_per_family} (score {d.score}: {d.why})") for d in unit)
        else:
            kept.extend(unit)
            total += n
            per_family[fam] = per_family.get(fam, 0) + len(unit)

    for d in [d for d in live if d.pin]:
        take([d])
    units: dict[tuple, list[Definition]] = {}
    for d in live:
        if not d.pin:
            units.setdefault(_unit(d) or ("one", d.id), []).append(d)
    queues: dict[str, list[list[Definition]]] = {}
    for u in sorted(units.values(), key=lambda u: (-max(d.score for d in u), u[0].id)):
        queues.setdefault(u[0].family, []).append(u)
    order = sorted(queues, key=lambda f: (-max(d.score for d in queues[f][0]), f))
    while any(queues[f] for f in order):
        for f in order:
            if queues[f]:
                take(queues[f].pop(0))
    return kept, left
