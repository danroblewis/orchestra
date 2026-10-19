"""identify(): the per-step model by output error: linear terms pruned by BIC, then products and
hinges where BIC says the data earn them (docs/research/odefit.md)."""

from __future__ import annotations

import math
import time

import numpy as np

from ...identify import identify as mainline
from ...simulate import behaviour_error
from . import compare as C
from . import extend as E
from . import fit as F
from .write import sig, to_flows

SEG = 100            # steps per segment: each segment's start state is estimated, the model runs free within it
EARN = 10.0          # BIC a nonlinear extension must save over the linear model to be kept
TRAIN = 0.7          # held-out check: numbers refitted on this first share, judged on the rest
HELD_SEG = 20        # held-out segments (each with its start state fitted): the skill horizon
OWN_OPTS = ("budget", "seg", "prune", "products", "hinges")
BETTER = 0.8         # an extension's held-out error must be at most this share of the linear model's


def prepare(stocks: list[dict], run: dict, opts: dict) -> tuple[F.Data, list[str], list[str]]:
    ids = [s["id"] for s in stocks]
    t = np.asarray(run["t"], dtype=float)
    Y = np.nan_to_num(np.array([np.asarray(run["levels"][i], dtype=float) for i in ids]).T)
    inputs = sorted((opts.get("inputs") or {}).keys())
    U = np.array([np.nan_to_num(np.asarray(opts["inputs"][k], dtype=float)) for k in inputs]).T if inputs else np.zeros((len(t), 0))
    J = np.zeros_like(Y)
    pos = {float(x): k for k, x in enumerate(t)}
    for j in opts.get("injections") or []:
        k = pos.get(float(j["t"]))
        if k is not None and j.get("stock") in ids:
            J[k, ids.index(j["stock"])] += float(j["amount"])
    return F.Data(Y, U, J), ids, inputs


def nparams(spec: F.Spec) -> int:
    return spec.nW + len(spec.hinges) * spec.H


FLOOR = np.zeros(0)  # set per run (identify): each stock's weighted rss at the data's rounding


def resolution(Y: np.ndarray) -> np.ndarray:
    """Each stock's recording step: 10^-k for the fewest decimals k (up to 8) that hold all its
    levels (4-decimal levels: 1e-4); 0 when none do."""
    out = np.zeros(Y.shape[1])
    for i in range(Y.shape[1]):
        y = Y[:, i]
        for k in range(9):
            if np.allclose(y * 10 ** k, np.round(y * 10 ** k), rtol=0, atol=1e-6):
                out[i] = 10.0 ** -k
                break
    return out


def bic(rss: np.ndarray, n: int, k: int) -> float:
    """BIC with each stock's rss floored at its rounding (nothing earns its place by fitting the
    rounding of the record)."""
    floor = FLOOR if FLOOR.shape == np.shape(rss) else 0.0
    return float(n * np.sum(np.log(np.maximum(np.maximum(rss, floor), 1e-300) / n)) + k * math.log(n))


def prune(spec: F.Spec, d: F.Data, w: np.ndarray, seg: int, base: dict, deadline: float, trace: list | None = None,
          only: set | None = None) -> tuple[F.Spec, dict]:
    """Backward elimination: drop the term whose removal lowers BIC most, until none does (`only`:
    the columns that may be dropped)."""
    n = d.n
    cur, res = spec, base
    score = bic(res["rss"], n, nparams(cur))
    while time.perf_counter() < deadline:
        best = None
        flat = np.flatnonzero(cur.mask.ravel())
        for pos, f in enumerate(flat):
            i, j = divmod(int(f), cur.P)
            if only is not None and j not in only:
                continue
            sp = cur.copy()
            sp.mask[i, j] = False
            r = F.fit(sp, d, seg, w, theta0=np.delete(res["theta"], pos), max_nfev=60, starts0=res.get("starts"))
            b = bic(r["rss"], n, nparams(sp))
            if best is None or b < best[0]:
                best = (b, sp, r, (i, j))
            if time.perf_counter() > deadline:
                break
        if best is None or best[0] >= score:
            break
        score, cur, res = best[0], best[1], best[2]
        if trace is not None:
            trace.append({"drop": best[3], "bic": round(score, 2)})
    return cur, res


def cut(d: F.Data, a: int, b: int) -> F.Data:
    return F.Data(d.Y[a:b], d.U[a:b], d.J[a:b])


def held_out(spec: F.Spec, theta: np.ndarray, d: F.Data, w: np.ndarray, seg: int, starts: list | None) -> float:
    """The numbers refitted on the first TRAIN of the run (from theta), then the weighted output
    error over the rest in HELD_SEG-step segments, each from its own fitted start state."""
    k = int(TRAIN * d.n)
    if d.n - k < HELD_SEG:
        return float("nan")
    tr, te = cut(d, 0, k), cut(d, k, d.n)
    segs_tr = F.segments(tr.n, seg)
    st = None if starts is None else [starts[min(len(starts) - 1, i)] for i in range(len(segs_tr))]
    r = F.fit(spec, tr, seg, w, theta0=theta, max_nfev=100, starts0=st)
    return float(F.fit_starts(spec, te, HELD_SEG, w, r["theta"]).sum())


def hinge_flows(spec: F.Spec, Hs: np.ndarray, ids: list[str], inputs: list[str]) -> list[dict]:
    names = ids + inputs
    out = []
    for (i, g), h in zip(spec.hinges, Hs):
        terms = [{"stock": names[j], "k": sig(h[j])} for j in range(len(names)) if h[j] != 0]
        rate = {"form": "linear", "c": sig(h[-1]), "terms": terms}
        out.append({"from": None, "to": ids[i], "ratio": 1, "rate": rate, "note": "switches off at 0"} if g > 0 else
                   {"from": ids[i], "to": None, "ratio": 1, "rate": rate, "note": "switches off at 0"})
    return out


def noise_kind(spec: F.Spec, theta: np.ndarray, d: F.Data, w: np.ndarray, seg: int) -> dict:
    """Per stock: R, the output error's variance over the fitted model's one-step error's, and the
    one-step error's lag-1 autocorrelation rho. Measurement error alone: R about 1/2 (the one-step
    error differences two errors), rho about -1/2. Noise in the dynamics (counting noise, random
    shocks): the output error accumulates it (R well above 1) while the one-step error is white
    (rho near 0). A deterministic misfit: both smooth (rho near 1)."""
    segs = F.segments(d.n, seg)
    oe = (residuals_of(spec, theta, d, segs, w)).reshape(d.n, d.S)
    W, Hs = spec.unpack(theta)
    X = (d.Y[:-1] + d.J[1:])
    pred = X.T + W @ F.columns(X.T, d.U[1:].T, spec)
    if spec.hinges:
        lin = np.vstack([X.T, d.U[1:].T, np.ones((1, d.n - 1))])
        for (i, g), h in zip(spec.hinges, Hs):
            pred[i] += g * np.maximum(0.0, h @ lin)
    one = (d.Y[1:] - pred.T) * w
    R = oe.var(axis=0) / np.maximum(one.var(axis=0), 1e-300)
    c = one - one.mean(axis=0)
    rho = (c[1:] * c[:-1]).sum(axis=0) / np.maximum((c ** 2).sum(axis=0), 1e-300)
    return {"R": R.tolist(), "rho": rho.tolist()}


def residuals_of(spec, theta, d, segs, w):
    """Output errors with each segment's start state fitted (solved for a linear spec)."""
    if spec.linear():
        return F.residuals(theta, spec, d, segs, w)
    r = F._fit_nonlinear(spec, d, segs, w, theta, np.ones_like(theta), 50, None, fixed=True)
    return F.residuals(theta, spec, d, segs, w, {"starts": r["starts"]})


def judge(flows: list[dict], stocks: list[dict], run: dict, opts: dict, horizons=(5, 20, 100)) -> float:
    """The main line's behaviour judge (identify.judge) with the measured inputs the flows read."""
    hs = [h for h in horizons if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    ids = [s["id"] for s in stocks]
    return sum(behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, injections=opts.get("injections"),
                               inputs=opts.get("inputs")) for h in hs) / len(hs)


def counted(run: dict) -> bool:
    """Levels that are all whole numbers: things counted, moving in whole units (the main line's ground)."""
    for v in run["levels"].values():
        a = np.asarray(v, dtype=float)
        a = a[np.isfinite(a)]
        if a.size and not np.all(a == np.round(a)):
            return False
    return True


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The main line's model, or the output-error model where it behaves better on the data."""
    opts = dict(opts or {})
    base = mainline(stocks, run, {k: v for k, v in opts.items() if k not in OWN_OPTS})
    if counted(run):
        return {**base, "chosen_by": "counted levels: the main line"}
    t = np.asarray(run["t"], dtype=float)
    if len(t) < 2 or not np.allclose(np.diff(t), 1.0):
        return {**base, "chosen_by": "uneven times: the main line"}
    if len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2:
        return {**base, "chosen_by": "announced eras: the main line"}
    try:
        own = output_error(stocks, run, opts)
    except Exception as e:                                     # noqa: BLE001  (the main line's model stands)
        return {**base, "chosen_by": f"output error failed: {type(e).__name__}: {e}"}
    if not own.get("flows"):
        return {**base, "chosen_by": "output error found nothing"}
    spec, theta, d, seg, _ = own["_fit"]
    own["noise"] = noise_kind(spec, theta, d, 1.0 / np.maximum(np.asarray(own["odefit"]["noise_sd"]), 1e-9), seg)
    if E.runs_away(spec, theta, d):
        return {**base, "chosen_by": "the output error model runs away: the main line"}
    shocks = dynamics_noise(own["noise"])
    choice = choose(base, own, stocks, run, opts, shocks)
    own.pop("_fit", None)
    if choice["pick"] == "output error":
        return {**own, "judged": choice, "chosen_by": f"output error model predicts better ({choice['how']})"}
    return {**base, "judged": choice, "chosen_by": f"the main line predicts better ({choice['how']})"}


def _slice(run: dict, opts: dict, a: int, b: int) -> tuple[dict, dict]:
    t = list(run["t"])[a:b]
    r = {"t": t, "levels": {k: list(v)[a:b] for k, v in run["levels"].items()}}
    o = {k: v for k, v in opts.items() if k not in ("inputs", "injections")}
    if opts.get("inputs"):
        o["inputs"] = {k: list(v)[a:b] for k, v in opts["inputs"].items()}
    if opts.get("injections"):
        o["injections"] = [j for j in opts["injections"] if t and t[0] <= float(j["t"]) <= t[-1]]
    return r, o


SHOCK_R = 1.3             # noise in the dynamics: output error this much above the one-step error's variance ...
SHOCK_RHO = (-0.3, 0.6)   # ... with a one-step error that is neither differenced measurement error nor a smooth misfit


def dynamics_noise(nk: dict) -> bool:
    """Whether some stock moves by shocks (counting noise, an unmeasured switch) and not only along a
    smooth path seen through measurement error (noise_kind)."""
    return any(r > SHOCK_R and SHOCK_RHO[0] < p < SHOCK_RHO[1] for r, p in zip(nk.get("R") or [], nk.get("rho") or []))


def choose(base: dict, own: dict, stocks: list[dict], run: dict, opts: dict, shocks: bool = False) -> dict:
    """Which model predicts better: both refitted on the first TRAIN of the run (the main line run
    again; odefit's chosen terms refitted), then compared by output error over the rest, each
    20-step segment from its fitted start (compare.py). With noise in the dynamics: the main line's
    judge on the whole run (runs from the measured levels). Without a long enough held-out part: the
    same comparison on the whole run; where a model has stocks of its own: the main line's judge."""
    ids = [s["id"] for s in stocks]
    w = 1.0 / np.maximum(np.asarray(own["odefit"]["noise_sd"]), 1e-9)
    n = len(run["t"])
    k = int(TRAIN * n)
    spec, theta, d, seg, inputs = own["_fit"]
    if shocks:            # one-step errors are the right yardstick there: the main line's judge
        eb, eo = judge(base.get("flows") or [], stocks, run, opts), judge(own["flows"], stocks, run, opts)
        return {"how": "judge (noise in the dynamics)", "main line": eb, "output error": eo, "pick": "output error" if eo <= eb else "main line"}
    if n - k >= 2 * C.SEG and k >= 24:
        run_tr, opts_tr = _slice(run, opts, 0, k)
        run_te, opts_te = _slice(run, opts, k, n)
        try:
            b_tr = mainline(stocks, run_tr, {kk: v for kk, v in opts_tr.items() if kk not in OWN_OPTS}).get("flows") or []
        except Exception:                                      # noqa: BLE001
            b_tr = []
        r = F.fit(spec, cut(d, 0, k), seg, w, theta0=theta, max_nfev=100)
        _, Hs = spec.unpack(r["theta"])
        units = {s["id"]: s.get("unit") or "" for s in stocks}
        o_tr = to_flows(r["W"], ids, inputs, spec.products, units, d.Y[:k].mean(axis=0), hinges=hinge_flows(spec, Hs, ids, inputs))
        eb, eo = C.output_error(b_tr, ids, run_te, opts_te, w), C.output_error(o_tr, ids, run_te, opts_te, w)
        how = "held out"
    else:
        eb, eo = C.output_error(base.get("flows") or [], ids, run, opts, w), C.output_error(own["flows"], ids, run, opts, w)
        how = "output error"
    if not (np.isfinite(eb) or np.isfinite(eo)) or np.isnan(eb) or np.isnan(eo):
        eb, eo, how = judge(base.get("flows") or [], stocks, run, opts), judge(own["flows"], stocks, run, opts), "judge"
    return {"how": how, "main line": eb, "output error": eo, "pick": "output error" if eo <= eb else "main line"}


def output_error(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    began = time.perf_counter()
    budget = float(opts.get("budget", 150))
    deadline = began + budget
    d, ids, inputs = prepare(stocks, run, opts)
    if d.n < 12 or not ids:
        return {"flows": [], "note": "too short"}
    seg = int(opts.get("seg", SEG))
    spec = F.Spec(d.S, d.m)
    w = 1.0 / np.maximum(d.Y.std(axis=0), 1e-9)
    r = F.fit(spec, d, seg, w)
    # weights: each stock's own output error, so a noisier stock counts less
    sd = np.sqrt(r["rss"] / d.n) / w
    w = 1.0 / np.maximum(sd, 1e-6 * np.maximum(d.Y.std(axis=0), 1e-9))
    r = F.fit(spec, d, seg, w, theta0=r["theta"])
    global FLOOR
    FLOOR = d.n * (resolution(d.Y) * w) ** 2 / 12.0
    trace: list = []
    if opts.get("prune", True):
        spec, r = prune(spec, d, w, seg, r, began + 0.4 * budget, trace)
    r = F.fit(spec, d, seg, w, theta0=r["theta"], max_nfev=400)
    lin_held = held_out(spec, r["theta"], d, w, seg, r["starts"])
    best = (bic(r["rss"], d.n, nparams(spec)), spec, r, "linear", lin_held)
    tried = [{"name": "linear", "bic": round(best[0], 2), "held_out": lin_held}]

    def offer(name, sp, res):
        # kept when BIC says the data earn it and it predicts the held-out part clearly better
        nonlocal best
        if E.runs_away(sp, res["theta"], d):
            tried.append({"name": name, "runs_away": True})
            return
        b = bic(res["rss"], d.n, nparams(sp))
        h = held_out(sp, res["theta"], d, w, seg, res.get("starts")) if b < best[0] - EARN else float("nan")
        tried.append({"name": name, "bic": round(b, 2), "held_out": h})
        if b < best[0] - EARN and (not np.isfinite(lin_held) or (np.isfinite(h) and h <= BETTER * lin_held)):
            best = (b, sp, res, name, h)

    families = ["products"] + (["squares", "cross products"] if d.S > 1 else [])
    for fam in families if opts.get("products", True) else []:
        if time.perf_counter() > deadline:
            break
        sp, W2 = E.with_products(spec, r["W"], fam)
        if sp.P == spec.P:
            continue
        rp = F.fit(sp, d, seg, w, theta0=W2[sp.mask], max_nfev=200, starts0=r["starts"])
        prods = set(range(d.S + d.m + 1, sp.P))
        sp, rp = prune(sp, d, w, seg, rp, began + 0.7 * budget, trace, only=prods)
        if sp.mask[:, d.S + d.m + 1:].any():
            sp, rp = prune(sp, d, w, seg, rp, began + 0.75 * budget, trace)
            offer(fam, sp, rp)
    if opts.get("hinges", False) and time.perf_counter() < deadline:
        for i in range(d.S):
            for sp, th in E.with_hinge(spec, d, r["W"], i):
                if time.perf_counter() > deadline:
                    break
                rh = F.fit(sp, d, seg, w, theta0=th, max_nfev=200, starts0=r["starts"])
                sp2, rh2 = prune(sp, d, w, seg, rh, began + 0.95 * budget, trace)
                offer(f"hinge on {ids[i]}", sp2, rh2)
    _, spec, r, chosen, _ = best
    units = {s["id"]: s.get("unit") or "" for s in stocks}
    _, Hs = spec.unpack(r["theta"])
    flows = to_flows(r["W"], ids, inputs, spec.products, units, d.Y.mean(axis=0), hinges=hinge_flows(spec, Hs, ids, inputs))
    return {"flows": flows, "chosen": chosen, "tried": tried, "_fit": (spec, r["theta"], d, seg, inputs),
            "odefit": {"W": r["W"].tolist(), "mask": spec.mask.tolist(), "hinges": Hs.tolist(), "trace": trace,
                       "rss": r["rss"].tolist(), "noise_sd": sd.tolist(), "seconds": time.perf_counter() - began}}
