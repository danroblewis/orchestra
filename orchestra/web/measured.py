"""Instruments attached to declared machines, on the Machines and Instruments pages
(docs/proposals/instruments-on-machines.md §3): the web server's background read of what each
attachment selects, and what ``/api/machines`` and ``/api/instruments`` derive from it on read.

**The read** (``read_all``), every ``EVERY_S`` and at once when the declared layer changes, under a
time limit, as counted traffic is (``traffic.py``): an own instrument's series through
``MetricsStore.recent`` (``sd.intended.measured.read_own``); a source's through the sources'
catalogue, from the source's cached definitions over the last ``traffic.READ_S``, in the web
server's share of the store's rate (``Catalogue.selected``); never copied into the metrics store
(rule 5). So a source's series is measured for the hour it was read over: a source's points are a
query's steps, not the times it was written. An attachment whose read failed, or that is newer
than the last read, has "series unknown".

**On read** (``merge_machines``, ``hung_on``): each declared machine gains ``measured``
(``machine_measured``: ``attachments``, ``measured``, ``last_measured``, ``instances``,
``instruments``, ``unknown``) and ``comparison`` (``heard``, "measured, never heard", "attached,
nothing measured", "declared, neither heard nor measured", or "series unknown"); every other
machine has ``measured: null``. Being measured never makes a machine seen or active: ``last_seen``
and ``active`` are the bus's and counted traffic's alone (AGENTS.md rule 2). Each instrument on
the Instruments page gains ``hung_on``: the declared machines its attachments name, with their
matches and whether two machines select one series (``shared``)."""

from __future__ import annotations

import time

from ..sd.intended import measured as m
from ..sd.intended.attach import parse
from ..sd.intended.facts import within
from ..sd.intended.instruments import Instruments
from .traffic import READ_S, READ_STEP_S

EVERY_S = 60.0
LIMIT_S = 10.0          # one read of the own store, all attachments told


def read_all(project, metrics, catalogue, layer: dict, now: float | None = None) -> dict:
    """Every attachment's series: ``{"at", "series": {id: [(name, labels, points)] | None}, "errors"}``."""
    now = time.time() if now is None else now
    kinds = Instruments(project).kinds()
    atts = list(layer.get("attachments", {}).values())
    series: dict[str, list | None] = {}
    errors: dict[str, str] = {}
    own = [a for a in atts if kinds.get(a["instrument"]) not in ("source", None)]
    if own:
        got, ok = within(lambda: {a["id"]: m.read_own(metrics, project.key, a, now) for a in own}, LIMIT_S)
        if ok:
            series |= got
        else:
            errors["metrics"] = f"the metrics store did not answer within {LIMIT_S:g} s"
            series |= dict.fromkeys((a["id"] for a in own), None)
    for name in sorted({a["instrument"] for a in atts if kinds.get(a["instrument"]) == "source"}):
        mine = [a for a in atts if a["instrument"] == name]
        spec = next((s for s in catalogue.specs.sources if s.name == name), None) if catalogue is not None else None
        if spec is None:
            series |= dict.fromkeys((a["id"] for a in mine), None)
            continue
        prefixes = [parse(a.get("match"))[0].removeprefix(spec.series_prefix) for a in mine]
        try:
            got, why = catalogue.selected(name, lambda d, ps=prefixes: any(d.name.startswith(p) for p in ps),
                                          now - READ_S, now, READ_STEP_S)
        except Exception as e:  # noqa: BLE001 - that source's attachments are unknown, with why
            got, why = None, f"{type(e).__name__}: {e}"
        if why:
            errors[f"source {name}"] = why
        rows = None if got is None else [(r["name"], r["labels"], r["points"]) for r in got]
        series |= dict.fromkeys((a["id"] for a in mine), rows)
    return {"at": now, "series": series, "errors": errors}


def views(project, layer: dict, cache: dict | None, now: float | None = None) -> list[dict]:
    """Every attachment's view, from the last read (``attachment_view``), shared series marked."""
    now = time.time() if now is None else now
    ins = Instruments(project)
    kinds = ins.kinds()
    got = (cache or {}).get("series") or {}
    out = []
    for a in layer.get("attachments", {}).values():
        kind = kinds.get(a["instrument"])
        aliases, strip = None, ""
        if kind == "source" and (spec := ins.source(a["instrument"])) is not None:
            aliases, strip = spec.aliases(), spec.series_prefix
        out.append(m.attachment_view(a, got.get(a["id"]), now, kind or "unknown", project.config.max_instances, aliases, strip))
    m.mark_shared(out)
    return out


def merge_machines(out: dict, project, layer: dict, cache: dict | None, now: float | None = None) -> None:
    """``measured`` and ``comparison`` on each machine of an ``/api/machines`` answer, in place."""
    vs = views(project, layer, cache, now)
    for mach in out.get("machines") or []:
        intent = mach.get("intent")
        if intent is None:
            mach.setdefault("measured", None)
            mach.setdefault("comparison", None)
            continue
        mine = m.machine_measured([v for v in vs if v["machine"] == mach["id"]])
        mach["measured"] = mine
        mach["comparison"] = m.comparison(bool(intent.get("heard")), mine)
    if cache and cache.get("errors"):
        out["measured_errors"] = cache["errors"]


def hung_on(instruments: list[dict], project, layer: dict, cache: dict | None, now: float | None = None) -> None:
    """``hung_on`` on each instrument row: the declared machines its attachments name."""
    vs = views(project, layer, cache, now)
    for row in instruments:
        row["hung_on"] = [{"machine": v["machine"], "attachment": v["id"], "state": v["state"], "match": v["match"],
                           "shown": v["shown"], "instance_label": v["instance_label"], "status": v["status"],
                           "series": None if v["series"] is None else len(v["series"]), "shared": v.get("shared", False),
                           "shared_with": sorted({o for r in v["series"] or [] for o in r.get("shared_with", [])})}
                          for v in vs if v["instrument"] == row.get("name")]
