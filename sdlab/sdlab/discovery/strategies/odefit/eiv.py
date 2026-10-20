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

Pruning (docs/research/k8s-303.md). Where the data show measurement error, the structure itself was
chosen on the biased one-step fit, so it can carry parts the instrumented fit cannot tell from nothing:
an exact, smooth input stands in for the noisy level it nearly copies (a spurious `outside -> inflight
= k x traffic`, an inflated drain), a drain is split between a move and an exit, chance pieces fill the
gap. Before the refit above, the parts are tested on the instrumented fit itself: each part's numbers
by their Wald statistic (sandwich covariance, the moments summed over the stocks per step with a
Bartlett window of 2 steps, since measurement error leaves them MA(1)), the part with the largest
shortfall below PRICE per number dropped (a part that never flows, its rate gone negative, first), and
the rest refitted, until every part pays its price. Rows a level outlier touches (a one-step residual
beyond TRIM robust sds) are left out of these fits. The pruned model is kept if, at the judge's longest
horizon, it runs no further from the data than the found one by more than GUARD paired standard errors
(over the judge's runs); at shorter horizons the measurement error at each run's start, which a
faster-draining model forgets sooner, still favours the biased numbers. Failing that, the last stage
before it is tried, and failing all, the refit above as before.
Flows that read a stock nobody measures are left as they are.
"""

from __future__ import annotations

import copy

import numpy as np
from scipy.stats import norm

from ...simulate import Model, behaviour_error, levels_array, starts_for

ALPHA = 1e-3          # the white-noise test's level (one-sided, over the stocks)
ITERATIONS = 3        # Gauss-Newton steps of each fit (the rates are linear in their numbers, so one is
                      # exact unless a floor, a shared stock or an effect bends them)
HORIZONS = (5, 20, 100)
PRICE = 2.0           # a part's price per number on the instrumented fit's Wald statistic (Akaike's)
TRIM = 5.0            # a one-step residual beyond this many robust sds marks a level outlier
GUARD = 2.0           # paired standard errors the pruned model may lose by at the longest horizon


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


def _units(flows: list[dict]) -> list[tuple[int, int | None]]:
    """The parts pruning may drop, as (flow, term): a whole flow (None), or one term of a linear rate
    with more than one number. Flows that follow the eras are left alone."""
    out = []
    for fi, f in enumerate(flows):
        if f.get("byTime"):
            continue
        r = f.get("rate") or {}
        terms = [ti for ti, x in enumerate(r.get("terms") or []) if x.get("k") is not None]
        if r.get("form") == "linear" and len(terms) + bool(r.get("c")) > 1:
            out += [(fi, ti) for ti in terms]
        else:
            out.append((fi, None))
    return out


def _unit_places(fit: _Fit, unit: tuple[int, int | None]) -> list[int]:
    """The positions of a part's numbers in fit.places."""
    fi, ti = unit
    f = fit.flows[fi]
    if ti is not None:
        mine = {id(f["rate"]["terms"][ti])}
    else:
        r = f.get("rate") or {}
        mine = {id(g) for g in f.get("inflow") or []} | {id(r)} | {id(x) for x in r.get("terms") or []}
    return [j for j, (d, k) in enumerate(fit.places) if id(d) in mine and (ti is None or k == "k")]


def _without(flows: list[dict], unit: tuple[int, int | None]) -> list[dict]:
    fi, ti = unit
    out = copy.deepcopy(flows)
    if ti is None:
        del out[fi]
    else:
        r = out[fi]["rate"]
        del r["terms"][ti]
        if out[fi].get("rates"):
            out[fi]["rates"] = [r]
    return out


def _name(flows: list[dict], unit: tuple[int, int | None]) -> str:
    f = flows[unit[0]]
    return (f"{f.get('from') or 'outside'} -> {f.get('to') or 'outside'}"
            + (f" [{f['rate']['terms'][unit[1]].get('stock')}]" if unit[1] is not None else ""))


class _Instrumented:
    """A structure's instrumented fit: its numbers (least squares, then instrumental-variables steps;
    a step that fails keeps the last finite one), their covariance, and which numbers some row reads."""

    def __init__(self, flows: list[dict], ids: list[str], t: np.ndarray, A: np.ndarray, inputs: dict | None,
                 rows: np.ndarray, w: np.ndarray):
        self.work, self.w = copy.deepcopy(flows), w
        self.fit = _Fit(self.work, ids, t, A, inputs, rows)
        th = self.fit.theta()
        self.ok = len(th) > 0
        if not self.ok:
            return
        for _ in range(ITERATIONS):
            th = th + np.linalg.lstsq(self.stack(self.fit.jac(th, 1)), self.stack(self.fit.resid(th)), rcond=None)[0]
        e = self.fit.resid(th)
        dev = np.abs(e - np.median(e, axis=1, keepdims=True))
        bad = set(rows[np.any(dev > TRIM * 1.4826 * np.maximum(np.median(dev, axis=1), 1e-12)[:, None], axis=0)].tolist())
        keep = np.array([r for r in rows if not {r - 1, r, r + 1, r + 2} & bad])
        if bad and len(keep) >= 10 * len(th):            # the rows a level outlier touches, as a change or an instrument
            self.fit = _Fit(self.work, ids, t, A, inputs, keep)
        good = None
        for _ in range(ITERATIONS):
            J, Zi = self.stack(self.fit.jac(th, 1)), self.stack(self.fit.jac(th, 2))
            c = np.sqrt((J ** 2).sum(axis=0))
            act = c > 0                                  # a number no row reads (a piece outside the rows) stays
            ZJ = (Zi[:, act] / c[act]).T @ (J[:, act] / c[act])
            if not act.any() or not np.all(np.isfinite(ZJ)) or np.linalg.cond(ZJ) > 1e12:
                break
            step = np.zeros_like(th)
            step[act] = np.linalg.solve(ZJ, (Zi[:, act] / c[act]).T @ self.stack(self.fit.resid(th))) / c[act]
            if not np.all(np.isfinite(th + step)):
                break
            th = good = th + step
        self.ok = good is not None
        if not self.ok:
            return
        self.th = good
        J, Zi, e = self.fit.jac(good, 1), self.fit.jac(good, 2), self.fit.resid(good)
        self.live = np.abs(J).sum(axis=(0, 1)) > 0
        g = np.einsum("srp,sr->rp", Zi * w[:, None, None], e * w[:, None])     # each step's moments
        S = g.T @ g
        for lag, weight in ((1, 2 / 3), (2, 1 / 3)):
            C = g[lag:].T @ g[:-lag]
            S += weight * (C + C.T)
        B = np.linalg.pinv(np.einsum("srp,srq->pq", Zi * w[:, None, None], J * w[:, None, None]))
        self.V = B @ S @ B.T
        self.fit.set(good)

    def stack(self, M: np.ndarray) -> np.ndarray:
        w = self.w
        return (M * (w[:, None] if M.ndim == 2 else w[:, None, None])).reshape(-1, *M.shape[2:])

    def weakest(self) -> tuple[int, int | None] | None:
        """The part with the largest shortfall of its Wald statistic below PRICE per number, or None."""
        best = None
        for u in _units(self.work):
            js = _unit_places(self.fit, u)
            if not js:
                continue
            if not self.live[js].any():                 # it never flows
                return u
            wald = float(self.th[js] @ np.linalg.pinv(self.V[np.ix_(js, js)]) @ self.th[js])
            short = wald - PRICE * len(js)
            if short < 0 and (best is None or short < best[0]):
                best = (short, u)
        return best and best[1]


def _runs(flows: list[dict], ids: list[str], run: dict, opts: dict) -> np.ndarray:
    """Each run's share of the judge (behaviour_error) at its longest horizon."""
    hs = [h for h in HORIZONS if h < len(run["t"]) / 4]
    A = levels_array(run["levels"], ids)
    n, h = A.shape[1], hs[-1]
    s0 = starts_for(n, h, 80)
    sd = A.std(axis=1)
    sd[sd == 0] = 1
    tt = np.asarray(run["t"], dtype=float)
    inputs = opts.get("inputs")
    end = Model(flows, ids, inputs={"t": run["t"], "values": inputs} if inputs else None).run(
        A[:, s0 - 1], tt[s0[None, :] + np.arange(h)[:, None]], opts.get("injections"))
    obs = A[:, s0 + h - 1]
    e = ((end - obs) / sd[:, None]) ** 2
    e[~np.isfinite(e)] = 1e6
    return e.sum(axis=0) / max(1e-9, float((((obs - A[:, s0 - 1]) / sd[:, None]) ** 2).sum()))


def _prune(flows: list[dict], ids: list[str], t: np.ndarray, A: np.ndarray, inputs: dict | None, rows: np.ndarray,
           w: np.ndarray, run: dict, opts: dict) -> tuple[list[dict], dict] | None:
    """The flows with the parts the instrumented fit cannot tell from nothing dropped and the rest
    refitted, and what was done; None when nothing is dropped or no stage passes the guard."""
    cur, names, stages = _Instrumented(flows, ids, t, A, inputs, rows, w), [], []
    while cur.ok and len(cur.work) > 1:
        u = cur.weakest()
        if u is None:
            break
        nxt = _Instrumented(_without(cur.work, u), ids, t, A, inputs, rows, w)
        if not nxt.ok:
            break
        names.append(_name(cur.work, u))
        cur = nxt
        stages.append((cur.work, list(names)))
    if not stages or not [h for h in HORIZONS if h < len(run["t"]) / 4]:
        return None
    before = _runs(flows, ids, run, opts)
    for work, dropped in reversed(stages):
        d = _runs(work, ids, run, opts) - before
        z = float(d.sum() / max(1e-12, np.sqrt(len(d) * d.var(ddof=1)))) if len(d) > 1 else float("inf")
        if z <= GUARD:
            return work, {"dropped": dropped, "z": round(z, 2)}
    return None


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
    fit.set(theta0)
    pruned = _prune(flows, ids, t, A, {"t": list(run["t"]), "values": inputs} if inputs else None, rows, w, run, opts)
    if pruned:
        return pruned[0], {**info, **pruned[1], "used": True}
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
