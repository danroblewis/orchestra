"""Outside inflows as a repeating profile (docs/research/periodic-inflows.md).

The main line first. Then each stock whose outside inflow is better told, by BIC, as one period's
profile repeated plus a slow level (discovery/periodic.py) has that inflow taken out as known, and the
main line runs again on the rest: its rows' levels are fitted beside the profile instead of beside
pieces that could follow anything, and whatever the profile leaves is still free to become pieces.
The profile is written into the result as an ordinary outside inflow in segments (with the pieces the
second pass found added in), so the simulator and the page are unchanged. Without a period that pays,
the result is the main line's.

The declared boundary (boundary.py, a copy of matrix/boundary.py at 723f72c; docs/research/declared-boundary.md):
a profile is an estimated outside flow, so it is looked for only on a stock whose boundary may have one;
the main line's rows are fitted inside the boundary (earned.refit), every candidate (both passes) is
guarded before the judge, and the answer is kept inside it (guard and moves where declared, each outside
flow priced as a boundary claim where not).
"""

from __future__ import annotations

import numpy as np

from . import boundary
from .earned import main_line as matrix_identify
from ...identify import VARIANTS, judge
from ...matrix import configurations, identify_one, known_changes, known_flows
from ...periodic import find, refit


def _series(flow: dict, times: np.ndarray) -> np.ndarray:
    segs = flow["inflow"]
    out = np.full(times.shape[0], float(segs[-1]["value"]))
    for g in reversed(segs):
        m = (times >= g["from"]) & (times <= g["to"])
        out[m] = float(g["value"])
    return out


def _segments(times: np.ndarray, v: np.ndarray) -> list[dict]:
    v = np.round(v, 4)
    out = []
    for k in range(v.shape[0]):
        if out and out[-1]["value"] == v[k]:
            out[-1]["to"] = float(times[k])
        else:
            out.append({"from": float(times[k]), "to": float(times[k]), "value": float(v[k])})
    return out


def with_profiles(flows: list[dict], profiles: dict, t: list) -> list[dict]:
    """flows with each profiled stock's outside inflow = its profile + the pieces found beside it."""
    times = np.asarray(t[1:], dtype=float)
    out = []
    total = {s: fp["series"].copy() for s, fp in profiles.items()}
    # (the boundary's price, boundary.py) the profile's own numbers (its segments' values and places, the
    # slow pieces', the period) plus a value and a place per piece folded into it
    numbers = {s: 2 * len(fp["segments"]) + 2 * max(0, len(fp["slow"]) - 2) + 1 for s, fp in profiles.items()}
    for f in flows:
        if f.get("inflow") and not f.get("from") and f.get("to") in total:
            total[f["to"]] += _series(f, times)
            numbers[f["to"]] += 2 * len(f["inflow"]) - 1
            continue
        if f.get("inflow") and f.get("from") in total and not f.get("to"):
            total[f["from"]] -= _series(f, times)
            numbers[f["from"]] += 2 * len(f["inflow"]) - 1
            continue
        out.append(f)
    for s, v in total.items():
        mean = float(v.mean())
        segs = _segments(times, v)
        if mean >= 0:
            out.append({"from": None, "to": s, "ratio": 1, "rate": {"form": "constant", "value": round(mean, 4)}, "rates": [{"form": "constant", "value": round(mean, 4)}],
                        "perStep": mean, "nearly": [], "bothWays": False, "inflow": segs, "changes": len(segs) - 1, "period": profiles[s]["P"], "numbers": numbers[s]})
        else:
            neg = [{**g, "value": -g["value"]} for g in segs]
            out.append({"from": s, "to": None, "ratio": 1, "rate": {"form": "constant", "value": round(-mean, 4)}, "rates": [{"form": "constant", "value": round(-mean, 4)}],
                        "perStep": -mean, "nearly": [], "bothWays": False, "inflow": neg, "changes": len(neg) - 1, "period": profiles[s]["P"], "numbers": numbers[s]})
    return out


def reader_columns(prev: np.ndarray, ids: list[str], t: list, opts: dict) -> tuple[np.ndarray, list[str]]:
    """Every series a row's numbers may read, and their names: the stocks' levels at the start of each
    step, then the measured inputs (opts "inputs") during it (the value at the step's end), as the
    matrix method builds them. An input is a known regressor of the row, never a stock."""
    inputs = [(k, np.nan_to_num(np.asarray(v, dtype=float))[1: len(t)]) for k, v in (opts.get("inputs") or {}).items() if k not in ids]
    if not inputs:
        return prev, list(ids)
    return np.vstack([prev] + [v[None, :] for _, v in inputs]), list(ids) + [k for k, _ in inputs]


def remeasure(r: dict, profiles: dict, stocks: list[dict], run: dict, opts: dict) -> None:
    """Each profile measured again beside the numbers its row ends with (conservation may have
    changed its drain after the profile was measured), with the pieces found beside it kept."""
    ids = [s["id"] for s in stocks]
    t = run["t"]
    T = len(t) - 1
    times = np.asarray(t[1:], dtype=float)
    lv = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, [0] * len(t)), dtype=float) for i in ids]))
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    columns, names = reader_columns(prev, ids, t, opts)
    if opts.get("known"):
        dy = dy - known_changes(opts["known"], ids, len(t))[:, 1:]
    conf = configurations(opts.get("eras"), t) if r.get("eras") else None
    cfg = conf[1] if conf else np.zeros(T, dtype=int)
    rows = {m["id"]: m for m in r.get("matrix") or []}
    for s, fp in profiles.items():
        row = rows.get(s)
        if row is None:
            continue
        k = ids.index(s)
        res = dy[k].copy()
        for c, coef in enumerate(row["coefL"]):
            m = cfg == c
            for j, b in coef.items():
                res[m] -= b * columns[names.index(j)][m]
        for f in r["flows"]:
            if f.get("inflow") and not f.get("from") and f.get("to") == s:
                res -= _series(f, times)
            elif f.get("inflow") and f.get("from") == s and not f.get("to"):
                res += _series(f, times)
        fp["series"] = refit(res, fp)


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    b = boundary.Boundary(run)
    # a profile is an estimated outside flow: only on a stock whose boundary may have one
    profiles = {s: fp for s, fp in (find(stocks, run, opts) or {}).items() if b.pieces_ok(s)}
    if not profiles:
        r = matrix_identify(stocks, run, opts)
        r["periods"] = {}
        return r
    n = len(run["t"])
    ids = [s["id"] for s in stocks]
    known = {k: list(np.nan_to_num(np.asarray(v, dtype=float))[:n]) + [0.0] * max(0, n - len(v)) for k, v in (opts.get("known") or {}).items()}
    for s, fp in profiles.items():
        base = np.asarray(known.get(s) or [0.0] * n, dtype=float)
        base[1:] += fp["series"]
        known[s] = list(base)
    # the main line's candidates, each with the profiles taken out as known; a profiled row's inflow
    # varies, so conservation may set its drain from its receivers, as for a row with pieces. Each
    # candidate's profiles are measured again beside its numbers before it is judged.
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    extra = known_flows(opts["known"], ids, run["t"]) if opts.get("known") else []
    variants = opts.pop("variants", None) or VARIANTS
    best, tried = None, []
    for v in variants:
        if v.get("split_eras") and not has_eras:
            continue
        r = identify_one(stocks, run, {**opts, **v, "known": known, "varying_inflow": set(profiles)})
        own = {s: dict(fp) for s, fp in profiles.items()}
        remeasure(r, own, stocks, run, opts)
        r["flows"] = with_profiles(r["flows"], own, run["t"])
        if b.declared and r.get("flows"):
            r = boundary.apply(r, stocks, run, opts, final=False)
        e = judge(r["flows"] + extra, stocks, run)
        tried.append({"name": v["name"], "error": e})
        if best is None or e < best[1]:
            best = (r, e, v["name"])
    r = best[0]
    r["chosen"], r["tried"] = best[2], tried
    if opts.get("against_main_line", True):
        # the main line's own choice competes on the same terms: a profile that takes an internal
        # flow (a rate that repeats, times a level) makes the model run away, and the judge sees it
        m = matrix_identify(stocks, run, {**opts, "variants": variants})
        e = min(x["error"] for x in m["tried"])
        if e < best[1]:
            m["tried"] = tried + [{"name": "main line: " + x["name"], "error": x["error"]} for x in m["tried"]]
            m["periods"] = {}
            m["rejected_periods"] = {s: fp["P"] for s, fp in profiles.items()}
            return m
        r["tried"] = tried + [{"name": "main line: " + x["name"], "error": x["error"]} for x in m["tried"]]
    r["periods"] = {s: {"period": fp["P"], "segments": len(fp["segments"]), "slow": len(fp["slow"]) - 1} for s, fp in profiles.items()}
    return r


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (the _eiv_ code below), then kept inside the announced boundary (boundary.py:
    the guard and moves where one is declared, each outside flow priced as a boundary claim where none is)."""
    r = _eiv_apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)
    return boundary.apply(r, stocks, run, opts)


# Errors in variables (docs/research/eiv-refit.md): a copy of the strategies' eiv.py, its names prefixed
# _eiv_. When the levels carry measurement error (one-step residuals negatively correlated from step to
# step), the found numbers are refitted with the levels two steps back as instruments, and kept only if
# the model then runs at least as close to the data over 5, 20 and 100 steps. Parts the instrumented fit
# cannot tell from nothing are pruned first (docs/research/k8s-303.md).
import copy as _eiv_copy  # noqa: E402

import numpy as _eiv_np  # noqa: E402
from scipy.stats import norm as _eiv_norm  # noqa: E402

from ...simulate import Model as _EivModel, behaviour_error as _eiv_behaviour_error, levels_array as _eiv_levels_array, starts_for as _eiv_starts_for  # noqa: E402

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


def _eiv_carried(flows: list[dict], ids: list[str], t: _eiv_np.ndarray, L: _eiv_np.ndarray, inputs: dict | None) -> _eiv_np.ndarray:
    """What each flow carries in each step from levels L at times t (flows x steps; what its receiver
    gets), each flow on its own."""
    out = _eiv_np.zeros((len(flows), L.shape[1]))
    for i, f in enumerate(flows):
        if f.get("from") in ids:
            out[i] = -_EivModel([{**f, "to": None}], ids, inputs=inputs).change(L, t)[ids.index(f["from"])] / float(f.get("ratio") or 1)
        elif f.get("to") in ids:
            out[i] = _EivModel([f], ids, inputs=inputs).change(L, t)[ids.index(f["to"])]
    return out


def _eiv_level_ll(y: _eiv_np.ndarray, level: _eiv_np.ndarray) -> float:
    """-2 log-likelihood of a level-space residual y = R0 + e with var(e) = a + b x level^2 (feasible GLS:
    R0 and a, b fitted from the residuals in turn; each squared residual counted at most TRIM^2 variances)."""
    V = _eiv_np.column_stack([_eiv_np.ones_like(level), level ** 2])
    v = _eiv_np.ones_like(y)
    for it in range(4):
        w = 1 / v
        r = y - float((w * y).sum() / w.sum())
        z = r ** 2 if it == 0 else _eiv_np.minimum(r ** 2, _EIV_TRIM ** 2 * v)
        ab = _eiv_np.linalg.lstsq(V * w[:, None], z * w, rcond=None)[0]
        v = _eiv_np.maximum(max(ab[0], 0.0) + max(ab[1], 0.0) * level ** 2, 1e-9 * max(float(_eiv_np.mean(z)), 1e-12))
    w = 1 / v
    r = y - float((w * y).sum() / w.sum())
    return float(_eiv_np.sum(_eiv_np.log(v) + _eiv_np.minimum(r ** 2 / v, _EIV_TRIM ** 2)))


def _eiv_set_rate(f: dict, rate: dict) -> None:
    f["rate"] = rate
    if f.get("rates"):
        f["rates"] = [rate]


def _eiv_moves(flows: list[dict], fi: int, R: str) -> list[tuple[list[dict], int, int | None, dict | None]]:
    """The drain flows[fi] made a move into R, and, for each inflow from outside into R that reads the
    drain's stock, the move replacing that reading; each as (flows, how many numbers it removes, the
    replaced inflow's index in flows, what is left of that inflow or None). The moved flow is marked
    "_moved"."""
    X = flows[fi]["from"]
    a = _eiv_copy.deepcopy(flows)
    a[fi]["to"], a[fi]["_moved"] = R, True
    out: list = [(a, 0, None, None)]
    for gi, g in enumerate(flows):
        r = g.get("rate") or {}
        if g.get("from") is not None or g.get("to") != R or g.get("byTime") or g.get("inflow"):
            continue
        if r.get("form") == "proportional" and r.get("stock") == X:
            rest = None
        elif r.get("form") == "linear" and any(x.get("stock") == X and x.get("k") is not None for x in r.get("terms") or []):
            terms = [x for x in r["terms"] if x.get("stock") != X]
            rest = None
            if terms or r.get("c"):
                rest = _eiv_copy.deepcopy(g)
                _eiv_set_rate(rest, {**r, "terms": terms} if terms else {"form": "constant", "value": r["c"]})
        else:
            continue
        b = [h for hi, h in enumerate(a) if hi != gi] if rest is None else [rest if hi == gi else h for hi, h in enumerate(a)]
        out.append((b, len(_eiv_slots([g])) - (len(_eiv_slots([rest])) if rest else 0), gi, rest))
    return out


def _eiv_joined(flows: list[dict]) -> list[dict]:
    """The moved flow (marked "_moved", the mark removed) joined to a proportional flow on the same stock
    between the same stocks, if there is one."""
    fi = next(i for i, g in enumerate(flows) if g.get("_moved"))
    f = flows[fi]
    del f["_moved"]
    r = f.get("rate") or {}
    if f.get("byTime") or r.get("form") != "proportional":
        return flows
    for gi, g in enumerate(flows):
        q = g.get("rate") or {}
        if (gi != fi and g.get("from") == f["from"] and g.get("to") == f["to"] and not g.get("byTime")
                and q.get("form") == "proportional" and q.get("stock") == r.get("stock")
                and float(g.get("ratio") or 1) == float(f.get("ratio") or 1)):
            _eiv_set_rate(g, {**q, "k": float(q["k"]) + float(r["k"])})
            return [h for hi, h in enumerate(flows) if hi != fi]
    return flows


def _eiv_merge(flows: list[dict], ids: list[str], run: dict, opts: dict) -> tuple[list[dict], list[str]]:
    """The flows with drains to outside made moves where a measured stock's level shows it receives
    them (the module's Moves), and the moves made."""
    t = _eiv_np.asarray(run["t"], dtype=float)
    A = _eiv_levels_array(run["levels"], ids)
    n = A.shape[1]
    inputs = {"t": list(run["t"]), "values": opts["inputs"]} if opts.get("inputs") else None
    J = _eiv_np.zeros((len(ids), n - 1))                     # announced injections, added before their step's flows
    for j in opts.get("injections") or []:
        if j.get("stock") in ids:
            J[ids.index(j["stock"]), _eiv_np.nonzero(t[1:] == float(j["t"]))[0]] += float(j["amount"])
    L, tt, price = A[:, :-1] + J, t[1:], float(_eiv_np.log(n))
    done: list[str] = []
    for _ in range(len(flows)):
        c = _eiv_carried(flows, ids, tt, L, inputs)
        net = _eiv_np.zeros((len(ids), n - 1))               # what the flows add to each stock in each step
        for i, f in enumerate(flows):
            if f.get("to") in ids:
                net[ids.index(f["to"])] += c[i]
            if f.get("from") in ids:
                net[ids.index(f["from"])] -= c[i] * float(f.get("ratio") or 1)
        y = A[:, 1:] - _eiv_np.cumsum(J + net, axis=1)       # each stock's level less what its flows added
        now: dict[int, float] = {}
        best = None
        for fi, f in enumerate(flows):
            if f.get("to") is not None or f.get("from") not in ids or f.get("inflow"):
                continue
            for r, R in enumerate(ids):
                if R == f["from"]:
                    continue
                if r not in now:
                    now[r] = _eiv_level_ll(y[r], A[r, 1:])
                for cand, fewer, gi, rest in _eiv_moves(flows, fi, R):
                    extra = c[fi].copy()
                    if gi is not None:
                        extra -= c[gi]
                        if rest is not None:
                            extra += _eiv_carried([rest], ids, tt, L, inputs)[0]
                    gain = now[r] - _eiv_level_ll(y[r] - _eiv_np.cumsum(extra), A[r, 1:]) - price * (1 - fewer)
                    if gain > price and (best is None or gain > best[0]):
                        best = (gain, cand, f"{f['from']} -> {R}" + (" (replacing an inflow)" if gi is not None else ""))
        if best is None:
            break
        flows = _eiv_joined(best[1])
        done.append(best[2])
    return flows, done


def _eiv_refit(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None = None) -> tuple[list[dict], dict]:
    """The flows with their numbers refitted by instrumental variables where the module says, drains
    made moves where a level shows its receiver (Moves), and what was found ({} where nothing could be
    tested)."""
    out, info = _eiv_refit_numbers(flows, stocks, run, opts)
    if not info.pop("error", False):
        return out, info
    moved, done = _eiv_merge(out, [s["id"] for s in stocks], run, opts or {})
    if not done:
        return out, info
    return moved, {**info, "moved": done, "used": True}


def _eiv_refit_numbers(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None = None) -> tuple[list[dict], dict]:
    """refit's numbers and pruning; info["error"] where the data show measurement error."""
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
    info["error"] = True
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
        # (as eiv.py, the declared boundary) a structure that arrives with nothing to prune (outside flows
        # kept to the boundary already) is held to the pruned model's test: no further from the data at
        # the judge's longest horizon by more than GUARD paired standard errors, since at shorter horizons
        # the measurement error at each run's start still favours the biased numbers (303 meas-long)
        if not [h for h in _EIV_HORIZONS if h < len(run["t"]) / 4]:
            return flows, info
        d = _eiv_runs(work, ids, run, opts) - _eiv_runs(flows, ids, run, opts)
        z = float(d.sum() / max(1e-12, _eiv_np.sqrt(len(d) * d.var(ddof=1)))) if len(d) > 1 else float("inf")
        info["z"] = round(z, 2)
        if not z <= _EIV_GUARD:
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


# A capacity limit offered to the fit (capmin.py, docs/research/k8s-306-s1.md, 2026-10-21): identify above
# runs with the regime-clipped series MIN(X, theta x Y) as one more measured input where the data show a
# limit, and every term that reads it is written back as MIN(a x X, a theta x Y).
from . import capmin as _capmin  # noqa: E402

_identify_linear = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    """(2026-10-21, k8s-307, docs/research/k8s-307-c1.md) Between the fit and the MIN written back, where the
    levels carry measurement error, the numbers are refitted and the structure revised on the output error
    and judged on a Kalman likelihood (oefit.py, a copy of combined2's: the model run through the whole
    record against the measured levels)."""
    from . import oefit

    o, cap = _capmin.offer(stocks, run, opts)
    r = oefit.refit(_identify_linear(stocks, run, o, *args, **kw), stocks, run, o, cap)
    return _capmin.restore(r, cap)
