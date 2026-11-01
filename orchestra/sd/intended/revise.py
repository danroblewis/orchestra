"""Revising an element (§4). A revision by ``author: owner`` with a quote applies at once, except
on a machine or an attachment that is no longer proposed: there, as for any other author, the
revision becomes a **pending change** on the element, shown as proposed and answered by
``confirm`` or ``discard`` with its change id (E2: the Supervisor changes a proposed machine as
the owner talks; a confirmed one changes only when confirmed again). A revision the op has the
owner's consent for (``consent``: it answers the owner's request, ``consent.py``) applies at once
too, even on a confirmed machine. An applied revision records ``latest``: the element's difference from its baseline
(``refinement.py``: as last confirmed, or as first declared while proposed; what was added,
removed and what the changed fields were before), across every change since, with their ids and
quotes and the request it answered, which the Machines page marks "just now".

**Precedence** (§3): where the owner's pending change and another author's touch the same fields
(the same ``set`` keys, or an ``add`` or ``remove`` of the same list), the other is
``overridden_by`` the owner's (``overridden``, derived on read), and is not confirmed while the
owner's is pending unless the owner asks for it (on a page, or quoted through a plugin) or the
owner's request names it."""

from __future__ import annotations

from .checks import IntentError
from .consent import at_once, owner_asks, verified
from .refinement import latest, refine


def _guesses(el: dict, touched: set[str], guessed: list[str]) -> None:
    """A guessed field stays a guess until it is set; the op's own guesses are added."""
    kept = [g for g in el.get("guessed") or [] if g.split("[", 1)[0] not in touched]
    el["guessed"] = kept + [g for g in guessed if g not in kept]


def revise(el: dict, set_: dict, add: dict, remove: dict, guessed: list[str], ctx: dict, *,
           waits_once_confirmed: bool = False, consent: bool = False) -> dict:
    """Apply a revision now or keep it pending; returns the change's record.
    ``waits_once_confirmed``: a machine's or an attachment's, where even the owner's revision
    waits once the element is no longer proposed. ``consent``: the op answers the owner's
    request, so it applies at once."""
    prov, cid = ctx["provenance"], ctx["change"]
    now = consent or (at_once(prov) and (not waits_once_confirmed or el.get("state") == "proposed"))
    if not now:
        el.setdefault("pending", []).append({"change": cid, "set": set_, "add": add, "remove": remove, "guessed": guessed,
                                             "provenance": prov})
        return {"pending": True}
    diff, prior = refine(el, set_, add, remove)
    _guesses(el, set(set_) | set(add) | set(remove), guessed)
    el["latest"] = latest(prior, cid, prov["at"], [prov["quote"]] if prov.get("quote") else [], diff,
                          **({"request": prov["request"]} if consent else {}))
    return {"pending": False}


def _fields(p: dict) -> set[str]:
    return set(p.get("set") or {}) | set(p.get("add") or {}) | set(p.get("remove") or {})


def overridden(pending: list[dict]) -> dict[str, str]:
    """Each pending change another author made on fields the owner's pending change also touches,
    and the owner's change that overrides it."""
    owners = [p for p in pending if (p.get("provenance") or {}).get("author") == "owner"]
    out = {}
    for p in pending:
        if (p.get("provenance") or {}).get("author") == "owner":
            continue
        by = next((o["change"] for o in owners if _fields(o) & _fields(p)), None)
        if by is not None:
            out[p["change"]] = by
    return out


def pending_view(el: dict) -> list[dict]:
    """The element's pending changes as the pages read them: ``overridden_by`` on each the owner's
    pending change overrides."""
    pend = el.get("pending") or []
    over = overridden(pend)
    return [{**p, "overridden_by": over[p["change"]]} if p["change"] in over else p for p in pend]


def settle_pending(el: dict, change: str, accept: bool, ctx: dict, part: str) -> None:
    """Confirm (apply) or discard one pending change. One the owner's pending change overrides is
    confirmed only when the owner asks for it or the owner's request names it."""
    pend = el.get("pending") or []
    p = next((x for x in pend if x["change"] == change), None)
    if p is None:
        raise IntentError(f"{el.get('id')} has no pending change {change}")
    by = overridden(pend).get(change)
    if accept and by is not None and not (owner_asks(ctx["provenance"])
                                          or verified(ctx, part, el.get("id"), "confirm", change, exact=True)):
        raise IntentError(f"{part} {el.get('id')}: the owner's pending change {by} touches the same fields as {change}; "
                          "it is confirmed only when the owner asks for it")
    el["pending"] = [x for x in pend if x is not p]
    if accept:
        diff, prior = refine(el, p["set"], p["add"], p["remove"])
        _guesses(el, set(p["set"]) | set(p["add"]) | set(p["remove"]), p.get("guessed") or [])
        el["latest"] = latest(prior, change, ctx["provenance"]["at"],
                              [q for q in (p["provenance"].get("quote"), ctx["provenance"].get("quote")) if q], diff,
                              confirmed_by=ctx["change"])
