"""Multi-step (output) error of a model on the measured data, as a vector of residuals.

The model is started from the measured levels at ~`starts` moments and run forward each horizon;
each residual is a measured stock's distance from what was measured `h` steps later, in units of
that stock's spread, scaled so that the sum of squares over one horizon is the judge's error for it
(identify.judge, but at other moments than the judge's). Its own outside inflows feed the model.

Stocks nobody measures (a hidden stock a fit proposes) start from the level their flows imply: the
flow into one is evaluated on the measured data and the stock drains in proportion to what it holds,
so its level over the run is a first-order filter of what entered it.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

from .simulate import Model, levels_array, starts_for


def hidden_levels(into: dict, delay: float, ids: list[str], A: np.ndarray, t: np.ndarray) -> np.ndarray:
    """The level a hidden stock holds over the run, given the flow into it (evaluated on the
    measured levels) and a drain of 1/delay of what it holds a step."""
    probe = Model([{**into, "to": None}], ids)
    src = ids.index(into["from"])
    amount = A[src, :-1] - probe.step(A[:, :-1], t[1:])[src]
    a = 1.0 - 1.0 / max(1.0, delay)
    h0 = float(amount[: max(1, min(len(amount), int(5 * delay)))].mean()) * max(1.0, delay)
    h, _ = lfilter([1.0], [1.0, -a], amount, zi=[a * h0])
    return np.concatenate([[h0], h])


class Objective:
    """Residuals of a model's runs from many moments in the data, over several horizons."""

    def __init__(self, ids: list[str], t: list, levels: dict, horizons=(5, 20, 100), starts: int = 80, shift: bool = True):
        self.ids = ids
        self.A = levels_array(levels, ids)
        self.t = np.asarray(t, dtype=float)
        n = self.A.shape[1]
        sd = self.A.std(axis=1)
        sd[sd == 0] = 1
        self.sd = sd
        self.evals = 0
        self.plans = []
        for h in (h for h in horizons if h < n / 4):
            s0 = starts_for(n, h, starts) + (h % 7 if shift else 0)       # other moments than the judge's
            s0 = s0[s0 + h - 1 < n]
            if len(s0):
                moved = (((self.A[:, s0 + h - 1] - self.A[:, s0 - 1]) / sd[:, None]) ** 2).sum()
                self.plans.append((h, s0, self.t[s0[None, :] + np.arange(h)[:, None]], self.A[:, s0 + h - 1], np.sqrt(max(1e-9, moved))))

    def residuals(self, flows: list[dict], hidden: list[dict] | None = None) -> np.ndarray:
        """hidden: [{"id", "into": flow dict, "delay"}] for stocks the flows name that are not measured."""
        self.evals += 1
        ids, A = self.ids, self.A
        if hidden:
            ids = ids + [h["id"] for h in hidden]
            A = np.vstack([A] + [hidden_levels(h["into"], h["delay"], ids, np.vstack([A, np.zeros((len(hidden), A.shape[1]))]), self.t)[None, :] for h in hidden])
        m = Model(flows, ids)
        S = len(self.ids)
        out = []
        for h, s0, times, obs, scale in self.plans:
            end = m.run(A[:, s0 - 1], times)[:S]
            e = ((end - obs) / self.sd[:, None]) / scale
            e[~np.isfinite(e)] = 1e3
            out.append(np.clip(e, -1e3, 1e3).ravel())
        return np.concatenate(out) if out else np.zeros(0)

    def cost(self, flows: list[dict], hidden: list[dict] | None = None) -> float:
        r = self.residuals(flows, hidden)
        return float(r @ r)
