"""Judging a model as the goal does: runs forward from many moments in the data, with the measured
inputs it reads (the main line's judge, sdlab/discovery/identify.py, steps without them), per stock.

Each stock's error is its own squared miss at the horizon over its spread, relative to how far the
whole data moved: the sum over stocks is the main line's behaviour error (simulate.behaviour_error),
and a block's share is the sum over its stocks, so blocks can be compared one by one.
"""

from __future__ import annotations

import numpy as np

from ...simulate import Model, levels_array, starts_for

HORIZONS = (5, 20, 100)


class Judge:
    def __init__(self, ids: list[str], t: list, levels: dict, injections=None, inputs=None, starts: int = 80, horizons=HORIZONS):
        self.ids, self.t, self.injections = ids, t, injections
        self.inputs = {"t": t, "values": inputs} if inputs else None
        self.A = levels_array(levels, ids)
        sd = self.A.std(axis=1)
        sd[sd == 0] = 1
        self.sd = sd
        self.tt = np.asarray(t, dtype=float)
        self.hs = [h for h in horizons if h < len(t) / 4]
        self.s0 = {h: starts_for(self.A.shape[1], h, starts) for h in self.hs}

    def per_stock(self, flows: list[dict], inferred: dict | None = None) -> np.ndarray:
        """Each stock's share of the behaviour error, averaged over the horizons (inf: no model). The
        model's own unmeasured stocks start from their estimated levels (`inferred`, aligned with t)."""
        S = len(self.ids)
        if not flows or not self.hs:
            return np.full(S, np.inf)
        out = np.zeros(S)
        hidden = list(inferred or {})
        A = np.vstack([self.A] + [np.nan_to_num(np.asarray(inferred[h], dtype=float))[None, :] for h in hidden]) if hidden else self.A
        try:
            model = Model(flows, self.ids + hidden, inputs=self.inputs)
        except Exception:                                         # noqa: BLE001  (a model the simulator cannot run)
            return np.full(S, np.inf)
        raw = np.zeros(S)
        for h in self.hs:
            s0 = self.s0[h]
            with np.errstate(all="ignore"):
                end = model.run(A[:, s0 - 1], self.tt[s0[None, :] + np.arange(h)[:, None]], self.injections)[:S]
                obs = self.A[:, s0 + h - 1]
                e = ((end - obs) / self.sd[:, None]) ** 2
                er = (end - obs) ** 2
            e[~np.isfinite(e)] = 1e6
            er[~np.isfinite(er)] = 1e30
            moved = (((obs - self.A[:, s0 - 1]) / self.sd[:, None]) ** 2).sum()
            out += e.sum(axis=1) / max(1e-9, moved)
            raw += er.sum(axis=1) / max(1e-9, ((obs - self.A[:, s0 - 1]) ** 2).sum())
        self.raw = raw / len(self.hs)
        return out / len(self.hs)

    def __call__(self, flows: list[dict], inferred: dict | None = None) -> float:
        return float(self.per_stock(flows, inferred).sum())
