# Vendored for combined2 from sdlab/discovery/strategies/own_tables/split.py at commit 67a604b (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""A row's net curve g(x) of its own level, read back as flows to and from outside.

Every SD Lab rate is floored at 0, so a curve that is below 0 everywhere is one outflow c x table(x),
above 0 everywhere one inflow. A curve that crosses 0 needs two flows, and the data say only their
difference. Three readings, each one flow more than a single table:

- a drain k x (the stock's own level) and an inflow table g(x) + k x, k the slope g has over most of
  the range (the length-weighted median of its segments' slopes), raised if needed so the inflow is
  never below 0: a switch or a ramp on top of a plain drain (a heater shut by its own level);
- a constant inflow c = max g and an outflow table c - g(x);
- a constant outflow c = -min g and an inflow table g(x) + c.

The reading kept is the one whose table moves least (total variation: the sum of the jumps between
its points; the drain's reading must move at least 10% less than the curve itself), so a curve's straight part goes to the drain and the table is flat where it can be;
between the last two (the same variation) a falling curve is an outflow that rises with the level,
a rising one an inflow.
"""

from __future__ import annotations

import numpy as np


def _r(v: float) -> float:
    return float(f"{float(v):.6g}")


def _flow(src, dst, rate: dict, **extra) -> dict:
    return {"from": src, "to": dst, "ratio": 1, "rate": rate, "rates": [rate], "nearly": [], "bothWays": False, **extra}


def table_flow(src, dst, stock: str, knots: np.ndarray, values: np.ndarray) -> dict | None:
    """value x table(stock) with the table's largest point at 1; None if the table is all 0."""
    v = np.maximum(0.0, np.asarray(values, dtype=float))
    top = float(v.max())
    if top <= 0:
        return None
    rate = {"form": "constant", "value": _r(top)}
    pts = [[_r(a), _r(b / top)] for a, b in zip(knots, v)]
    return _flow(src, dst, rate, driver=stock, own_table=True, effects=[{"stock": stock, "shape": "table", "points": pts}])


def wmedian_slope(knots: np.ndarray, values: np.ndarray) -> float:
    dx = np.diff(knots)
    s = np.diff(values) / np.maximum(1e-12, dx)
    o = np.argsort(s)
    c = np.cumsum(dx[o])
    return float(s[o][np.searchsorted(c, 0.5 * c[-1])])


def tv(v: np.ndarray) -> float:
    return float(np.abs(np.diff(v)).sum())


def readings(knots: np.ndarray, g: np.ndarray, eps: float) -> list[dict]:
    """Every reading of the curve, the preferred first: {table: +1 (inflow) or -1 (outflow), values
    (the table's, >= 0), other: None, ("drain", k), ("in", c) or ("out", c)}."""
    knots, g = np.asarray(knots, dtype=float), np.asarray(g, dtype=float)
    if g.max() <= eps:
        return [{"table": -1, "values": np.maximum(0.0, -g), "other": None}]
    if g.min() >= -eps:
        return [{"table": 1, "values": np.maximum(0.0, g), "other": None}]
    out = []
    k = -wmedian_slope(knots, g)
    pos = knots > 1e-12
    if np.any(~pos & (g < -eps)):
        k = -1.0
    else:
        k = max(k, float(np.max(np.where(pos, -g / np.where(pos, knots, 1.0), 0.0))))
    if k > 0:
        v = g + k * knots
        out.append((tv(v), 0, {"table": 1, "values": np.maximum(0.0, v), "other": ("drain", k)}))
    c_in, c_out = float(g.max()), float(-g.min())
    falling = g[-1] < g[0]
    out.append((0.9 * tv(g), 1 if falling else 2, {"table": -1, "values": np.maximum(0.0, c_in - g), "other": ("in", c_in)}))
    out.append((0.9 * tv(g), 2 if falling else 1, {"table": 1, "values": np.maximum(0.0, g + c_out), "other": ("out", c_out)}))
    out.sort(key=lambda r: (round(r[0], 9), r[1]))
    return [r for _, _, r in out]


def name(rd: dict) -> str:
    t = "an inflow table" if rd["table"] > 0 else "an outflow table"
    if rd["other"] is None:
        return t
    kind, v = rd["other"]
    return {"drain": f"drain {v:.4g}", "in": f"inflow {v:.4g}", "out": f"outflow {v:.4g}"}[kind] + " and " + t


def flows(row: str, knots: np.ndarray, rd: dict) -> list[dict]:
    """The reading as flows of the row's stock."""
    out = []
    if rd["other"] is not None:
        kind, v = rd["other"]
        if v > 0:
            if kind == "drain":
                out.append(_flow(row, None, {"form": "proportional", "stock": row, "k": _r(v)}))
            elif kind == "in":
                out.append(_flow(None, row, {"form": "constant", "value": _r(v)}))
            else:
                out.append(_flow(row, None, {"form": "constant", "value": _r(v)}))
    f = table_flow(None, row, row, knots, rd["values"]) if rd["table"] > 0 else table_flow(row, None, row, knots, rd["values"])
    return out + ([f] if f else [])


def extend(flows: list[dict]) -> list[dict]:
    """The tables this strategy wrote, continued past the levels the run visited along their end
    segments' slopes (to 0 below, and one visited range above; values floored at 0). An SD table is
    flat beyond its points, which for a drain that bends is the worst guess on a run that goes
    further (phys-draining-tank none-short: the fresh run's skill fell to 88% against 98% for the
    straight line); the continued slope is the straight line's guess there. The run never sees
    these points, so the fit is unchanged; they are added after the choice, not priced."""
    out = []
    for f in flows:
        if not f.get("own_table"):
            out.append(f)
            continue
        e = f["effects"][0]
        pts = [list(p) for p in e["points"]]
        if len(pts) >= 2:
            (x0, y0), (x1, y1) = pts[0], pts[1]
            (xa, ya), (xb, yb) = pts[-2], pts[-1]
            span = xb - x0
            if x0 > 0 and x1 > x0:
                lo = max(0.0, x0 - span)
                pts.insert(0, [_r(lo), _r(max(0.0, y0 - (y1 - y0) / (x1 - x0) * (x0 - lo)))])
            if xb > xa and span > 0:
                pts.append([_r(xb + span), _r(max(0.0, yb + (yb - ya) / (xb - xa) * span))])
        g = {k: v for k, v in f.items() if k != "own_table"}
        g["effects"] = [{**e, "points": pts}]
        out.append(g)
    return out
