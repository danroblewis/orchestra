"""Which candidates go to discovery: families × statistics × groupings × views explode, so each
candidate is scored and the best are kept, up to ``max_series`` series per source and
``max_per_family`` definitions per family.

A higher score: it **moves** within the window (measured by a read of it, ``infer.probe``); its
groups move **apart** (a grouping whose groups' changes do not move together: three queues,
consumer groups, pod phases, each its own stock, which their total would merge); its grouping
labels are **stable** (low churn); it is **small** (few series); its grouping is **coarse**; its
view is one discovery uses most (counts and counters first, a minimum last). Only a level's own
groups count as apart: merging them merges stocks. A counter's split is worth its series only
where a level is split by the same label, alone or with another, because its groups move apart
(the lag by consumer group, or by consumer group and topic: the offsets produced per topic): then it scores as apart as that level, so the flows of each group are there to balance
it; anywhere else its total balances the total, and its groups (successes and failures) moving
apart is no reason to spend the cap.

The cap is spent in two rounds. First every family's coarsest candidate (its total, mostly), best
family first, so every family that moves is read at least as a whole and none takes the cap, up
to ``WHOLE_SHARE`` of the cap; then every other candidate (and the coarsest that did not fit),
best first across families, so the splits whose groups move apart (three
queues, three consumer groups, the phases of pods) come before a family's second view of
anything; each further split by a label already taken (the nodes, again) is worth less of its
apart, ``1/(1+n)`` of it after ``n``, so the cap is spread over what the system is split by. Each definition says what it merges (``views.py``), so a total that could not be
split says so. A count
and its two turnover counters are one unit, taken or left out together and sized as their sum: a
count kept without them cannot balance. Two counts with the same series (the same pods, counted
from two families: ``duplicates.same_shape``) are one too many: the better is kept, the other left
out as its duplicate. A script's ``pin`` bypasses the ranking, not the cap. What is left out is
kept with its score and the reason."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from math import log10

from .checks import COLLECTION_LABELS
from .duplicates import same_shape
from .spec import SourceSpec
from .views import WEIGHT, Definition

APART = 1.5                  # what a grouping whose groups move apart adds to its score, at most
APART_VALUES = 8             # ... by one label of at most this many values (a few queues, topics, phases)
EXACT = ("increments", "sum_by", "rollup")    # views alike only when equal at every point
TARGET_LABELS = COLLECTION_LABELS | {"endpoint", "metrics_path", "instance"}   # who reported a series, not what it is of
WHOLE_SHARE = 0.6            # of the cap, what the first round (every family's coarsest) may take before the splits


def _labels(d: Definition) -> list[str]:
    """The grouping labels (each of at most ``APART_VALUES`` values) a definition is split by that
    name something of the system (a queue, a topic, a phase), not who reported it (``job``,
    ``endpoint``: ``TARGET_LABELS``, which the collection adds)."""
    return [c for c in d.group_by if d.labels_info.get(c, {}).get("role") == "grouping"
            and int(d.labels_info[c].get("cardinality", 0)) <= APART_VALUES
            and d.labels_info[c].get("real", c) not in TARGET_LABELS]


def _split(d: Definition) -> str | None:
    """The one such label a definition is split by, when it is split by exactly one grouping label."""
    split = [c for c in d.group_by if d.labels_info.get(c, {}).get("role") == "grouping"]
    return split[0] if len(split) == 1 and _labels(d) == split else None


def stock_splits(defs: list[Definition], probes: dict[str, dict]) -> dict[str, float]:
    """The labels a level is split by because its groups move apart (lag by consumer group, or by
    consumer group and topic), with how far apart: the counters split by the same label are what
    can balance each group (the offsets produced on each topic), so they score as far apart as the
    level (a hair less, so the level is taken first). A level split by two labels credits both."""
    out: dict[str, float] = {}
    for d in defs:
        if d.kind == "level" and d.view in ("sum_by", "rollup"):
            a = float((probes.get(d.id) or {}).get("apart") or 0.0)
            if a >= 0.5:
                for c in _labels(d):
                    out[c] = max(out.get(c, 0.0), 0.99 * a)
    return out


def score(d: Definition, probe: dict | None, shared: dict[str, float] | None = None) -> tuple[float, str]:
    churn = max([float(d.labels_info.get(c, {}).get("churn", 0.0)) for c in d.group_by] or [0.0])
    n = (probe or {}).get("series", d.est_series)
    moves = 1.5 if probe is None else (3.0 if probe.get("moves") else 0.0)
    split, own = _split(d), float((probe or {}).get("apart") or 0.0)
    apart = 0.0 if split is None else ((shared or {}).get(split, 0.0) if d.kind != "level" else own)
    parts = {"moves": moves, "apart": APART * apart, "stable": 1.0 - churn,
             "small": 1.0 / (1.0 + log10(max(1, n))), "coarse": 1.0 / (1.0 + len(d.group_by)), "view": WEIGHT.get(d.view, 0.5)}
    return round(sum(parts.values()), 3), ", ".join(f"{k} {v:.2f}" for k, v in parts.items())


def _unit(d: Definition) -> tuple | None:
    """A count and its two turnover counters (the same thing counted, the same grouping) are one
    unit: the count balances only with both, so they are kept or left out together."""
    return (d.counts, tuple(d.group_by)) if d.view in ("count", "starts", "stops") and d.counts and not d.pin else None


def _same_counts(live: list[Definition], left: list[Definition], probes: dict[str, dict]) -> None:
    """Counts whose series are another count's (the same pods, from another family), and counters
    and sums whose values are another family's at every point (a histogram's ``_count`` beside the
    counter of the same requests; a deployment's replicas and its replicas updated, outside a
    rollout): the best scored is kept, the others move to ``left`` with why; a count's turnover
    goes with it."""
    alike = sorted((d for d in live if d.view in ("count", "distinct", *EXACT) and not d.pin and (probes.get(d.id) or {}).get("shape")),
                   key=lambda d: (-d.score, d.family, d.id))
    kept: list[Definition] = []
    for d in alike:
        exact = d.view in EXACT
        twin = next((k for k in kept if (k.view in EXACT) == exact and k.family != d.family
                     and same_shape(probes[k.id]["shape"], probes[d.id]["shape"], exact=exact)), None)
        if twin is None:
            kept.append(d)
            continue
        live.remove(d)
        what = ("the same events counted by another family" if d.kind != "level" else "the same quantity reported by another family"
                ) if exact else "the same things counted from another family"
        left.append(replace(d, why=f"the same series as {twin.name} by ({', '.join(twin.group_by)}): {what}"))


def rank(defs: list[Definition], spec: SourceSpec, probes: dict[str, dict]) -> tuple[list[Definition], list[Definition]]:
    """(kept, left out), each with its score and why."""
    scored, shared, apart_of = [], stock_splits(defs, probes), {}
    for d in defs:
        s, why = score(d, probes.get(d.id), shared)
        scored.append(replace(d, score=s, why=why))
        apart_of[d.id] = float(why.split("apart ")[1].split(",")[0]) / APART if "apart " in why else 0.0
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
    _same_counts(live, left, probes)
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
    firsts, rest = [], []
    for f in order:
        least = min(sum(size(d) for d in u) for u in queues[f])
        first = next(u for u in queues[f] if sum(size(d) for d in u) == least)
        firsts.append(first)
        rest += [u for u in queues[f] if u is not first]
    later = []
    for u in firsts:                                 # every family's coarsest first, within a share of the cap
        if total + sum(size(d) for d in u) <= WHOLE_SHARE * spec.max_series or any(d.pin for d in u):
            take(u)
        else:
            later.append(u)
    pending, splits = rest + later, Counter()        # then the rest, best first: splits whose groups move apart lead,

    def worth(u: list[Definition]) -> tuple:         # each further split by a label already taken worth less of its apart
        d = max(u, key=lambda d: d.score)
        c = _split(d)
        return (-(d.score - APART * apart_of.get(d.id, 0.0) * (1 - 1 / (1 + splits[c]))) if c else -d.score, u[0].id)
    while pending:
        u = min(pending, key=worth)
        pending.remove(u)
        before = len(kept)
        take(u)
        if len(kept) > before and (c := _split(max(u, key=lambda d: d.score))):
            splits[c] += 1
    return kept, left
