"""A behaviour judge that does not replay a model's own inflow pieces: rolling-origin forecasts with
the found outside inflows held at the value they had when the forecast began.

combined's runaway guard runs each candidate from many moments of the run over 5, 20 and 100 steps,
fed its own outside-inflow pieces (simulate.behaviour_error). A model whose structure is wrong can
carry pieces that follow the data step by step, so over the run it looks as good as a sound one
(sd-webshop-stock short: the lna model 0.239, effect_hats' 0.181, while their skill@20 against the
truth's inflows is -7.6 and 0.74). The ladder's skill feeds a model the truth's outside inflows, not
its own pieces; on a page the future inflow is unknown too.

Here each run starts at a moment s of the data and every found inflow piece is held at the value it
had at the last step before s, for the whole horizon: what the model would forecast from s knowing
only the past of its own inflow. Announced eras (byTime), measured inputs and announced injections
still follow their times, since they are known. A sound model then forecasts well wherever the
inflow does not change much within the horizon, whatever its pieces; a model whose pieces stand in
for missing structure runs off as soon as they stop following the data.

The error is behaviour_error's (each stock scaled by its spread; 1 = no better than nothing
changing), averaged over the horizons that fit a quarter of the run.
"""

from __future__ import annotations

import numpy as np

from orchestra.sdlab.discovery.simulate import Model, levels_array, starts_for

HORIZONS = (5, 20, 100)
STARTS = 80


class Held(Model):
    """simulate.Model whose found outside-inflow pieces read the time `hold` (one per state column)
    instead of the step's own time; everything else as Model."""

    hold: np.ndarray | None = None
    found_eras = False           # byTime segments were found, not announced: held too

    def _seg(self, segs, vals, t, zero):
        if segs is None:
            return zero
        if self.hold is not None and (vals is not None or self.found_eras):
            return segs(self.hold)
        return segs(t)

    def _amounts(self, L: np.ndarray, t: np.ndarray) -> list:
        if self.inputs is not None or self.n_sub > 1 or self.ceilings:
            return self._amounts_added(L, t)
        zero = np.zeros(L.shape[1], int)
        amounts = []
        for src, dst, ratio, segs, rate, vals in self.parts:
            seg = self._seg(segs, vals, t, zero)
            amounts.append(vals[seg] if vals is not None else rate(L, seg))
        for i, effect in self.effects:
            amounts[i] = amounts[i] * effect(L)
        for c, takers in self.takers.items():
            want = sum(amounts[i] * w for i, w in takers)
            k = np.where((want > L[c]) & (L[c] > -1), np.maximum(0.0, L[c]) / np.where(want > 0, want, 1), 1.0)
            for i, _ in takers:
                amounts[i] = amounts[i] * k
        return amounts

    def _amounts_added(self, L: np.ndarray, t: np.ndarray) -> list:
        S = L.shape[0]
        R = self._read(L, t)
        zero = np.zeros(L.shape[1], int)
        amounts = []
        for src, dst, ratio, segs, rate, vals in self.parts:
            seg = self._seg(segs, vals, t, zero)
            amounts.append(vals[seg] if vals is not None else rate(R, seg))
        for i, effect in self.effects:
            amounts[i] = amounts[i] * effect(R)
        if self.n_sub > 1:
            amounts = [a * self.dt for a in amounts]
        for c, takers in self.takers.items():
            want = sum(amounts[i] * w for i, w in takers)
            k = np.where((want > L[c]) & (L[c] > -1), np.maximum(0.0, L[c]) / np.where(want > 0, want, 1), 1.0)
            for i, _ in takers:
                amounts[i] = amounts[i] * k
        for c, cap in self.ceilings:
            ins = self.into.get(c) or []
            if not ins or c >= S:
                continue
            want = sum(amounts[i] for i in ins)
            room = np.maximum(0.0, cap - L[c])
            k = np.where(want > room, room / np.where(want > 0, want, 1), 1.0)
            for i in ins:
                amounts[i] = amounts[i] * k
        return amounts


def held_error(flows: list[dict], ids: list[str], t: list, levels: dict, horizon: int = 20, starts: int = STARTS,
               injections: list[dict] | None = None, inferred: dict | None = None, inputs: dict | None = None,
               found_eras: bool = False) -> float:
    """behaviour_error with every found inflow piece (and, with found_eras, every byTime segment) held,
    in each run, at its value at the start."""
    inferred = inferred or {}
    S = len(ids)
    A = levels_array({**levels, **inferred}, ids + list(inferred))
    n = A.shape[1]
    s0 = starts_for(n, horizon, starts)
    if not len(s0):
        return float("inf")
    sd = A[:S].std(axis=1)
    sd[sd == 0] = 1
    tt = np.asarray(t, dtype=float)
    m = Held(flows, ids + list(inferred), inputs={"t": t, "values": inputs} if inputs else None)
    # the piece in force over the last step seen (from s - 1 to s; s >= 1, so the step ending at t[s - 1]
    # is seen only from s >= 2: at s = 1 the first step's piece)
    m.hold = tt[np.maximum(1, s0 - 1)]
    m.found_eras = found_eras
    end = m.run(A[:, s0 - 1], tt[s0[None, :] + np.arange(horizon)[:, None]], injections)[:S]
    obs = A[:S, s0 + horizon - 1]
    e = ((end - obs) / sd[:, None]) ** 2
    e[~np.isfinite(e)] = 1e6
    moved = (((obs - A[:S, s0 - 1]) / sd[:, None]) ** 2).sum()
    return float(e.sum() / max(1e-9, moved))


def held(flows: list[dict], data, run: dict, inferred: dict | None = None, eras: bool = False) -> float:
    """The held-inflow error over the horizons that fit a quarter of the run (inf without flows);
    `data` is combined's judge.Data, `inferred` the unmeasured stocks' open-loop estimate, `eras`
    whether eras were announced (then byTime segments follow their times; else they are held)."""
    hs = [h for h in HORIZONS if h < len(data.t) / 4]
    if not flows or not hs:
        return float("inf")
    return sum(held_error(flows, data.ids, run["t"], run["levels"], horizon=h, injections=data.injections,
                          inferred=inferred or None, inputs=data.inputs or None, found_eras=not eras) for h in hs) / len(hs)
