"""What the last discovery made of each candidate a source's inference kept: the verdicts the next
round reads (``explore.py``).

Every series read from a source carries the candidate it was read by (``explore.ident``: family,
view, statistic and grouping, the same in every round) in the discovery record's ``sourced``. Of
the series of one candidate, discovery made

- **a stock** (its level is a stock's series) or **a flow** (a fitted flow's counter, or one it
  sums): the candidate is *kept*, its verdict carried without probing it again;
- **refuted**: left out as "an input, not a stock" or "no counters balance it" (``REFUTED``): the
  candidate is *demoted*.

A stock outranks a flow, a flow a refutation, over a candidate's series. Anything else (a series
discovery read and used as an input, or left out for another reason) says nothing of the candidate.
This reads the model it is handed and never opens the model store (``catalogue.py`` does, through
``ModelStore``)."""

from __future__ import annotations

import re

from ..sd.series import series_key

REFUTED = re.compile(r"an input, not a stock|no counters (?:of its own )?balance")
ORDER = {"stock": 0, "flow": 1, "refuted": 2}


def _key(ref) -> str | None:
    return series_key(ref.name, dict(ref.labels or {})) if ref is not None else None


def verdicts(at: float, model, source: str) -> dict[str, dict]:
    """Candidate ident -> {fate: stock | flow | refuted, why, series, at}, for the series discovery
    read from ``source`` (``model``: a discovery, ``at``: when it ran)."""
    d = getattr(model, "discovery", None) or {}
    sourced, left = d.get("sourced") or {}, d.get("left_out") or {}
    stocks = {k for s in model.stocks if (k := _key(s.series))}
    flows = {k for f in model.flows if any(e.origin == "fitted" for e in f.equations)
             for k in [_key(f.counter), *(_key(r) for r in f.measured_by)] if k}
    out: dict[str, dict] = {}
    for key, p in sourced.items():
        cand = p.get("candidate")
        if p.get("source") != source or not cand:
            continue
        if key in stocks:
            fate, why = "stock", "discovery made it a stock"
        elif key in flows:
            fate, why = "flow", "discovery fitted it as a flow"
        elif (w := left.get(key)) and REFUTED.search(w):
            fate, why = "refuted", f"discovery left it out: {w}"
        else:
            continue
        was = out.get(cand)
        if was is None or ORDER[fate] < ORDER[was["fate"]]:
            out[cand] = {"fate": fate, "why": why, "series": key, "at": at}
    return out
