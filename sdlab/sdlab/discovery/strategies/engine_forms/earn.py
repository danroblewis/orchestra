"""Every move earns its place on all the rows at once (k8s-316, docs/research/fixes/316-engine_forms.md;
the "flow-earn" the fix ledger proposed from 308-structures).

On noisy rows (counts: the run moves in whole numbers, the levels are what happened) the base fit can keep two
moves that cancel each other through near-collinear levels: on 316 counts-long, pricing_queue -> frontend_inflight
(0.107 x pricing_queue) beside frontend_inflight -> catalog_queue (0.038 x frontend_inflight), with the calls into
pricing pushed to 0.46 for 0.4. Each stock's change is linear in the numbers of the linear flows, so all of them are
refitted together, every row at once (each row weighted by its own residual variance under the answer; the flows
the refit does not run, such as expressions, held at their amounts), and each move between two measured stocks is
dropped in turn, greedily, while the refit's BIC (each row Gaussian, T log RSS/T, every number log n) does not get
worse. Outside flows stay: the declared boundary or the base put them there. Nothing changes unless a move is
dropped; then the refitted numbers are written, and kept only if the rows as the engine runs the new flows (rates
floored at 0) have a better BIC than the answer's.
"""

from __future__ import annotations

import copy
import math

import numpy as np

from ._kalman import boundary as _boundary

RESOLUTION = 1e-8      # a row's variance below this share of its mean squared change is rounding (as capmin.py)


def _terms(f: dict) -> list[tuple[str, float]] | None:
    """A flow's numbers as [(column, k)] ("1" the constant), or None where the refit does not run it."""
    if any(f.get(k) for k in ("byTime", "inflow", "effects", "uses", "via", "hidden")) or float(f.get("ratio") or 1) != 1:
        return None
    r = f.get("rate") or {}
    form = r.get("form")
    if form == "constant":
        return [("1", float(r.get("value") or 0.0))]
    if form == "proportional":
        return [(r.get("stock"), float(r.get("k") or 0.0))]
    if form == "linear":
        out = [(t.get("stock"), float(t.get("k") or 0.0)) for t in r.get("terms") or []]
        return out + ([("1", float(r.get("c") or 0.0))] if float(r.get("c") or 0.0) else [])
    return None


def _bic(R: np.ndarray, k: int, floors: np.ndarray) -> float:
    S, T = R.shape
    rss = np.sum(R ** 2, axis=1) / T
    return float(T * np.sum(np.log(rss + floors)) + k * math.log(S * T))


def _write(f: dict, cols: list[str], k: np.ndarray) -> dict:
    g = {key: v for key, v in f.items() if key != "rate"}
    c = float(sum(x for n, x in zip(cols, k) if n == "1"))
    ts = [{"stock": n, "k": float(x)} for n, x in zip(cols, k) if n != "1"]
    if not ts:
        g["rate"] = {"form": "constant", "value": c}
    elif len(ts) == 1 and not c:
        g["rate"] = {"form": "proportional", "stock": ts[0]["stock"], "k": ts[0]["k"]}
    else:
        g["rate"] = {"form": "linear", "c": c, "terms": ts}
    return g


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None, log: list | None = None) -> dict:
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    opts = opts or {}
    data = _boundary.Data(stocks, run, opts)
    if not data.usable:
        return result
    ids, T, S = data.ids, data.T, len(data.ids)
    t = [float(x) for x in run["t"]]
    at = {x: i for i, x in enumerate(t)}
    col = {s: data.L[i] for i, s in enumerate(ids)} | {"1": np.ones(T)}
    for name, v in (opts.get("inputs") or {}).items():
        v = np.asarray(v, dtype=float)
        if name not in col and len(v) == len(t):
            col[name] = np.array([v[at[float(x)]] for x in data.tt])
    from .hidden import _change

    flows = copy.deepcopy(result["flows"])
    if any(x not in ids and x is not None for f in flows for x in (f.get("from"), f.get("to"))):
        return result
    try:
        R0 = data.dy - _change(flows, data, {k: v for k, v in col.items() if k not in ids and k != "1"})
    except Exception:                                     # noqa: BLE001
        return result
    run_ = [n for n, f in enumerate(flows) if not f.get("input") and (tm := _terms(f)) is not None and all(c in col for c, _ in tm)]
    held = [f for n, f in enumerate(flows) if n not in run_]
    if not run_:
        return result
    extra = {k: v for k, v in col.items() if k not in ids and k != "1"}
    Y = data.dy - (_change(held, data, extra) if held else 0.0)
    floors = np.array([RESOLUTION * float(np.mean(data.dy[i] ** 2)) + 1e-300 for i in range(S)])
    w = 1.0 / np.sqrt(np.maximum(np.mean(R0 ** 2, axis=1), floors))   # each row by its own noise under the answer
    idx = {s: i for i, s in enumerate(ids)}
    params = [(n, c) for n in run_ for c, _ in _terms(flows[n])]

    def design(keep: list[int]):
        P = [(n, c) for n, c in params if n in keep]
        A = np.zeros((S, T, len(P)))
        for j, (n, c) in enumerate(P):
            f = flows[n]
            if f.get("from") is not None:
                A[idx[f["from"]], :, j] -= col[c]
            if f.get("to") is not None:
                A[idx[f["to"]], :, j] += col[c]
        return P, A

    def fit(keep: list[int]):
        P, A = design(keep)
        M = (A * w[:, None, None]).reshape(S * T, len(P))
        y = (Y * w[:, None]).reshape(S * T)
        k, *_ = np.linalg.lstsq(M, y, rcond=None) if len(P) else (np.zeros(0),)
        R = Y - (np.einsum("stp,p->st", A, k) if len(P) else 0.0)
        return P, k, _bic(R, len(P), floors)

    moves = [n for n in run_ if flows[n].get("from") in idx and flows[n].get("to") in idx]
    keep = list(run_)
    P, k, best = fit(keep)
    dropped = []
    while True:
        trial = [(fit([m for m in keep if m != d]), d) for d in moves if d in keep]
        if not trial:
            break
        (P2, k2, b2), d = min(trial, key=lambda x: x[0][2])
        if b2 > best:
            break
        keep = [m for m in keep if m != d]
        P, k, best = P2, k2, b2
        dropped.append(d)
    if not dropped:
        return result
    new = []
    for n, f in enumerate(flows):
        if n in dropped:
            continue
        if n in keep:
            cols = [c for (m, c) in P if m == n]
            ks = np.array([x for (m, _), x in zip(P, k) if m == n])
            new.append(_write(f, cols, ks))
        else:
            new.append(f)
    try:
        R1 = data.dy - _change(new, data, extra)
    except Exception:                                     # noqa: BLE001
        return result
    count = lambda fl: sum(len(_terms(f) or [None]) for f in fl)  # noqa: E731
    before, after = _bic(R0, count(flows), floors), _bic(R1, count(new), floors)
    if after >= before:
        return result
    note = [f"dropped {flows[d].get('from')} -> {flows[d].get('to')}; BIC {before:.0f} -> {after:.0f}" for d in dropped]
    if log is not None:
        log.extend(note)
    return {**result, "flows": new, "earn": note}
