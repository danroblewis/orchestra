"""Experiment mass_balance (docs/research/mass-balance-hidden.md): hidden stocks reconstructed from a
unit's mass balance (sdlab/discovery/balance.py), on top of the main line.

The main line's model is found as usual. Then, while one helps: every pair (A loses to outside, B of
A's unit gets things from outside) is turned into A -> H -> B with H's level reconstructed from the
balance; a pair that does not balance (H drifts, goes negative, or A would send more than it loses)
is rejected before it is judged. A proposal is accepted when the model with it behaves better on the
data than the model it came from with B's arrivals held at their mean (with its pieces, fitted to
this run, the old model always looks better on the run). The found model's unmeasured stocks carry
their own estimated levels (result["inferred_levels"]): what the model itself gives from the
measured levels (sdlab/discovery/observer.py).

opts: "mb_margin" (accept only below margin x the reference's error; default 1.0), "mb_against"
("means": B's arrivals at their mean, the default; "found": the model as found), "mb_max" (hidden
stocks at most; default 3), "mb_rest" (also try keeping what A loses beyond
what H takes as a loss to outside; default False: conservation first, A loses only what H takes, as
the main line reads a drain off what receivers take), "mb_tol" (with mb_rest, the rest is kept only
if that behaves better by more than this share; default 0.05), "mb_all" (try every candidate of the main
line, not only the chosen one; default False), "mb_trace" (print every proposal).
"""

from __future__ import annotations

from ..balance import arrivals, pairs, propose
from ..identify import VARIANTS
from ..identify import identify as main_line
from ..identify import judge as main_judge
from ..matrix import identify_one
from ..observer import observe
from ..simulate import behaviour_error

HORIZONS = (5, 20, 100)


def judge(flows: list[dict], stocks: list[dict], run: dict, inferred: dict | None = None) -> float:
    hs = [h for h in HORIZONS if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    ids = [s["id"] for s in stocks]
    return sum(behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, inferred=inferred) for h in hs) / len(hs)


def at_means(flows: list[dict], idx: list[int]) -> list[dict]:
    """The flows with the arrivals in idx (pieces) held at their mean."""
    out = []
    for i, f in enumerate(flows):
        if i in idx and f.get("inflow"):
            w = [g["to"] - g["from"] + 1 for g in f["inflow"]]
            m = sum(g["value"] * n for g, n in zip(f["inflow"], w)) / max(1, sum(w))
            f = {k: v for k, v in f.items() if k not in ("inflow", "changes")}
            f["rate"] = {"form": "constant", "value": m}
        out.append(f)
    return out


def augment(flows: list[dict], stocks: list[dict], run: dict, opts: dict, tried: list) -> tuple[list[dict], dict, list[str]]:
    """The flows with every hidden stock the balance supports (accepted one at a time, best first),
    their estimated levels, and the receivers whose arrivals they replaced."""
    ids = [s["id"] for s in stocks]
    levels, receivers = {}, []
    trace = opts.get("mb_trace")
    margin = opts.get("mb_margin", 1.0)
    tol = opts.get("mb_tol", 0.05)
    for _ in range(opts.get("mb_max", 3)):
        base = judge(flows, stocks, run, levels)
        best = None
        for a, b in pairs(flows, stocks):
            p = propose(flows, stocks, run, a, b, opts)
            if p is None:
                continue
            rec = p.get("rec") or {}
            if p["flows"] is None:
                tried.append({"pair": f"{a}>{b}", "why": p["why"]})
                if trace:
                    print(f"  {a} -> ? -> {b}: rejected ({p['why']})")
                continue
            h = p["hidden"]
            ref = base if opts.get("mb_against") == "found" else judge(at_means(flows, arrivals(flows, a, b)), stocks, run, levels)
            pick = None
            variants = [("all to H", p.get("alt") or p["flows"])]
            if opts.get("mb_rest") and p.get("alt"):
                variants.append(("rest to outside", p["flows"]))
            for name, fl in variants:
                est = observe(fl, ids, run["t"], run["levels"], [h], {h: p["level"][0]})
                inferred = {**levels, **est}
                e = judge(fl, stocks, run, inferred)
                tried.append({"pair": f"{a}>{b}", "variant": name, "error": e, "against": ref, "alpha": rec.get("alpha"), "d": rec.get("d")})
                if trace:
                    print(f"  {a} -> H -> {b} ({name}): alpha {rec['alpha']:.3f}, d {rec['d']:.4f}, H0 {rec['h0']:.1f}; error {e:.4f} vs {ref:.4f} (found {base:.4f})")
                # conservation first: A loses only what H takes unless the data clearly says otherwise
                if pick is None or (1 + tol) * e < pick[0]:
                    pick = (e, fl, inferred, b)
            if pick and pick[0] < margin * ref and (best is None or pick[0] < best[0]):
                best = pick
        if best is None:
            break
        flows, levels = best[1], best[2]
        receivers.append(best[3])
    return flows, levels, receivers


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    tried: list = []
    if not opts.get("mb_all"):
        r = main_line(stocks, run, opts)
        flows, levels, _ = augment(r["flows"], stocks, run, opts, tried)
    else:
        r, flows, levels = every_candidate(stocks, run, opts, tried)
    r["flows"] = flows
    if levels:
        r["inferred_levels"] = levels
        r["chosen"] = f"{r.get('chosen')} + {len(levels)} hidden from the balance"
    r["balance"] = tried
    return r


def every_candidate(stocks: list[dict], run: dict, opts: dict, tried: list):
    """The balance tried on every candidate of the main line (a constant-inflow candidate may have
    nothing to pair where a changing-inflow one does). The chosen candidate (as the main line chooses)
    is kept unless another candidate with hidden stocks behaves better than it does with the arrivals
    those stocks replaced held at their mean."""
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    cands = []
    for v in VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        c = identify_one(stocks, run, {**opts, **v})
        cands.append((main_judge(c["flows"], stocks, run) if c["flows"] else float("inf"), v["name"], c))
    e0, name0, r = min(cands, key=lambda x: x[0])
    r["chosen"], r["tried"] = name0, [{"name": n, "error": e} for e, n, _ in cands]
    flows, levels, _ = augment(r["flows"], stocks, run, opts, tried)
    best = (judge(flows, stocks, run, levels), flows, levels, name0) if levels else None
    for e, name, c in cands:
        if name == name0 or not c["flows"]:
            continue
        f2, l2, recv = augment(c["flows"], stocks, run, opts, [])
        if not l2:
            continue
        e2 = judge(f2, stocks, run, l2)
        ref = judge(at_means(r["flows"], [i for i, f in enumerate(r["flows"]) if f.get("to") in recv and f.get("from") is None and not f.get("driver")]), stocks, run)
        if opts.get("mb_trace"):
            print(f"  candidate {name}: {len(l2)} hidden, error {e2:.4f} vs chosen at means {ref:.4f}")
        if e2 < ref and (best is None or e2 < best[0]):
            best = (e2, f2, l2, name)
    if best is None:
        return r, r["flows"], {}
    r["chosen"] = best[3]
    return r, best[1], best[2]


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
