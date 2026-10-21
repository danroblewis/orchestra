"""z3robust: z3exact's class searched by Z3's optimiser, tolerant of noise (docs/research/z3robust.md).

z3exact (docs/research/z3.md) asks Z3 for the fewest terms that fit every one-step change within the data's
rounding: exact on noise-free data, nothing on noisy data. z3robust keeps its candidate class (core.py, a
copy: moves between stocks of one unit reading one of their two stocks, outside terms only where the
declared boundary allows them, a declared "input" inflow fixed at 1 x its series, the offered capacity
series MIN(X, theta Y) with its regime (capmin.py, a copy), per-era columns for announced eras plus a
whole-run column each, goal gaps as a constant and a level on one row) and replaces the equality by an
optimisation (robust.py): per-step residuals beyond an epsilon band (in units of each stock's noise level,
estimated from the data) are slack variables, and Z3 minimises their sum (L1) plus a price of log n per
included term, on a sample of the steps. The structure's numbers are then refitted by least squares on
every step (rows weighted by their noise level, steps whose residual is gross left out once), with the
declared inputs at 1.

The classes tried: ends moves with the boundary as written ("kinds"), and, where a boundary is declared,
by sides as the scorer reads it ("sides"); the lower objective is kept (kinds on a tie).
"""

from __future__ import annotations

import time

import numpy as np

from . import capmin as _capmin
from . import core, flows, robust

TOTAL = 90.0                  # seconds for everything (the ladder's item timeout is 120 s; Z3 is not interruptible)
SOLVE = 25.0                  # seconds of Z3 per class at most
CLASSES = (("ends", "kinds"), ("ends", "sides"))
EQUATIONS = "compressed"      # what Z3 reads: "compressed" (rotated equations of every step) or "blocks"
ENCODING = "band"             # robust.solve's encoding: "band" (MaxSMT under an L1 ball per row), "weighted", "maxsmt", "ladder"
TRIM = 5.0                    # the refit leaves out steps whose residual exceeds this many noise levels (once)


def _fixed(p: core.Problem, run: dict) -> dict[int, float]:
    """Terms fixed at 1 when included: an outside inflow reading a measured input on a stock whose declared
    inflow side has the kind "input" (the series is that inflow, 2026-10-21, the user)."""
    if not run.get("boundary_declared"):
        return {}
    out = {}
    for m, t in enumerate(p.terms):
        c = p.cols[t.col]
        kinds = ((run.get("boundary") or {}).get(t.a) or {}).get("in") or []
        if t.kind == "outside" and c.kind == "input" and "input" in kinds and "in" in t.sides and not _capmin.level_series(c.name):
            out[m] = 1.0
    return out


def refit(p: core.Problem, sup: list[int], sigma: np.ndarray, fixed: dict[int, float]) -> tuple[np.ndarray, float, int]:
    """Least-squares numbers of a structure on every step (all rows jointly, each row divided by its noise
    level; the fixed terms at their numbers), once more without the steps whose residual exceeds TRIM noise
    levels: (numbers in sup's order, the largest absolute residual, steps left out)."""
    X, Y = core._floats(p)
    S, n = Y.shape
    W = 1.0 / sigma
    G = np.zeros((S * n, len(sup)))
    for j, m in enumerate(sup):
        t = p.terms[m]
        for r, sid in enumerate(p.ids):
            sg = core._contrib(p, t, sid)
            if sg:
                G[r * n:(r + 1) * n, j] = sg * X[:, t.col] * W[r]
    y = (Y * W[:, None]).reshape(-1)
    free = [j for j, m in enumerate(sup) if m not in fixed]
    fx = np.array([fixed.get(m, 0.0) for m in sup])
    y0 = y - G @ fx
    k = fx.copy()
    rows = np.ones(S * n, dtype=bool)
    dropped = 0
    for _ in range(2):
        if free:
            sol, *_ = np.linalg.lstsq(G[rows][:, free], y0[rows], rcond=None)
            k[free] = sol
        res = y - G @ k
        bad = np.abs(res) > TRIM
        if not bad.any() or bad.mean() > 0.2:
            break
        rows = ~bad
        dropped = int(bad.sum())
    res = (y - G @ k).reshape(S, n) / W[:, None]
    return k, float(np.abs(res).max()) if res.size else 0.0, dropped


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    began = time.perf_counter()
    declared = bool(run.get("boundary_declared"))
    tried, best = [], None
    for moves, rule in CLASSES:
        if rule == "sides" and not declared:
            break
        left = TOTAL - (time.perf_counter() - began)
        if left < 5:
            tried.append(f"[{moves}, {rule}] not tried (out of time)")
            break
        p = core.prepare(stocks, run, opts, moves=moves, boundary=rule, pooled=True)
        if p.steps < 20:
            return {"flows": [], "note": "z3robust: too few steps."}
        if best is not None and [t.key(p.cols) for t in p.terms] == best["keys"]:
            continue                                        # the same class as the one solved
        B = robust.Compressed(p) if EQUATIONS == "compressed" else robust.Blocks(p)
        sigma = robust.noise_scales(p, B)
        cand = robust.screen(p, B, sigma)
        fixed = {m: v for m, v in _fixed(p, run).items() if m in cand}
        got = robust.solve_guarded(p, B, cand, sigma, fixed, min(SOLVE, left - 8), encoding=ENCODING)
        if got["support"] is not None:         # the classes compared on one scale whatever the encoding
            got["objective"] = robust.objective(p, B, got["support"], got["numbers"], sigma, got["price"])
        tried.append(f"[{moves}, {rule}] {got['status']}: {len(got['support'] or [])} of {got['candidates']} candidates "
                     f"({len(p.terms)} in the class), objective {got.get('objective', float('nan')):.4g} on {got["n"]} equations per stock "
                     f"from {got['m']} steps, {got['seconds']:.2f} s")
        if got["support"] is None:
            continue
        if best is None or got["objective"] < best["got"]["objective"] - 1e-9:
            best = {"p": p, "got": got, "sigma": sigma, "B": B, "fixed": fixed, "moves": moves, "rule": rule,
                    "keys": [t.key(p.cols) for t in p.terms]}
    if best is None:
        return {"flows": [], "note": "z3robust: Z3 found no model within its time: " + "; ".join(tried),
                "z3robust": {"tried": tried, "seconds": round(time.perf_counter() - began, 3)}}
    p, got = best["p"], best["got"]
    sup = sorted(got["support"])
    ss = robust.step_sigma(p, sup, best["sigma"], best["B"])
    k, miss, dropped = refit(p, sup, ss, best["fixed"])
    while any(robust.link(p, m) and v < 0 for m, v in zip(sup, k)):     # a link the refit turned negative: dropped
        worst = min((v, m) for m, v in zip(sup, k) if robust.link(p, m))[1]
        sup = [m for m in sup if m != worst]
        k, miss, dropped = refit(p, sup, ss, best["fixed"])
    fl = flows.fixed_inputs(flows.flows_of(p, sup, k), run, (opts.get("inputs") or {}).keys())
    note = (f"z3robust: {len(sup)} terms in the class '{best['moves']}, {best['rule']}' (Z3 Optimize, {ENCODING}: "
            f"{got['n']} equations per stock from {got['m']} steps, price {got['price']:.3g} per term; {got['status']}; chosen: {got.get('from')}); numbers by "
            f"least squares on every step ({dropped} gross residuals left out); largest one-step residual {miss:.3g}; noise levels "
            + ", ".join(f"{s}={v:.3g}" for s, v in zip(p.ids, best["sigma"])) + "; " + "; ".join(tried))
    return {"flows": fl, "note": note, "z3robust": {"status": got["status"], "terms": len(sup), "moves": best["moves"],
            "boundary": best["rule"], "objective": got["objective"], "solve_seconds": got["seconds"],
            "seconds": round(time.perf_counter() - began, 3), "blocks": got["n"], "block_steps": got["m"], "candidates": got["candidates"],
            "structure": [p.terms[m].key(p.cols) for m in sup], "from": got.get("from"), "smallest": got.get("smallest"),
            "k_min": got.get("k_min"), "warm": got.get("warm")}}


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:
    """_identify with a capacity limit MIN(a X, b Y) offered where the data show one (capmin.py)."""
    return _capmin.wrap(_identify, stocks, run, opts, *args, **kw)
