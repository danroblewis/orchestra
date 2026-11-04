"""What the owner says a metric is, over inference's own reading: ``kinds`` on a ``[[sources]]``
entry (``{"grpc_client_callMillis:count" = "flow", "some_gauge" = "level"}``), a measurement
fact like ``split``, never a binding to a stock (AGENTS.md rule 7).

- **flow**: its samples are a flow: a counter stays one; anything else is each sample a count of
  its own (a summary's per-interval part, a delta), summed over each step.
- **level**: read as a level (a gauge), whatever its samples did.
- **ignore**: never read; left out with the reason.

A key names a family (its name, one of its metrics, or a histogram's base) or one recording rule
of it (``metric:fn``); a rule's kind is the rule's alone. A key may be a glob (``*``, ``?``,
``[…]``: ``"gcp_pubsub_*_count" = "flow"``, ``"*:count" = "flow"``) matched against those names:
an exact name wins over a pattern, a longer pattern over a shorter (``entry``). Applied after the
names, the metadata and the samples were judged (``conventions.py``, ``survey.py``), so the
declaration wins, and each family or rule records it (``declared_kind``) and the entry that said it
(``declared_by``) for the Instruments page ("kind: flow (declared by *:count)")."""

from __future__ import annotations

from fnmatch import fnmatchcase

from .family import Family

KINDS = ("flow", "level", "ignore")
IGNORED = "declared ignore in [[sources]] kinds: never read"
GLOB = set("*?[")


def pattern(key: str) -> bool:
    return bool(GLOB & set(key))


def entry(names, table: dict[str, str]) -> str | None:
    """The key of ``table`` that decides for a thing called any of ``names``: an exact name first
    (the first of them in sorted order), else the longest pattern matching one of them (ties by
    the key's own order); None when none does. Shared by ``kinds`` and ``names`` (``naming.py``)."""
    names = sorted(set(names))
    if hit := next((n for n in names if n in table and not pattern(n)), None):
        return hit
    pats = sorted((k for k in table if pattern(k) and any(fnmatchcase(n, k) for n in names)), key=lambda k: (-len(k), k))
    return pats[0] if pats else None


def declared(families: list[Family], kinds: dict[str, str]) -> None:
    """Each family and rule ``kinds`` names, set to what it says."""
    if not kinds:
        return
    for fam in families:
        for r in fam.rollups.values():
            if (k := entry([r["metric"]], kinds)) is not None:
                r["declared_kind"], r["declared_by"] = kinds[k], k
        if fam.kind == "rollup" and fam.rollups:
            continue                           # a family of rules only: each rule's kind is its own
        k = entry({fam.name, fam.name.removesuffix("_count"), *fam.metrics}, kinds)
        if k is None:
            continue
        said = kinds[k]
        fam.declared_kind, fam.declared_by = said, k
        if said == "ignore":
            fam.kind, fam.retyped, fam.counter_form = "ignored", IGNORED, ""
        elif said == "level":
            fam.kind, fam.counter_form = "gauge", ""
            fam.retyped = "declared a level in [[sources]] kinds: read as a level, whatever its samples did"
        elif fam.kind != "counter":
            fam.kind, fam.counter_form = "counter", "delta"
            fam.retyped = "declared a flow in [[sources]] kinds: each sample a count of its own, summed over each step"
