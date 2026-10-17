"""Experiment gradient: the matrix method's model, its numbers fitted by gradient descent through a
differentiable simulator on multi-step error, and a generous structure pruned by sparsity.

Candidates, each judged by behaviour on the data as identify() judges (the best is kept):
  - matrix: identify()'s model as it is;
  - refined: the same structure, every number fitted on 5- and 20-step error from many moments
    (outside inflows fixed as the matrix found them);
  - generous: the refined model plus an effect table of every measured stock on every flow (group
    lasso on its distance from 1) and a co-flow of every measured stock on every flow (L1), small
    survivors dropped, the rest refitted without the price; "generous-nolinks": the same without
    the matrix's links (a pair of links is often an effect read linearly).

opts (besides identify()'s):
  modes        which candidates to build ("refined", "generous", "generous-nolinks")
  horizons     the curriculum (default 5, 20)
  inflows      in the generous fits: "fixed" (as the matrix found them) or "learn" (they move,
               under `piece_lambda` x their squared distance from where they were found and `tv`
               x the total variation between a flow's consecutive pieces, both relative to the
               refined model's error)
  flatten      with learn: every found outside inflow starts flat, at its mean, so its pieces come
               apart only where effects and co-flows cannot explain the data
  lambda       the sparsity price, as a share of the refined model's error (default 0.1)
  rate_l1      in the generous fits, an L1 price on the structure's own rate numbers too (x lambda)
  maxiter      L-BFGS iterations per horizon in the generous fit
  trace        True prints the fits

SDLAB_GRADIENT=<attempt> (environment) picks one of ATTEMPTS: how the bench runs each attempt;
the default is "refined", the better of the two measured (docs/DISCOVERY-EXPERIMENTS.md).
"""

from __future__ import annotations

import os
import time

import numpy as np

from ..diffsim import compile_flows, to_flows
from ..gradfit import Fit, data_of, default_masks
from ..identify import identify as identify_matrix
from ..structure import candidates, drop_small, prune_report
from ..identify import judge

CLEAN = {"inflows": "learn", "piece_lambda": 0.0, "tv": 0.02, "flatten": True, "rate_l1": 1.0, "lambda": 0.1, "maxiter": 500, "starts": 500}
ATTEMPTS = {
    "default": {"modes": ["refined"]},
    "refined": {"modes": ["refined"]},
    "clean": {"modes": ["refined", "generous-nolinks"], **CLEAN},
}

OWN = ("modes", "horizons", "inflows", "piece_lambda", "tv", "lambda", "rate_l1", "flatten", "maxiter", "starts", "trace")


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = {**ATTEMPTS[os.environ.get("SDLAB_GRADIENT") or "default"], **(opts or {})}
    log = print if opts.get("trace") is True else None
    began = time.time()
    r = identify_matrix(stocks, run, {k: v for k, v in opts.items() if k not in OWN})
    tried = [("matrix", r["flows"], min(x["error"] for x in r["tried"]))]
    if len(run["t"]) < 60 or not r["flows"]:
        return {**r, "chosen_gradient": "matrix"}
    ids = [s["id"] for s in stocks]
    data = data_of(run["levels"], ids)
    horizons = tuple(opts.get("horizons") or (5, 20))
    modes = opts.get("modes") or ("refined", "generous-nolinks")
    learn = opts.get("inflows") == "learn"
    lam = float(opts.get("lambda", 0.1))
    notes = {}

    spec = compile_flows(r["flows"], ids, run["t"])
    fit = Fit(spec, data)
    p = fit.run(None, horizons, log=log)
    refined = to_flows(spec, p)
    base_err = fit.error(p, horizons[-1])
    if "refined" in modes:
        tried.append(("refined", refined, judge(refined, stocks, run)))

    def inflows(spec, tv: bool = True) -> dict:
        """With learn, the found outside inflows move under their prices (in units of the stock's
        one-step change spread)."""
        if not learn or not len(spec.init["pieces"]):
            return {}
        masks = default_masks(spec)
        masks["pieces"] = np.ones(len(spec.init["pieces"]), bool)
        step_sd = np.diff(data.A, axis=1).std(axis=1)
        ends = np.where(spec.dst >= 0, spec.dst, spec.src)
        scale = np.maximum(1e-6, step_sd[np.maximum(ends[spec.piece_flow], 0)])
        return {"masks": masks, "piece_lambda": float(opts.get("piece_lambda", 1.0)) * base_err, "piece_scale": scale,
                "piece_tv": float(opts.get("tv", 0.0)) * base_err if tv else 0.0}

    for mode in [m for m in modes if m.startswith("generous")]:
        flows, extra_e, extra_u, groups, price, rate_price = candidates(
            refined, ids, data, spec_of=lambda fl: compile_flows(fl, ids, run["t"]), drop_links=mode == "generous-nolinks")
        spec2 = compile_flows(flows, ids, run["t"], extra_effects=extra_e, extra_uses=extra_u, cap_all_users=True)
        if learn and opts.get("flatten"):
            flatten(spec2)
        fit2 = Fit(spec2, data, starts=int(opts.get("starts", 1000)), effect_groups=groups(spec2), effect_lambda=lam * base_err, use_price=price(spec2) * lam * base_err,
                   rate_price={k: v * lam * base_err * float(opts.get("rate_l1", 0)) for k, v in rate_price(spec2).items()},
                   **inflows(spec2))
        p2 = fit2.run(None, horizons, maxiter=int(opts.get("maxiter", 150)), log=log)
        kept = drop_small(to_flows(spec2, p2, effect_min=0.05), spec2, p2, data)
        kept, notes[mode] = prune_report(kept, spec2, p2, data, ids)
        spec3 = compile_flows(kept, ids, run["t"])
        fit3 = Fit(spec3, data, starts=int(opts.get("starts", 1000)), **inflows(spec3, tv=False))   # the survivors refitted, pieces free of the variation price
        generous = to_flows(spec3, fit3.run(None, horizons[-1:], log=log))
        tried.append((mode, generous, judge(generous, stocks, run)))

    name, flows, _ = min(tried, key=lambda x: x[2])
    if log:
        log(f"  gradient: {[(n, round(e, 4)) for n, _, e in tried]} -> {name}")
    return {**r, "flows": flows, "chosen_gradient": name, "tried_gradient": [{"name": n, "error": e} for n, _, e in tried],
            "gradient_seconds": round(time.time() - began, 1), **({"pruned": notes} if notes else {})}


def flatten(spec) -> None:
    """Every found outside inflow starts flat, at its time-weighted mean."""
    pv = spec.init["pieces"]
    for f in set(spec.piece_flow.tolist()):
        w = np.bincount(spec.piece[f][spec.piece[f] >= 0], minlength=len(pv))
        m = spec.piece_flow == f
        pv[m] = (pv * w)[m].sum() / max(1, w[m].sum())
