"""What the program fits: each measured stock's one-step change and the values the rates may read.

A step k runs from the levels at t[k] to those at t[k+1]: its change is L[k+1] - L[k] less the announced
injections at t[k+1] (they are added at the start of the step, as the engine adds them); a rate in it
reads the stocks' levels at t[k] (with those injections added) and each measured input's value at t[k+1] (the engine's convention).
"""

from __future__ import annotations

import numpy as np


class Steps:
    def same_unit(self, a: str, b: str) -> bool:
        """Can a move carry a's contents into b? (2026-10-21) Only between stocks of one unit (or where a unit is
        not given): what leaves a arrives in b, so it is the same stuff. A capacity may read any unit.
        (k8s-316) Except where the declared boundary leaves no other drawing: a source the boundary gives no outside
        outflow and no other stock of its unit could receive, and a receiver it gives no outside inflow and no
        other stock of its unit could feed, can each only exchange with a stock of another unit (queries waiting
        for a pool acquire connections), so the move across units is offered between two such stocks. (Requiring
        only one side alone offered every request queue a move into the pool, and the counts fit took one.)"""
        ua, ub = self.units.get(a), self.units.get(b)
        if not ua or not ub or ua == ub:
            return True
        if self.open_sides is None or a in self.final or b in self.final:
            return False
        if "out" in self.open_sides.get(a, ()) or "in" in self.open_sides.get(b, ()):
            return False                                           # an outside flow is declared on that side
        alone_out = not any(x != a and self.units.get(x) == ua for x in self.ids)
        alone_in = not any(x != b and x not in self.final and self.units.get(x) == ub for x in self.ids)
        return alone_out and alone_in

    def __init__(self, stocks: list[dict], run: dict, opts: dict):
        self.ids = [s["id"] for s in stocks]
        self.final = {s["id"] for s in stocks if s.get("final")}
        self.units = {s["id"]: s.get("unit") for s in stocks}
        raw = run.get("boundary") or {}                            # the sides the declared boundary opens, per stock (None: undeclared)
        self.open_sides = {s: {side for side in ("in", "out") if (raw.get(s) or {}).get(side)} for s in self.ids} \
            if run.get("boundary_declared") else None
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
        self.level_rows: dict[int, np.ndarray] = {}                # stocks fitted in level space (counter.py), with their level noise sd
        self.counts = bool(np.all(np.abs(L - np.round(L)) < 1e-9)) and float(np.abs(dy).max(initial=0)) > 0

    def series(self, name: str) -> np.ndarray:
        """The value a rate reads at every step: a stock's level, an input, or 1 for the constant."""
        if name is None:
            return np.ones(self.T)
        if name in self.inputs:
            return self.inputs[name]
        return self.L[self.ids.index(name)]
