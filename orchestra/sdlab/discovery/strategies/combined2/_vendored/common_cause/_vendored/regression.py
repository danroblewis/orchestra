# Vendored for combined2 from sdlab/discovery/strategies/common_cause/_vendored/regression.py at commit 3f5f064 (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""regression.stepwise with the fit passed in.

Copied from sdlab/discovery/regression.py at commit 19fd8f8 (the file last changed at 72b4054).
The only change: `fit_subset` is a parameter (the shared one by default) instead of the module's
own, so common_cause's floored fit reaches stepwise without patching the shared module.
"""

from __future__ import annotations

from orchestra.sdlab.discovery.regression import Sums, bic
from orchestra.sdlab.discovery.regression import fit_subset as _fit_subset


def stepwise(sums: Sums, start: list[int], allowed: list[int], add_gain: float, max_steps: int, fit_subset=_fit_subset) -> list[int]:
    """Add the level that improves BIC most (by more than add_gain), or drop one whose removal
    improves it by more than 2, until nothing does."""
    chosen = list(start)
    score = bic(sums.T, fit_subset(sums, chosen).rss, len(chosen) + sums.pieces)
    for _ in range(max_steps):
        best = None
        for j in allowed:
            if j in chosen:
                continue
            sc = bic(sums.T, fit_subset(sums, chosen + [j]).rss, len(chosen) + 1 + sums.pieces)
            if sc < score - add_gain and (best is None or sc < best[1]):
                best = (chosen + [j], sc)
        for j in chosen:
            ns = [x for x in chosen if x != j]
            sc = bic(sums.T, fit_subset(sums, ns).rss, len(ns) + sums.pieces)
            if sc < score - 2 and (best is None or sc < best[1]):
                best = (ns, sc)
        if best is None:
            break
        chosen, score = best
    return chosen
