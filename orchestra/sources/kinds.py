"""What the owner says a metric is, over inference's own reading: ``kinds`` on a ``[[sources]]``
entry (``{"grpc_client_callMillis:count" = "flow", "some_gauge" = "level"}``), a measurement
fact like ``split``, never a binding to a stock (AGENTS.md rule 7).

- **flow**: its samples are a flow: a counter stays one; anything else is each sample a count of
  its own (a summary's per-interval part, a delta), summed over each step.
- **level**: read as a level (a gauge), whatever its samples did.
- **ignore**: never read; left out with the reason.

A key names a family (its name, one of its metrics, or a histogram's base) or one recording rule
of it (``metric:fn``); a rule's kind is the rule's alone. Applied after the samples were judged
(``survey.py``), so the declaration wins, and each family or rule records it (``declared_kind``)
for the Instruments page ("kind: flow (declared)")."""

from __future__ import annotations

from .family import Family

KINDS = ("flow", "level", "ignore")
IGNORED = "declared ignore in [[sources]] kinds: never read"


def declared(families: list[Family], kinds: dict[str, str]) -> None:
    """Each family and rule ``kinds`` names, set to what it says."""
    for fam in families:
        for r in fam.rollups.values():
            if r["metric"] in kinds:
                r["declared_kind"] = kinds[r["metric"]]
        if fam.kind == "rollup" and fam.rollups:
            continue                           # a family of rules only: each rule's kind is its own
        names = {fam.name, fam.name.removesuffix("_count"), *fam.metrics}
        said = next((kinds[n] for n in sorted(names) if n in kinds), None)
        if said is None:
            continue
        fam.declared_kind = said
        if said == "ignore":
            fam.kind, fam.retyped, fam.counter_form = "ignored", IGNORED, ""
        elif said == "level":
            fam.kind, fam.counter_form = "gauge", ""
            fam.retyped = "declared a level in [[sources]] kinds: read as a level, whatever its samples did"
        elif fam.kind != "counter":
            fam.kind, fam.counter_form = "counter", "delta"
            fam.retyped = "declared a flow in [[sources]] kinds: each sample a count of its own, summed over each step"
