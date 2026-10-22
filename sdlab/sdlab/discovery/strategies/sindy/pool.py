# sindy's copy of engine_forms/pool.py at 2bca23f (rule 11: copied, never imported; port-sindy, 2026-10-22).
"""A pool the declared boundary forces across units, read from its two rows (k8s-316, docs/research/fixes/316-engine_forms.md).

Where the boundary leaves x (the only stock of its unit) no outside outflow and z (the only stock of another unit)
no outside inflow (capmin.forced_pairs), what x loses can only go into z: pgbouncer's waiting queries getting pool
connections. The base fit pairs moves within one unit only, so it reads such a move as two unrelated outside
terms, which the boundary does not have. On exact data reread.py re-reads the pair; on noisy rows (counts) nothing
did. Here the pair's two rows are read together, on any data:

    dx = sum_j a_j C_j - m          (x's declared outside inflows: the terms of the summed row read positively)
    dz = m - sum_j b_j C_j          (z's declared outside outflow: the terms read negatively)
    m  = min(g x, c - d z)          (the move, limited by a fixed pool z occupies; d = 0: a fixed cap)

The summed row dx + dz has no m: its terms are the best subset (up to MAX_TERMS columns, BIC) of the non-final
levels, inputs and a constant, and their signs give the sides. The move's numbers are started from a grid over the
pool and refitted with the sides by least squares on both rows at once. The pair is replaced only when the answer
has no move x -> z, the two rows' Gaussian BIC improves by more than PRICE x log T, and nothing leaves the
declared boundary. Reads only levels, inputs, units and the boundary.
"""

from __future__ import annotations

import copy
import itertools
import math

import numpy as np
from scipy.optimize import least_squares

from . import boundary as _boundary
from .capmin import POOLS, forced_pairs

MAX_TERMS = 4          # columns of the summed row
PRICE = 6.0            # the BIC gain the re-read pair must show, in log T (as capmin.py's PRICE)
RESOLUTION = 1e-8      # a residual variance below this share of the mean squared change is rounding (as capmin.py)
GRID = 24              # cap candidates (quantiles of the move's amount on the capped side)


def _bic(r: np.ndarray, k: int, floor: float) -> float:
    T = len(r)
    return T * math.log(float(r @ r) / T + floor) + k * math.log(T)


def _subset(y: np.ndarray, C: np.ndarray, floor: float) -> tuple[list[int], np.ndarray]:
    """The best column subset of y (Gaussian BIC), up to MAX_TERMS columns."""
    best = (_bic(y, 0, floor), [], np.zeros(0))
    for n in range(1, MAX_TERMS + 1):
        found = False
        for sub in itertools.combinations(range(C.shape[0]), n):
            A = C[list(sub)].T
            k, *_ = np.linalg.lstsq(A, y, rcond=None)
            b = _bic(y - A @ k, n, floor)
            if b < best[0]:
                best, found = (b, list(sub), k), True
        if not found and n >= 2:
            break
    return best[1], best[2]


def _start(m: np.ndarray, X: np.ndarray, Z: np.ndarray) -> tuple[float, float, float] | None:
    """(g, c, d) of m ~ min(g X, c - d Z) from a grid: the pool beta (a multiple of Z's largest level) and the
    share theta of its headroom, the rest by least squares; None when nothing fits."""
    best = None
    zmax = float(np.max(Z))
    if zmax <= 0:
        return None
    for f in POOLS + (math.inf,):
        H = np.ones_like(Z) if math.isinf(f) else f * zmax - Z      # math.inf: a fixed cap (d = 0)
        ratio = X / np.maximum(H, 1e-12)
        for th in np.unique(np.quantile(ratio, np.linspace(0.05, 0.95, GRID))):
            u = np.minimum(X, th * H)
            g = float(u @ m) / max(float(u @ u), 1e-300)
            r = m - g * u
            sse = float(r @ r)
            if g > 0 and (best is None or sse < best[0]):
                best = (sse, g, g * th * (1.0 if math.isinf(f) else f * zmax), 0.0 if math.isinf(f) else g * th)
    return None if best is None else best[1:]


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None, log: list | None = None) -> dict:
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    pairs = forced_pairs(stocks, run)
    if not pairs:
        return result
    opts = opts or {}
    data = _boundary.Data(stocks, run, opts)
    if not data.usable:
        return result
    ids = data.ids
    final = {s["id"] for s in stocks if s.get("final")}
    t = [float(x) for x in run["t"]]
    at = {x: i for i, x in enumerate(t)}
    ins = []
    for name, v in (opts.get("inputs") or {}).items():
        if name in ids or str(name).startswith("capmin__"):
            continue
        v = np.asarray(v, dtype=float)
        if len(v) == len(t):
            ins.append((name, np.array([v[at[float(x)]] for x in data.tt])))
    names = [s for s in ids if s not in final] + [n for n, _ in ins] + ["1"]
    C = np.vstack([data.L[ids.index(s)][None, :] for s in ids if s not in final] + [u[None, :] for _, u in ins]
                  + [np.ones((1, data.T))])
    from .hidden import _change
    from .reread import _per_side, _rate

    b = _boundary.Boundary(run)
    flows = copy.deepcopy(result["flows"])
    trace = []
    for x, z in pairs:
        if any(f.get("from") == x and f.get("to") == z for f in flows):
            continue
        xi, zi = ids.index(x), ids.index(z)
        dx, dz = data.dy[xi], data.dy[zi]
        T = len(dx)
        X, Z = data.L[xi], data.L[zi]
        floors = [RESOLUTION * float(np.mean(dx ** 2)) + 1e-300, RESOLUTION * float(np.mean(dz ** 2)) + 1e-300]
        try:
            now = data.dy - _change(flows, data, dict(ins))
        except Exception:                                 # noqa: BLE001  (a flow the simulator cannot evaluate)
            continue
        touches = [f for f in flows if x in (f.get("from"), f.get("to")) or z in (f.get("from"), f.get("to"))]
        k_now = sum(len((f.get("rate") or {}).get("terms") or []) + 1 for f in touches)
        before = _bic(now[xi], 0, floors[0]) + _bic(now[zi], 0, floors[1]) + k_now * math.log(T)
        sub, k = _subset(dx + dz, C, min(floors))
        if not sub:
            continue
        ins_x = {j: float(v) for j, v in zip(sub, k) if v > 0}
        out_z = {j: -float(v) for j, v in zip(sub, k) if v < 0}
        if (ins_x and not b.may(x, "in", "estimate")) or (out_z and not b.may(z, "out", "estimate")):
            continue
        Ax = C[list(ins_x)].T @ np.array(list(ins_x.values())) if ins_x else np.zeros(T)
        Oz = C[list(out_z)].T @ np.array(list(out_z.values())) if out_z else np.zeros(T)
        m0 = 0.5 * ((Ax - dx) + (dz + Oz))                 # the move as both rows see it
        s0 = _start(m0, X, Z)
        if s0 is None:
            continue
        ji, jo = list(ins_x), list(out_z)

        def resid(p):
            a, o, (g, c, d) = p[:len(ji)], p[len(ji):len(ji) + len(jo)], p[-3:]
            m = np.minimum(g * X, c - d * Z)
            rx = dx - (C[ji].T @ a if ji else 0.0) + m
            rz = dz - m + (C[jo].T @ o if jo else 0.0)
            return np.concatenate([rx, rz])

        p0 = np.array(list(ins_x.values()) + list(out_z.values()) + list(s0))
        lo = np.array([0.0] * (len(ji) + len(jo)) + [0.0, 0.0, 0.0])
        try:
            fit = least_squares(resid, p0, bounds=(lo, np.full(len(p0), np.inf)), x_scale="jac", max_nfev=400 * len(p0))
        except Exception:                                 # noqa: BLE001
            continue
        p = fit.x
        g, c, d = (float(v) for v in p[-3:])
        new = [{"from": None, "to": x, "rate": _rate({names[j]: float(v) for j, v in zip(ji, p[:len(ji)])}, names)}] if ji else []
        new += [{"from": z, "to": None, "rate": _rate({names[j]: float(v) for j, v in zip(jo, p[len(ji):len(ji) + len(jo)])}, names)}] if jo else []
        new = _per_side(new, b)
        cap = f"{c!r} + {-d!r} * {z}" if d > 0 else f"{c!r}"
        new.append({"id": f"pool:{x}:{z}", "from": x, "to": z, "rate": {"form": "expr", "expr": f"min({g!r} * {x}, {cap})"}})
        for f in new:
            rd = f["rate"]
            if rd.get("form") == "proportional" and rd.get("stock") in {n for n, _ in ins} and f["from"] is None:
                f["input"] = rd["stock"]
        if _boundary.violations(new, ids, b, {n for n in (opts.get("inputs") or {})}):
            continue
        cand = [f for f in flows if f not in touches] + new
        try:
            r2 = data.dy - _change(cand, data, dict(ins))
        except Exception:                                 # noqa: BLE001
            continue
        k_new = sum(len((f.get("rate") or {}).get("terms") or []) + 1 for f in new) + 2
        after = _bic(r2[xi], 0, floors[0]) + _bic(r2[zi], 0, floors[1]) + k_new * math.log(T)
        if after < before - PRICE * math.log(T):
            flows = cand
            trace.append(f"{x} -> {z}: pool read from both rows, BIC {before:.0f} -> {after:.0f}")
    if not trace:
        return result
    out = dict(result)
    out["flows"] = flows
    out["pool"] = trace
    if log is not None:
        log.extend(trace)
    return out
