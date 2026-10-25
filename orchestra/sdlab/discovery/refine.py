"""Refining a found model's numbers by multi-step (output) error instead of one-step error.

The matrix method fits every number on single steps. A small bias there (an outside inflow change
put in the wrong place, a hidden stock, a floor) is invisible over one step and compounds over a
hundred. Here the structure stays as found and only the flows' numbers move: they are chosen so the
model, started from the measured levels at many moments and run forward several horizons, stays
closest to what was measured (multiple shooting with horizons that grow).

What the refinement may change: the rates of the flows between and out of stocks (their k's, per
era where a rate follows the eras). Outside inflows are not free parameters: with `profile` they
are re-measured for every candidate set of numbers as what the stock's change leaves over on
average in each of their pieces (so they stay what the data says arrives from outside, and a loop
cannot take over their mean); without it they stay as found.
"""

from __future__ import annotations

import copy
import math

import numpy as np
from scipy.optimize import least_squares

from .simulate import Model, levels_array, starts_for


def _slots(flows: list[dict]) -> tuple[list[list[tuple[dict, str]]], list[str]]:
    """The numbers the refinement may move, each as the (dict, key) places that hold it, and a name
    for each. A flow whose rate follows the eras has a number per era only where the matrix found
    one: eras that share a value share the number."""
    slots, names, seen = [], [], set()
    for f in flows:
        if f.get("inflow"):
            continue
        rs = []
        for r in ([g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]):
            if id(r) not in seen:
                seen.add(id(r))
                rs.append(r)
        name = f"{f.get('from')}>{f.get('to')}" + (f" by {f['driver']}" if f.get("driver") else "")
        places: dict[tuple, list] = {}
        for r in rs:
            if r.get("form") == "proportional":
                places.setdefault(("k", r.get("k")), []).append((r, "k"))
            elif r.get("form") == "linear":
                for i, x in enumerate(r.get("terms") or []):
                    places.setdefault((i, x.get("k")), []).append((x, "k"))
        for (key, _), ps in places.items():
            slots.append(ps)
            names.append(name + (f" [{key}]" if key != "k" else "") + (f" x{len(ps)}" if len(rs) > 1 else ""))
    return slots, names


class _Inflows:
    """Re-measures the found outside inflows' pieces from the data, given the other flows."""

    def __init__(self, flows: list[dict], ids: list[str], t: np.ndarray, A: np.ndarray):
        self.ids, self.A = ids, A
        self.prev, self.dy, self.tt = A[:, :-1], np.diff(A, axis=1), t[1:]
        self.items = []
        for f in flows:
            if not f.get("inflow"):
                continue
            s = ids.index(f["to"]) if f.get("to") in ids else ids.index(f["from"]) if f.get("from") in ids else None
            if s is None:
                continue
            sign = 1.0 if f.get("to") in ids else -1.0
            piece = np.full(len(self.tt), len(f["inflow"]))
            for i in range(len(f["inflow"]) - 1, -1, -1):      # the first segment that covers a time
                g = f["inflow"][i]
                piece[(self.tt >= g["from"]) & (self.tt <= g["to"])] = i
            count = np.bincount(piece, minlength=len(f["inflow"]) + 1)[:-1]
            self.items.append((f, s, sign, piece, count))

    def update(self, flows: list[dict]) -> None:
        own = [f for f in flows if not f.get("inflow")]
        if not self.items:
            return
        internal = Model(own, self.ids).change(self.prev, self.tt)
        res = self.dy - internal
        for f, s, sign, piece, count in self.items:
            total = np.bincount(piece, weights=res[s], minlength=len(count) + 1)[:-1]
            for g, c, v in zip(f["inflow"], count, total):
                if c:
                    g["value"] = float(sign * v / c)


def refine(flows: list[dict], ids: list[str], t: list, levels: dict, opts: dict | None = None) -> tuple[list[dict], dict]:
    """A copy of `flows` with its rates refined by multi-step error, and a note of what happened."""
    opts = opts or {}
    flows = copy.deepcopy(flows)
    slots, names = _slots(flows)
    A = levels_array(levels, ids)
    n = A.shape[1]
    tt = np.asarray(t, dtype=float)
    if not slots or n < 40:
        return flows, {"refined": False}
    horizons = [h for h in opts.get("horizons", (5, 20, 100)) if h < n / 4]
    if not horizons:
        return flows, {"refined": False}
    sd = A.std(axis=1)
    sd[sd == 0] = 1
    inflows = _Inflows(flows, ids, tt, A) if opts.get("profile", True) else None
    x0 = np.array([float(ps[0][0].get(ps[0][1]) or 0.0) for ps in slots])
    count = opts.get("starts", 80)
    prev, dy, t1 = A[:, :-1], np.diff(A, axis=1), tt[1:]

    def put(x):
        for ps, v in zip(slots, x):
            for d, k in ps:
                d[k] = float(v)
        if inflows is not None:
            inflows.update(flows)

    def one_step(m):
        """Each stock's one-step squared error."""
        return ((dy - (m.step(prev, t1) - prev)) ** 2).sum(axis=1)

    plans = []
    for h in horizons:
        s0 = starts_for(n, h, count) + (h % 7)  # other moments than the judge's
        s0 = s0[s0 + h - 1 < n]
        if len(s0):
            moved = (((A[:, s0 + h - 1] - A[:, s0 - 1]) / sd[:, None]) ** 2).sum()
            plans.append((h, s0, tt[s0[None, :] + np.arange(h)[:, None]], A[:, s0 + h - 1], np.sqrt(max(1e-9, moved))))

    def multi(m):
        out = []
        for h, s0, times, obs, scale in plans:
            end = m.run(A[:, s0 - 1], times)
            e = ((end - obs) / sd[:, None]) / scale
            e[~np.isfinite(e)] = 1e3
            out.append(np.clip(e, -1e3, 1e3).ravel())
        return np.concatenate(out)

    # the one-step error as a prior: moving the numbers costs what the single steps say against it,
    # in chi-square units (one-step error / its noise variance at the start); a fall of the
    # multi-step error by a share d is worth d x (price per number) x (numbers)
    price = opts.get("prior")
    put(x0)
    m0 = Model(flows, ids)
    f0 = float((r := multi(m0)) @ r)
    var0 = np.maximum(one_step(m0) / dy.shape[1], 1e-12)
    chi0 = float((one_step(m0) / var0).sum())
    weight = np.sqrt(price * len(x0) * math.log(dy.shape[1]) / max(f0, 1e-12)) if price else 1.0

    def residuals(x):
        put(x)
        m = Model(flows, ids)
        r = multi(m) * weight
        if price:
            chi = float((one_step(m) / var0).sum()) - chi0
            r = np.append(r, np.sqrt(max(0.0, chi)))
        return r

    x_scale = np.maximum(np.abs(x0), 1e-3)
    nfev = 0
    try:
        sol = least_squares(residuals, x0, bounds=(np.zeros_like(x0), np.full_like(x0, np.inf)), x_scale=x_scale,
                            diff_step=1e-3, max_nfev=opts.get("max_nfev", 15), method="trf")
        x1, nfev = sol.x, sol.nfev
    except Exception:
        x1 = x0
    c0, c1 = (lambda r: float(r @ r))(residuals(x0)), (lambda r: float(r @ r))(residuals(x1))
    if not c1 < c0:
        put(x0)
        return flows, {"refined": False, "error": (c0, c1)}
    put(x1)
    f1 = float((r := multi(Model(flows, ids))) @ r)
    return flows, {"refined": True, "error": (f0, f1), "cost": (c0, c1), "nfev": nfev,
                   "moved": [(float(a), float(b)) for a, b in zip(x0, x1)], "labels": names}
