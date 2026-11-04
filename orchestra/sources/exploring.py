"""``orchestra sources explore``: a bounded survey of a source's ``explore`` scope beyond its
``match`` (``docs/proposals/metric-explorer.md``), for the explorer to choose its next experiment
from. It reads; it never changes ``match``, ``explore`` or anything else.

Per ``explore`` selector, the metric names under it (``label/__name__/values`` with that
``match[]`` and a ``limit``), narrowed by ``family`` (a glob on the metric names), grouped into
families as inference groups them (``schema._group``); per ``match`` selector the names under it,
so each family says whether the model reads it already (``in_match``). The families outside the
match come first; at most ``limit`` of them (``MAX_FAMILIES`` at most) are surveyed, the rest
named only. A surveyed family gets:

- its label names (``/api/v1/labels`` with its ``match[]``) and, for at most ``MAX_LABELS`` of
  them, how many values each has (``label/<name>/values`` with ``match[]`` and ``limit``
  ``VALUES`` + 1: "50+" when more);
- its metadata, metric by metric (at most ``MAX_META`` of its metrics);
- its kind as inference would judge it (``conventions.convention``, then ``behaviour.classify``,
  then the owner's ``kinds``) from the raw samples of a few series (``census.raw`` of
  ``checks.pick`` over a bounded listing of ``SAMPLE`` series).

Every request goes through the transport with the source's ``explore`` as its scope, each
selector conjoined with the ``explore`` selector its family was found under (``console.conjoined``),
at the store's own rate and daily cap (``limits.for_store``), within a budget of the requests the
worst case needs (``cost``), logged ``by`` ``explore`` (``reqlog.py``). When that worst case would
pass the store's daily cap, nothing is sent: the refusal is logged (``sent`` false) and returned
with its reason."""

from __future__ import annotations

import time
from dataclasses import replace
from fnmatch import fnmatchcase
from pathlib import Path

from . import PastDeadline, SourceError, census, reqlog
from .behaviour import classify
from .checks import pick
from .console import Refused, conjoined, resets
from .conventions import convention
from .family import UNREAD, Family
from .kinds import declared
from .limits import Budget, DailyCap, for_store
from .prometheus import PrometheusSource
from .schema import SKIP_LABELS, _group
from .spec import SourceSpec

BY = "explore"
LIMIT = 10                   # families surveyed per call, by default
MAX_FAMILIES = 50            # ... at most
MAX_LABELS = 8               # labels per family whose values are counted
VALUES = 50                  # values counted per label, at most ("50+")
MAX_META = 3                 # metrics per family whose metadata is asked
SAMPLE = 10                  # series listed per family to pick the sampled ones from
PICKS = 3                    # series whose raw samples judge its kind
NAMES = 1000                 # names listed per selector, at most
WINDOW_S = 3600.0
DEADLINE_S = 120.0
PER_FAMILY = 2 + MAX_LABELS + MAX_META + 1      # labels, series, values, metadata, raw


def cost(spec: SourceSpec, families: int) -> int:
    """The most requests a survey of ``families`` families may make: what is checked against the
    daily cap before anything is sent, and the call's budget."""
    return len(spec.explore) + len(spec.match) + families * PER_FAMILY


def reads_as(kind: str) -> str:
    return "flow" if kind == "counter" else "level" if kind == "gauge" else "neither" if kind in UNREAD else kind


def _names(src: PrometheusSource, sels: list[str], start: float, end: float, notes: list[str]) -> dict[str, str]:
    """name -> the first selector it was listed under."""
    out: dict[str, str] = {}
    for sel in sels:
        got = src.names([sel], start, end, limit=NAMES + 1)
        if len(got) > NAMES:
            notes.append(f"{sel}: more than {NAMES} names; the first {NAMES} listed (narrow it with --family)")
        for n in got[:NAMES]:
            out.setdefault(n, sel)
    return out


def _kind(src: PrometheusSource, fam: Family, sel: str, sets: list[dict], meta: dict, start: float, end: float,
          until: float) -> tuple[str, str, str]:
    """(kind, counter form, why), as inference would read it from a few sampled series."""
    typ = (meta.get(fam.first_metric()) or {}).get("type")
    picked, n = pick(fam.first_metric(), sets, PICKS)
    raw, bad = census.raw(src, {fam.name: (conjoined(picked, [sel]), n)}, start, end, until, 1)
    if fam.name in bad:
        return fam.kind, fam.counter_form, f"its samples could not be read ({bad[fam.name]}): kept as its type and name say"
    series = raw.get(fam.name) or []
    if fam.kind == "rollup" or fam.counter_form:
        return fam.kind, fam.counter_form, fam.retyped or fam.help or ""
    if said := convention(fam.first_metric(), typ, fam.help, series):
        return said
    kind, why = classify(fam.first_metric(), "counter" if fam.kind == "counter" else typ, fam.help, series)
    if kind:
        return ("counter", "delta", why) if kind == "delta" else (kind, "", why)
    return fam.kind, fam.counter_form, (f"typed {typ}" if typ else "by its name") + (f", {len(series)} series sampled" if series else ", no samples in the window")


def _family(src: PrometheusSource, spec: SourceSpec, fam: Family, sel: str, start: float, end: float, until: float) -> dict:
    one = conjoined(fam.first_metric(), [sel])
    names = [x for x in src.label_names([one], start, end, MAX_LABELS * 4) if x not in SKIP_LABELS]
    labels = {}
    for lab in names[:MAX_LABELS]:
        vals = src.label_values(lab, [one], start, end, VALUES + 1)
        labels[lab] = {"values": min(len(vals), VALUES), "more": len(vals) > VALUES, "first": vals[:3]}
    meta = src.metadata(list(fam.metrics)[:MAX_META])
    sets = [{k: v for k, v in s.items() if k != "__name__"} for s in src.series([one], start, end, limit=SAMPLE, narrow=False)]
    md = meta.get(fam.first_metric()) or {}
    fam.help = fam.help or md.get("help") or None
    kind, form, why = _kind(src, fam, sel, sets, meta, start, end, until)
    fam.kind, fam.counter_form, fam.retyped = kind, form, why
    declared([fam], spec.kinds)
    return {"labels": labels, "labels_more": max(0, len(names) - MAX_LABELS), "type": md.get("type"), "unit": md.get("unit") or fam.unit,
            "help": fam.help, "kind": fam.kind, "form": fam.counter_form, "reads_as": reads_as(fam.kind), "why": fam.retyped or "",
            "declared": fam.declared_by or None, "series_sampled": len(sets)}


def explore(state_dir: Path, spec: SourceSpec, *, family: str | None = None, limit: int | None = None,
            minutes: float | None = None, now: float | None = None) -> dict:
    """The survey (the module's docstring), as a dict: ``families`` (surveyed, outside the match
    first), ``not_surveyed`` (the families past ``limit``), ``requests``, ``notes``; with
    ``refused`` (and nothing sent) when the daily cap would be passed, ``error`` when a read failed."""
    n = max(1, min(int(limit or LIMIT), MAX_FAMILIES))
    end = (time.time() if now is None else now) - spec.settle
    start = end - (WINDOW_S if not minutes or minutes <= 0 else min(86400.0, minutes * 60))
    out: dict = {"source": spec.name, "explore": list(spec.explore), "match": list(spec.match), "family": family, "limit": n,
                 "window": [round(start, 3), round(end, 3)], "families": [], "not_surveyed": [], "notes": [], "requests": 0}
    store = for_store(spec)
    need = cost(spec, n)
    p = store.peek()
    if p.get("per_day") and p["today"] + need > p["per_day"]:
        why = (f"the store has made {p['today']} of its {p['per_day']} requests today and this survey may need {need}: "
               f"not sent; {resets()}, or ask for fewer families (--limit)")
        reqlog.append(state_dir, spec.name, {"endpoint": "explore", "query": list(spec.explore), "window": out["window"],
                                             "series": None, "points": None, "ms": 0, "by": BY, "sent": False, "error": why})
        return {**out, "refused": why}
    budget = Budget(need, time.monotonic() + DEADLINE_S, "this survey")
    wide = PrometheusSource(replace(spec, match=list(spec.explore)), store, log_dir=state_dir, by=BY)
    narrow = PrometheusSource(spec, store, log_dir=state_dir, by=BY)
    wide.budget = narrow.budget = budget
    try:
        found = _names(wide, spec.explore, start, end, out["notes"])
        if family:
            found = {k: v for k, v in found.items() if fnmatchcase(k, family)}
        matched = set(_names(narrow, spec.match, start, end, out["notes"]))
        fams = _group({k: [] for k in found}, {})
        inside = {f.name: any(m in matched for m in f.metrics) for f in fams}
        fams.sort(key=lambda f: (inside[f.name], f.name))
        out["names"] = len(found)
        out["not_surveyed"] = [{"family": f.name, "in_match": inside[f.name]} for f in fams[n:]]
        for f in fams[:n]:
            row = {"family": f.name, "metrics": sorted(f.metrics), "in_match": inside[f.name], "under": found[f.first_metric()]}
            try:
                row.update(_family(wide, spec, f, found[f.first_metric()], start, end, budget.until))
            except (DailyCap, PastDeadline):
                raise
            except (SourceError, Refused) as e:
                row.update(kind="unknown", reads_as="neither", why=f"could not be read: {e}", labels={})
            out["families"].append(row)
    except DailyCap as e:
        out["error"] = f"{e}; {resets()}"
    except (SourceError, Refused) as e:
        out["error"] = str(e)
    out["requests"] = wide.requests + narrow.requests
    return out


def table(out: dict) -> list[str]:
    """The survey as text: a row per family surveyed, the rest named."""
    head = (f"{out['source']}: explore {', '.join(out['explore'])} beyond match {', '.join(out['match'])}"
            + (f", families {out['family']}" if out.get("family") else ""))
    if out.get("refused"):
        return [head, f"  REFUSED: {out['refused']}"]
    lines = [head, (f"  {out.get('names', 0)} names; {len(out['families'])} famil{'y' if len(out['families']) == 1 else 'ies'} "
                    f"surveyed in {out['requests']} requests (logged by explore)")]
    cols = ("family", "in match", "kind", "reads as", "type", "labels (values)", "why")
    rows = [(r["family"], "yes" if r["in_match"] else "no", r.get("kind", "?") + (f" ({r['form']})" if r.get("form") else ""),
             r.get("reads_as", "?") + (f" (declared by {r['declared']})" if r.get("declared") else ""), r.get("type") or "-",
             ", ".join(f"{k}={v['values']}{'+' if v['more'] else ''}" for k, v in (r.get("labels") or {}).items())
             + (f", +{r['labels_more']} more" if r.get("labels_more") else "") or "-", r.get("why") or "") for r in out["families"]]
    w = [max(len(c), *(len(x[i]) for x in rows)) if rows else len(c) for i, c in enumerate(cols[:-1])]
    lines.append("  " + "  ".join(c.ljust(w[i]) for i, c in enumerate(cols[:-1])) + "  " + cols[-1])
    lines += ["  " + "  ".join(x[i].ljust(w[i]) for i in range(len(w))) + "  " + x[-1] for x in rows]
    if out["not_surveyed"]:
        lines.append(f"  not surveyed ({len(out['not_surveyed'])}, past --limit {out['limit']}): "
                     + ", ".join(f"{x['family']}{' (in match)' if x['in_match'] else ''}" for x in out["not_surveyed"][:20])
                     + (" …" if len(out["not_surveyed"]) > 20 else ""))
    lines += [f"  note: {x}" for x in out["notes"]]
    if out.get("error"):
        lines.append(f"  STOPPED: {out['error']}")
    return lines
