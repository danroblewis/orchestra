"""Revising an element (§4). A revision by ``author: owner`` with a quote applies at once, except
on a machine or an attachment that is no longer proposed: there, as for any other author, the
revision becomes a **pending change** on the element, shown as proposed and answered by
``confirm`` or ``discard`` with its change id (E2: the Supervisor changes a proposed machine as
the owner talks; a confirmed one changes only when confirmed again). An applied revision records
its difference as ``latest`` (what was added, removed and what the changed fields were before),
which the Machines page marks "just now"."""

from __future__ import annotations

import copy

from .checks import IntentError


def at_once(prov: dict) -> bool:
    return prov.get("author") == "owner" and bool(prov.get("quote"))


def owner_asks(prov: dict) -> bool:
    """The owner asked for it: through a plugin with the owner's words quoted, or on a page."""
    return prov.get("author") == "owner" and (bool(prov.get("quote")) or prov.get("via") == "page")


def _apply(el: dict, set_: dict, add: dict, remove: dict) -> dict:
    """Change ``el`` in place; returns the difference {added, removed, before}."""
    added: dict = {}
    removed: dict = {}
    before: dict = {}
    for k, v in set_.items():
        if k == "spec" and isinstance(el.get("spec"), dict):
            old = el["spec"]
            for sk in list(dict.fromkeys([*old, *v])):
                if old.get(sk) != v.get(sk):
                    before[sk] = copy.deepcopy(old.get(sk))
        elif el.get(k) != v:
            before[k] = copy.deepcopy(el.get(k))
        el[k] = v
    for k, items in add.items():
        cur = list(el.get(k) or [])
        new = [x for x in items if x not in cur]
        if new:
            el[k] = cur + new
            added[k] = new
    for k, items in remove.items():
        cur = list(el.get(k) or [])
        gone = [x for x in items if x in cur]
        if gone:
            el[k] = [x for x in cur if x not in gone]
            removed[k] = gone
    return {"added": added, "removed": removed, "before": before}


def _guesses(el: dict, touched: set[str], guessed: list[str]) -> None:
    """A guessed field stays a guess until it is set; the op's own guesses are added."""
    kept = [g for g in el.get("guessed") or [] if g.split("[", 1)[0] not in touched]
    el["guessed"] = kept + [g for g in guessed if g not in kept]


def revise(el: dict, set_: dict, add: dict, remove: dict, guessed: list[str], ctx: dict, *,
           waits_once_confirmed: bool = False) -> dict:
    """Apply a revision now or keep it pending; returns the change's record.
    ``waits_once_confirmed``: a machine's or an attachment's, where even the owner's revision
    waits once the element is no longer proposed."""
    prov, cid = ctx["provenance"], ctx["change"]
    now = at_once(prov) and (not waits_once_confirmed or el.get("state") == "proposed")
    if not now:
        el.setdefault("pending", []).append({"change": cid, "set": set_, "add": add, "remove": remove, "guessed": guessed,
                                             "provenance": prov})
        return {"pending": True}
    diff = _apply(el, set_, add, remove)
    _guesses(el, set(set_) | set(add) | set(remove), guessed)
    el["latest"] = {"change": cid, "at": prov["at"], "quotes": [prov["quote"]] if prov.get("quote") else [], **diff}
    return {"pending": False}


def settle_pending(el: dict, change: str, accept: bool, ctx: dict) -> None:
    """Confirm (apply) or discard one pending change."""
    pend = el.get("pending") or []
    p = next((x for x in pend if x["change"] == change), None)
    if p is None:
        raise IntentError(f"{el.get('id')} has no pending change {change}")
    el["pending"] = [x for x in pend if x is not p]
    if accept:
        diff = _apply(el, p["set"], p["add"], p["remove"])
        _guesses(el, set(p["set"]) | set(p["add"]) | set(p["remove"]), p.get("guessed") or [])
        el["latest"] = {"change": change, "at": ctx["provenance"]["at"], "confirmed_by": ctx["change"],
                        "quotes": [q for q in (p["provenance"].get("quote"), ctx["provenance"].get("quote")) if q], **diff}
