"""One schema round over a remote store (``schema.read``), in phases that each read every family
at once (``census.py``):

1. list names and series (``listing.py``) and the metadata, and group families (``schema.py``);
2. sample a few series of each (raw, the window): interval, native histograms, behaviour;
3. for the families the window cannot judge (it only rose), the same series over ``history``;
   for those whose samples are all 1, their extremes (an info metric);
4. each label's role: identity, unit, constant, or grouping when its values do not churn;
5. labels the collection adds whose values repeat each other (``duplicates.py``), recording rules
   included (a rule evaluated by each replica of an HA pair carries the replica label,
   and summed across it counts everything twice).

A name over the store's per-query limit across an HA pair's replicas but under it at one
(``listing.py``) is read at that replica: its family's ``where``.

A family any phase could not read is not guessed at: it keeps the last round's verdict
(``known``: kind, interval, label roles, the value read of a duplicated label), noted, or else is
``unknown`` (read as neither level nor flow, and said so). A type judged in an earlier round
changes only when this round's samples decide it (``behaviour.decides``)."""

from __future__ import annotations

import time

from . import Source, census
from .behaviour import classify, counter_like, decides
from .checks import (
    CHURN,
    COLLECTION_LABELS,
    DUPLICATE_SERIES,
    HIGH_CARDINALITY,
    PICKS,
    interval,
    is_object,
    is_unit,
    pick,
)
from .duplicates import duplicated
from .family import UNREAD, Family, LabelInfo, Schema, esc
from .listing import REPLICA_LABELS, listing
from .schema import SKIP_LABELS, _aliases, _group
from .spec import SourceSpec

RETYPABLE = ("gauge", "counter")


def known_record(f: Family) -> dict:
    """What a later round keeps of a family it cannot read (``Inference.families``)."""
    return {"kind": f.kind, "resolution_s": f.resolution_s, "retyped": f.retyped, "where": dict(f.where),
            "constants": dict(f.constants), "counter_form": f.counter_form,
            "labels": {c: {"real": i.real, "cardinality": i.cardinality, "churn": i.churn, "role": i.role} for c, i in f.labels.items()},
            "rule_resolution": {r["metric"]: r.get("resolution_s") for r in f.rollups.values()}}


def _restore(fam: Family, k: dict | None, why: str) -> None:
    if not k:
        fam.kind, fam.retyped = "unknown", f"could not be read this round ({why}) and no earlier round judged it: left out, not guessed"
        return
    fam.kind, fam.resolution_s, fam.retyped = k["kind"], k.get("resolution_s"), k.get("retyped")
    fam.where, fam.constants, fam.counter_form = dict(k.get("where") or {}), dict(k.get("constants") or {}), k.get("counter_form", "")
    fam.labels = {c: LabelInfo(i["real"], i["cardinality"], i["churn"], i["role"]) for c, i in (k.get("labels") or {}).items()}
    for r in fam.rollups.values():
        r["resolution_s"] = (k.get("rule_resolution") or {}).get(r["metric"], r.get("resolution_s"))
    fam.notes.append(f"could not be read this round ({why}): kept as the last round found it")


def _remembered(lst, old: dict | None) -> dict:
    """What the next rounds' listings keep of this one's: names too big, names listed at one replica."""
    now = time.time()
    keep = lambda kind, n: (old or {}).get(kind, {}).get(n, {}).get("at", now)
    return {"too_big": {n: {"why": w.split(" (found at ")[0], "at": keep("too_big", n)} for n, w in lst.too_big.items()},
            "pinned": {n: {"pin": p, "at": keep("pinned", n)} for n, p in lst.pinned.items()}}


def _at(sel: str, where: dict[str, str]) -> str:
    """``sel`` narrowed to the label values of ``where``."""
    if not where:
        return sel
    m = ",".join(f'{k}="{esc(v)}"' for k, v in sorted(where.items()))
    if sel.endswith("}"):
        return sel[:-1] + ("" if sel.endswith("{}") else ",") + m + "}"
    return f"{sel}{{{m}}}"


def _metadata(source: Source, names: list[str]) -> dict:
    try:
        return source.metadata(names)
    except TypeError:                      # a source whose metadata takes no names
        return source.metadata()


def survey(source: Source, spec: SourceSpec, start: float, end: float, *, until: float | None = None,
           known: dict[str, dict] | None = None, remembered: dict | None = None) -> Schema:
    known = known or {}
    conc = spec.concurrency
    lst = listing(source, spec.match, start, end, until=until, concurrency=conc, max_names=spec.max_names, known=remembered)
    notes = list(lst.notes)
    names = lst.names
    meta = _metadata(source, sorted(names))
    families = _group(names, meta)
    families_by = {f.name: f for f in families}
    for fam in families:                   # listed at one replica of an HA pair: read there
        if pin := next((lst.pinned[m] for m in fam.metrics if m in lst.pinned), None):
            fam.where.update(pin)
            fam.notes.append(f"over the store's per-query limit across its replicas: read at {', '.join(f'{k}={v}' for k, v in pin.items())} "
                             "only (an HA pair's replicas repeat each other)")
    failed: dict[str, str] = {}
    sets_of: dict[str, list] = {}
    one_of: dict[str, list] = {}
    for fam in families:
        fam_sets = [lab for m in fam.metrics for lab in names.get(m, [])]
        one = [lab for lab in names.get(fam.first_metric(), [])
               if not fam.stat_label or lab.get(fam.stat_label) == next(iter(fam.stat_values.values()), None)]
        fam.series = len({tuple(sorted((k, v) for k, v in lab.items() if k != fam.stat_label)) for lab in one}) or len(fam_sets)
        sets_of[fam.name], one_of[fam.name] = fam_sets, one or fam_sets

    # 2. raw samples of a few series of each family, and of each recording rule
    judged = {f.name for f in families if f.kind in RETYPABLE and not f.stats and not f.counter_form}
    picks = {f.name: pick(f.first_metric(), one_of[f.name], PICKS if f.name in judged else 3) for f in families}
    rule_picks = {(f.name, r["metric"]): pick(r["metric"], names.get(r["metric"], []), 3) for f in families for r in f.rollups.values()}
    for fam in families:                   # a family read at one replica is sampled there too
        if fam.where:
            picks[fam.name] = (_at(picks[fam.name][0], fam.where), picks[fam.name][1])
            for r in fam.rollups.values():
                rule_picks[(fam.name, r["metric"])] = (_at(rule_picks[(fam.name, r["metric"])][0],
                                                           {k: v for k, v in fam.where.items() if k in r.get("labels", [])}),
                                                       rule_picks[(fam.name, r["metric"])][1])
    raw, bad = census.raw(source, {**picks, **rule_picks}, start, end, until, conc)
    for fam in families:
        if fam.name in bad:
            failed[fam.name] = f"its samples: {bad[fam.name]}"
            continue
        fam.resolution_s = interval(raw.get(fam.name, []))
        for r in fam.rollups.values():
            if (fam.name, r["metric"]) in bad:
                failed[fam.name] = f"its rule {r['metric']}'s samples: {bad[(fam.name, r['metric'])]}"
            r["resolution_s"] = interval(raw.get((fam.name, r["metric"]), []))
        if fam.first_metric() in getattr(source, "native", set()) and fam.kind in RETYPABLE:
            fam.kind, fam.counter_form = "counter", "native"
            fam.retyped = "a native histogram: read by its count, a counter"

    # 3. behaviour: the window, the history where the window cannot judge, extremes for an info metric
    window: dict[str, tuple] = {}
    for fam in families:
        if fam.name in judged and fam.name not in failed and raw.get(fam.name):
            typ = (meta.get(fam.first_metric()) or {}).get("type")
            window[fam.name] = (typ, raw[fam.name])
    ones = {n: families_by[n].selector() for n, (_, r) in window.items()
            if all(v == 1.0 for p in r for _, v in p)}
    ext, bad = census.extremes(source, {n: (sel, families_by[n].series) for n, sel in ones.items()}, start, end, until, conc) if ones else ({}, {})
    for n, why in bad.items():
        failed[n] = f"its extremes: {why}"
    unsure = {n: picks[n] for n, (typ, r) in window.items() if n not in failed and typ != "counter" and counter_like(r)[0]
              and families_by[n].kind != "counter"}
    long, bad = census.history(source, unsure, end, spec.history, until, conc) if unsure and spec.history > end - start else ({}, {})
    for n, why in bad.items():
        notes.append(f"{n}: its history could not be read ({why}): judged on the window alone")
    for n, (typ, r) in window.items():
        if n in failed:
            continue
        fam = families_by[n]
        low, high = ext.get(n, (None, None))
        base = fam.kind
        kind, why = classify(fam.first_metric(), "counter" if fam.kind == "counter" else typ, fam.help, r, low=low, high=high)
        evidence = r
        if n in long and long[n] and kind not in ("timestamp", "clock", "info"):
            hk, hwhy = classify(fam.first_metric(), "counter" if fam.kind == "counter" else typ, fam.help, long[n])
            kind, why, evidence = hk, (f"{hwhy}, over the last {spec.history / 3600:g} h" if hk else ""), long[n]
        new = {"delta": "counter"}.get(kind, kind) if kind else base
        prev = (known.get(n) or {}).get("kind")
        if prev in RETYPABLE and new in RETYPABLE and prev != new and decides(evidence) != new:
            k = known[n]
            fam.kind, fam.retyped, fam.counter_form = prev, k.get("retyped"), k.get("counter_form", "")
            fam.notes.append(f"kept a {prev}, as judged before: this round's samples do not decide it is a {new}")
            continue
        if kind and kind != fam.kind:
            fam.kind, fam.retyped = new, why
            if kind == "delta":
                fam.counter_form = "delta"

    # 4. label roles
    asks: dict[str, tuple] = {}
    real_of: dict[str, dict[str, str]] = {}
    for fam in families:
        fam_sets = sets_of[fam.name]
        real = {k for lab in fam_sets for k in lab} - SKIP_LABELS - ({fam.stat_label} if fam.stat_label else set())
        need = []
        real_of[fam.name] = _aliases(real, spec)
        for canonical, rl in real_of[fam.name].items():
            values = {lab[rl] for lab in fam_sets if rl in lab}
            if canonical in spec.identity:
                fam.labels[canonical] = LabelInfo(rl, len(values), 0.0, "identity")
            elif len(values) > 1 and is_unit(canonical, rl, values):
                fam.labels[canonical] = LabelInfo(rl, len(values), 0.0, "unit")
            elif len(values) > 1 and is_object(canonical, rl, values):
                fam.labels[canonical] = LabelInfo(rl, len(values), 0.0, "identity")
            elif len(values) <= 1:
                fam.labels[canonical] = LabelInfo(rl, len(values), 0.0, "constant")
                if values:
                    fam.constants[canonical] = next(iter(values))
            else:
                need.append(canonical)
        if need and fam.name not in failed:
            asks[fam.name] = (fam.selector(fam.stats[0] if fam.stats else None), [real_of[fam.name][c] for c in need],
                              fam.resolution_s, max(1, fam.series))
            fam.labels.update({c: LabelInfo(real_of[fam.name][c], 0, 0.0, "pending") for c in need})
    got, bad = census.churn(source, asks, start, end, until, conc) if asks else ({}, {})
    for n, why in bad.items():
        failed.setdefault(n, f"its labels' churn: {why}")
    for n, by_label in got.items():
        fam = families_by[n]
        for c, info in list(fam.labels.items()):
            if info.role != "pending":
                continue
            card, churned = by_label.get(info.real, (0, 0.0))
            role = "identity" if (churned >= CHURN and card > 3) or card > HIGH_CARDINALITY else ("grouping" if card > 1 else "constant")
            fam.labels[c] = LabelInfo(info.real, card, churned, role)
            values = {lab[info.real] for lab in sets_of[n] if info.real in lab}
            if role == "constant" and len(values) == 1:
                fam.constants[c] = next(iter(values))

    # 5. duplicates
    dups = {f.name: [c for c, i in f.labels.items() if i.role == "grouping" and 2 <= i.cardinality <= 4 and i.real in COLLECTION_LABELS]
            for f in families if f.name not in failed and f.series <= DUPLICATE_SERIES and f.kind not in UNREAD}
    dups = {n: cs for n, cs in dups.items() if cs}
    grids, bad = census.grid(source, {n: (families_by[n].selector(families_by[n].stats[0] if families_by[n].stats else None),
                                          families_by[n].resolution_s, max(1, families_by[n].series)) for n in dups},
                             start, end, until, conc) if dups else ({}, {})
    for n, why in bad.items():
        failed.setdefault(n, f"its duplicates check: {why}")
    for n, cs in dups.items():
        if n in failed:
            continue
        fam, series = families_by[n], grids.get(n, [])
        for c in cs:
            real = fam.labels[c].real
            if (dup := duplicated(series, real, counter=fam.kind == "counter")) is None:
                continue
            keep, dropped = dup
            fam.where[real] = keep
            fam.labels[c] = LabelInfo(real, 1, 0.0, "constant")
            fam.constants[c] = keep
            fam.series = max(1, fam.series // (1 + len(dropped)))
            fam.notes.append(f"{real}={', '.join(dropped)} only repeats {real}={keep}, target for target: only {keep} is read")
            series = [(lab, v) for lab, v in series if lab.get(real) not in dropped]
    for fam in families:                   # too big to check by its data: an HA pair's replica label is read at one value
        if fam.name in failed or fam.name in dups or fam.series <= DUPLICATE_SERIES or fam.kind in UNREAD:
            continue
        for c, i in list(fam.labels.items()):
            if i.role == "grouping" and 2 <= i.cardinality <= 4 and i.real in REPLICA_LABELS:
                counts: dict[str, int] = {}
                for lab in sets_of[fam.name]:
                    if i.real in lab:
                        counts[lab[i.real]] = counts.get(lab[i.real], 0) + 1
                keep = min(counts, key=lambda v: (-counts[v], v))
                fam.where[i.real] = keep
                fam.labels[c] = LabelInfo(i.real, 1, 0.0, "constant")
                fam.constants[c] = keep
                fam.series = max(1, fam.series // len(counts))
                fam.notes.append(f"{i.real} names a replica of an HA pair ({len(counts)} values): read at {i.real}={keep} only, "
                                 f"never summed across it (too many series, {sum(counts.values())}, to compare the replicas by their data)")

    for n, why in failed.items():
        _restore(families_by[n], known.get(n), why)
    if failed:
        kept = sum(1 for n in failed if known.get(n))
        notes.append(f"{len(failed)} famil{'y' if len(failed) == 1 else 'ies'} could not be read this round: {kept} kept as the last "
                     f"round found them, {len(failed) - kept} unknown and left out; the first: {next(iter(failed.values()))}")
    for n, why in lst.failed.items():
        notes.append(f"{n}: could not be listed ({why})")
    return Schema(families, notes, _remembered(lst, remembered))

