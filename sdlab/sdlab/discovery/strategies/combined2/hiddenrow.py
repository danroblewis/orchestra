"""A hidden integrator read by a stock's outside inflow (docs/research/fixes/310-combined2.md, round 2, 2026-10-22).

Some stocks are driven by a quantity nobody measures that builds up and drains: a memory leak that grows
by a fixed amount a step and is freed when a pod restarts. Since 198baf2 the scorer credits a found
model's own hidden stock (the user, 2026-10-21), so the integrator can be written as a stock, not a
schedule standing in for it (a schedule is "fits, not robust").

For each measured, non-final stock S whose outside inflow side is open (declared `in`, not a measured
input) and whose row the model leaves well above rounding, S's row (its one-step change less the moves
between S and other stocks) is refitted as

    in  = c + b H + sum_j w_j Z_j          out = a S

where H is a hidden stock, H' = 1 - d_t H (an inflow of 1 a step: H's scale is not identifiable; the
read coefficient b carries it), started at h0 >= 0. H's level is linear in (h0, 1): H = h0 P + Q with P,
Q stepped from d_t, so S's row is linear in [1, S, P, Q, Z...]. The drain fraction d_t is m times
the per-unit fraction of a flow the model already has that reads a table effect on a measured level
(k x A x table(X): d_t = m k table(X_t)), m by golden section from 1: the same event (an OOM kill) acting
on another quantity per unit. A constant drain is not offered: with a constant inflow its H is a fixed
curve in time, a schedule standing in for state (the scorer's "fits, not robust"), not a stock the data
show.
The Z are measured levels, inputs and per-unit rates X / max(1, Y) of two measured stocks, chosen by
forward selection on BIC (at most MAX_EXTRA). The rewrite is kept only where S's row's BIC falls by more
than GAIN log n against both the model's own sides and the best plain refit (the same columns, no H).

Adopting it: copy this file (it needs hinge.py's columns/row_error/amount/allowed_sides) and call
`apply(result, stocks, run, opts)` on the final answer; it adds `inferred_levels` for the hidden stocks.
"""

from __future__ import annotations

import copy
import math

import numpy as np

from . import hinge

GAIN = 2.0
FLOOR_REL = 1e-9
MAX_EXTRA = 3          # measured columns or per-unit rates S's inflow may read beside H
SKIP_REL = 1e-6        # a row the model explains to this share of its change's energy is left alone
TINY = 1e-3           # a column that moves the row by less than this share of its change's spread is no term


def _integrator(d: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """(P, Q) over n+1 steps: H = h0 P + Q for H' = 1 - d H."""
    P, Q = np.ones(n + 1), np.zeros(n + 1)
    keep = np.clip(1.0 - d[:n], 0.0, 1.0)
    for t in range(n):
        P[t + 1] = P[t] * keep[t]
        Q[t + 1] = Q[t] * keep[t] + 1.0
    return P, Q


def _bic(sse: float, k: int, n: int, floor: float) -> float:
    return n * math.log(max(sse, floor) / n) + k * math.log(n)


def _fit(y: np.ndarray, base: list[np.ndarray], pool: dict, n: int, floor: float, k0: int) -> dict:
    """Forward selection of at most MAX_EXTRA columns of `pool` beside `base`: {"bic", "sse", "b", "names"}."""
    def ls(names):
        M = np.column_stack(base + [pool[x] for x in names])
        b, *_ = np.linalg.lstsq(M, y, rcond=None)
        e = M @ b - y
        sse = float(e @ e)
        return {"bic": _bic(sse, k0 + len(base) + len(names), n, floor), "sse": sse, "b": b, "names": list(names), "e": e}
    best = ls([])
    for _ in range(MAX_EXTRA):
        step = None
        for x in pool:
            if x in best["names"]:
                continue
            got = ls(best["names"] + [x])
            if step is None or got["bic"] < step["bic"]:
                step = got
        if step is None or not _earns(best, step, n, floor) or \
                float(np.std(step["b"][-1] * pool[step["names"][-1]])) < TINY * float(np.std(y)):
            break
            break
        best = step
    return best


def _earns(old: dict, new: dict, n: int, floor: float) -> bool:
    """A column earns its place when it lowers the SSE by more than GAIN log n on the residuals' effective
    number of steps (n (1 - rho) / (1 + rho), rho the lag-1 correlation of the residuals with it): a misfit
    left running in long stretches (an integrator's small error) is a few pieces of evidence, not n, so a
    column that only bends it is not bought; one that removes the structure leaves residuals near white."""
    e = new["e"]
    rho = float(np.corrcoef(e[:-1], e[1:])[0, 1]) if len(e) > 2 and e[:-1].std() > 0 and e[1:].std() > 0 else 0.0
    m = max(2.0, n * (1 - max(0.0, rho)) / (1 + max(0.0, rho)))
    return m * math.log(max(old["sse"], floor) / max(new["sse"], floor)) > GAIN * math.log(n)


def _golden(f, lo: float, hi: float, iters: int = 25) -> float:
    g = (math.sqrt(5) - 1) / 2
    a, b = math.log(lo), math.log(hi)
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = f(math.exp(c)), f(math.exp(d))
    for _ in range(iters):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = f(math.exp(c))
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = f(math.exp(d))
    return math.exp((a + b) / 2)


def _fractions(flows: list[dict], levels: dict, cols: dict, n: int) -> list[tuple[str, np.ndarray, dict]]:
    """The per-unit fractions k x table(X) of the model's flows k x A x table(X) on measured levels."""
    out = []
    for f in flows:
        r = f.get("rate") or {}
        effs = f.get("effects") or []
        if r.get("form") != "proportional" or r.get("stock") not in levels or f.get("from") != r.get("stock") or len(effs) != 1:
            continue
        e = effs[0]
        if e.get("shape") != "table" or e.get("stock") not in cols or not e.get("points"):
            continue
        pts = sorted((float(a), float(b)) for a, b in e["points"])
        frac = float(r.get("k") or 0.0) * np.maximum(0.0, np.interp(cols[e["stock"]][:n], [p[0] for p in pts], [p[1] for p in pts]))
        if frac.max() <= 0 or frac.max() > 1:
            continue
        key = (e["stock"], tuple(pts), round(float(r.get("k") or 0.0), 12))
        if any(o[0] == key for o in out):
            continue
        out.append((key, frac, {"k": float(r.get("k") or 0.0), "effect": copy.deepcopy(e)}))
    return out


def _ratios(levels: dict, cols: dict, finals: set, n: int) -> dict:
    stocks = [s for s in levels if s not in finals]
    out = {}
    for x in [*stocks, *[c for c in cols if c not in levels]]:
        for y in stocks:
            if x == y:
                continue
            v = cols[x][:n] / np.maximum(1.0, cols[y][:n])
            if np.std(v) > 0:
                out[f"{x} / max(1, {y})"] = v
    return out


def _row(s: str, flows: list[dict], levels: dict, cols: dict, n: int):
    """S's row less its moves, and the numbers and SSE of its outside sides; None where a flow cannot be evaluated."""
    got = hinge.row_error(s, flows, levels, cols, n)
    if got is None:
        return None
    r, sides = got
    k = 0
    for f in flows:
        if hinge._side(f, s):
            k += hinge._k(f) + sum(len(e.get("points") or []) for e in f.get("effects") or [])
    return r, float(np.sum((r - sides["in"] + sides["out"]) ** 2)), k


def _one(s: str, flows: list[dict], levels: dict, cols: dict, n: int, fracs, ratios: dict, finals: set):
    got = _row(s, flows, levels, cols, n)
    if got is None:
        return None
    y, sse_cur, k_cur = got
    energy = float(np.sum(hinge.delta(levels, s, n) ** 2))
    if sse_cur <= SKIP_REL * energy:
        return None
    scale = max(1e-12, float(np.abs(hinge.delta(levels, s, n)).max()))
    floor = n * (FLOOR_REL * scale) ** 2
    one, S = np.ones(n), cols[s][:n]
    pool = {c: cols[c][:n] for c in cols if c != s and c not in finals and np.std(cols[c][:n]) > 0}
    pool.update(ratios)
    plain = _fit(y, [one, S], pool, n, floor, 0)

    def with_h(d: np.ndarray, extra_k: int):
        P, Q = _integrator(d, n)
        a = {**_fit(y, [one, S, Q[:n], P[:n]], pool, n, floor, extra_k + 1), "p": True}    # + h0
        b = {**_fit(y, [one, S, Q[:n]], pool, n, floor, extra_k), "p": False}              # h0 = 0
        if a["b"][2] > 0 and a["b"][3] / a["b"][2] < 0:
            a["bic"] = math.inf                             # a negative start: not a stock
        return min((a, b), key=lambda z: z["bic"]), P, Q

    trials = []
    for i, (_, frac, _) in enumerate(fracs):
        trials.append((with_h(frac, 1)[0]["bic"], i))
    if not trials:
        return None
    trials.sort(key=lambda z: z[0])
    frac, info = fracs[trials[0][1]][1], fracs[trials[0][1]][2]
    m = _golden(lambda v: with_h(frac * v, 1)[0]["bic"], 0.2, min(5.0, 0.999 / float(frac.max())))
    if not with_h(frac * m, 1)[0]["bic"] < trials[0][0]:
        m = 1.0                                         # the section search strayed from the fraction itself
    best, P, Q = with_h(frac * m, 1)
    drain = {"k": info["k"] * m, "effect": info["effect"]}
    b = best["b"]
    bq = float(b[2])
    h0 = float(b[3]) / bq if best["p"] and bq > 0 else 0.0
    if not (bq > 0 and -float(b[1]) > 0 and h0 >= 0):
        return None
    bic_cur = _bic(sse_cur, k_cur, n, floor)
    if not best["bic"] < min(bic_cur, plain["bic"]) - GAIN * math.log(n):
        return None
    return {"c": float(b[0]), "a": -float(b[1]), "bq": bq, "h0": h0, "names": best["names"],
            "w": [float(x) for x in b[len(b) - len(best["names"]):]] if best["names"] else [],
            "drain": drain, "H": h0 * P + Q, "sse": best["sse"], "sse_before": sse_cur, "bic": best["bic"], "bic_before": bic_cur,
            "bic_plain": plain["bic"]}


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer with each stock whose inflow reads a hidden integrator rewritten (module docstring)."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    levels, cols, n = hinge.columns(run, opts)
    if n < 20:
        return result
    finals = {s["id"] for s in stocks if s.get("final")}
    out = copy.deepcopy(result)
    flows = out["flows"]
    names = {x for f in flows for x in (f.get("from"), f.get("to")) if x}
    if any(x not in levels for x in names):
        return result                                   # the model already has a hidden stock: not this pass's to change
    ratios = _ratios(levels, cols, finals, n)
    notes = []
    for s in sorted(levels):
        if s in finals or "in" not in hinge.allowed_sides(s, run, flows) or not any(hinge._side(f, s) == "in" for f in flows):
            continue                                    # a side the model has is rewritten, never one invented
        kinds = ((run.get("boundary") or {}).get(s) or {}).get("in") or []
        if run.get("boundary_declared") and "input" in kinds:
            continue                                    # a measured input is the inflow, fixed at 1 x series
        fracs = _fractions(flows, levels, cols, n)
        got = _one(s, flows, levels, cols, n, fracs, ratios, finals)
        if got is None:
            continue
        h = f"{s}_hidden"
        while h in levels or h in names:
            h += "_"
        parts = [repr(got["c"]), f"{got['bq']!r} * {h}"] + [f"{w!r} * {nm}" for w, nm in zip(got["w"], got["names"])]
        keep = [f for f in flows if not hinge._side(f, s)]
        drain = {"id": f"{h}_drain", "from": h, "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": h, "k": got["drain"]["k"]}}
        if got["drain"]["effect"]:
            drain["effects"] = [copy.deepcopy(got["drain"]["effect"])]
        keep += [
            {"id": f"{h}_in", "from": None, "to": h, "ratio": 1, "rate": {"form": "constant", "value": 1.0}},
            drain,
            {"id": f"hidden_{s}_in", "from": None, "to": s, "ratio": 1, "rate": {"form": "expr", "expr": " + ".join(parts)}},
            {"id": f"hidden_{s}_out", "from": s, "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": s, "k": got["a"]}},
        ]
        flows[:] = keep
        names |= {h}
        out.setdefault("inferred_levels", {})[h] = [float(v) for v in got["H"]]
        notes.append({"stock": s, "hidden": h, "reads": got["names"], "drain": "effect",
                      **{k: got[k] for k in ("sse_before", "sse", "bic_before", "bic", "bic_plain", "h0")}})
    if notes:
        out["hidden_rows"] = notes
    return out
