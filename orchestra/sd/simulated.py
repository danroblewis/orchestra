"""Simulated series (docs/proposals/intended-model.md §6.3): a placeholder instrument's
``[[collect]]`` entry carries ``simulated = true``, and the instrument labels every point
``simulated="true"`` (``collect.round``). Discovery reads such a series as any other, but only
while an entry with ``simulated = true`` names its instrument; once the entry is gone its points
stay in the store and the series is left out ("simulated, expired"), so the simulated parts leave
the next version.

Every stock and flow fitted from a simulated series, and every machine hypothesis on such a flow,
is marked ``simulated: true`` in the saved version (in its ``evidence``), from the label, so the
mark lives in ``vN``. A prediction verdict never counts a simulated part as an unpredicted change
(``sd.verdict``) and a target backed only by simulated parts is never met (``sd.intended``). This
is a flag, not a rule change: the parts are discovered as any other.

A **draft** instrument (``draft = true``, with ``expires``: an option the Supervisor is trying,
P4's draft namespace) labels its points ``draft="true"``; discovery leaves every such series out
of its candidates, always ("a draft instrument's series"). Past ``expires`` the instrument records
nothing more; keeping it is the plugin's (it drops the flag), and points already written stay
draft-labelled and left out."""

from __future__ import annotations

LABEL = "simulated"
DRAFT = "draft"
DRAFTED = "a draft instrument's series: recorded for an option being tried, not read by discovery until kept"
EXPIRED = "simulated, expired: no [[collect]] entry with simulated = true names its instrument any more"


def is_simulated(labels: dict | None) -> bool:
    return (labels or {}).get(LABEL) == "true"


def configured(raw: dict) -> set[str]:
    """The instruments whose entries say ``simulated = true``."""
    return {e.get("name") for kind in ("collect", "scrape") for e in raw.get(kind) or []
            if isinstance(e, dict) and e.get("simulated") is True}


def select(dump: list, allowed: set[str]) -> tuple[list, dict[str, str]]:
    """The dump without the draft series and the simulated ones no entry names any more, and why
    each was left out."""
    from .series import series_key

    kept, left = [], {}
    for name, labels, pts in dump:
        if (labels or {}).get(DRAFT) == "true":
            left[series_key(name, labels)] = DRAFTED
        elif is_simulated(labels) and labels.get("instrument") not in allowed:
            left[series_key(name, labels)] = EXPIRED
        else:
            kept.append((name, labels, pts))
    return kept, left


def mark(model) -> None:
    """Mark the parts fitted from a simulated series, in place."""
    sim_stocks = {s.id for s in model.stocks if s.series and is_simulated(s.series.labels)}
    for s in model.stocks:
        if s.id in sim_stocks:
            s.evidence["simulated"] = True
    for f in model.flows:
        refs = [r for r in [f.counter, *(f.measured_by or [])] if r is not None]
        inputs = {i for e in f.equations for i in e.inputs}
        if any(is_simulated(r.labels) for r in refs) or {f.src, f.dst} & sim_stocks or inputs & sim_stocks:
            f.evidence["simulated"] = True
            for h in ((f.evidence.get("machines") or {}).get("hypotheses") or []):
                h["simulated"] = True
