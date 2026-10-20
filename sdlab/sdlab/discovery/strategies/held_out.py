"""Candidates chosen on data they were not fitted on (experiment: held-out judge).

The same candidate ways of estimating the matrix as the main line (identify.VARIANTS), but each is
judged by blocked cross-validation (holdout.py, copied below with the measured inputs): the run is cut into contiguous blocks, the
candidate is fitted on all but one, and run forward inside the held-out block, its outside inflows
there taken from what the fit knows (the piece in force before the block). The candidate with the
lowest held-out error is then fitted on all the data.
"""

from __future__ import annotations

import math

import numpy as np

from ..holdout import blocks, fill_gaps
from ..identify import VARIANTS, judge
from ..matrix import identify_one
from ..simulate import behaviour_error

FOLDS = 5
HORIZONS = (5, 20, 100)
CAP = 1e3          # one block where a candidate runs away counts as badly as any other runaway


def held_out_errors(stocks: list[dict], run: dict, opts: dict, folds: int = 5, horizons=(5, 20, 100), fill: str = "last") -> list[dict]:
    """holdout.held_out_errors (a copy, from 66086e7) with the measured inputs (opts["inputs"]): each
    held-out block's runs read the inputs over that block, as the fit on the other steps did. Per
    held-out block: {"block": (a, b), "errors": {horizon: error}} (behaviour_error, run on the block's
    own levels; a horizon is used only when it is under half the block)."""
    t = run["t"]
    T = len(t) - 1
    ids = [s["id"] for s in stocks]
    inputs = opts.get("inputs") or None
    out = []
    for a, b in blocks(T, folds):
        mask = np.ones(T, bool)
        mask[a:b] = False
        r = identify_one(stocks, run, {**opts, "steps": mask})
        flows = fill_gaps(r["flows"], fill)
        tb = t[a:b + 1]
        lb = {i: list(run["levels"][i][a:b + 1]) for i in run["levels"]}
        ib = {k: list(v[a:b + 1]) for k, v in inputs.items()} if inputs else None
        errs = {h: behaviour_error(flows, ids, tb, lb, horizon=h, inputs=ib) if flows else float("inf") for h in horizons if h < (b - a) / 2}
        out.append({"block": (a, b), "errors": errs})
    return out


def score(blocks: list[dict]) -> float:
    vals = []
    for b in blocks:
        e = [min(CAP, v) for v in b["errors"].values()]
        if e:
            vals.append(sum(e) / len(e))
    return sum(vals) / len(vals) if vals else float("inf")


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """opts beyond identify_one's: folds, fill ("last" or "mean"), horizons, and blend: with
    blend > 0 the score is log(in-sample error) + blend x log(held-out error) (the main line's judge,
    nudged by the held-out one)."""
    opts = dict(opts or {})
    folds, fill = opts.pop("folds", FOLDS), opts.pop("fill", "last")
    horizons, blend = opts.pop("horizons", HORIZONS), opts.pop("blend", 0)
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    best, tried = None, []
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        e = score(held_out_errors(stocks, run, {**opts, **v}, folds=folds, horizons=horizons, fill=fill))
        full = None
        if blend:
            full = identify_one(stocks, run, {**opts, **v})
            e = math.log(max(1e-9, judge(full["flows"], stocks, run, inputs=opts.get("inputs") or None))) + blend * math.log(max(1e-9, e))
        tried.append({"name": v["name"], "error": e})
        if best is None or e < best[1]:
            best = (v, e, full)
    r = best[2] or identify_one(stocks, run, {**opts, **best[0]})
    r["chosen"], r["tried"] = best[0]["name"], tried
    return r


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (the _eiv_ code below)."""
    return _eiv_apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)


# Errors in variables (docs/research/eiv-refit.md): a copy of the strategies' eiv.py, its names prefixed
# _eiv_. When the levels carry measurement error (one-step residuals negatively correlated from step to
# step), the found numbers are refitted with the levels two steps back as instruments, and kept only if
# the model then runs at least as close to the data over 5, 20 and 100 steps. Parts the instrumented fit
# cannot tell from nothing are pruned first (docs/research/k8s-303.md).
import copy as _eiv_copy  # noqa: E402

import numpy as _eiv_np  # noqa: E402
from scipy.stats import norm as _eiv_norm  # noqa: E402

from ..simulate import Model as _EivModel, behaviour_error as _eiv_behaviour_error, levels_array as _eiv_levels_array, starts_for as _eiv_starts_for  # noqa: E402

_EIV_ALPHA = 1e-3          # the white-noise test's level (one-sided, over the stocks)
_EIV_ITERATIONS = 3        # Gauss-Newton steps of each fit (the rates are linear in their numbers, so one is
                      # exact unless a floor, a shared stock or an effect bends them)
_EIV_HORIZONS = (5, 20, 100)
_EIV_PRICE = 2.0           # a part's price per number on the instrumented fit's Wald statistic (Akaike's)
_EIV_TRIM = 5.0            # a one-step residual beyond this many robust sds marks a level outlier
_EIV_GUARD = 2.0           # paired standard errors the pruned model may lose by at the longest horizon


def _eiv_slots(flows: list[dict]) -> list[tuple[dict, str]]:
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


def _eiv_known(flows: list[dict], names: set) -> bool:
    """Every stock the flows name is measured or a measured input (no hidden stocks)."""
    for f in flows:
        named = [f.get("from"), f.get("to")]
        for r in [g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]:
            named += [r.get("stock")] + [x.get("stock") for x in r.get("terms") or []]
        named += [e.get("stock") for e in f.get("effects") or []] + [u.get("stock") for u in f.get("uses") or []]
        if any(s is not None and s not in names for s in named):
            return False
    return True


def _eiv_judge(flows: list[dict], ids: list[str], run: dict, opts: dict) -> float:
    """The main line's judge (identify.judge) with the measured inputs: the mean multi-step error."""
    hs = [h for h in _EIV_HORIZONS if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    kw = {"inputs": opts["inputs"]} if opts.get("inputs") else {}
    return sum(_eiv_behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, injections=opts.get("injections"), **kw)
               for h in hs) / len(hs)


class _EivFit:
    """The flows' numbers as a vector, and each stock's change over the rows' steps for any of them."""

    def __init__(self, flows: list[dict], ids: list[str], t: _eiv_np.ndarray, A: _eiv_np.ndarray, inputs: dict | None, rows: _eiv_np.ndarray):
        self.flows, self.ids, self.t, self.A, self.inputs, self.rows = flows, ids, t, A, inputs, rows
        self.places = _eiv_slots(flows)
        self.dy = A[:, rows] - A[:, rows - 1]

    def theta(self) -> _eiv_np.ndarray:
        return _eiv_np.array([float(d[k]) for d, k in self.places])

    def set(self, theta: _eiv_np.ndarray) -> None:
        for (d, k), v in zip(self.places, theta):
            d[k] = float(v)

    def change(self, theta: _eiv_np.ndarray, lag: int) -> _eiv_np.ndarray:
        """Each stock's change over the rows' steps (stocks x rows), from the levels `lag` steps before
        each row (1: the step's own start; 2: one step earlier), at the row's time and inputs."""
        self.set(theta)
        return _EivModel(self.flows, self.ids, inputs=self.inputs).change(self.A[:, self.rows - lag], self.t[self.rows])

    def resid(self, theta: _eiv_np.ndarray) -> _eiv_np.ndarray:
        return self.dy - self.change(theta, 1)

    def jac(self, theta: _eiv_np.ndarray, lag: int) -> _eiv_np.ndarray:
        """d change / d numbers (stocks x rows x numbers), by differences."""
        base = self.change(theta, lag)
        J = _eiv_np.empty(base.shape + (len(theta),))
        for j in range(len(theta)):
            h = 1e-4 * max(1e-3, abs(theta[j]))
            th = theta.copy()
            th[j] += h
            J[:, :, j] = (self.change(th, lag) - base) / h
        self.set(theta)
        return J


def _eiv_white_z(e: _eiv_np.ndarray, dy: _eiv_np.ndarray) -> list[float]:
    """Each stock's lag-1 correlation of its residuals, as a z-score under white noise (0 where the
    residuals are nothing but rounding)."""
    out = []
    for s in range(e.shape[0]):
        es = e[s] - e[s].mean()
        v = float(es @ es)
        out.append(float(es[1:] @ es[:-1]) / v * _eiv_np.sqrt(len(es)) if v > 1e-12 * max(1.0, float(dy[s] @ dy[s])) else 0.0)
    return out


def _eiv_units(flows: list[dict]) -> list[tuple[int, int | None]]:
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


def _eiv_unit_places(fit: _EivFit, unit: tuple[int, int | None]) -> list[int]:
    """The positions of a part's numbers in fit.places."""
    fi, ti = unit
    f = fit.flows[fi]
    if ti is not None:
        mine = {id(f["rate"]["terms"][ti])}
    else:
        r = f.get("rate") or {}
        mine = {id(g) for g in f.get("inflow") or []} | {id(r)} | {id(x) for x in r.get("terms") or []}
    return [j for j, (d, k) in enumerate(fit.places) if id(d) in mine and (ti is None or k == "k")]


def _eiv_without(flows: list[dict], unit: tuple[int, int | None]) -> list[dict]:
    fi, ti = unit
    out = _eiv_copy.deepcopy(flows)
    if ti is None:
        del out[fi]
    else:
        r = out[fi]["rate"]
        del r["terms"][ti]
        if out[fi].get("rates"):
            out[fi]["rates"] = [r]
    return out


def _eiv_name(flows: list[dict], unit: tuple[int, int | None]) -> str:
    f = flows[unit[0]]
    return (f"{f.get('from') or 'outside'} -> {f.get('to') or 'outside'}"
            + (f" [{f['rate']['terms'][unit[1]].get('stock')}]" if unit[1] is not None else ""))


class _EivInstrumented:
    """A structure's instrumented fit: its numbers (least squares, then instrumental-variables steps;
    a step that fails keeps the last finite one), their covariance, and which numbers some row reads."""

    def __init__(self, flows: list[dict], ids: list[str], t: _eiv_np.ndarray, A: _eiv_np.ndarray, inputs: dict | None,
                 rows: _eiv_np.ndarray, w: _eiv_np.ndarray):
        self.work, self.w = _eiv_copy.deepcopy(flows), w
        self.fit = _EivFit(self.work, ids, t, A, inputs, rows)
        th = self.fit.theta()
        self.ok = len(th) > 0
        if not self.ok:
            return
        for _ in range(_EIV_ITERATIONS):
            th = th + _eiv_np.linalg.lstsq(self.stack(self.fit.jac(th, 1)), self.stack(self.fit.resid(th)), rcond=None)[0]
        e = self.fit.resid(th)
        dev = _eiv_np.abs(e - _eiv_np.median(e, axis=1, keepdims=True))
        bad = set(rows[_eiv_np.any(dev > _EIV_TRIM * 1.4826 * _eiv_np.maximum(_eiv_np.median(dev, axis=1), 1e-12)[:, None], axis=0)].tolist())
        keep = _eiv_np.array([r for r in rows if not {r - 1, r, r + 1, r + 2} & bad])
        if bad and len(keep) >= 10 * len(th):            # the rows a level outlier touches, as a change or an instrument
            self.fit = _EivFit(self.work, ids, t, A, inputs, keep)
        good = None
        for _ in range(_EIV_ITERATIONS):
            J, Zi = self.stack(self.fit.jac(th, 1)), self.stack(self.fit.jac(th, 2))
            c = _eiv_np.sqrt((J ** 2).sum(axis=0))
            act = c > 0                                  # a number no row reads (a piece outside the rows) stays
            ZJ = (Zi[:, act] / c[act]).T @ (J[:, act] / c[act])
            if not act.any() or not _eiv_np.all(_eiv_np.isfinite(ZJ)) or _eiv_np.linalg.cond(ZJ) > 1e12:
                break
            step = _eiv_np.zeros_like(th)
            step[act] = _eiv_np.linalg.solve(ZJ, (Zi[:, act] / c[act]).T @ self.stack(self.fit.resid(th))) / c[act]
            if not _eiv_np.all(_eiv_np.isfinite(th + step)):
                break
            th = good = th + step
        self.ok = good is not None
        if not self.ok:
            return
        self.th = good
        J, Zi, e = self.fit.jac(good, 1), self.fit.jac(good, 2), self.fit.resid(good)
        self.live = _eiv_np.abs(J).sum(axis=(0, 1)) > 0
        g = _eiv_np.einsum("srp,sr->rp", Zi * w[:, None, None], e * w[:, None])     # each step's moments
        S = g.T @ g
        for lag, weight in ((1, 2 / 3), (2, 1 / 3)):
            C = g[lag:].T @ g[:-lag]
            S += weight * (C + C.T)
        B = _eiv_np.linalg.pinv(_eiv_np.einsum("srp,srq->pq", Zi * w[:, None, None], J * w[:, None, None]))
        self.V = B @ S @ B.T
        self.fit.set(good)

    def stack(self, M: _eiv_np.ndarray) -> _eiv_np.ndarray:
        w = self.w
        return (M * (w[:, None] if M.ndim == 2 else w[:, None, None])).reshape(-1, *M.shape[2:])

    def weakest(self) -> tuple[int, int | None] | None:
        """The part with the largest shortfall of its Wald statistic below PRICE per number, or None."""
        best = None
        for u in _eiv_units(self.work):
            js = _eiv_unit_places(self.fit, u)
            if not js:
                continue
            if not self.live[js].any():                 # it never flows
                return u
            wald = float(self.th[js] @ _eiv_np.linalg.pinv(self.V[_eiv_np.ix_(js, js)]) @ self.th[js])
            short = wald - _EIV_PRICE * len(js)
            if short < 0 and (best is None or short < best[0]):
                best = (short, u)
        return best and best[1]


def _eiv_runs(flows: list[dict], ids: list[str], run: dict, opts: dict) -> _eiv_np.ndarray:
    """Each run's share of the judge (behaviour_error) at its longest horizon."""
    hs = [h for h in _EIV_HORIZONS if h < len(run["t"]) / 4]
    A = _eiv_levels_array(run["levels"], ids)
    n, h = A.shape[1], hs[-1]
    s0 = _eiv_starts_for(n, h, 80)
    sd = A.std(axis=1)
    sd[sd == 0] = 1
    tt = _eiv_np.asarray(run["t"], dtype=float)
    inputs = opts.get("inputs")
    end = _EivModel(flows, ids, inputs={"t": run["t"], "values": inputs} if inputs else None).run(
        A[:, s0 - 1], tt[s0[None, :] + _eiv_np.arange(h)[:, None]], opts.get("injections"))
    obs = A[:, s0 + h - 1]
    e = ((end - obs) / sd[:, None]) ** 2
    e[~_eiv_np.isfinite(e)] = 1e6
    return e.sum(axis=0) / max(1e-9, float((((obs - A[:, s0 - 1]) / sd[:, None]) ** 2).sum()))


def _eiv_prune(flows: list[dict], ids: list[str], t: _eiv_np.ndarray, A: _eiv_np.ndarray, inputs: dict | None, rows: _eiv_np.ndarray,
           w: _eiv_np.ndarray, run: dict, opts: dict) -> tuple[list[dict], dict] | None:
    """The flows with the parts the instrumented fit cannot tell from nothing dropped and the rest
    refitted, and what was done; None when nothing is dropped or no stage passes the guard."""
    cur, names, stages = _EivInstrumented(flows, ids, t, A, inputs, rows, w), [], []
    while cur.ok and len(cur.work) > 1:
        u = cur.weakest()
        if u is None:
            break
        nxt = _EivInstrumented(_eiv_without(cur.work, u), ids, t, A, inputs, rows, w)
        if not nxt.ok:
            break
        names.append(_eiv_name(cur.work, u))
        cur = nxt
        stages.append((cur.work, list(names)))
    if not stages or not [h for h in _EIV_HORIZONS if h < len(run["t"]) / 4]:
        return None
    before = _eiv_runs(flows, ids, run, opts)
    for work, dropped in reversed(stages):
        d = _eiv_runs(work, ids, run, opts) - before
        z = float(d.sum() / max(1e-12, _eiv_np.sqrt(len(d) * d.var(ddof=1)))) if len(d) > 1 else float("inf")
        if z <= _EIV_GUARD:
            return work, {"dropped": dropped, "z": round(z, 2)}
    return None


def _eiv_refit(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None = None) -> tuple[list[dict], dict]:
    """The flows with their numbers refitted by instrumental variables where the module says, and
    what was found ({} where nothing could be tested)."""
    opts = opts or {}
    ids = [s["id"] for s in stocks]
    inputs = opts.get("inputs") or {}
    t = _eiv_np.asarray(run["t"], dtype=float)
    n = len(t)
    if not flows or n < 20 or not _eiv_known(flows, set(ids) | set(inputs)) or _eiv_np.any(_eiv_np.diff(t) != 1):
        return flows, {}
    A = _eiv_levels_array(run["levels"], ids)
    if not _eiv_np.all(_eiv_np.isfinite(_eiv_np.asarray([run["levels"].get(i, []) for i in ids], dtype=float))):
        return flows, {}
    work = _eiv_copy.deepcopy(flows)
    pulses = {float(j["t"]) for j in opts.get("injections") or []}
    rows = _eiv_np.array([i for i in range(2, n) if t[i] not in pulses and t[i - 1] not in pulses])
    fit = _EivFit(work, ids, t, A, {"t": list(run["t"]), "values": inputs} if inputs else None, rows)
    theta0 = fit.theta()
    p = len(theta0)
    if p == 0 or len(rows) < 10 * p:
        return flows, {}
    # each stock's rows weighted by the spread of its one-step residuals
    sd = fit.resid(theta0).std(axis=1)
    w = 1.0 / _eiv_np.maximum(sd, 1e-9 * max(1.0, float(_eiv_np.abs(A).max())))

    def stack(M: _eiv_np.ndarray) -> _eiv_np.ndarray:        # stocks x rows (x numbers) -> weighted rows
        return (M * (w[:, None] if M.ndim == 2 else w[:, None, None])).reshape(-1, *M.shape[2:])

    th_o = theta0.copy()
    for _ in range(_EIV_ITERATIONS):
        th_o = th_o + _eiv_np.linalg.lstsq(stack(fit.jac(th_o, 1)), stack(fit.resid(th_o)), rcond=None)[0]
    z = _eiv_white_z(fit.resid(th_o), fit.dy)
    info = {"white_z": [round(x, 2) for x in z], "used": False}
    if min(z) > -_eiv_norm.isf(_EIV_ALPHA / len(z)):
        fit.set(theta0)
        return flows, info
    fit.set(theta0)
    pruned = _eiv_prune(flows, ids, t, A, {"t": list(run["t"]), "values": inputs} if inputs else None, rows, w, run, opts)
    if pruned:
        return pruned[0], {**info, **pruned[1], "used": True}
    th_i = th_o.copy()
    for _ in range(_EIV_ITERATIONS):
        J, Z = stack(fit.jac(th_i, 1)), stack(fit.jac(th_i, 2))
        ZJ = Z.T @ J
        if not _eiv_np.all(_eiv_np.isfinite(ZJ)) or _eiv_np.linalg.cond(ZJ) > 1e12:
            fit.set(theta0)
            return flows, {**info, "skipped": "weak instruments"}
        th_i = th_i + _eiv_np.linalg.solve(ZJ, Z.T @ stack(fit.resid(th_i)))
    if not _eiv_np.all(_eiv_np.isfinite(th_i)):
        fit.set(theta0)
        return flows, {**info, "skipped": "no finite fit"}
    fit.set(_eiv_np.round(th_i, 6))
    before, after = _eiv_judge(flows, ids, run, opts), _eiv_judge(work, ids, run, opts)
    info.update(found=theta0.round(6).tolist(), instrumented=th_i.round(6).tolist(), judged=[before, after])
    if not after <= before:
        return flows, info
    return work, {**info, "used": True}


def _eiv_apply(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """A strategy's result with its flows refitted (refit), and what the refit found under "eiv"."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    try:
        flows, info = _eiv_refit(result["flows"], stocks, run, opts)
    except (ValueError, _eiv_np.linalg.LinAlgError, FloatingPointError) as e:
        return {**result, "eiv": {"error": f"{type(e).__name__}: {e}"[:200]}}
    return {**result, "flows": flows, "eiv": info}
