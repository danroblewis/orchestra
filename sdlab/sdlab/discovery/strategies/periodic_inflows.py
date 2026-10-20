"""Outside inflows as a repeating profile (docs/research/periodic-inflows.md).

The main line first. Then each stock whose outside inflow is better told, by BIC, as one period's
profile repeated plus a slow level (discovery/periodic.py) has that inflow taken out as known, and the
main line runs again on the rest: its rows' levels are fitted beside the profile instead of beside
pieces that could follow anything, and whatever the profile leaves is still free to become pieces.
The profile is written into the result as an ordinary outside inflow in segments (with the pieces the
second pass found added in), so the simulator and the page are unchanged. Without a period that pays,
the result is the main line's.
"""

from __future__ import annotations

import numpy as np

from ..identify import identify as matrix_identify
from ..identify import VARIANTS, judge
from ..matrix import configurations, identify_one, known_changes, known_flows
from ..periodic import find, refit


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
    for f in flows:
        if f.get("inflow") and not f.get("from") and f.get("to") in total:
            total[f["to"]] += _series(f, times)
            continue
        if f.get("inflow") and f.get("from") in total and not f.get("to"):
            total[f["from"]] -= _series(f, times)
            continue
        out.append(f)
    for s, v in total.items():
        mean = float(v.mean())
        segs = _segments(times, v)
        if mean >= 0:
            out.append({"from": None, "to": s, "ratio": 1, "rate": {"form": "constant", "value": round(mean, 4)}, "rates": [{"form": "constant", "value": round(mean, 4)}],
                        "perStep": mean, "nearly": [], "bothWays": False, "inflow": segs, "changes": len(segs) - 1, "period": profiles[s]["P"]})
        else:
            neg = [{**g, "value": -g["value"]} for g in segs]
            out.append({"from": s, "to": None, "ratio": 1, "rate": {"form": "constant", "value": round(-mean, 4)}, "rates": [{"form": "constant", "value": round(-mean, 4)}],
                        "perStep": -mean, "nearly": [], "bothWays": False, "inflow": neg, "changes": len(neg) - 1, "period": profiles[s]["P"]})
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
    profiles = find(stocks, run, opts)
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
    measurement error (the _eiv_ code below)."""
    return _eiv_apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)


# Errors in variables (docs/research/eiv-refit.md): a copy of the strategies' eiv.py, its names prefixed
# _eiv_. When the levels carry measurement error (one-step residuals negatively correlated from step to
# step), the found numbers are refitted with the levels two steps back as instruments, and kept only if
# the model then runs at least as close to the data over 5, 20 and 100 steps.
import copy as _eiv_copy  # noqa: E402

import numpy as _eiv_np  # noqa: E402
from scipy.stats import norm as _eiv_norm  # noqa: E402

from ..simulate import Model as _EivModel, behaviour_error as _eiv_behaviour_error, levels_array as _eiv_levels_array  # noqa: E402

_EIV_ALPHA = 1e-3          # the white-noise test's level (one-sided, over the stocks)
_EIV_ITERATIONS = 3        # Gauss-Newton steps of each fit (the rates are linear in their numbers, so one is
                      # exact unless a floor, a shared stock or an effect bends them)
_EIV_HORIZONS = (5, 20, 100)


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
