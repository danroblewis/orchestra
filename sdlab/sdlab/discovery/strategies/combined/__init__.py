"""combined: the specialist strategies run side by side, and one judge picks among their models
(docs/research/combined.md).

1. Candidates. Each specialist is called as a black box through its own `identify()`, so its
   improvements flow in: lna (the best single strategy: flows chosen by the counting likelihood),
   gap_prior (lna with a drain read off another stock written as the goal gap it equals),
   lna_pulses (one-step bursts taken out before lna reads the moves),
   common_cause (independent and identical stocks, noise-free fits, inflow changes the data
   earns), censored (floors that bind, stocks that run empty), hidden_transit (an unmeasured stock
   between two measured ones), effect_hats (effects of a third stock's level; also re-cuts the
   outside inflows) and periodic_inflows (an inflow that repeats). The specialists that start from
   the matrix method's model share one computation of it (shared.py). A specialist that raises is
   skipped; once `budget` seconds have gone, the remaining ones are skipped too.
2. One judge (judge.py): the one-step likelihood of the measured changes under each candidate's
   equations, applied exactly as the simulator applies them (floors, caps, effects, co-flows,
   unmeasured stocks run open loop), with counting noise read through the linear noise
   approximation (each flow a Poisson draw) or, for data that are not counts, each stock's own
   variance floored at the data's rounding; plus a BIC price of 0.5 log T for every number the
   candidate wrote down (params.py: rate numbers, inflow values and change places, effect points,
   co-flows, unmeasured stocks). Before it is judged, every candidate's numbers are refitted on the
   same terms (refit.py: least squares of the one-step changes, its structure kept), and the
   refitted numbers are kept when they raise its likelihood. The lowest score wins; exact ties go to the model with fewer flows
   that read a stock other than the ones they join, then to fewer numbers, then to the earlier
   candidate in the list.

opts (also SDLAB_COMBINED, JSON): "specialists" (names, in order; default SPECIALISTS), "price"
(the BIC multiplier, default 1), "per_flow" (numbers a flow costs for being there, default 0: a
flow is priced by its numbers), "budget" (seconds, default 75), "refit" (refit every candidate's numbers, default on), "trace" (keep every candidate's
flows in the result).
"""

from __future__ import annotations

import json
import os
import time

from sdlab.discovery.strategies.censored import identify as censored
from sdlab.discovery.strategies.common_cause import identify as common_cause
from sdlab.discovery.strategies.effect_hats import identify as effect_hats
from sdlab.discovery.strategies.gap_prior import identify as gap_prior
from sdlab.discovery.strategies.hidden_transit import identify as hidden_transit
from sdlab.discovery.strategies.lna import identify as lna
from sdlab.discovery.strategies.lna_pulses import identify as lna_pulses
from sdlab.discovery.strategies.periodic_inflows import identify as periodic_inflows

from . import judge as J
from .refit import refit
from .shared import once

STRATEGIES = {"lna": lna, "gap_prior": gap_prior, "lna_pulses": lna_pulses, "common_cause": common_cause, "censored": censored,
              "hidden_transit": hidden_transit, "periodic_inflows": periodic_inflows, "effect_hats": effect_hats}
SPECIALISTS = ["lna", "gap_prior", "lna_pulses", "censored", "hidden_transit", "periodic_inflows", "effect_hats", "common_cause"]
DEFAULTS = {"price": 1.0, "per_flow": 0.0, "budget": 75.0, "trace": False, "refit": True}


def cross_reads(flows: list[dict]) -> int:
    """Flows whose rate reads a stock other than the ones it joins (a drain that follows another
    level, an inflow that follows another stock): the conventional SD reading of a tie is the one
    where each flow follows its own stocks."""
    n = 0
    for f in flows or []:
        r = f.get("rate") or {}
        reads = {r.get("stock")} | {x.get("stock") for x in r.get("terms") or []}
        reads.discard(None)
        if reads - {f.get("from"), f.get("to")}:
            n += 1
    return n


def candidates(stocks: list[dict], run: dict, opts: dict, names: list[str], budget: float) -> list[dict]:
    out = []
    began = time.perf_counter()
    with once() as cached:
        for name in names:
            if out and time.perf_counter() - began > budget:
                out.append({"name": name, "skipped": "budget"})
                continue
            t0 = time.perf_counter()
            try:
                r = (cached.get(name) or STRATEGIES[name])(stocks, run, dict(opts))
            except Exception as e:                       # noqa: BLE001
                out.append({"name": name, "error": f"{type(e).__name__}: {e}"[:300]})
                continue
            out.append({"name": name, "result": r, "seconds": round(time.perf_counter() - t0, 3)})
    return out


def choose(cands: list[dict], data: J.Data, price: float, per_flow: float, do_refit: bool = True) -> dict | None:
    best, best_key = None, None
    for i, c in enumerate(cands):
        r = c.get("result")
        if not r or r.get("flows") is None:
            continue
        starts = {h: v[0] for h, v in (r.get("inferred_levels") or {}).items() if v}
        try:
            s = J.score(r["flows"], data, price, per_flow, starts)
        except Exception as e:                           # noqa: BLE001
            c["judge_error"] = f"{type(e).__name__}: {e}"[:300]
            continue
        if do_refit:
            try:
                flows = refit(r["flows"], data, J.weights(r["flows"], data))
                s2 = J.score(flows, data, price, per_flow, starts) if flows else None
            except Exception as e:                       # noqa: BLE001
                c["refit_error"] = f"{type(e).__name__}: {e}"[:300]
                s2 = None
            if s2 is not None and s2["nll"] < s["nll"] - 1e-9:
                c["result"] = r = {**r, "flows": flows, "refitted": True}
                s = {**s2, "refitted": True}
        c["score"] = s
        key = (round(s["bic"], 6), cross_reads(r["flows"]), s["k"], i)
        if best_key is None or key < best_key:
            best, best_key = c, key
    return best


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    env = json.loads(os.environ.get("SDLAB_COMBINED") or "{}")
    own = {k: opts.pop(k) for k in list(opts) if k in DEFAULTS or k == "specialists"}
    cfg = {**DEFAULTS, **own, **env}
    names = list(cfg.get("specialists") or SPECIALISTS)
    cands = candidates(stocks, run, opts, names, float(cfg["budget"]))
    data = J.Data(stocks, run, opts.get("injections"))
    best = choose(cands, data, float(cfg["price"]), float(cfg["per_flow"]), bool(cfg["refit"]))
    if best is None:
        return {"flows": [], "combined": {"chosen": None, "candidates": _summary(cands, cfg)}}
    r = dict(best["result"])
    r["combined"] = {"chosen": best["name"], "candidates": _summary(cands, cfg)}
    return r


def _summary(cands: list[dict], cfg: dict) -> list[dict]:
    out = []
    for c in cands:
        s = {k: c[k] for k in ("name", "seconds", "error", "skipped", "judge_error") if k in c}
        if "score" in c:
            s.update({k: round(v, 3) if isinstance(v, float) else v for k, v in c["score"].items()})
        if cfg.get("trace") and c.get("result"):
            s["flows"] = c["result"].get("flows")
        out.append(s)
    return out
