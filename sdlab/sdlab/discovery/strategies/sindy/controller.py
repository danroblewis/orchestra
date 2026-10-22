# sindy's copy of engine_forms/controller.py at 2bca23f (rule 11: copied, never imported; port-sindy, 2026-10-22).
"""A count stock driven to a quantized target (k8s-308, docs/research/fixes/308-engine_forms.md, 2026-10-21).

A stock whose levels are whole numbers and which, most steps, does not change at all is not drained or
filled at a rate: something counts it up and down in whole units when another quantity crosses a
threshold (a controller: replicas scaled to a load, machines added for a demand). Its one-step changes
are events, and a linear rate of the levels can only smear them.

The form read here is the gap to a quantized target, one per direction, each on its own declared side:

- up:   max(0, min(HI, ceil(X / a)) - S)   S counted up to the whole number of units X needs at `a` each;
- down: max(0, S - max(LO, ceil(X / b)))   S counted down to the units X needs at `b` each;

each optionally capped at a step size (`min(c, ...)`) where the events are smaller than the gap, and the
clamps HI / LO written only where the data show them binding (a step at the highest / lowest level where
the threshold says move and the stock did not). The thresholds follow from where the events happen: S is
counted up exactly when X > a S and down exactly when X <= b (S - 1), so a (b) is any number between the
largest X / S on a step without (with) the event and the smallest one with (without) it; the middle of that
interval is taken. The driver X is any measured stock or input; the one that separates the events
exactly is used.

The form replaces the stock's outside flows only where it explains every one-step change of the stock
exactly (it is either right or it is not: a controller acts exactly) and the stock has no move; otherwise
nothing changes. General: it reads only the measured levels, the inputs and the declared boundary.
"""

from __future__ import annotations

import copy
import math

import numpy as np

from . import boundary as _boundary

MIN_EVENTS = 3          # events in a direction before its threshold is read
QUIET = 0.5             # the share of steps with no change a count stock needs


def _series(levels: dict, inputs: dict, n: int) -> dict:
    out = {}
    for name, v in list(levels.items()) + list(inputs.items()):
        a = np.asarray(v, dtype=float)
        if a.shape[0] >= n and np.all(np.isfinite(a[:n])):
            out.setdefault(name, a[:n])
    return out


def _interval(on: np.ndarray, off: np.ndarray):
    """(lo, hi) with every off-value <= lo < hi <= ... every on-value above: the event happens where the
    ratio is above the threshold. None when no threshold separates them."""
    if not on.size:
        return None
    lo = float(np.max(off)) if off.size else -math.inf
    hi = float(np.min(on))
    return (lo, hi) if lo < hi else None


def _num(x: float) -> str:
    return repr(float(round(x, 6)))


def _up(S0, X0, dS, top):
    """The up-direction controller on driver X0, or None: (expr pieces, predicted amounts, numbers)."""
    ev = dS > 0
    if ev.sum() < MIN_EVENTS or np.any(S0 <= 0):
        return None
    r = X0 / S0
    clamp = None
    iv = _interval(r[ev], r[~ev])
    if iv is None:                                       # perhaps held at the top: steps there that would rise but cannot
        quiet = ~ev & (S0 < top)
        iv = _interval(r[ev], r[quiet])
        if iv is None or not np.any(~ev & (S0 >= top) & (r > iv[0])):
            return None
        clamp = top
    if not math.isfinite(iv[0]):
        return None
    a = 0.5 * (iv[0] + iv[1])
    target = np.ceil(X0 / a)
    if clamp is not None:
        target = np.minimum(clamp, target)
    gap = np.maximum(0.0, target - S0)
    return a, clamp, gap


def _down(S0, X0, dS, bottom):
    ev = dS < 0
    if ev.sum() < MIN_EVENTS or np.any(S0[ev] <= 1):
        return None
    ok = S0 > 1
    r = np.where(ok, X0 / np.maximum(S0 - 1, 1e-12), math.inf)
    # down where X / (S - 1) <= b: as a rise in -r
    clamp = None
    iv = _interval(-r[ev], -r[~ev & ok])
    if iv is None:
        quiet = ~ev & ok & (S0 > bottom)
        iv = _interval(-r[ev], -r[quiet])
        if iv is None or not np.any(~ev & ok & (S0 <= bottom) & (-r > iv[0])):
            return None
        clamp = bottom
    if not math.isfinite(iv[0]):
        return None
    b = -0.5 * (iv[0] + iv[1])
    target = np.ceil(X0 / b)
    if clamp is not None:
        target = np.maximum(clamp, target)
    gap = np.maximum(0.0, S0 - target)
    return b, clamp, gap


def _capped(gap, size):
    """The step cap c with min(c, gap) == size on every event, None when the gap itself is the size,
    False when neither holds."""
    on = gap > 0
    if np.all(np.abs(gap[on] - size[on]) < 1e-9):
        return None
    c = float(np.max(size[on]))
    return c if np.all(np.abs(np.minimum(c, gap[on]) - size[on]) < 1e-9) else False


def _fit(S0, dS, cols: dict, name: str, which: str):
    """The best (exact) controller for one direction: (expr, amounts, driver) or None."""
    best = None
    size = np.abs(dS) * ((dS > 0) if which == "up" else (dS < 0))
    for x, X0 in cols.items():
        if x == name:
            continue
        got = (_up if which == "up" else _down)(S0, X0, dS, float(np.max(S0)) if which == "up" else float(np.min(S0)))
        if got is None:
            continue
        k, clamp, gap = got
        cap = _capped(gap, size)
        if cap is False:
            continue
        amount = gap if cap is None else np.minimum(cap, gap)
        if np.any(np.abs(amount - size) > 1e-9):
            continue
        if which == "up":
            tgt = f"ceil({x} / {_num(k)})"
            tgt = f"min({_num(clamp)}, {tgt})" if clamp is not None else tgt
            e = f"max(0, {tgt} - {name})"
        else:
            tgt = f"ceil({x} / {_num(k)})"
            tgt = f"max({_num(clamp)}, {tgt})" if clamp is not None else tgt
            e = f"max(0, {name} - {tgt})"
        e = f"min({_num(cap)}, {e})" if cap is not None else e
        n = 1 + (clamp is not None) + (cap is not None)
        if best is None or n < best[3]:
            best = (e, amount, x, n)
    return best


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """The result with each count stock's outside flows written as a quantized-target controller where
    one explains its every change exactly (what was replaced under "controller")."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    levels = run.get("levels") or {}
    inputs = (opts or {}).get("inputs") or {}
    n = len(run.get("t") or [])
    if n < 3:
        return result
    cols = _series(levels, inputs, n)
    b = _boundary.Boundary(run)
    out, log = copy.deepcopy(result), []
    for s in [x["id"] for x in stocks]:
        S = cols.get(s)
        if S is None or s not in levels or np.any(np.abs(S - np.round(S)) > 1e-9):
            continue
        dS = np.diff(S)
        if np.mean(dS == 0) < QUIET or not np.any(dS):
            continue
        flows = out["flows"]
        if any(f.get("from") and f.get("to") and s in (f.get("from"), f.get("to")) for f in flows):
            continue                                             # a stock with a move: not this form
        S0 = S[:-1]
        others = {k: v[:-1] for k, v in cols.items() if k != s}
        made = {}
        for which, side in (("up", "in"), ("down", "out")):
            ev = dS > 0 if which == "up" else dS < 0
            if not ev.any():
                continue
            if not b.may(s, side, "estimate"):
                made = None
                break
            got = _fit(S0, dS, others, s, which)
            if got is None:
                made = None
                break
            made[which] = got
        if not made:
            continue
        pred = sum(made[w][1] * (1 if w == "up" else -1) for w in made)
        if np.any(np.abs(pred - dS) > 1e-9):
            continue
        keep = [f for f in flows if not ((not f.get("from") and f.get("to") == s) or (f.get("from") == s and not f.get("to")))]
        for w, (e, _, x, _) in made.items():
            f = {"from": None, "to": s} if w == "up" else {"from": s, "to": None}
            keep.append({**f, "id": f"controller_{s}_{w}", "rate": {"form": "expr", "expr": e}})
            log.append(f"{s} {w}: {e} (driver {x})")
        out["flows"] = keep
    if log:
        out["controller"] = log
    return out
