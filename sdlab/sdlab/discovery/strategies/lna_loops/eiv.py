# A copy, one per strategy that uses it (sdlab/CLAUDE.md invariant 11: no strategy imports another).
"""Errors in variables: the found flows' numbers refitted by instrumental variables when the levels
carry measurement error (docs/research/eiv-refit.md).

A one-step fit regresses each stock's change y[i] - y[i-1] on the levels y[i-1]. When the levels are
measured with error, the same error sits in the regressor and (with the opposite sign) in the change,
so drains come out too fast and inflows follow to keep the steady state; the bias does not shrink
with more data. Instrumenting each row's regressors (the derivative of the step's change with respect
to each number) with the same derivative taken at the levels one step earlier, y[i-2], removes it:
measurement error is white, so y[i-2] is independent of the errors at i-1 and i, and counting noise
(each step's own draw) is independent of every earlier level, so the instrumented fit is consistent
under both. Measured inputs are their own instruments.

The instrumented numbers replace the found ones only when
- the data show measurement error: some stock's one-step residuals are negatively correlated from
  one step to the next beyond chance (p < ALPHA, one-sided, over the stocks; counting noise leaves
  them white, a structure that misses something leaves them smooth), and
- the refitted model runs at least as close to the data over 5, 20 and 100 steps (the main line's
  judge: a multi-step error, which measurement error does not bias), so a structure the instruments
  do not suit keeps its numbers.
The structure is never changed. Flows that read a stock nobody measures are left as they are.
"""

from __future__ import annotations

import copy

import numpy as np
from scipy.stats import norm

from ...simulate import Model, behaviour_error, levels_array

ALPHA = 1e-3          # the white-noise test's level (one-sided, over the stocks)
ITERATIONS = 3        # Gauss-Newton steps of each fit (the rates are linear in their numbers, so one is
                      # exact unless a floor, a shared stock or an effect bends them)
HORIZONS = (5, 20, 100)


def slots(flows: list[dict]) -> list[tuple[dict, str]]:
    """The numbers to refit, as (dict, key): a proportional rate's k, a linear rate's constant (when
    not 0) and its terms' k, a constant rate's value, a found outside inflow's piece values; per era
    where a rate follows the eras (eras that share a rate dict share the number)."""
    out, seen = [], set()
    for f in flows:
        if f.get("inflow"):
            out += [(g, "value") for g in f["inflow"] if g.get("value") is not None]
            continue
        for r in ([g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]):
            if id(r) in seen:
                continue
            seen.add(id(r))
            form = r.get("form")
            if form == "proportional" and r.get("k") is not None:
                out.append((r, "k"))
            elif form == "constant" and r.get("value") is not None:
                out.append((r, "value"))
            elif form == "linear":
                if r.get("c"):
                    out.append((r, "c"))
                out += [(x, "k") for x in r.get("terms") or [] if x.get("k") is not None]
    return out


def _known(flows: list[dict], names: set) -> bool:
    """Every stock the flows name is measured or a measured input (no hidden stocks)."""
    for f in flows:
        named = [f.get("from"), f.get("to")]
        for r in [g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]:
            named += [r.get("stock")] + [x.get("stock") for x in r.get("terms") or []]
        named += [e.get("stock") for e in f.get("effects") or []] + [u.get("stock") for u in f.get("uses") or []]
        if any(s is not None and s not in names for s in named):
            return False
    return True


def judge(flows: list[dict], ids: list[str], run: dict, opts: dict) -> float:
    """The main line's judge (identify.judge) with the measured inputs: the mean multi-step error."""
    hs = [h for h in HORIZONS if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    kw = {"inputs": opts["inputs"]} if opts.get("inputs") else {}
    return sum(behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, injections=opts.get("injections"), **kw)
               for h in hs) / len(hs)


class _Fit:
    """The flows' numbers as a vector, and each stock's change over the rows' steps for any of them."""

    def __init__(self, flows: list[dict], ids: list[str], t: np.ndarray, A: np.ndarray, inputs: dict | None, rows: np.ndarray):
        self.flows, self.ids, self.t, self.A, self.inputs, self.rows = flows, ids, t, A, inputs, rows
        self.places = slots(flows)
        self.dy = A[:, rows] - A[:, rows - 1]

    def theta(self) -> np.ndarray:
        return np.array([float(d[k]) for d, k in self.places])

    def set(self, theta: np.ndarray) -> None:
        for (d, k), v in zip(self.places, theta):
            d[k] = float(v)

    def change(self, theta: np.ndarray, lag: int) -> np.ndarray:
        """Each stock's change over the rows' steps (stocks x rows), from the levels `lag` steps before
        each row (1: the step's own start; 2: one step earlier), at the row's time and inputs."""
        self.set(theta)
        return Model(self.flows, self.ids, inputs=self.inputs).change(self.A[:, self.rows - lag], self.t[self.rows])

    def resid(self, theta: np.ndarray) -> np.ndarray:
        return self.dy - self.change(theta, 1)

    def jac(self, theta: np.ndarray, lag: int) -> np.ndarray:
        """d change / d numbers (stocks x rows x numbers), by differences."""
        base = self.change(theta, lag)
        J = np.empty(base.shape + (len(theta),))
        for j in range(len(theta)):
            h = 1e-4 * max(1e-3, abs(theta[j]))
            th = theta.copy()
            th[j] += h
            J[:, :, j] = (self.change(th, lag) - base) / h
        self.set(theta)
        return J


def white_z(e: np.ndarray, dy: np.ndarray) -> list[float]:
    """Each stock's lag-1 correlation of its residuals, as a z-score under white noise (0 where the
    residuals are nothing but rounding)."""
    out = []
    for s in range(e.shape[0]):
        es = e[s] - e[s].mean()
        v = float(es @ es)
        out.append(float(es[1:] @ es[:-1]) / v * np.sqrt(len(es)) if v > 1e-12 * max(1.0, float(dy[s] @ dy[s])) else 0.0)
    return out


def refit(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None = None) -> tuple[list[dict], dict]:
    """The flows with their numbers refitted by instrumental variables where the module says, and
    what was found ({} where nothing could be tested)."""
    opts = opts or {}
    ids = [s["id"] for s in stocks]
    inputs = opts.get("inputs") or {}
    t = np.asarray(run["t"], dtype=float)
    n = len(t)
    if not flows or n < 20 or not _known(flows, set(ids) | set(inputs)) or np.any(np.diff(t) != 1):
        return flows, {}
    A = levels_array(run["levels"], ids)
    if not np.all(np.isfinite(np.asarray([run["levels"].get(i, []) for i in ids], dtype=float))):
        return flows, {}
    work = copy.deepcopy(flows)
    pulses = {float(j["t"]) for j in opts.get("injections") or []}
    rows = np.array([i for i in range(2, n) if t[i] not in pulses and t[i - 1] not in pulses])
    fit = _Fit(work, ids, t, A, {"t": list(run["t"]), "values": inputs} if inputs else None, rows)
    theta0 = fit.theta()
    p = len(theta0)
    if p == 0 or len(rows) < 10 * p:
        return flows, {}
    # each stock's rows weighted by the spread of its one-step residuals
    sd = fit.resid(theta0).std(axis=1)
    w = 1.0 / np.maximum(sd, 1e-9 * max(1.0, float(np.abs(A).max())))

    def stack(M: np.ndarray) -> np.ndarray:        # stocks x rows (x numbers) -> weighted rows
        return (M * (w[:, None] if M.ndim == 2 else w[:, None, None])).reshape(-1, *M.shape[2:])

    th_o = theta0.copy()
    for _ in range(ITERATIONS):
        th_o = th_o + np.linalg.lstsq(stack(fit.jac(th_o, 1)), stack(fit.resid(th_o)), rcond=None)[0]
    z = white_z(fit.resid(th_o), fit.dy)
    info = {"white_z": [round(x, 2) for x in z], "used": False}
    if min(z) > -norm.isf(ALPHA / len(z)):
        fit.set(theta0)
        return flows, info
    th_i = th_o.copy()
    for _ in range(ITERATIONS):
        J, Z = stack(fit.jac(th_i, 1)), stack(fit.jac(th_i, 2))
        ZJ = Z.T @ J
        if not np.all(np.isfinite(ZJ)) or np.linalg.cond(ZJ) > 1e12:
            fit.set(theta0)
            return flows, {**info, "skipped": "weak instruments"}
        th_i = th_i + np.linalg.solve(ZJ, Z.T @ stack(fit.resid(th_i)))
    if not np.all(np.isfinite(th_i)):
        fit.set(theta0)
        return flows, {**info, "skipped": "no finite fit"}
    fit.set(np.round(th_i, 6))
    before, after = judge(flows, ids, run, opts), judge(work, ids, run, opts)
    info.update(found=theta0.round(6).tolist(), instrumented=th_i.round(6).tolist(), judged=[before, after])
    if not after <= before:
        return flows, info
    return work, {**info, "used": True}


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """A strategy's result with its flows refitted (refit), and what the refit found under "eiv"."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    try:
        flows, info = refit(result["flows"], stocks, run, opts)
    except (ValueError, np.linalg.LinAlgError, FloatingPointError) as e:
        return {**result, "eiv": {"error": f"{type(e).__name__}: {e}"[:200]}}
    return {**result, "flows": flows, "eiv": info}
