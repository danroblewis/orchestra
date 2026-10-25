"""The run as one-step changes: every step's starting state (the levels after that step's announced
injections), the measured inputs during the step, and what the flows changed (engine_forms).

Step i goes from the levels at t[i] to those at t[i + 1]; it is run at time t[i + 1] (an input's
value of that step, its injections added before its flows), as the ground-truth engine and
sdlab/discovery/simulate.py step it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from orchestra.sdlab.discovery.simulate import Model


@dataclass
class Steps:
    ids: list[str]                      # the measured stocks
    t: np.ndarray                       # the run's times (n)
    S: np.ndarray                       # stocks x steps: the state each step starts from
    D: np.ndarray                       # stocks x steps: what the flows changed in the step
    U: dict[str, np.ndarray] = field(default_factory=dict)   # input -> its value during each step
    inputs: dict | None = None          # the inputs as simulate.Model takes them
    E: np.ndarray | None = None         # stocks x steps: the levels each step ends at
    w: np.ndarray | None = None         # the steps a fit reads (1) or leaves out (0): set per stock

    def signed(self, x: str) -> bool:
        """Does x go below 0 (a signed stock)? Clearly: on at least 5% of the steps, and by more than
        1% of its largest size (a level reported with an error dips just below 0 now and then)."""
        v = self.S[self.ids.index(x)]
        return bool(np.mean(v < 0) >= 0.05 and np.min(v) < -0.01 * np.max(np.abs(v)))

    def free(self, x: str) -> np.ndarray:
        """The steps where x's floor did not bind: x ended above 0 (or x goes below 0 somewhere,
        a signed stock with no floor)."""
        i = self.ids.index(x)
        if self.signed(x):
            return np.ones(self.n)
        return (self.E[i] > 0).astype(float)

    @property
    def n(self) -> int:
        return self.S.shape[1]

    def series(self, name: str) -> np.ndarray:
        """A stock's starting levels or an input's values, one per step."""
        if name in self.ids:
            return self.S[self.ids.index(name)]
        return self.U[name]

    def change(self, flows: list[dict]) -> np.ndarray:
        """What these flows change in every stock over each step (stocks x steps)."""
        if not flows:
            return np.zeros_like(self.D)
        return Model(flows, self.ids, inputs=self.inputs).change(self.S.copy(), self.t[1:])


def build(stocks: list[dict], run: dict, opts: dict) -> Steps | None:
    ids = [s["id"] for s in stocks]
    t = np.asarray(run["t"], dtype=float)
    if len(t) < 30 or np.any(np.diff(t) != 1):
        return None
    L = np.array([np.asarray(run["levels"][i], dtype=float) for i in ids])
    if not np.isfinite(L).all():
        return None
    S = L[:, :-1].copy()
    for j in opts.get("injections") or []:
        if j.get("stock") in ids:
            hit = np.nonzero(t[1:] == float(j["t"]))[0]
            k = ids.index(j["stock"])
            moved = S[k, hit] + float(j["amount"])
            S[k, hit] = np.where((moved < 0) & (S[k, hit] >= 0), 0.0, moved)   # never below 0 (unless already)
    D = L[:, 1:] - S
    U, inputs = {}, None
    if opts.get("inputs"):
        vals = {k: np.asarray(v, dtype=float) for k, v in opts["inputs"].items() if k not in ids}
        U = {k: v[1:len(t)] if len(v) >= len(t) else np.resize(v, len(t))[1:] for k, v in vals.items()}
        inputs = {"t": list(t), "values": {k: list(v) for k, v in vals.items()}}
    return Steps(ids, t, S, D, U, inputs, L[:, 1:].copy())
