"""Running a truth model over a series' samples, and refitting a published structure on the training part.

`run(model, n)` steps the model as the engine does with noise none (sdlab/discovery/simulate.py, the
same equations): sample 0 is the stocks' initial levels, sample i the levels after step i, and an
injection at t is added at the start of step t. The real cases' "published model, refitted" is the
family's numbers chosen by least squares on the training samples (the free run from the first sample
against the measured levels, each stock scaled by its spread), from several starts.
"""

from __future__ import annotations

import math

import numpy as np

from ...discovery.simulate import Model
from ...skill import truth_by_time


def run(model: dict, n: int, start: dict | None = None, from_t: int = 0, injections: list[dict] | None = None) -> dict[str, np.ndarray]:
    """{stock: levels at samples from_t .. n-1} of a truth model (every stock, hidden ones too), starting
    from `start` ({stock: level}; default the stocks' initial levels) at sample from_t."""
    ids = [s["id"] for s in model["stocks"]]
    t = list(range(n))
    flows, _ = truth_by_time({"flows": model["flows"], "schedule": model.get("schedule")}, t)
    m = Model(flows, ids)
    init = {s["id"]: float(s["initial"]) for s in model["stocks"]}
    L = np.array([[float((start or init).get(s, init[s]))] for s in ids])
    inj = model.get("injections") if injections is None else injections
    out = [L[:, 0].copy()]
    for k in range(from_t + 1, n):
        out.append(m.run(L, np.array([[k]], dtype=float), inj)[:, 0])
        L = out[-1][:, None]
    A = np.array(out).T
    return {s: A[i] for i, s in enumerate(ids)}


def scaled_residuals(model: dict, levels: dict, n_train: int) -> np.ndarray:
    """(model's free run - measured) / each stock's spread, over the training samples."""
    sim = run(model, n_train)
    res = []
    for s, v in levels.items():
        y = np.asarray(v[:n_train], dtype=float)
        sd = max(float(np.std(y)), 1e-6 * max(1.0, float(np.max(np.abs(y)))))
        r = (sim[s] - y) / sd
        r[~np.isfinite(r)] = 1e3
        res.append(r)
    return np.concatenate(res)


def least_squares(make, x0s: list[list[float]], bounds: tuple[list[float], list[float]], levels: dict, n_train: int) -> tuple[list[float], float]:
    """The numbers (from several starts) whose model's free run is closest to the training samples."""
    from scipy.optimize import least_squares as lsq

    from .models import exact

    best, cost = None, math.inf
    for x0 in x0s:
        x0 = np.clip(np.asarray(x0, dtype=float), bounds[0], bounds[1])
        try:
            with exact():
                r = lsq(lambda x: scaled_residuals(make(x), levels, n_train), x0, bounds=bounds, method="trf", max_nfev=400, x_scale="jac")
        except (ValueError, FloatingPointError):
            continue
        if r.cost < cost:
            best, cost = list(map(float, r.x)), float(r.cost)
    if best is None:
        raise RuntimeError("no start converged")
    return best, cost


def one_step(model: dict, levels: dict, n_train: int) -> dict[str, np.ndarray]:
    """Each measured stock's one-step-ahead residual over the training samples: the model stepped once from
    the measured levels (hidden stocks from the model's own free run) against the next sample."""
    free = run(model, n_train)
    out = {s: [] for s in levels}
    for i in range(1, n_train):
        start = {s: float(free[s][i - 1]) for s in free}
        start.update({s: float(levels[s][i - 1]) for s in levels})
        nxt = run(model, i + 1, start=start, from_t=i - 1)
        for s in levels:
            out[s].append(float(nxt[s][-1]) - float(levels[s][i]))
    return {s: np.array(v) for s, v in out.items()}


def twin_noise(model: dict, levels: dict, n_train: int) -> dict:
    """The twin's measurement error per measured stock: sd = rel x max(level, floor), floor 5% of the
    stock's largest level, and rel the smaller of two estimates over the training samples, each the size
    of a per-sample error that would explain what is seen: the published model's one-step residuals
    (rms relative size / sqrt(2): an error on two levels) and the series' second differences (rms / sqrt(6),
    what white error alone gives). The first counts the published model's misfit as noise, the second
    the series' curvature; the smaller is the closer bound."""
    res = one_step(model, levels, n_train)
    rel, floor = {}, {}
    for s, r in res.items():
        y = np.asarray(levels[s][:n_train], dtype=float)
        fl = 0.05 * max(1e-9, float(np.max(np.abs(y))))
        scale = np.maximum(np.abs(y), fl)
        one = float(np.sqrt(np.mean((r / scale[1:]) ** 2)) / math.sqrt(2)) if len(r) else 0.0
        d2 = np.diff(y, 2) / scale[1:-1] if len(y) > 2 else np.zeros(0)
        two = float(np.sqrt(np.mean(d2 ** 2)) / math.sqrt(6)) if len(d2) else one
        rel[s] = min(one, two)
        floor[s] = fl
    return {"rel": {s: round(v, 5) for s, v in rel.items()}, "floor": {s: round(v, 6) for s, v in floor.items()}}
