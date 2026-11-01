"""The Dynamics page's ``model.intended`` (§6.1, frames D1–D3): the expected set, the marks, what
was removed, the Changes panel's rows, the suggestions' groups and each part's key (``keys``:
``{stocks: {id: key}, flows: {id: key}}``, so the page never makes a key itself), for one discovered model
against a base version (``since``: the previous version by default, ``off`` for no marks, or any
version). Browsing a past ``vN`` pairs it with the ``dN`` current when ``vN`` was saved.

The latest discovery is shown as the newest saved version ``vN`` when its structure is that
version's (its base ``vN-1``, labelled ``vN``); otherwise it is an unsaved discovery, compared
with ``vN`` by default and labelled "the latest discovery", so an absence is never said of a
version that has the part.

Structure comes from the cached diff (``diff.py``); every metrics fact is read now, under a time
limit (``facts.py``)."""

from __future__ import annotations

from ..discover import structure
from . import diff as diffs
from .expected import flow_entry, level_entry, mark_entry, target_of
from .facts import LIMIT_S, Facts
from .keys import Keys
from .params import OFF, since_of

LATEST = "the latest discovery"
_structures: dict[tuple[str, int], list] = {}


def _rate(flow) -> str | None:
    q = (flow.current().quality if flow and flow.current() else None) or {}
    if q.get("events") is None or not q.get("live_minutes"):
        return None
    return f"{q['events'] / q['live_minutes']:.2f} /min"


def _machines(flow) -> list[dict]:
    hyps = ((flow.evidence or {}).get("machines") or {}).get("hypotheses") or []
    return [{"machine": h.get("machine"), "confidence": h.get("confidence")} for h in hyps]


def _saved_structure(models, n: int):
    """A saved version's structure (cached: a saved version never changes)."""
    ck = (str(models.dir), n)
    if ck not in _structures:
        m = models.load(n)
        if m is None:
            return None
        _structures[ck] = structure(m)
        if len(_structures) > 1024:
            _structures.pop(next(iter(_structures)))
    return _structures[ck]


def unsettled_of(status: dict, shown: Keys, ignored: dict, expected: set) -> list[dict]:
    """The unsettled suggestions (§3.3): a key whose history makes it a suggestion, in the shown
    model, neither ignored nor expected; each with its id and the version its run began."""
    return [{"part": p, "key": k, "id": shown.of(p).get(k), "since": s.get("since")}
            for p in ("stock", "flow") for k, s in sorted(status[p].items())
            if s["status"] == "suggestion" and k in shown.of(p) and k not in ignored and k not in expected]


def resolve(models, nums: list[int], version: int | None, live: bool, since, model=None) -> tuple[int | None, int | None, str]:
    """(the shown version's number, or None for an unsaved discovery; the base's number, or None
    for no marks; the shown model's label). ``nums``: the saved versions' numbers."""
    newest = nums[-1] if nums else None
    if live:
        same = newest is not None and model is not None and structure(model) == _saved_structure(models, newest)
        shown = newest if same else None
    else:
        shown = version if version is not None else newest
    label = f"v{shown}" if shown else LATEST
    base = since_of(since, nums)
    if base == OFF:
        return shown, None, label
    if base is not None:
        return shown, base, label
    if shown is None:
        return None, newest, label
    prev = [n for n in nums if n < shown]
    return shown, (prev[-1] if prev else None), label


def dynamics_block(intended, model=None, since=None, *, hold: int, version: int | None = None, live: bool | None = None,
                   stamp: float | None = None, metrics=None, limit_s: float = LIMIT_S, now: float | None = None,
                   d: int | None = None) -> dict:
    """The ``intended`` block for ``model`` (default: the latest discovery, else the current
    version). ``version``: the saved version ``model`` is (None with ``live``). ``hold``: the
    project's ``[discovery] announce_hold``, which suggestions settle by."""
    models = intended.models
    saved_list = models.versions()
    nums = [v["version"] for v in saved_list]
    if model is None:
        cached = models.latest_discovery()
        if cached:
            stamp, model = cached
            live = True if live is None else live
        else:
            model, version, live = models.load(), (nums[-1] if nums else None), False
    live = bool(live) if live is not None else version is None
    shown_n, base_n, label = resolve(models, nums, version, live, since, model)
    saved = {v["version"]: v for v in saved_list}
    past = version is not None and not live and version != max(saved, default=None)
    if d is None:
        d = intended.at((saved.get(version) or {}).get("saved_at")) if past else (intended.current_version() or 0)
    layer = intended.read(d)["layer"]
    shown = Keys(model)
    base_model = models.load(base_n) if base_n else None
    base = Keys(base_model) if base_model is not None else None
    v = "live" if shown_n is None else shown_n
    st = diffs.cached(intended, d, v, base_n if base is not None else None, model.era if model else None, shown, base, layer,
                      hold, models, stamp, nums)
    facts = Facts(metrics, limit_s, now, project=getattr(getattr(intended, "project", None), "key", None))
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
    suggestions = unsettled_of(status, shown, ignored, expected_keys)
    for part in ("stock", "flow"):
        rowed = set()
        for key in st["new"][part]:
            s = status[part].get(key) or {}
            if s.get("status") == "settled" or key in ignored:
                continue
            pid = shown.of(part).get(key)
            put(part, pid, "new")
            rowed.add(key)
            changes.append({"sign": "+", "part": part, "key": key, "id": pid, "status": "new", "since": shown_n,
                            "why": f"new in {label}", "controls": ["unexpect", "ignore"] if key in expected_keys else ["expect", "ignore"]})
        for sg in suggestions:                   # unsettled, though not new against this base: listed until answered
            if sg["part"] != part or sg["key"] in rowed:
                continue
            if base is not None:
                put(part, sg["id"], "new")
            changes.append({"sign": "+", "part": part, "key": sg["key"], "id": sg["id"], "status": "suggestion", "since": sg["since"],
                            "why": f"new in v{sg['since']}" if sg["since"] else f"new in {LATEST}", "controls": ["expect", "ignore"]})
    removed = {"stocks": [], "flows": []}
    for key in st["removed"]["stock"]:
        sid = base.stocks.get(key)
        s = next((x for x in base_model.stocks if x.id == sid), None)
        sim = {"simulated": True} if s is not None and (s.evidence or {}).get("simulated") else {}
        removed["stocks"].append({"key": key, "id": sid, "name": s.name if s else sid, "in": base_n, **sim})
        changes.append({"sign": "-", "part": "stock", "key": key, "id": sid, "in": base_n, **sim})
    for key in st["removed"]["flow"]:
        fid = base.flows.get(key)
        f = next((x for x in base_model.flows if x.id == fid), None)
        sim = {"simulated": True} if f is not None and (f.evidence or {}).get("simulated") else {}
        removed["flows"].append({"key": key, "id": fid, "from": f.src if f else None, "to": f.dst if f else None,
                                 "rate": _rate(f), "machines": _machines(f) if f else [], "in": base_n, **sim})
        changes.append({"sign": "-", "part": "flow", "key": key, "id": fid, "in": base_n, **sim})
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
    targets = [{"part": t["part"], "key": k, "id": shown.of("flow" if t["part"] == "flow" else "stock").get(k),
                "target": next((e["target"] for e in entries if e.get("key") == k and e.get("target")), None)
                or target_of(t["target"], t["part"], k, shown, facts)}
               for k, t in sorted(layer["targets"].items())]
    return {"version": d, "shown": shown_n, "live": live, "since": base_n if base is not None else None,
            "since_saved_at": (saved.get(base_n) or {}).get("saved_at") if base is not None else None,
            "expected": entries, "marks": marks, "removed": removed, "changes": changes, "came_and_went": went,
            "ignored": ign, "settled": sum(1 for p in ("stock", "flow") for k, s in status[p].items()
                                           if s["status"] == "settled" and k in shown.of(p)),
            "unsettled": len(suggestions), "stabilised": not suggestions, "suggestions": suggestions, "targets": targets,
            "predicted": [{**p, "id": shown.flows.get(p["key"]) if p["key"] else None} for p in diffs.predicted(layer, shown)],
            "keys": {"stocks": shown.stock_of_id, "flows": shown.flow_of_id}, "missing": facts.missing}
