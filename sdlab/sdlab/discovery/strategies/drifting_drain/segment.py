"""A drain whose rate moves in time, beside a steady inflow: y_t = c - k_t x_t, k_t piecewise constant.

Given c, each step says what the drain's rate was, z_t = (c - y_t) / x_t, as precisely as x_t is
large (weight x_t^2: the residual in the stock's units is x_t (z_t - k)). Cutting z into stretches of
one rate is an optimal partition (dynamic programming over the cut points) whose price per stretch
is 2 log T x the noise variance (a value and a cut, BIC). With the stretches held, c and every k are
refitted together by least squares; the two steps alternate until the stretches stop changing.

The noise variance comes from the residual of a fine fit (stretches of `fine` steps), so it is the
data's noise and not the drift (noise-free data: the 4-decimal rounding floor). Long runs are cut on
blocks of steps (at most `most_blocks` blocks), so the partition stays O(blocks^2).
"""

from __future__ import annotations

import math

import numpy as np


def partition(z: np.ndarray, w: np.ndarray, pen: float, min_len: int = 3, most_blocks: int = 4000) -> list[tuple[int, int]]:
    """Stretches [a, b) of steps minimising sum w (z - mean_w)^2 + pen per stretch."""
    T = len(z)
    m = max(1, math.ceil(T / most_blocks))
    edges = np.arange(0, T, m)
    W = np.add.reduceat(w, edges)
    Wz = np.add.reduceat(w * z, edges)
    Wzz = np.add.reduceat(w * z * z, edges)
    B = len(W)
    cW, cWz, cWzz = (np.concatenate([[0.0], np.cumsum(v)]) for v in (W, Wz, Wzz))
    least = max(1, math.ceil(min_len / m))
    F = np.full(B + 1, np.inf)
    F[0] = -pen
    back = np.zeros(B + 1, dtype=int)
    for t in range(least, B + 1):
        s = np.arange(0, t - least + 1)
        sw = cW[t] - cW[s]
        swz = cWz[t] - cWz[s]
        cost = (cWzz[t] - cWzz[s]) - np.where(sw > 0, swz * swz / np.where(sw > 0, sw, 1.0), 0.0)
        tot = F[s] + cost + pen
        j = int(np.argmin(tot))
        F[t], back[t] = tot[j], s[j]
    cuts, t = [], B
    while t > 0:
        cuts.append((int(back[t]), t))
        t = int(back[t])
    out = []
    for a, b in reversed(cuts):
        out.append((int(edges[a]), int(edges[b]) if b < B else T))
    return out


def _design(x: np.ndarray, spans: list[tuple[int, int]]) -> np.ndarray:
    T = len(x)
    A = np.zeros((T, 1 + len(spans)))
    A[:, 0] = 1.0
    for q, (a, b) in enumerate(spans):
        A[a:b, 1 + q] = -x[a:b]
    return A


def fit_spans(y: np.ndarray, x: np.ndarray, spans: list[tuple[int, int]]) -> tuple[float, np.ndarray, float]:
    """(c, k per stretch, rss) by least squares."""
    A = _design(x, spans)
    b = np.linalg.lstsq(A, y, rcond=None)[0]
    r = y - A @ b
    return float(b[0]), b[1:], float(r @ r)


def noise_var(y: np.ndarray, x: np.ndarray, fine: int, floor: float) -> float:
    """The steps' noise variance: every stretch of `fine` steps fitted on its own (y = c - k x), the
    residuals' spread read robustly (1.4826 x their median absolute value), so a stretch with a cut
    inside it does not count as noise."""
    T = len(y)
    res = []
    for a in range(0, T - 2, fine):
        b = min(T, a + fine)
        A = np.vstack([np.ones(b - a), x[a:b]]).T
        if b - a < 3:
            continue
        coef = np.linalg.lstsq(A, y[a:b], rcond=None)[0]
        res.append((y[a:b] - A @ coef) * math.sqrt((b - a) / max(1, b - a - 2)))
    if not res:
        return floor
    r = np.concatenate(res)
    return max((1.4826 * float(np.median(np.abs(r)))) ** 2, floor)


def _partition_cost(z: np.ndarray, w: np.ndarray, spans: list[tuple[int, int]]) -> float:
    cost = 0.0
    for a, b in spans:
        sw = w[a:b].sum()
        if sw > 0:
            m = float((w[a:b] * z[a:b]).sum() / sw)
            cost += float((w[a:b] * (z[a:b] - m) ** 2).sum())
    return cost


def search(y: np.ndarray, x: np.ndarray, floor_var: float, mult: float = 2.0, fine: int = 10, grid: int = 24, rounds: int = 3,
           counting: bool = False, rounding: float = 1 / 6, coarse: int = 400) -> dict | None:
    """{c, spans, k, rss, var}; None when the level is not clearly above 0 (a drain's rate is unreadable).

    A stock near its moving balance changes little (y ~ 0 while c = k_t x_t), so c is told only by
    how the level lags the drift: c is profiled. For each c on a grid over what it can be (every rate
    >= 0 and <= 1 per step: max y <= c <= min(y + x)), the drift is partitioned and priced; the best
    c is refined between its neighbours, then c and the rates are refitted jointly with the stretches
    held, and the stretches re-cut from that c (`rounds` times)."""
    T = len(y)
    if np.mean(x > 1e-9) < 0.9:
        return None
    ok = x > 1e-9
    xs = np.where(ok, x, 1e-9)
    w = np.where(ok, x * x, 0.0)
    var = noise_var(y, x, fine, floor_var)
    pen = mult * math.log(T) * var
    lo, hi = max(0.0, float(np.quantile(y, 0.99))), float(np.quantile((y + x)[ok], 0.01))
    if not hi > lo:
        return None

    def price(c, blocks=4000):
        z = (c - y) / xs
        spans = partition(z, w, pen, most_blocks=blocks)
        return _partition_cost(z, w, spans) + pen * len(spans), spans

    cs = np.linspace(lo, hi, grid)
    prices = [price(c, coarse)[0] for c in cs]          # the grid on blocks of steps (cheap)
    j = int(np.argmin(prices))
    a, b = cs[max(0, j - 1)], cs[min(grid - 1, j + 1)]
    for _ in range(12):                                   # golden-section between the neighbours
        m1, m2 = a + 0.382 * (b - a), a + 0.618 * (b - a)
        if price(m1)[0] <= price(m2)[0]:
            b = m2
        else:
            a = m1
    c = 0.5 * (a + b)
    spans = price(c)[1]
    for _ in range(rounds):
        c, k, rss = fit_spans(y, x, spans)
        new = price(c)[1]
        if new == spans:
            break
        spans = new
    c, k, rss = fit_spans(y, x, spans)
    if counting:
        # counting noise: a step's variance is what moved (in + out, c + k_t x_t = 2c - its mean
        # change) plus the rounding of the levels, so the residuals' size says what c is
        for _ in range(10):
            m = y - (y - _design(x, spans) @ np.concatenate([[c], k]))
            r2 = float(np.mean((y - m) ** 2))
            c_new = max(lo, min(hi, 0.5 * (r2 + float(np.mean(m)) - rounding)))
            z = (c_new - y) / xs
            spans = partition(z, w, pen)
            k = np.array([float((w[a:b] * z[a:b]).sum() / max(1e-300, w[a:b].sum())) for a, b in spans])
            done = abs(c_new - c) <= 1e-4 * max(1.0, abs(c))
            c = c_new
            if done:
                break
        r = y - _design(x, spans) @ np.concatenate([[c], k])
        rss = float(r @ r)
    return {"c": c, "spans": spans, "k": k, "rss": rss, "var": var}
