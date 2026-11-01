"""The Machines page's declared layer (§6.1, frames E1–E3): each machine gains ``intent`` (``null``
when undeclared); a declared machine not yet heard is appended (``unseen: true``); a plugin's
placeholder never replaces an intent. The card's kind is the declared kind until the machine is
heard, then the announced one. A declaration never makes a machine exist in the observed layer
(rule 2 as amended): ``heard`` is whether its source (or an alias) is on the bus, read now.

The top level gains ``intended_edges`` (``{from, to, kind, state, observed, gone}``) and
``intended_types`` (declared event types and their descriptions)."""

from __future__ import annotations

import re

from .requests import unanswered

ENVELOPE = ("title", "description", "tags", "kind", "managed", "engagement", "receives", "emits", "reads", "spec")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _label(edit: dict, names: dict[str, str]) -> str:
    for part in ("stock", "flow", "loop"):
        if part in edit:
            n = names.get(edit[part], edit[part])
            if edit.get("rises"):
                return f"{n} ↑"
            if edit.get("falls"):
                return f"{n} ↓"
            if "factor" in edit:
                return f"{n} ×{edit['factor']:g}"
            if edit.get("appears"):
                return f"{n} appears"
            if edit.get("disappears"):
                return f"{n} disappears"
            if edit.get("unchanged"):
                return f"{n} unchanged"
            if "below" in edit or "above" in edit:
                return f"{n} {'below ' + format(edit['below'], 'g') if 'below' in edit else 'above ' + format(edit['above'], 'g')}"
            return n
    return f"{names.get(edit.get('from'), edit.get('from') or 'outside')} → {names.get(edit.get('to'), edit.get('to') or 'outside')} appears"


def expected_effect(m: dict, layer: dict, model, predictions: dict[str, dict]) -> dict | None:
    """A machine's draft prediction, each edit with its label, link and whether it can be
    published yet (an edit on a declared stock with no ``found_as`` waits for a series)."""
    ee = m.get("expected_effect")
    if not ee:
        return None
    names = {s.id: s.name for s in (model.stocks if model else [])} | {f.id: f.name for f in (model.flows if model else [])}
    names |= {k: v["name"] for g in ("stocks", "effects") for k, v in layer[g].items()}
    edits = []
    for e in ee["edits"]:
        row = {"edit": e, "label": _label(e, names), "publishable": True, "why": None}
        sid = e.get("stock")
        if sid is not None:
            row["link"] = f"/dynamics#s:{sid}"
            decl = layer["stocks"].get(sid) or layer["effects"].get(sid)
            if decl is not None and not decl.get("found_as"):
                row.update(publishable=False, why="waits for a series")
            elif decl is None and sid not in names:
                row.update(publishable=False, why="not in the model")
        elif e.get("flow") is not None:
            row["link"] = f"/dynamics#f:{e['flow']}"
        else:
            row["link"] = "/dynamics"
            for end in (e.get("from"), e.get("to")):
                d = layer["stocks"].get(end) if end else None
                if d is not None and not d.get("found_as"):
                    row.update(publishable=False, why="waits for a series")
        edits.append(row)
    pid = ee.get("prediction")
    p = predictions.get(pid) if pid else None
    return {"horizon_s": ee["horizon_s"], "prediction": pid, "status": (p or {}).get("status"),
            "verdict": ((p or {}).get("verdict") or {}).get("verdict"), "edits": edits}


def intent_of(m: dict, layer: dict, heard: bool, requested: dict | None, model, predictions: dict) -> dict:
    out = {"state": m["state"], "author": (m.get("provenance") or {}).get("author"), "heard": heard,
           **{k: m.get(k) for k in ENVELOPE}, "guessed": m.get("guessed") or [], "pending": m.get("pending") or [],
           "requested": requested, "aliases": m.get("aliases") or [],
           "expected_effect": expected_effect(m, layer, model, predictions), "provenance": m.get("provenance"),
           "latest": m.get("latest"), "change": m.get("change"),
           "attachments": [{k: a.get(k) for k in ("id", "instrument", "match", "instance_label", "state", "pending", "provenance")}
                           for a in layer["attachments"].values() if a["machine"] == m["id"]]}
    return out


def merge(out: dict, intended, model=None, predictions: list[dict] | None = None) -> None:
    """Add the declared layer to an ``/api/machines`` answer in place."""
    layer = intended.read()["layer"]
    preds = {p.get("id"): p for p in predictions or []}
    asked = unanswered(intended)
    machines = out.setdefault("machines", [])
    by_id = {m["id"]: m for m in machines}
    observed_ids = {m["id"] for m in machines if not m.get("unseen")}
    for m in machines:
        m.setdefault("intent", None)
    observed_edges = {(e.get("from"), e.get("to"), e.get("kind")) for e in out.get("edges") or []}
    edges = []
    for mid, m in layer["machines"].items():
        names = [mid, *(m.get("aliases") or [])]
        seen = next((by_id[n] for n in names if n in observed_ids), None)
        heard = seen is not None
        intent = intent_of(m, layer, heard, asked.get(("machine", mid)), model, preds)
        if not heard:
            intent["alias_candidates"] = sorted(o for o in observed_ids if o != mid and o not in layer["machines"]
                                                and (_norm(o) == mid or _norm(o.rsplit(".", 1)[-1]) == mid))
        if heard:
            seen["intent"] = intent
        elif mid in by_id:                       # a plugin's placeholder: the declaration stands, and its kind
            by_id[mid].update(intent=intent, kind=m["kind"], unseen=True)
        else:
            machines.append({"id": mid, "bootstrap": False, "mode": (m.get("engagement") or {}).get("mode"), "kind": m["kind"],
                             "package": None, "about": {}, "unseen": True, "publishes": [], "subscribes": list(m.get("receives") or []),
                             "flows": [], "logs": [], "instances": [], "first_seen": None, "last_seen": None, "active": False,
                             "intent": intent})
        removed = (m.get("latest") or {}).get("removed") or {}
        for t in m.get("receives") or []:
            edges.append({"from": t, "to": mid, "kind": "subscribes", "state": m["state"],
                          "observed": any((t, n, "subscribes") in observed_edges for n in names), "gone": False})
        for t in m.get("emits") or []:
            edges.append({"from": mid, "to": t, "kind": "publishes", "state": m["state"],
                          "observed": any((n, t, "publishes") in observed_edges for n in names), "gone": False})
        edges += [{"from": t, "to": mid, "kind": "subscribes", "state": m["state"], "observed": False, "gone": True}
                  for t in removed.get("receives") or []]
        edges += [{"from": mid, "to": t, "kind": "publishes", "state": m["state"], "observed": False, "gone": True}
                  for t in removed.get("emits") or []]
    out["intended_edges"] = edges
    out["intended_types"] = [{"type": t, "description": e.get("description"), "implicit": e.get("implicit", False)}
                             for t, e in sorted(layer["events"].items())]
    out["intended_version"] = intended.current_version() or 0
