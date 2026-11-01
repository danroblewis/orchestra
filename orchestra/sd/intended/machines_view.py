"""The Machines page's declared layer (§6.1, frames E1–E3): each machine gains ``intent`` (``null``
when undeclared); a declared machine not yet heard is appended (``unseen: true``); a plugin's
placeholder never replaces an intent. The card's kind is the declared kind until the machine is
heard, then the announced one. A declaration never makes a machine exist in the observed layer
(rule 2 as amended): ``heard`` is whether its source (or an alias) is on the bus, read now, and
an appended unheard machine carries no observed values (no subscribes, publishes or mode: what
it is declared to receive and its engagement are under ``intent`` and ``intended_edges``). Each
declared machine also gains ``comparison`` (§6.1, ``measured.comparison``): ``heard``, or "declared, neither heard nor
measured" while nothing is measured. Heard is one rule here and in ``design``
(``heard_as``): the machine's id or one of its aliases (a counted ``<prefix>.<name>`` included)
among the observed machines (``observed_ids``: those on the bus and those counted traffic names).
A pending change the owner's overrides carries ``overridden_by`` (``revise.pending_view``), and
each attachment row its owner's unanswered request (``requested``).

The top level gains ``intended_edges`` (``{from, to, kind, state, observed, gone}``) and
``intended_types`` (declared event types and their descriptions)."""

from __future__ import annotations

import re

from .drafts import publishable
from .keys import Keys
from .machine_ops import ENVELOPE_DEFAULTS
from .measured import comparison
from .names import link, resolve
from .requests import unanswered
from .revise import pending_view

ENVELOPE = tuple(ENVELOPE_DEFAULTS)


def _norm(s: str) -> str:
    """An observed name as a machine id would spell it (not ``checks.make_slug``, which names an
    empty result "element")."""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def observed_ids(machines: list[dict]) -> set[str]:
    """The machines the Machines page has observed: each it lists that is not an unseen
    placeholder or declaration (the bus, and counted traffic's ``<prefix>.<name>``)."""
    return {m["id"] for m in machines if not m.get("unseen")}


def heard_as(mid: str, m: dict, observed: set[str]) -> str | None:
    """The observed name a declared machine is heard as: its id, else its first alias observed."""
    return next((n for n in (mid, *(m.get("aliases") or [])) if n in observed), None)


def _names(edit: dict, layer: dict, keys: Keys) -> str:
    """What an edit names, as a label: a stock by ``names.resolve``; a flow or loop by its name in
    the model."""
    if "stock" in edit:
        return resolve(edit["stock"], layer, keys).label
    part = "flow" if "flow" in edit else "loop"
    found = next((f for f in (keys.model.flows if keys.model else []) if f.id == edit[part]), None) if part == "flow" else None
    return found.name if found else edit[part]


def _label(edit: dict, layer: dict, keys: Keys) -> str:
    for part in ("stock", "flow", "loop"):
        if part in edit:
            n = _names(edit, layer, keys)
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
    a, b = (resolve(edit.get(k), layer, keys).label for k in ("from", "to"))
    return f"{a} → {b} appears"


def expected_effect(m: dict, layer: dict, model, predictions: dict[str, dict]) -> dict | None:
    """A machine's draft prediction, each edit with its label, link and whether it can be
    published yet (``drafts.publishable``)."""
    ee = m.get("expected_effect")
    if not ee:
        return None
    keys = Keys(model)
    edits = []
    for e in ee["edits"]:
        ok, why = publishable(e, layer, keys)
        row = {"edit": e, "label": _label(e, layer, keys), "publishable": ok, "why": why}
        if e.get("stock") is not None:
            row["link"] = link(resolve(e["stock"], layer, keys))
        elif e.get("flow") is not None:
            row["link"] = f"/dynamics#f:{e['flow']}"
        else:
            row["link"] = "/dynamics"
        edits.append(row)
    pid = ee.get("prediction")
    p = predictions.get(pid) if pid else None
    return {"horizon_s": ee["horizon_s"], "prediction": pid, "status": (p or {}).get("status"),
            "verdict": ((p or {}).get("verdict") or {}).get("verdict"), "edits": edits}


def intent_of(m: dict, layer: dict, heard: bool, requested: dict | None, model, predictions: dict,
              asked: dict | None = None) -> dict:
    """``asked``: the owner's unanswered requests by (part, id), for the attachments' rows."""
    asked = asked or {}
    out = {"state": m["state"], "author": (m.get("provenance") or {}).get("author"), "heard": heard,
           **{k: m.get(k) for k in ENVELOPE}, "guessed": m.get("guessed") or [], "pending": pending_view(m),
           "requested": requested, "aliases": m.get("aliases") or [],
           "expected_effect": expected_effect(m, layer, model, predictions), "provenance": m.get("provenance"),
           "latest": m.get("latest"), "change": m.get("change"), "confirmed": m.get("confirmed"),
           "attachments": [{**{k: a.get(k) for k in ("id", "instrument", "match", "instance_label", "state", "provenance",
                                                     "confirmed")},
                            "pending": pending_view(a), "requested": asked.get(("attachment", a["id"]))}
                           for a in layer["attachments"].values() if a["machine"] == m["id"]]}
    return out


def merge(out: dict, intended, model=None, predictions: list[dict] | None = None) -> None:
    """Add the declared layer to an ``/api/machines`` answer in place."""
    layer = intended.read()["layer"]
    preds = {p.get("id"): p for p in predictions or []}
    asked = unanswered(intended, layer)
    machines = out.setdefault("machines", [])
    by_id = {m["id"]: m for m in machines}
    observed = observed_ids(machines)
    for m in machines:
        m.setdefault("intent", None)
        m.setdefault("comparison", None)
    observed_edges = {(e.get("from"), e.get("to"), e.get("kind")) for e in out.get("edges") or []}
    edges = []
    for mid, m in layer["machines"].items():
        names = [mid, *(m.get("aliases") or [])]
        as_ = heard_as(mid, m, observed)
        seen = by_id[as_] if as_ is not None else None
        heard = seen is not None
        intent = intent_of(m, layer, heard, asked.get(("machine", mid)), model, preds, asked)
        if not heard:
            intent["alias_candidates"] = sorted(o for o in observed if o != mid and o not in layer["machines"]
                                                and (_norm(o) == mid or _norm(o.rsplit(".", 1)[-1]) == mid))
        if heard:
            seen.update(intent=intent, comparison=comparison(True, None))
        elif mid in by_id:                       # a plugin's placeholder: the declaration stands, and its kind
            by_id[mid].update(intent=intent, kind=m["kind"], unseen=True, comparison=comparison(False, None))
        else:                                    # nothing observed: no subscribes, publishes or mode of its own
            machines.append({"id": mid, "bootstrap": False, "mode": None, "kind": m["kind"],
                             "package": None, "about": {}, "unseen": True, "publishes": [], "subscribes": [],
                             "flows": [], "logs": [], "instances": [], "first_seen": None, "last_seen": None, "active": False,
                             "intent": intent, "comparison": comparison(False, None)})
        node = seen["id"] if heard else mid      # heard through an alias: the edges attach to the drawn node
        removed = (m.get("latest") or {}).get("removed") or {}
        for t in m.get("receives") or []:
            edges.append({"from": t, "to": node, "kind": "subscribes", "state": m["state"],
                          "observed": any((t, n, "subscribes") in observed_edges for n in names), "gone": False})
        for t in m.get("emits") or []:
            edges.append({"from": node, "to": t, "kind": "publishes", "state": m["state"],
                          "observed": any((n, t, "publishes") in observed_edges for n in names), "gone": False})
        edges += [{"from": t, "to": node, "kind": "subscribes", "state": m["state"], "observed": False, "gone": True}
                  for t in removed.get("receives") or []]
        edges += [{"from": node, "to": t, "kind": "publishes", "state": m["state"], "observed": False, "gone": True}
                  for t in removed.get("emits") or []]
    out["intended_edges"] = edges
    out["intended_types"] = [{"type": t, "description": e.get("description"), "implicit": e.get("implicit", False)}
                             for t, e in sorted(layer["events"].items())]
    out["intended_version"] = intended.current_version() or 0
