"""Predictions and their verdicts as text, for ``orchestra sd predictions`` (``sd.predictions``,
``sd.judge``)."""

from __future__ import annotations

from datetime import UTC, datetime


def _when(t: float | None) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M") if t else "-"


def _dur(s: float) -> str:
    return f"{s / 3600:g}h" if s >= 3600 and s % 1800 == 0 else f"{s / 60:g}m" if s >= 60 else f"{s:g}s"


def expectation(e: dict) -> str:
    k = e["kind"]
    if k == "factor":
        return f"{e['flow']}{'.' + e['param'] if e.get('param') else ''} ×{e['factor']:g}"
    if k == "unchanged":
        return f"{e['flow']} unchanged"
    if k == "level":
        return " and ".join(f"{e['stock']} {w} {e[w]:g}" for w in ("below", "above") if w in e)
    if e.get("id") is None:
        return f"a new flow {e.get('from') or 'outside'} → {e.get('to') or 'outside'} {k}"
    return f"{e['part']} {e['id']} {k}"


def _status(s: dict) -> str:
    out = f"{expectation(s)}: {s['status']}"
    for n in s.get("params") or []:
        out += f"; {n['param']} {n['before']:.4g} → {n['after']:.4g}" + (f" (×{n['ratio']:g}" if n.get("ratio") is not None else " (")
        out += f", z {n['z']}" + (f"; predicted {n['predicted']:.4g}, z {n['z_predicted']}" if "predicted" in n else "") + ")"
    if law := s.get("law"):
        out += f"; its form changed: the old law expects {law['expected']:g} events, {law['events']:g} counted (z {law['z']})"
    if s.get("flow") and s["kind"] == "appears":
        out += f": {s['flow']}"
    if "level" in s:
        out += f"; mean level {s['level']:g}"
    if s.get("reason"):
        out += f" ({s['reason']})"
    return out


def verdict_lines(v: dict) -> list[str]:
    head = f"{v['verdict']}" + (f" (until era {v['interrupted_by']} began; the rules then say {v.get('partial') or 'nothing yet'})"
                                if v["verdict"] == "interrupted" else "")
    out = [head + ("  · made after its change began" if v.get("late") else "")]
    out += [f"  {_status(s)}" for s in v.get("expectations") or []]
    for u in v.get("unpredicted") or []:
        extra = f": {u['param']} {u['before']:.4g} → {u['after']:.4g} (z {u['z']})" if "param" in u else ""
        out.append(f"  not predicted: {u['part']} {u['id']} {u['status']}{extra}")
    st = v.get("stocks") or {}
    if st.get("rows"):
        out.append(f"  stocks against the {'predicted' if st['from'] == 'prediction' else 'simulated'} run: "
                   + "; ".join(f"{r['stock']} {r['level']:.4g} against {r['central']:.4g} (z {r['z']}{', out' if r['out'] else ''})" for r in st["rows"]))
    elif st.get("reason"):
        out.append(f"  stocks not simulated ({st['reason']})")
    fc = v.get("false_change") or {}
    if fc:
        m = (f"measured {fc['measured']:.0%} of {fc['flows']} flows in the previous era's two halves, {fc['expected']:g} expected here"
             if fc.get("measured") is not None else f"not measured ({fc.get('reason')})")
        out.append(f"  a number changed at |z| ≥ {fc['z']:g}; false changes: {fc['nominal']:.2%} a number nominally, {m}")
    return out


def lines(predictions: list[dict], eras: list) -> list[str]:
    if not predictions:
        return [("no predictions yet: a machine records one before its change (orchestra.prediction.made; "
                 "`orchestra sd predict`; sd.predictions.Predictions)")]
    by_era = {e.cause: e for e in eras if e.cause}
    groups: dict[str, list[dict]] = {}
    for p in predictions:
        era = by_era.get(p.get("change"))
        groups.setdefault(era.id if era else "", []).append(p)
    out = []
    for e in [*eras, None]:
        ps = groups.get(e.id if e else "")
        if not ps:
            continue
        out.append(f"era {e.id}, from {_when(e.start)}: {e.label}" if e else "not yet matched (their change has not begun an era):")
        for p in ps:
            if p["status"] == "invalid":
                out.append(f"  {p['id']} from {p.get('source')}, made {_when(p.get('made_at'))}: invalid: {p['why']}")
                continue
            what = ", ".join(expectation(x) for x in p["expect"]) or "nothing changes (the null test)"
            out.append(f"  {p['id']} from {p.get('source')}, made {_when(p.get('made_at'))}, change {p['change']}, "
                       f"horizon {_dur(p['horizon_s'])}: {what}")
            if p["status"] == "judged":
                out += [f"    {x}" for x in verdict_lines(p["verdict"])]
            else:
                due = (e.start + p["horizon_s"]) if e else None
                out.append(f"    waiting{' until ' + _when(due) if due else ' for its change'}")
    return out
