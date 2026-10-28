"""The evidence for an accepted net flow, measured as for a balance (``sd.identify``).

``sd.netflow`` accepts a level's net flow when its form survives refutations. That says it is the
best of the forms tried, not how far to trust it: the form was chosen from hundreds of drivers, so
chance alone finds one that fits a wandering level about as well. Measured here, for the stock's
trust (``sd.stocktrust.net_flow``):

- **held out**: the form fitted on each half of its stretches, scored on the other (the worse R²);
- **the level reproduced**: the running total of what the fitted net flow misses, over the level's
  own spread;
- **the shift null**: the level's stretches moved circularly in time against every other series,
  ``SHIFTS`` times, and the best of the same drivers in the same form (``c + a × X``, with ``b ×
  level`` when the form has it) fitted again by least squares: the share of those (counting the real
  one) that fit at least as well. It prices the choice among hundreds of drivers. It does not run
  the refutations ``sd.netflow`` applies, so it is the stricter test: a shifted level that a driver
  fits well enough counts even when a refutation would have struck it.

What it cannot price is the choice among levels: every level conservation leaves is tried, so a
discovery over hundreds of levels accepts a few net flows from noise however each one scores
(the metrics lab's null runs: about two a run on 600 series). That is the discovery's null, and
the metrics lab's report measures it; the per-stock trust says how each fit compares with chance."""

from __future__ import annotations

import math
from statistics import pstdev

from .netflow import _mean, _ols, _stretches

SHIFTS = 19


def _rows(level, f, starts: list[int], k: int) -> list[list[float]]:
    return [[1.0, *([_mean(f.driver.values, a, k)] if f.driver else []), *([level.values[a]] if f.own else [])] for a in starts]


def _held_out(rows: list[list[float]], y: list[float]) -> float | None:
    h = len(y) // 2
    if h < 3:
        return None
    worst = math.inf
    for fit_on, test_on in ((range(h), range(h, len(y))), (range(h, len(y)), range(h))):
        got = _ols([rows[i] for i in fit_on], [y[i] for i in fit_on])
        if got is None:
            return None
        yt = [y[i] for i in test_on]
        mean = sum(yt) / len(yt)
        sst = sum((v - mean) ** 2 for v in yt)
        sse = sum((y[i] - sum(c * x for c, x in zip(got[0], rows[i]))) ** 2 for i in test_on)
        worst = min(worst, 1 - sse / sst if sst > 0 else 0.0)
    return worst


def _r2(y: list[float], x: list[float], lv: list[float] | None) -> float:
    """R² of ``y`` on an intercept and ``x`` (and ``lv``), from correlations: cheap enough to try
    every driver at every shift."""
    def corr(a, b):
        n = len(a)
        ma, mb = sum(a) / n, sum(b) / n
        va = sum((u - ma) ** 2 for u in a)
        vb = sum((v - mb) ** 2 for v in b)
        return sum((u - ma) * (v - mb) for u, v in zip(a, b)) / math.sqrt(va * vb) if va > 0 and vb > 0 else 0.0
    ryx = corr(y, x)
    if lv is None:
        return ryx * ryx
    ryl, rxl = corr(y, lv), corr(x, lv)
    if abs(rxl) >= 1 - 1e-9:
        return max(ryx * ryx, ryl * ryl)
    return (ryx * ryx + ryl * ryl - 2 * ryx * ryl * rxl) / (1 - rxl * rxl)


def shift_null(level, f, drivers: list, starts: list[int], k: int, y: list[float], shifts: int) -> list[float]:
    """The best R² among ``drivers`` in the fit's form, for the level's stretches moved by each shift."""
    m = len(y)
    lv = [level.values[a] for a in starts] if f.own else None
    xs = [[_mean(d.values, a, k) for a in starts] for d in drivers]
    out = []
    for j in range(shifts):
        off = round(m * (0.1 + 0.8 * j / max(1, shifts - 1)))
        if off <= 0 or off >= m:
            continue
        ys = y[off:] + y[:off]
        ls = None if lv is None else lv[off:] + lv[:off]
        out.append(max((_r2(ys, x, ls) for x in xs), default=0.0))
    return out


def measured(level, f, drivers: list, step: float, unit_s: float, shifts: int = SHIFTS) -> dict:
    """What a net flow's trust is computed from (``Fit.notes``)."""
    n = len(level.values) - 1
    k = max(1, round(f.block_s / step))
    starts = _stretches(set(range(n)) if level.live is None else set(level.live), n, k)
    dt = k * step / unit_s
    y = [(level.values[a + k] - level.values[a]) / dt for a in starts]
    rows = _rows(level, f, starts, k)
    out: dict = {"units": len(y)}
    if len(y) >= 6:
        out["held_out_r2"] = _held_out(rows, y)
        acc, run = 0.0, []
        for r, v in zip(rows, y):
            acc += (v - sum(c * x for c, x in zip(f.coef, r))) * dt
            run.append(acc)
        spread = pstdev([level.values[a + k] for a in starts])
        out["cum_ratio"] = pstdev(run) / spread if spread > 0 else None
    if f.driver is not None and shifts and len(y) >= 6:
        null = shift_null(level, f, drivers, starts, k, y, shifts)
        out["p_null"] = (1 + sum(1 for v in null if v >= f.r2 - 1e-9)) / (1 + len(null))
        out["null_shifts"], out["null_r2_max"] = len(null), max(null, default=None)
    return {k_: (round(v, 4) if isinstance(v, float) and math.isfinite(v) else v) for k_, v in out.items()}
