"""Whether a declared machine is **measured**, and its measured **instances**: derived on read from
its attachments' series, never stored (docs/proposals/instruments-on-machines.md §2.1; P2 §5).

- A series (or one instance's series) is **measured** while its last point is within
  ``max(1 h, active_within(cadence))``, the cadence being ``orchestra/cadence.py``'s median gap
  over its last ``BEATS`` points: the rule bus activity uses, applied to points. Past its window it
  is **quiet**, listed, never dropped. Measured means data is arriving, not that the thing is up:
  the last value is shown (``pg_up = 0`` is measured).
- **Instances per attachment, never unioned**: the values of its instance label (replicas only),
  each measured or quiet; more than ``max_instances`` values list none ("N values: too many for
  instances"). The machine shows the largest measured count of its declared attachments, never a
  sum.
- Only a **declared** attachment makes the machine measured; a proposed one shows what it would
  select and counts for nothing until confirmed.

Being measured never makes a machine seen or active (AGENTS.md rule 2): nothing here touches
``last_seen`` or ``active``; ``last_measured`` is its own field.

``read_own`` reads an attachment's series from the project's own store (an instrument's points
carry ``instrument=<name>``) with ``MetricsStore.recent``; a source's are read by the web server's
background reader (``web/measured.py``) and handed in the same shape."""

from __future__ import annotations

import time

from ...cadence import ACTIVE_MARGIN, BEATS, DAY, active_within, gaps
from .attach import parse, selects, shown

FLOOR_S = 3600.0                         # measured for at least an hour after a point
SPAN_S = ACTIVE_MARGIN * DAY             # the longest window a cadence can give: how far back recent() reads
MAX_INSTANCES = 50
NOTHING = "attached, nothing measured"
NEITHER = "declared, neither heard nor measured"
MEASURED_NEVER_HEARD = "measured, never heard"
HEARD = "heard"
UNKNOWN = "series unknown"

Series = tuple[str, dict, list]          # (name, labels, points): what recent() answers


def window(points: list) -> float:
    """How long after its last point a series with these points is measured."""
    return max(FLOOR_S, active_within(gaps((t for t, _ in points), least=2)))


def read_own(metrics, project_key: str, att: dict, now: float | None = None) -> list[Series]:
    """An attachment's series in the own store: the instrument's points, narrowed by its match."""
    now = time.time() if now is None else now
    prefix, ms = parse(att.get("match"))
    want = [("instrument", "=", att["instrument"]), ("project", "=", project_key), *ms]
    return metrics.recent(prefix, want, since=now - SPAN_S, keep=BEATS)


def key(name: str, labels: dict) -> str:
    """A series' identity on the page: its name and labels."""
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{inner}}}"


def _series_row(name: str, labels: dict, pts: list, now: float) -> dict:
    t, v = pts[-1]
    return {"key": key(name, labels), "name": name, "labels": labels, "last": t, "value": v, "window_s": window(pts),
            "measured": now - t <= window(pts)}


def attachment_view(att: dict, series: list[Series] | None, now: float, kind: str | None = None,
                    cap: int = MAX_INSTANCES, aliases: dict | None = None, strip: str = "") -> dict:
    """One attachment on the page: what it is, the series it selects (``None``: the read failed or
    has not happened, "series unknown"), measured and quiet, and its instances."""
    out = {k: att.get(k) for k in ("id", "machine", "instrument", "match", "instance_label", "state", "pending", "provenance")}
    out.update(kind=kind, shown=shown(att.get("match")))
    if series is None:
        return {**out, "status": UNKNOWN, "series": None, "names": None, "instances": None, "last_measured": None,
                "measured": False, "comparison": None}
    rows = [_series_row(n, lab, pts, now) for n, lab, pts in series
            if pts and selects(n, lab, att.get("match"), aliases, strip)]
    rows.sort(key=lambda r: r["key"])
    names: dict[str, int] = {}
    for r in rows:
        names[r["name"]] = names.get(r["name"], 0) + 1
    measured = any(r["measured"] for r in rows)
    out.update(series=rows, names=[{"name": n, "count": c} for n, c in sorted(names.items())],
               last_measured=max((r["last"] for r in rows), default=None), measured=measured,
               status="measured" if measured else ("quiet" if rows else "nothing"),
               comparison=None if measured else (NOTHING if att.get("state") == "declared" else None),
               instances=_instances(rows, att.get("instance_label"), cap, aliases))
    return out


def _instances(rows: list[dict], label: str | None, cap: int, aliases: dict | None) -> dict | None:
    if not label:
        return None
    from .attach import canonical

    by: dict[str, dict] = {}
    for r in rows:
        v = canonical(r["labels"], aliases).get(label)
        if not v:
            continue
        i = by.setdefault(v, {"value": v, "last": None, "last_value": None, "measured": False, "series": 0})
        i["series"] += 1
        i["measured"] = i["measured"] or r["measured"]
        if i["last"] is None or r["last"] > i["last"]:
            i["last"], i["last_value"] = r["last"], r["value"]
    if len(by) > cap:
        return {"label": label, "values": len(by), "too_many": True, "measured": None, "quiet": None, "list": None,
                "note": f"{len(by)} values: too many for instances"}
    listed = sorted(by.values(), key=lambda i: i["value"])
    return {"label": label, "values": len(by), "too_many": False, "measured": sum(i["measured"] for i in listed),
            "quiet": sum(not i["measured"] for i in listed), "list": listed, "note": None}


def mark_shared(views: list[dict]) -> None:
    """A series two machines' attachments both select is marked ``shared_with`` the others: the
    owner's statement (a host's CPU under both), not an error."""
    owners: dict[tuple[str, str], set[str]] = {}
    for v in views:
        for r in v.get("series") or []:
            owners.setdefault((v["instrument"], r["key"]), set()).add(v["machine"])
    for v in views:
        for r in v.get("series") or []:
            r["shared_with"] = sorted(owners[(v["instrument"], r["key"])] - {v["machine"]})
        v["shared"] = any(r["shared_with"] for r in v.get("series") or [])


def machine_measured(views: list[dict]) -> dict:
    """``measured`` on a declared machine: its attachments, when it was last measured and how many
    measured instances it has (the largest of its declared attachments', never a sum)."""
    declared = [v for v in views if v.get("state") == "declared"]
    lasts = [v["last_measured"] for v in declared if v.get("last_measured")]
    counts = [(v.get("instances") or {}).get("measured") or 0 for v in declared]
    return {"attachments": views, "measured": any(v.get("measured") for v in declared),
            "last_measured": max(lasts, default=None), "instances": max(counts, default=0),
            "instruments": sorted({v["instrument"] for v in views}),
            "unknown": any(v.get("status") == UNKNOWN for v in declared)}


def comparison(heard: bool, measured: dict | None) -> str:
    """The machine's entry in the comparison (P2 §6.1, P5 §3)."""
    if heard:
        return HEARD
    m = measured or {}
    if m.get("measured"):
        return MEASURED_NEVER_HEARD
    if m.get("unknown"):
        return UNKNOWN
    if any(v.get("state") == "declared" for v in m.get("attachments") or []):
        return NOTHING
    return NEITHER


__all__ = ["FLOOR_S", "NEITHER", "NOTHING", "SPAN_S", "attachment_view", "comparison", "machine_measured", "mark_shared",
           "read_own", "window"]
