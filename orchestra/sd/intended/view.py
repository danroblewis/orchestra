"""The Dynamics page's ``model.intended`` (§6.1, frames D1–D3): the expected set, the marks, what
was removed, the Changes panel's rows, and the suggestions' groups, for one discovered model
against a base version (``since``: the previous version by default, ``off`` for no marks, or any
version). Browsing a past ``vN`` pairs it with the ``dN`` current when ``vN`` was saved.

Structure comes from the cached diff (``diff.py``); every metrics fact is read now, under a time
limit (``facts.py``)."""

from __future__ import annotations

from . import diff as diffs
from .expected import flow_entry, level_entry, mark_entry, target_of
from .facts import LIMIT_S, Facts
from .keys import Keys

HOLD = 3


def _rate(flow) -> str | None:
    q = (flow.current().quality if flow and flow.current() else None) or {}
    if q.get("events") is None or not q.get("live_minutes"):
        return None
    return f"{q['events'] / q['live_minutes']:.2f} /min"


def _machines(flow) -> list[dict]:
    hyps = ((flow.evidence or {}).get("machines") or {}).get("hypotheses") or []
    return [{"machine": h.get("machine"), "confidence": h.get("confidence")} for h in hyps]


def resolve(models, version: int | None, live: bool, since) -> tuple[int | None, int | None]:
    """(the shown version's number, the base's number or None for no marks)."""
    nums = [v["version"] for v in models.versions()]
    shown = version if version is not None else (nums[-1] if nums else None)
    if since in ("off", "none", False):
        return shown, None
    if since is not None and since != "":
        return shown, int(since)
    prev = [n for n in nums if shown is not None and n < shown]
    return shown, (prev[-1] if prev else None)


def dynamics_block(intended, model=None, since=None, *, version: int | None = None, live: bool | None = None,
                   stamp: float | None = None, metrics=None, hold: int = HOLD, limit_s: float = LIMIT_S, now: float | None = None,
                   d: int | None = None) -> dict:
    """The ``intended`` block for ``model`` (default: the latest discovery, else the current
    version). ``version``: the saved version ``model`` is (None with ``live``)."""
    models = intended.models
    if model is None:
        cached = models.latest_discovery()
        if cached:
            stamp, model = cached
            live = True if live is None else live
        else:
            model, version, live = models.load(), models.current_version(), False
    live = bool(live) if live is not None else version is None
    shown_n, base_n = resolve(models, version, live, since)
    saved = {v["version"]: v for v in models.versions()}
    past = version is not None and not live and version != max(saved, default=None)
    if d is None:
        d = intended.at((saved.get(version) or {}).get("saved_at")) if past else (intended.current_version() or 0)
    layer = intended.read(d)["layer"] if d else intended.read(0)["layer"]
    shown = Keys(model)
    base_model = models.load(base_n) if base_n else None
    base = Keys(base_model) if base_model is not None else None
    v = "live" if live else shown_n
    st = diffs.cached(intended, d, v, base_n if base is not None else None, model.era if model else None, shown, base, layer,
                      hold, models, stamp)
    facts = Facts(metrics, limit_s, now)
    label = f"v{shown_n}" if shown_n else "this discovery"
    status = st["status"]
    ignored = layer["marks"]["ignored"]
    expected_keys = set(layer["marks"]["expected"])
    entries, marks = [], {"stocks": {}, "flows": {}}

    def put(part, pid, mark):
        if pid:
            marks["stocks" if part == "stock" else "flows"].setdefault(pid, [])
            if mark not in marks["stocks" if part == "stock" else "flows"][pid]:
                marks["stocks" if part == "stock" else "flows"][pid].append(mark)

    for row in st["expected"]:
        if row.get("mark"):
            mk = layer["marks"]["expected"][row["key"]]
            tgt = (layer["targets"].get(row["key"]) or {}).get("target")
            entries.append(mark_entry(mk, row, shown, facts, status[mk["part"]].get(row["key"]), tgt, label))
            if row["present"]:
                put(mk["part"], shown.of(mk["part"]).get(row["key"]), "expected")
        elif row["part"] == "flow":
            entries.append(flow_entry(layer["flows"][row["id"]], row, shown, facts, label))
            if row["present"]:
                put("flow", shown.flows.get(row["key"]), "expected")
        else:
            el = layer["stocks" if row["part"] == "stock" else "effects"][row["id"]]
            entries.append(level_entry(el, row, shown, facts, label))
            if row["present"]:
                put("stock", shown.stocks.get(row["key"]), "expected")
    changes = []
    for part in ("stock", "flow"):
        for key in st["new"][part]:
            s = status[part].get(key) or {}
            if s.get("status") == "settled" or key in ignored:
                continue
            pid = shown.of(part).get(key)
            put(part, pid, "new")
            changes.append({"sign": "+", "part": part, "key": key, "id": pid, "status": "new", "since": shown_n,
                            "why": f"new in {label}", "controls": ["unexpect", "ignore"] if key in expected_keys else ["expect", "ignore"]})
    removed = {"stocks": [], "flows": []}
    for key in st["removed"]["stock"]:
        sid = base.stocks.get(key)
        s = next((x for x in base_model.stocks if x.id == sid), None)
        removed["stocks"].append({"key": key, "id": sid, "name": s.name if s else sid, "in": base_n})
        changes.append({"sign": "-", "part": "stock", "key": key, "id": sid, "in": base_n})
    for key in st["removed"]["flow"]:
        fid = base.flows.get(key)
        f = next((x for x in base_model.flows if x.id == fid), None)
        removed["flows"].append({"key": key, "id": fid, "from": f.src if f else None, "to": f.dst if f else None,
                                 "rate": _rate(f), "machines": _machines(f) if f else [], "in": base_n})
        changes.append({"sign": "-", "part": "flow", "key": key, "id": fid, "in": base_n})
    for e in entries:
        if not e["present"]:
            changes.append({"sign": "o", "part": e["part"], "id": e.get("id"), "key": e.get("key"), "why": e.get("why"),
                            "candidates": e.get("candidates") or []})
    for part in ("stock", "flow"):
        for pid in (shown.stocks if part == "stock" else shown.flows).values():
            obj = next((x for x in (model.stocks if part == "stock" else model.flows) if x.id == pid), None)
            if obj is not None and (obj.evidence or {}).get("simulated"):
                put(part, pid, "simulated")
    went = [{"part": p, "key": k, "versions": s["versions"], "last": s.get("last")}
            for p in ("stock", "flow") for k, s in sorted(status[p].items()) if s["status"] == "came_and_went" and k not in ignored]
    ign = [{"part": mk["part"], "key": k, "id": shown.of(mk["part"]).get(k), "present": k in shown.of(mk["part"]),
            "provenance": mk["provenance"]} for k, mk in sorted(ignored.items())]
    unsettled = [k for p in ("stock", "flow") for k, s in status[p].items()
                 if s["status"] == "suggestion" and k not in ignored and k not in expected_keys]
    targets = [{"part": t["part"], "key": k, "id": shown.of("flow" if t["part"] == "flow" else "stock").get(k),
                "target": next((e["target"] for e in entries if e.get("key") == k and e.get("target")), None)
                or target_of(t["target"], t["part"], k, shown, facts)}
               for k, t in sorted(layer["targets"].items())]
    return {"version": d, "shown": shown_n, "live": live, "since": base_n if base is not None else None,
            "since_saved_at": (saved.get(base_n) or {}).get("saved_at") if base is not None else None,
            "expected": entries, "marks": marks, "removed": removed, "changes": changes, "came_and_went": went,
            "ignored": ign, "settled": sum(1 for p in ("stock", "flow") for k, s in status[p].items()
                                           if s["status"] == "settled" and k in shown.of(p)),
            "unsettled": len(unsettled), "stabilised": not unsettled, "targets": targets,
            "predicted": [{**p, "id": shown.flows.get(p["key"]) if p["key"] else None} for p in diffs.predicted(layer, shown)],
            "missing": facts.missing}
