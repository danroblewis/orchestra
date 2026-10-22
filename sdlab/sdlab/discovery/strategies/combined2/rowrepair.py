"""Rows the answer leaves unexplained, repaired with the moves they lack (docs/research/fixes/310-combined2.md,
round 2, 2026-10-22).

The judge picks one specialist's whole model. When every specialist that has a block of rows right runs
away elsewhere, the runaway guard sets it aside and the pick may carry no flows at all for that block
(kubernetes 310 none-short: the pick, realistic_hats, has no move between queue, inflight, retries and the
two counters; the levels say exactly what they are). The later passes only refit the flows a model has.

Here, for each unit (a move needs both stocks in one unit), the measured stocks of that unit form a block.
When one of its stocks has no flow at all in the model while its row (its one-step change) is above LOOSE of
its change's energy (a stock the pick left bare; rows with flows are the other passes' to refit: on the
noisy counts variants a looser trigger traded right moves for spurious ones), the moves and declared outflows the model lacks are offered together: every proportional
move A -> B (A not a counter, both in the block, neither direction present: a loop's two moves both come
from the fit, as queue <-> retries) and A -> outside on a declared
outflow side A has no flow on, fitted at once to the block's residual rows by non-negative least squares
(each move appears in two rows with opposite signs, so mass balance identifies it where a single row
cannot: one move at a time, greedy, took queue -> responses_total for inflight's two exits). The kept
trials are added and the block refitted jointly with the model's own flows (counted._repair_once: the
moves and outside rates by active-set least squares, the floored sides refitted); then each added flow is
dropped again unless it lowers the block's BIC by more than GAIN log n. The result replaces the block
only where its BIC falls by more than GAIN log n. A side declared "input" is never
touched (it is exactly 1 x the input).

Adopting it: copy this file with counted.py and hinge.py and call `apply(result, stocks, run, opts)` on
the answer before the floored refit (hinge.apply).
"""

from __future__ import annotations

import copy
import math

import numpy as np

from scipy.optimize import nnls

from . import counted, hinge

GAIN = 2.0
LOOSE = 1e-4          # a row whose misfit is above this share of its change's energy is unexplained
FLOOR_REL = 1e-9
TINY = 1e-3           # a kept trial must move the rows by more than this share of their misfit's spread


def resolution(levels: dict, rows) -> float:
    """The step the levels are reported in (0.0001 for four decimals; 0 when none is found): a row's change
    carries two roundings, variance q^2 / 6, below which no fit is better than another."""
    vals = np.concatenate([np.asarray(levels[x], dtype=float) for x in rows])
    vals = vals[np.isfinite(vals)]
    for k in range(0, 9):
        q = 10.0 ** -k
        if np.all(np.abs(vals / q - np.round(vals / q)) < 1e-6):
            return q if k else 0.0                      # whole numbers: counts, their own noise is the floor
    return 0.0


def _block_bic(flows, rows, levels, cols, n, floor) -> tuple[float, float, int] | None:
    sse = 0.0
    for x in rows:
        v = counted._row_sse(x, flows, levels, cols, n)
        if v is None:
            return None
        sse += v
    k = counted._nums(flows, set(rows))
    return counted._bic_rows(sse, k, n, len(rows), floor), sse, k


def _trials(cur, rows: set, finals: set, run: dict) -> list[tuple[str, str | None]]:
    have = {(f.get("from"), f.get("to")) for f in cur}
    out = []
    for a in sorted(rows - finals):
        out += [(a, b) for b in sorted(rows) if a != b and (a, b) not in have and (b, a) not in have]
        if "out" in hinge.allowed_sides(a, run, cur) and not any(hinge._side(f, a) == "out" for f in cur):
            out.append((a, None))
    return out


def _prop(a: str, b: str | None) -> dict:
    return {"id": f"repair_{a}_{b or 'out'}", "from": a, "to": b, "ratio": 1, "rate": {"form": "proportional", "stock": a, "k": 0.0}}


def _nnls(cur, rows: set, trials, levels, cols, n) -> list[tuple[str, str | None]]:
    """The trial moves and outflows that a non-negative least squares of the block's residual rows keeps."""
    order = sorted(rows)
    ys = []
    for x in order:
        got = hinge.row_error(x, cur, levels, cols, n)
        if got is None:
            return []
        r, sides = got
        ys.append(r - sides["in"] + sides["out"])
    y = np.concatenate(ys)
    M = np.zeros((len(y), len(trials)))
    for j, (a, b) in enumerate(trials):
        i = order.index(a)
        M[i * n:(i + 1) * n, j] -= cols[a][:n]
        if b is not None:
            i = order.index(b)
            M[i * n:(i + 1) * n, j] += cols[a][:n]
    k, _ = nnls(M, y)
    spread = float(np.std(y)) or 1.0
    return [t for t, v, c in zip(trials, k, M.T) if v > 0 and float(np.std(v * c)) > TINY * spread]


def _block(flows, rows: set, finals: set, run: dict, levels, cols, n, floor):
    """The block's flows with the moves and outflows it lacks added (module docstring); None: no change."""
    base = _block_bic(flows, rows, levels, cols, n, floor)
    if base is None:
        return None
    trials = _trials(flows, rows, finals, run)
    keep = _nnls(flows, rows, trials, levels, cols, n)
    if not keep:
        return None
    got = counted._repair_once(flows + [_prop(a, b) for a, b in keep], rows, levels, cols, n, run)
    if got is None:
        return None
    cur, bic = got[0], counted._bic_rows(got[1], got[2], n, len(rows), floor)
    added = list(keep)
    for t in list(keep):                                # backward: each added flow must earn its place
        fl = [f for f in cur if f.get("id") != _prop(*t)["id"]]
        q = counted._repair_once(fl, rows, levels, cols, n, run)
        if q is None:
            continue
        b2 = counted._bic_rows(q[1], q[2], n, len(rows), floor)
        if b2 < bic + GAIN * math.log(n):
            cur, bic = q[0], b2
            added.remove(t)
    if not added or not bic < base[0] - GAIN * math.log(n):
        return None
    return cur, {"rows": sorted(rows), "added": [f"{a} -> {b or 'outside'}" for a, b in added], "bic_before": base[0], "bic": bic}


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    levels, cols, n = hinge.columns(run, opts)
    if n < 10:
        return result
    unit = {s["id"]: s.get("unit") for s in stocks if s["id"] in levels}
    finals = {s["id"] for s in stocks if s.get("final")}
    out = copy.deepcopy(result)
    flows = out["flows"]
    if any(x and x not in levels for f in flows for x in (f.get("from"), f.get("to"))):
        return result                                   # hidden stocks: their rows are not known here
    notes = []
    for u in sorted({v for v in unit.values() if v is not None}):
        rows = {s for s, v in unit.items() if v == u}
        if len(rows) < 2:
            continue
        loose = False
        for x in rows:
            v = counted._row_sse(x, flows, levels, cols, n)
            if v is None:
                loose = False
                break
            energy = float(np.sum(hinge.delta(levels, x, n) ** 2))
            bare = not any(x in (f.get("from"), f.get("to")) for f in flows)
            loose = loose or (bare and v > LOOSE * max(energy, 1e-300))
        if not loose:
            continue
        scale = max(1e-12, max(float(np.abs(hinge.delta(levels, x, n)).max()) for x in rows))
        floor = len(rows) * n * max((FLOOR_REL * scale) ** 2, resolution(levels, rows) ** 2 / 6)
        got = _block(flows, rows, finals, run, levels, cols, n, floor)
        if got is None:
            continue
        flows[:] = got[0]
        notes.append(got[1])
    if notes:
        out["repaired_rows"] = notes
    return out
