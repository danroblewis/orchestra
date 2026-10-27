"""Which candidates go to discovery: families × statistics × groupings × views explode, so each
candidate is scored and the best are kept, up to ``max_series`` series per source and
``max_per_family`` definitions per family.

A higher score: it **moves** within the window (measured by a read of it, ``infer.probe``); its
grouping labels are **stable** (low churn); it is **small** (few series); its grouping is
**coarse**; its view is one discovery uses most (counts and counters first, a minimum last).
Candidates are taken round-robin across families, best family first, so one family cannot take
the cap. A script's ``pin`` bypasses the ranking, not the cap. What is left out is kept with its
score and the reason."""

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
    size = lambda d: int((probes.get(d.id) or {}).get("series", d.est_series)) or 1
    kept: list[Definition] = []
    total = 0
    per_family: dict[str, int] = {}

    def take(d: Definition) -> None:
        nonlocal total
        if total + size(d) > spec.max_series:
            left.append(replace(d, why=f"over the cap of {spec.max_series} series (score {d.score}: {d.why})"))
        elif per_family.get(d.family, 0) >= spec.max_per_family and not d.pin:
            left.append(replace(d, why=f"its family already has {spec.max_per_family} (score {d.score}: {d.why})"))
        else:
            kept.append(d)
            total += size(d)
            per_family[d.family] = per_family.get(d.family, 0) + 1

    for d in [d for d in live if d.pin]:
        take(d)
    queues: dict[str, list[Definition]] = {}
    for d in sorted((d for d in live if not d.pin), key=lambda d: (-d.score, d.id)):
        queues.setdefault(d.family, []).append(d)
    order = sorted(queues, key=lambda f: (-queues[f][0].score, f))
    while any(queues[f] for f in order):
        for f in order:
            if queues[f]:
                take(queues[f].pop(0))
    return kept, left
