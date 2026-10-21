"""What the program fits: each measured stock's one-step change and the values the rates may read.

A step k runs from the levels at t[k] to those at t[k+1]: its change is L[k+1] - L[k] less the announced
injections at t[k+1] (they are added at the start of the step, as the engine adds them); a rate in it
reads the stocks' levels at t[k] (with those injections added) and each measured input's value at t[k+1] (the engine's convention).
"""

from __future__ import annotations

import numpy as np


class Steps:
    def __init__(self, stocks: list[dict], run: dict, opts: dict):
        self.ids = [s["id"] for s in stocks]
        self.final = {s["id"] for s in stocks if s.get("final")}
        t = np.asarray(run["t"], dtype=float)
        L = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, []), dtype=float) for i in self.ids]))
        self.t = t
        self.T = L.shape[1] - 1                                    # steps
        dy = L[:, 1:] - L[:, :-1]
        at = {float(x): k for k, x in enumerate(t[1:])}
        index = {s: i for i, s in enumerate(self.ids)}
        read = L[:, :-1].copy()                                    # the levels each step's rates read
        for j in opts.get("injections") or []:
            k, i = at.get(float(j["t"])), index.get(j.get("stock"))
            if k is not None and i is not None:
                dy[i, k] -= float(j["amount"])
                read[i, k] = max(0.0, read[i, k] + float(j["amount"]))
        self.dy = dy
        self.L = read
        self.inputs = {}
        for name, v in (opts.get("inputs") or {}).items():
            if name in index:
                continue
            u = np.nan_to_num(np.asarray(v, dtype=float))
            if len(u) >= self.T + 1:
                self.inputs[name] = u[1:self.T + 1]
        # announced eras: each step's era (the last one starting at or before the step's time t[k+1])
        starts = sorted(float(e["start"]) for e in (opts.get("eras") or []) if e and e.get("start") is not None)
        self.era_starts = starts if len(starts) > 1 else [float(t[0])]
        self.era = np.searchsorted(np.array(self.era_starts), t[1:self.T + 1], side="right") - 1
        self.era = np.maximum(self.era, 0)
        # whole things moved (every measured level an integer): the changes are counts, their
        # scatter grows with the amount moved (a Poisson-like weight per step)
        self.counts = bool(np.all(np.abs(L - np.round(L)) < 1e-9)) and float(np.abs(dy).max(initial=0)) > 0

    def series(self, name: str) -> np.ndarray:
        """The value a rate reads at every step: a stock's level, an input, or 1 for the constant."""
        if name is None:
            return np.ones(self.T)
        if name in self.inputs:
            return self.inputs[name]
        return self.L[self.ids.index(name)]
