"""A revision applied to an element, and its difference from the element's **baseline**: the
element as the owner last confirmed it, or, while it is still proposed, as it was first declared.
The Machines page marks that difference "just now" (E2), so the marks cover the whole unconfirmed
refinement, every op since the baseline and not only the last one: a receive added by one op and
one removed by the next both show, and a change one op makes and a later op undoes shows as
nothing.

The baseline is kept on the element (``base``) as the original value of each field the
refinement has touched (``fields``) and of each ``spec`` key (``spec``), by key. It is carried
from op to op while the element is proposed; on a confirmed element each applied change is
confirmed already (the owner's, by consent or by confirming a pending change), so it starts a
new baseline. A list field's difference is what was ``added`` and ``removed``; any other field's
or ``spec`` key's is its value ``before`` (the baseline's)."""

from __future__ import annotations

import copy


def _remember(el: dict, base: dict, set_: dict, add: dict, remove: dict) -> None:
    """Record, for each field the revision touches and the baseline does not yet hold, its
    value now."""
    for k, v in set_.items():
        if k == "spec" and isinstance(el.get("spec"), dict) and isinstance(v, dict):
            for sk in dict.fromkeys([*el["spec"], *v]):
                if sk not in base["spec"]:
                    base["spec"][sk] = copy.deepcopy(el["spec"].get(sk))
        elif k not in base["fields"]:
            base["fields"][k] = copy.deepcopy(el.get(k))
    for k in [*add, *remove]:
        if k not in base["fields"]:
            base["fields"][k] = copy.deepcopy(el.get(k))


def _change(el: dict, set_: dict, add: dict, remove: dict) -> None:
    for k, v in set_.items():
        el[k] = v
    for k, items in add.items():
        cur = list(el.get(k) or [])
        if new := [x for x in items if x not in cur]:
            el[k] = cur + new
    for k, items in remove.items():
        cur = list(el.get(k) or [])
        if any(x in cur for x in items):
            el[k] = [x for x in cur if x not in items]


def difference(el: dict, base: dict) -> dict:
    """The element as it stands against its baseline: {added, removed, before}."""
    added: dict = {}
    removed: dict = {}
    before: dict = {}
    for k, orig in base["fields"].items():
        cur = el.get(k)
        if isinstance(orig, list) or isinstance(cur, list):
            orig, cur = orig or [], cur or []
            if a := [x for x in cur if x not in orig]:
                added[k] = a
            if r := [x for x in orig if x not in cur]:
                removed[k] = r
        elif cur != orig:
            before[k] = copy.deepcopy(orig)
    spec = el.get("spec") if isinstance(el.get("spec"), dict) else {}
    for sk, orig in base["spec"].items():
        if spec.get(sk) != orig:
            before[sk] = copy.deepcopy(orig)
    return {"added": added, "removed": removed, "before": before}


def refine(el: dict, set_: dict, add: dict, remove: dict) -> tuple[dict, dict | None]:
    """Change ``el`` in place. Returns its difference from the baseline and the ``latest`` it
    folds into (None when this change starts a new baseline)."""
    proposed = el.get("state") == "proposed"
    carried = el.get("base") if proposed else None
    base = carried or {"fields": {}, "spec": {}}
    _remember(el, base, set_, add, remove)
    _change(el, set_, add, remove)
    el["base"] = base
    return difference(el, base), (el.get("latest") if carried else None)


def latest(prior: dict | None, change: str, at, quotes: list[str], diff: dict, **extra) -> dict:
    """The element's ``latest``: this change, and the refinement's earlier changes and quotes
    when it folds into one (``prior``)."""
    prior = prior or {}
    return {"change": change, "at": at, "changes": [*(prior.get("changes") or []), change],
            "quotes": [*(prior.get("quotes") or []), *quotes], **extra, **diff}
