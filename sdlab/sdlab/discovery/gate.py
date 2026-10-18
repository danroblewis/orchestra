"""A behaviour-consistency gate: does a candidate model behave in ways the data rule out?

A candidate can replay or imitate the data in-sample (its own outside-inflow pieces feed it in the
judge) and still hold a loop that runs away, or grow from states the data never visit. Before
candidates are judged, each is run freely, with SD Lab's floors and caps (simulate.Model), from ~12
moments in the data, for H steps (half the run, 100-500):

  - "observed": from the measured levels, with its own outside inflows and again with each found
    inflow held at its mean (a model that only works with its own inflow pieces fails here);
  - "empty":    from every stock at 0, inflows at their means;
  - "high":     from every stock at `high` (5) x its observed maximum, inflows at their means.

A run fails if a stock goes beyond its observed maximum by more than `multiple` (3) x its observed
range (from "high", beyond where it started by that much: it grew from an already extreme state).
Behaviour is judged by simulation, never by the linear part's eigenvalues alone: a truth whose
linear part is unstable but held by floors and caps passes. For a failure, the step's Jacobian at
the failing state (the linearisation with the floors and caps active there) names the culprit: the
row and level whose coefficient pushes the dominant eigenvalue up most.

    v = check(flows, stocks, run)
    v["ok"], v["reasons"], v["culprit"]   # culprit: {"row", "level", "k", "eigenvalue"} or None

Only the data is used (the measured levels and their times), so any strategy can gate its candidates.
"""

from __future__ import annotations

import numpy as np

from .simulate import Model, levels_array

TESTS = ("observed", "empty", "high")


def mean_inflows(flows: list[dict]) -> list[dict]:
    """The flows with each found outside inflow (pieces) held at its mean over the run."""
    out = []
    for f in flows:
        segs = f.get("inflow")
        if not segs or f.get("known"):
            out.append(f)
            continue
        w = np.array([max(1.0, float(g["to"]) - float(g["from"]) + 1) for g in segs])
        v = np.maximum(0.0, np.array([float(g["value"]) for g in segs]))
        out.append({**{k: x for k, x in f.items() if k != "inflow"}, "rate": {"form": "constant", "value": float((w * v).sum() / w.sum())}})
    return out


def _run(model: Model, L0: np.ndarray, times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Each level's maximum over the run and its level at the end (stocks x states)."""
    L, top = L0.copy(), L0.copy()
    for t in times:
        L = model.step(L, t)
        L = np.where(np.isfinite(L), L, 1e300)
        top = np.maximum(top, L)
    return top, L


def jacobian(model: Model, L: np.ndarray, t: float, eps: float = 1e-3) -> np.ndarray:
    """d next level / d level at state L (one state), by forward differences (floors and caps as
    they act there)."""
    S = len(L)
    h = np.maximum(eps, 1e-6 * np.abs(L))
    X = np.repeat(L[:, None], S + 1, axis=1)
    X[np.arange(S), np.arange(1, S + 1)] += h
    Y = model.step(X, np.full(S + 1, t))
    return (Y[:, 1:] - Y[:, :1]) / h[None, :]


def culprit(J: np.ndarray, ids: list[str]) -> dict | None:
    """The coefficient (row i's number on level j, J - I) that raises the dominant eigenvalue of J
    most: first-order sensitivity w_i v_j / (w . v) times the coefficient."""
    if not np.all(np.isfinite(J)):
        return None
    vals, right = np.linalg.eig(J)
    d = int(np.argmax(vals.real))
    lv, left = np.linalg.eig(J.T)
    e = int(np.argmin(np.abs(lv - vals[d])))
    v, w = right[:, d], left[:, e]
    den = w @ v
    if abs(den) < 1e-12:
        return None
    B = J - np.eye(len(ids))
    push = (np.outer(w, v) / den).real * B
    i, j = np.unravel_index(int(np.argmax(push)), push.shape)
    if push[i, j] <= 0:
        return None
    return {"row": ids[i], "level": ids[j], "k": float(B[i, j]), "eigenvalue": float(vals[d].real)}


def check(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """{"ok", "reasons": [{"test", "inflows", "stock", "level", "bound"}], "culprit", "rho"}:
    rho is the dominant eigenvalue of the step's linearisation at the mean measured state."""
    opts = opts or {}
    tests = opts.get("tests", TESTS)
    multiple, high = float(opts.get("multiple", 3)), float(opts.get("high", 5))
    ids = [s["id"] for s in stocks]
    if not flows:
        return {"ok": True, "reasons": [], "culprit": None, "rho": None}
    A = levels_array(run["levels"], ids)
    t = np.asarray(run["t"], dtype=float)
    n = A.shape[1]
    H = int(opts.get("horizon") or min(500, max(100, n // 2)))
    hi, lo = A.max(axis=1), A.min(axis=1)
    rng = np.maximum(1.0, hi - lo)
    # growth the data show (a stock's trend in log level per step) may go on for H more steps
    centred = np.arange(n) - (n - 1) / 2
    trend = np.maximum(0.0, (np.log1p(np.maximum(A, 0)) @ centred) / max(1e-9, float(centred @ centred)))
    starts = np.unique(np.linspace(0, n - 1, int(opts.get("starts", 12))).astype(int))
    dt = t[1] - t[0] if n > 1 else 1.0
    # times from each start onwards (past the end of the run: the last segment of everything holds)
    k = np.arange(H)
    times = np.where(starts[None, :] + k[:, None] < n, t[np.minimum(n - 1, starts[None, :] + k[:, None])],
                     t[-1] + dt * (starts[None, :] + k[:, None] - n + 1))
    own, flat = Model(flows, ids), Model(mean_inflows(flows), ids)
    m = len(starts)
    plans = []
    if "observed" in tests:
        plans += [("observed", "own", own, A[:, starts]), ("observed", "mean", flat, A[:, starts])]
    if "empty" in tests:
        plans.append(("empty", "mean", flat, np.zeros((len(ids), m))))
    if "high" in tests:
        plans.append(("high", "mean", flat, np.repeat((high * np.maximum(hi, 1.0))[:, None], m, axis=1)))
    reasons, first_fail = [], None
    runs = {}
    for model in (own, flat):                      # the plans of one model run together
        mine = [p for p in plans if p[2] is model]
        if mine:
            top, end = _run(model, np.concatenate([p[3] for p in mine], axis=1), np.tile(times, len(mine)))
            for q, p in enumerate(mine):
                runs[(p[0], p[1])] = (top[:, q * m:(q + 1) * m], end[:, q * m:(q + 1) * m])
    for test, inflows, model, L0 in plans:
        top, end = runs[(test, inflows)]
        bound = ((L0 if test == "high" else hi[:, None]) + multiple * rng[:, None]) * np.exp(trend * H)[:, None]
        over = top > bound
        if not over.any():
            continue
        for s in np.nonzero(over.any(axis=1))[0]:
            reasons.append({"test": test, "inflows": inflows, "stock": ids[s], "level": float(top[s].max()), "bound": float(bound[s].max())})
        if first_fail is None:
            c = int(np.nonzero(over.any(axis=0))[0][0])
            first_fail = (model, end[:, c], float(times[-1, c]))
    out = {"ok": not reasons, "reasons": reasons, "culprit": None}
    if first_fail is not None:
        model, L, tt = first_fail
        L = np.minimum(L, 1e12)
        out["culprit"] = culprit(jacobian(model, L, tt), ids)
    J = jacobian(flat, A.mean(axis=1), float(t[n // 2]))
    out["rho"] = float(np.max(np.abs(np.linalg.eigvals(J)))) if np.all(np.isfinite(J)) else None
    return out


def choose(candidates: list[tuple[str, list[dict]]], stocks: list[dict], run: dict, judge, opts: dict | None = None) -> dict:
    """Gate every candidate (name, flows), then judge those that pass (`judge(flows, stocks, run)`,
    lower is better); if none passes, judge them all. Returns {"best": index, "errors": [judge
    error or None per candidate], "verdicts": [verdict per candidate], "passed": count}."""
    verdicts, seen = [], {}
    for _, flows in candidates:
        key = repr(flows)
        if key not in seen:
            seen[key] = check(flows, stocks, run, opts)
        verdicts.append(seen[key])
    ok = [i for i, (_, flows) in enumerate(candidates) if verdicts[i]["ok"] and flows]
    errors: list[float | None] = [None] * len(candidates)
    best = None
    for i in ok or range(len(candidates)):
        errors[i] = judge(candidates[i][1], stocks, run)
        if best is None or errors[i] < errors[best]:
            best = i
    return {"best": best, "errors": errors, "verdicts": verdicts, "passed": len(ok)}
