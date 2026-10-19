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


def bic(rss: np.ndarray, n: int, k: int) -> float:
    return float(n * np.sum(np.log(np.maximum(rss, 1e-300) / n)) + k * math.log(n))


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
    base = mainline(stocks, run, {k: v for k, v in opts.items() if k not in ("budget", "seg", "prune", "products", "hinges")})
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
    # both judged by output error with each segment's start fitted (compare.py); the main line's own
    # judge where its model has stocks of its own
    ids = [s["id"] for s in stocks]
    w = 1.0 / np.maximum(np.asarray(own["odefit"]["noise_sd"]), 1e-9)
    eb = C.output_error(base.get("flows") or [], ids, run, opts, w)
    eo = C.output_error(own["flows"], ids, run, opts, w)
    how = "output error"
    if not np.isfinite(eb):
        eb, eo, how = judge(base.get("flows") or [], stocks, run, opts), judge(own["flows"], stocks, run, opts), "judge"
    own["judged"] = {"how": how, "main line": eb, "output error": eo}
    if eo <= eb:
        return {**own, "chosen_by": f"output error model follows the data better ({how})"}
    return {**base, "judged": own["judged"], "chosen_by": f"the main line follows the data better ({how})"}


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
    return {"flows": flows, "chosen": chosen, "tried": tried,
            "odefit": {"W": r["W"].tolist(), "mask": spec.mask.tolist(), "hinges": Hs.tolist(), "trace": trace,
                       "rss": r["rss"].tolist(), "noise_sd": sd.tolist(), "seconds": time.perf_counter() - began}}
