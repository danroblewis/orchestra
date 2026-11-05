"""Whether an op has the owner's consent (§4, §6.2), in one place for the ops.

- The owner **asks**: through a plugin or the events endpoint with the owner's words quoted (``checks.provenance``
  requires the quote of a plugin's ``author: owner``), or on a page. A plugin's ``author: owner``
  is its assertion, backed by the quote.
- A plugin **answers the owner's request**: ``provenance.request`` names a request the web server
  noted (``requests.noted``) that no accepted call has answered yet, about the same part and id,
  with the same control (a ``confirm`` answers ``confirm``, a ``discard`` answers ``discard``, a
  revision of the kind answers ``switch_kind``) and the same ``change`` when the request names
  one. The store gives the ops the open requests (``ctx["requests"]``), so no op reads a file,
  and a set (``ctx["answered"]``) that ``verified`` adds each request it finds answered to: only
  those are written on the journal line as answered (``requests.open_requests``).

- The owner **stands consenting** (``standing``, AGENTS.md rule 9 as amended 2026-11-04): the
  owner names, by hand in the private overlay, the authors who may settle their own proposals
  (``[intended] settle_own = ["supervisor"]``, ``config.py``; ``config_edit`` refuses to change it,
  so no plugin gives it to itself). The store gives the ops where it was given (``ctx["standing"]``:
  ``{"authors", "from"}``). Under it, a named author confirms or discards a proposal it made, or a
  pending change it made, with its reason; the confirmation says so (``confirmed``: ``by`` the
  author, ``standing_consent``, ``reason``), never ``by: owner``, so the element stays the
  author's, which the owner may still discard (``by_standing``) or retract. It never reaches what
  is the owner's (``owners``), nor a pending change the owner's overrides.

What is the owner's (``owners``: an element, mark or target the owner declared, or an element the
owner confirmed, on a page, through a plugin quoting the owner, or by a plugin answering the
owner's request) is changed or removed only with the owner's consent; what a plugin proposed by
itself and nobody confirmed is its own."""

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
    the request names a pending change, that ``change``; ``exact``: the request names ``change``).
    A request found answered is added to ``ctx["answered"]``."""
    r = request(ctx)
    if r is None or (r.get("part"), r.get("id"), r.get("control")) != (part, eid, control):
        return False
    ok = r.get("change") == change or (not exact and r.get("change") is None)
    if ok and ctx.get("answered") is not None:
        ctx["answered"].add(r["event"])
    return ok


def standing(ctx: dict, el: dict | None, change: str | None = None) -> str | None:
    """Where the owner gave the standing consent that lets this call's author settle ``el`` (its
    pending ``change``, when given) on its own; None when there is none for it: the author is not
    named, the element is the owner's, or the proposal (or the pending change) is another's."""
    st, author = ctx.get("standing") or {}, ctx["provenance"].get("author")
    if not el or author == "owner" or author not in (st.get("authors") or ()) or owners(el):
        return None
    if change is not None:
        p = next((x for x in el.get("pending") or [] if x.get("change") == change), None)
        mine = p is not None and (p.get("provenance") or {}).get("author") == author
    else:
        mine = el.get("state") == "proposed" and (el.get("provenance") or {}).get("author") == author
    return (st.get("from") or "the owner's standing consent") if mine else None


def by_standing(el: dict | None) -> bool:
    """Whether ``el`` was confirmed by its author under the owner's standing consent (and not since
    by the owner): the owner may discard it, which removes it."""
    c = (el or {}).get("confirmed") or {}
    return bool(c.get("standing_consent")) and c.get("by") != "owner"


def may_settle(ctx: dict, part: str, eid, control: str, change: str | None = None, el: dict | None = None) -> str | None:
    """A proposal or pending change is settled by the owner, or in answer to the owner's request
    to do just that, or by its author under the owner's standing consent (returned: where the owner
    gave it), with the author's reason; never by its author alone."""
    prov = ctx["provenance"]
    if prov.get("author") == "owner":
        return None
    if not prov.get("request") and (where := standing(ctx, el, change)):
        if not str(prov.get("reason") or "").strip():
            raise IntentError(f"{control} under the owner's standing consent ({where}) carries the author's reason")
        if ctx.get("standing_used") is not None:
            ctx["standing_used"].add(where)
        return where
    if not prov.get("request"):
        raise IntentError("a proposal is confirmed by the owner: give the owner's quote or the request's event id")
    if not verified(ctx, part, eid, control, change):
        raise IntentError(f"provenance.request {prov['request']} is not the owner's unanswered request to {control} {part} {eid}"
                          + (f" (change {change})" if change else ""))
    return None


def owners(owned: dict | None) -> bool:
    """Whether an element, mark or target (a record with its ``provenance`` and, for an element,
    ``confirmed``) is the owner's: the owner declared it, or the owner confirmed it."""
    owned = owned or {}
    return (owned.get("provenance") or {}).get("author") == "owner" or (owned.get("confirmed") or {}).get("by") == "owner"


def consents(ctx: dict, part: str, eid, control: str = "discard") -> bool:
    """The owner asks, or the call answers the owner's request (``control`` on ``part`` ``eid``)."""
    return owner_asks(ctx["provenance"]) or verified(ctx, part, eid, control)


def guard_owners(owned: dict | None, ctx: dict, part: str, eid, control: str = "discard") -> None:
    """Refuse a change to what is the owner's (``owned``: the element, mark or target record),
    unless the owner consents (``consents``)."""
    if owners(owned) and not consents(ctx, part, eid, control):
        raise IntentError(ASK_THE_OWNER)
