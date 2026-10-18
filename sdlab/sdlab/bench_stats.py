"""Paired tests between two bench runs, so an adopt decision is not fooled by noise.

Two runs are paired by (example, length); each pair gives one difference in skill (clipped at -100%
as the headline is). The sign test counts which way the differences go (robust, ignores size);
the Wilcoxon signed-rank test also weighs them by rank (Demšar 2006). Differences under `tie`
(half a point by default: what evaluate.py prints as no change) are dropped as ties. Both p-values
are two-sided. Used by tests/bench/evaluate.py (--baseline) and the research view's comparison.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import binomtest, wilcoxon

TIE = 0.0005


def clip(v) -> float:
    return max(-1.0, float(v)) if isinstance(v, (int, float)) and math.isfinite(v) else -1.0


def pairs(before: list[dict], after: list[dict], key: str = "skill", h: int = 20) -> list[tuple[str, str, float, float]]:
    """(example, length, before, after) for every run in both, skills clipped at -100%."""
    b = {(x.get("example"), str(x.get("length"))): x for x in before if isinstance(x, dict)}
    out = []
    for x in after:
        if not isinstance(x, dict):
            continue
        y = b.get((x.get("example"), str(x.get("length"))))
        p, q = (y or {}).get(key) or {}, x.get(key) or {}
        if y is not None and str(h) in p and str(h) in q:
            out.append((x.get("example"), str(x.get("length")), clip(p[str(h)]), clip(q[str(h)])))
    return out


def paired(before: list[dict], after: list[dict], key: str = "skill", h: int = 20, tie: float = TIE) -> dict:
    """The change from `before` to `after` over the runs in both: how many got better, worse or
    stayed, the mean change, and the sign test's and Wilcoxon's two-sided p-values (None when
    nothing changed)."""
    ps = pairs(before, after, key, h)
    d = [q - p for _, _, p, q in ps]
    moved = [x for x in d if abs(x) >= tie]
    up, down = sum(x > 0 for x in moved), sum(x < 0 for x in moved)
    sign = float(binomtest(up, up + down, 0.5).pvalue) if moved else None
    wil = float(wilcoxon(moved).pvalue) if moved else None
    return {"key": key, "horizon": h, "n": len(ps), "better": up, "worse": down, "same": len(d) - len(moved),
            "mean": sum(d) / len(d) if d else None, "sign_p": sign, "wilcoxon_p": wil}


def describe(t: dict) -> str:
    """One line: 'skill@20: 5 better, 2 worse, 55 same; mean +1.2 points; sign test p=0.45, Wilcoxon p=0.30'."""
    label = f"{'fresh ' if t['key'] == 'fresh' else ''}skill@{t['horizon']}"
    if not t["n"]:
        return f"{label}: no runs in both"
    m = t["mean"] or 0.0
    p = "no change to test" if t["sign_p"] is None else f"sign test p={t['sign_p']:.3g}, Wilcoxon p={t['wilcoxon_p']:.3g}"
    return f"{label}: {t['better']} better, {t['worse']} worse, {t['same']} same of {t['n']}; mean {'+' if m >= 0 else ''}{100 * m:.1f} points; {p}"


def bootstrap_mean(values: list[float], n: int = 2000, seed: int = 0) -> list[float] | None:
    """95% percentile bootstrap interval of the mean of `values` (resampled with replacement), or
    None for fewer than two values: how much a headline mean over runs depends on which runs."""
    v = np.asarray([float(x) for x in values], dtype=float)
    if len(v) < 2:
        return None
    means = v[np.random.default_rng(seed).integers(0, len(v), size=(n, len(v)))].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return [float(lo), float(hi)]


def with_ci(mean: float, ci: list[float] | None) -> str:
    """'47.2% [44.1, 50.3]' (percent, the interval in points)."""
    return f"{100 * mean:.1f}%" + (f" [{100 * ci[0]:.1f}, {100 * ci[1]:.1f}]" if ci else "")
