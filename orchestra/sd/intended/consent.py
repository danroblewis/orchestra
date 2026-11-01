"""Whether an op has the owner's consent (§4, §6.2), in one place for the ops.

- The owner **asks**: through a plugin with the owner's words quoted (``checks.provenance``
  requires the quote of a plugin's ``author: owner``), or on a page. A plugin's ``author: owner``
  is its assertion, backed by the quote.
- A plugin **answers the owner's request**: ``provenance.request`` names a request the web server
  noted (``requests.noted``) that no accepted call has answered yet, about the same part and id,
  with the same control (a ``confirm`` answers ``confirm``, a ``discard`` answers ``discard``, a
  revision of the kind answers ``switch_kind``) and the same ``change`` when the request names
  one. The store gives the ops the open requests (``ctx["requests"]``), so no op reads a file.

What the owner declared (an element, mark or target whose provenance author is ``owner``) is
changed or removed only with the owner's consent; what a plugin proposed by itself is its own."""

from __future__ import annotations

from .checks import IntentError

ASK_THE_OWNER = "the owner declared this: ask the owner"


def at_once(prov: dict) -> bool:
    """A revision applied at once: the owner's, with the owner's words quoted."""
    return prov.get("author") == "owner" and bool(prov.get("quote"))


def owner_asks(prov: dict) -> bool:
    """The owner asked for it: through a plugin with the owner's words quoted, or on a page."""
    return prov.get("author") == "owner" and (bool(prov.get("quote")) or prov.get("via") == "page")


def request(ctx: dict) -> dict | None:
    """The owner's open request the call cites, as the web server noted it; None if it cites none
    or one that is not open (made up, or answered already)."""
    rid = ctx["provenance"].get("request")
    return (ctx.get("requests") or {}).get(rid) if rid else None


def verified(ctx: dict, part: str, eid, control: str, change: str | None = None, *, exact: bool = False) -> bool:
    """The call answers the owner's open request to ``control`` this ``part`` ``eid`` (and, when
    the request names a pending change, that ``change``; ``exact``: the request names ``change``)."""
    r = request(ctx)
    if r is None or (r.get("part"), r.get("id"), r.get("control")) != (part, eid, control):
        return False
    return r.get("change") == change or (not exact and r.get("change") is None)


def may_settle(ctx: dict, part: str, eid, control: str, change: str | None = None) -> None:
    """A proposal or pending change is settled by the owner, or in answer to the owner's request
    to do just that; never by its author alone."""
    prov = ctx["provenance"]
    if prov.get("author") == "owner":
        return
    if not prov.get("request"):
        raise IntentError("a proposal is confirmed by the owner: give the owner's quote or the request's event id")
    if not verified(ctx, part, eid, control, change):
        raise IntentError(f"provenance.request {prov['request']} is not the owner's unanswered request to {control} {part} {eid}"
                          + (f" (change {change})" if change else ""))


def guard_owners(owned: dict | None, ctx: dict, part: str, eid, control: str = "discard") -> None:
    """Refuse a change to what the owner declared (``owned``: its provenance), unless the owner
    asks or the call answers the owner's request (``control`` on ``part`` ``eid``)."""
    if (owned or {}).get("author") != "owner":
        return
    if owner_asks(ctx["provenance"]) or verified(ctx, part, eid, control):
        return
    raise IntentError(ASK_THE_OWNER)
