"""combined2: combined's specialists and the new ones side by side, one judge that does not replay a
model's own inflow pieces, and the specialists built on combined run as stages on its result
(docs/research/combined2.md).

Every specialist is a copy (_vendored/, each with its source commit): no other strategy is imported
(sdlab/CLAUDE.md invariant 11).

1. kalman (stages.Kalman, from kalman_lna): on up to 4 stocks, uneven reports or announced
   injections, the Kalman filter's superset is fitted first; when the levels carry a measurement
   error (or gross errors, or the reports are uneven) the filter's model is the answer.
2. Fewer than 20 steps: archetypes' model (the matrix method and everything on it refuse them).
3. Candidates (as combined, candidates()): each specialist through its own identify(), sharing one
   main-line computation (shared.py), each under a cap, within a budget, with the main line's model
   as the fallback when none finishes (never an empty model while one is to be had). Specialists
   that cannot matter on these data are skipped (screens.py): common_cause unless two stocks move
   alike; odefit on counts, or where the main line's model is exact to the data's rounding without
   inflow pieces (screens.plain_exact).
4. The judge (choose()): every candidate's numbers refitted on equal terms (refit.py), the one-step
   likelihood (with a discrete likelihood for small counts, judge.py) plus a BIC price on every
   number written down. Candidates are set aside first by combined's runaway guard (in-data
   multi-step error over `guard` (4) x the best and over 0.1), and by the held-inflow guard: a
   candidate whose in-data error is over `tight` (2) x the best's AND whose held-inflow forecast
   error is over `held` (1.25) x the best's (forecast.py: rolling-origin forecasts over 5, 20 and
   100 steps with every found inflow piece held at its value when the forecast starts). The in-data
   error alone, tightened, sets aside sound models whose few pieces cannot replay the run (it costs
   test cells); the held error alone is dominated by inflows that really change; a model worse on
   both is the runaway kind. The lowest BIC among the rest wins; ties as combined.
5. structures (stages.structures): the search for products, multi-stock gaps and hidden chains;
   its model replaces the chosen one when the judge prefers it and it behaves as well. Skipped when
   the chosen model is exact without pieces (screens.plain_exact).
6. archetypes (stages.archetypes): on up to 3 stocks and 120 steps, its model replaces the chosen
   one when it forecasts the run's last quarter better.
7. kalman again: a reporting delay or a stock counted at a scale sends the data to the filter,
   unless the pick fits the levels to their noise (screens.fits).

opts (also SDLAB_COMBINED2, JSON): combined's ("specialists", "price", "per_flow", "budget", "cap",
"refit", "guard", "guard_floor", "trace"), plus "tight", "held" and "held_floor" (the held-inflow
guard; held 0 turns it off), "discrete" (the small-counts likelihood, default on), "screens" (default on),
"stages" (default ["kalman", "structures", "archetypes"]), "odefit_budget" (seconds, default 60).
"""

from __future__ import annotations

import copy
import json
import math
import os
import time

from sdlab.discovery.identify import identify as _main_line

from . import judge as J2
from . import screens
from . import stages
from ._vendored.censored import identify as censored
from ._vendored.coflow_hats import identify as coflow_hats
from ._vendored.combined import judge as J
from ._vendored.combined.deadline import Overrun, deadline, outer_left
from ._vendored.combined.refit import refit
from ._vendored.common_cause import identify as common_cause
from ._vendored.drifting_drain import identify as drifting_drain
from ._vendored.effect_hats import identify as effect_hats
from ._vendored.gap_prior import identify as gap_prior
from ._vendored.hidden_transit import identify as hidden_transit
from ._vendored.lna import identify as lna
from ._vendored.lna_pulses import identify as lna_pulses
from ._vendored.lna_stack import identify as lna_stack
from ._vendored.odefit import identify as odefit
from ._vendored.own_tables import identify as own_tables
from ._vendored.periodic_inflows import identify as periodic_inflows
from ._vendored.realistic_hats import identify as realistic_hats
from .forecast import held
from .shared import once

STRATEGIES = {"lna": lna, "gap_prior": gap_prior, "lna_pulses": lna_pulses, "lna_stack": lna_stack, "common_cause": common_cause,
              "censored": censored, "hidden_transit": hidden_transit, "periodic_inflows": periodic_inflows, "effect_hats": effect_hats,
              "realistic_hats": realistic_hats, "coflow_hats": coflow_hats, "own_tables": own_tables, "drifting_drain": drifting_drain,
              "odefit": odefit}
# realistic_hats is effect_hats answering in time, with hidden transit stocks: it replaces it
SPECIALISTS = ["censored", "realistic_hats", "lna", "hidden_transit", "periodic_inflows", "gap_prior", "lna_pulses", "lna_stack",
               "coflow_hats", "own_tables", "drifting_drain", "odefit", "common_cause"]
# exact ties go to the earlier name here (whatever order they ran in)
PREFERENCE = ["lna", "gap_prior", "lna_pulses", "lna_stack", "censored", "realistic_hats", "effect_hats", "coflow_hats", "hidden_transit",
              "periodic_inflows", "own_tables", "drifting_drain", "odefit", "common_cause"]
DEFAULTS = {"price": 1.0, "per_flow": 0.0, "budget": 240.0, "cap": 90.0, "trace": False, "refit": True, "guard": 4.0, "guard_floor": 0.1,
            "tight": 2.0, "held": 1.25, "held_floor": 0.1, "discrete": True, "screens": True, "stages": ["kalman", "structures", "archetypes"],
            "odefit_budget": 60.0}
SHARE = 0.6           # the candidates' budget: at most this share of what the caller's timer leaves (the judge and stages need the rest)


def cross_reads(flows: list[dict]) -> int:
    """Flows whose rate reads a stock other than the ones it joins (combined's tie-break)."""
    n = 0
    for f in flows or []:
        r = f.get("rate") or {}
        reads = {r.get("stock")} | {x.get("stock") for x in r.get("terms") or []}
        reads.discard(None)
        if reads - {f.get("from"), f.get("to")}:
            n += 1
    return n


def _own_opts(name: str, opts: dict, cfg: dict) -> dict:
    o = dict(opts)
    if name == "odefit":
        left = outer_left()
        o["budget"] = float(cfg["odefit_budget"]) if left is None else min(float(cfg["odefit_budget"]), 0.5 * left)
    return o


def candidates(stocks: list[dict], run: dict, opts: dict, names: list[str], cfg: dict, cached: dict) -> list[dict]:
    """Each specialist's result, in order, each under a cap and all within the budget (combined's
    candidates()); specialists the screens rule out are skipped."""
    out = []
    began = time.perf_counter()
    left = outer_left()
    budget = float(cfg["budget"]) if left is None else min(float(cfg["budget"]), SHARE * left)
    skip = screens.skip(stocks, run, opts) if cfg["screens"] else {}
    data = J.Data(stocks, run, opts.get("injections"), opts.get("inputs"))
    eras = bool(opts.get("eras") and len(opts["eras"]) > 1)
    for name in names:
        if name == "odefit" and cfg["screens"] and name not in skip:
            main = [r for r in (cached.get("main_results") or {}).values() if isinstance(r, dict) and r.get("flows")]
            if main and screens.plain_exact(main[0]["flows"], data, eras):
                skip[name] = "the main line's model is exact, without pieces"
        if name in skip:
            out.append({"name": name, "skipped": skip[name]})
            continue
        spent = time.perf_counter() - began
        if out and spent > budget and any(c.get("result") for c in out):
            out.append({"name": name, "skipped": "budget"})
            continue
        t0 = time.perf_counter()
        try:
            with deadline(max(1.0, min(float(cfg["cap"]), budget - spent))):
                r = (cached.get(name) or STRATEGIES[name])(stocks, run, _own_opts(name, opts, cfg))
        except Overrun as e:
            out.append({"name": name, "error": f"capped: {e}", "seconds": round(time.perf_counter() - t0, 3)})
            continue
        except Exception as e:                           # noqa: BLE001
            out.append({"name": name, "error": f"{type(e).__name__}: {e}"[:300]})
            continue
        out.append({"name": name, "result": r, "seconds": round(time.perf_counter() - t0, 3)})
    if not any(c.get("result") for c in out):
        out.append(fallback(stocks, run, opts, cached))
    return out


def fallback(stocks: list[dict], run: dict, opts: dict, cached: dict) -> dict:
    """The main line's model when no specialist finished (combined's, beab53e)."""
    t0 = time.perf_counter()
    done = [r for r in (cached.get("main_results") or {}).values() if isinstance(r, dict) and r.get("flows")]
    if done:
        return {"name": "main_line", "result": copy.deepcopy(done[0]), "seconds": 0.0, "fallback": True}
    left = outer_left()
    try:
        with deadline(None if left is None else max(1.0, 0.8 * left)):
            r = (cached.get("main_line") or _main_line)(stocks, run, dict(opts))
    except Overrun as e:
        return {"name": "main_line", "error": f"capped: {e}", "seconds": round(time.perf_counter() - t0, 3), "fallback": True}
    except Exception as e:                               # noqa: BLE001
        return {"name": "main_line", "error": f"{type(e).__name__}: {e}"[:300], "fallback": True}
    return {"name": "main_line", "result": r, "seconds": round(time.perf_counter() - t0, 3), "fallback": True}


def _score(flows, data, cfg, starts):
    if cfg["discrete"]:
        return J2.score(flows, data, float(cfg["price"]), float(cfg["per_flow"]), starts)
    return J.score(flows, data, float(cfg["price"]), float(cfg["per_flow"]), starts)


def choose(cands: list[dict], data: J.Data, run: dict, cfg: dict, eras: bool = False) -> dict | None:
    """The candidate with the lowest score among those both guards keep (see the docstring)."""
    scored = []
    for i, c in enumerate(cands):
        r = c.get("result")
        if not r or r.get("flows") is None:
            continue
        starts = {h: v[0] for h, v in (r.get("inferred_levels") or {}).items() if v}
        try:
            s = _score(r["flows"], data, cfg, starts)
        except Exception as e:                           # noqa: BLE001
            c["judge_error"] = f"{type(e).__name__}: {e}"[:300]
            continue
        if cfg["refit"]:
            try:
                flows = refit(r["flows"], data, J.weights(r["flows"], data))
                s2 = _score(flows, data, cfg, starts) if flows else None
            except Exception as e:                       # noqa: BLE001
                c["refit_error"] = f"{type(e).__name__}: {e}"[:300]
                s2 = None
            if s2 is not None and s2["nll"] < s["nll"] - 1e-9:
                c["result"] = r = {**r, "flows": flows, "refitted": True}
                s = {**s2, "refitted": True}
        c["score"] = s
        scored.append((i, c, starts))
    if not scored:
        return None
    if cfg["guard"] or cfg["held"]:
        seen: dict = {}
        for _, c, starts in scored:
            key = json.dumps(c["result"]["flows"], sort_keys=True, default=repr)
            if key not in seen:
                seen[key] = _behaviours(c["result"]["flows"], data, run, starts, cfg, eras)
            c["score"]["behaviour"], c["score"]["held"] = seen[key]
        good = min(c["score"]["behaviour"] for _, c, _ in scored)
        best_held = min(c["score"]["held"] for _, c, _ in scored)
        floor = float(cfg["guard_floor"])

        def aside(sc: dict) -> bool:
            if cfg["guard"] and sc["behaviour"] > max(float(cfg["guard"]) * good, floor):
                return True                              # combined's runaway guard
            return bool(cfg["held"]) and sc["behaviour"] > max(float(cfg["tight"]) * good, floor) \
                and sc["held"] > max(float(cfg["held"]) * best_held, float(cfg["held_floor"]))
        for _, c, _ in scored:
            c["score"]["set_aside"] = aside(c["score"])
        scored = [x for x in scored if not x[1]["score"]["set_aside"]] or scored

    def rank(x):
        name = x[1]["name"]
        return (round(x[1]["score"]["bic"], 6), cross_reads(x[1]["result"]["flows"]), x[1]["score"]["k"],
                PREFERENCE.index(name) if name in PREFERENCE else len(PREFERENCE), x[0])
    return min(scored, key=rank)[1]


def _behaviours(flows, data, run, starts, cfg, eras) -> tuple[float, float]:
    """(in-data multi-step error, held-inflow forecast error); inf where a model cannot be run."""
    own = hld = math.inf
    try:
        fl, inferred = J.hidden_estimate(flows, data, starts)
    except Exception:                                    # noqa: BLE001
        return own, hld
    if cfg["guard"] or cfg["held"]:
        try:
            own = J.behaviour(flows, data, run, starts)
        except Exception:                                # noqa: BLE001
            pass
    if cfg["held"]:
        try:
            hld = held(fl, data, run, inferred, eras)
        except Exception:                                # noqa: BLE001
            pass
    return (own if math.isfinite(own) else 1e9), (hld if math.isfinite(hld) else 1e9)


def base(stocks: list[dict], run: dict, opts: dict, cfg: dict, cached: dict) -> dict:
    """Steps 3-4: the candidates and the judge's pick (never an empty model while one is to be had)."""
    names = list(cfg.get("specialists") or SPECIALISTS)
    cands = candidates(stocks, run, opts, names, cfg, cached)
    data = J.Data(stocks, run, opts.get("injections"), opts.get("inputs"))
    eras = bool(opts.get("eras") and len(opts["eras"]) > 1)
    best = choose(cands, data, run, cfg, eras)
    if best is None:
        best = next((c for c in cands if (c.get("result") or {}).get("flows")), None)
    if best is None:
        return {"flows": [], "combined2": {"chosen": None, "candidates": _summary(cands, cfg)}}
    r = dict(best["result"])
    r["combined2"] = {"chosen": best["name"], "candidates": _summary(cands, cfg)}
    return r


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    env = json.loads(os.environ.get("SDLAB_COMBINED2") or "{}")
    own = {k: opts.pop(k) for k in list(opts) if k in DEFAULTS or k == "specialists"}
    cfg = {**DEFAULTS, **own, **env}
    use = set(cfg["stages"] or [])
    began = time.perf_counter()
    trail: list = []
    kal = None
    if "kalman" in use:
        t0 = time.perf_counter()
        try:
            kal = stages.Kalman(stocks, run, opts)
            got = kal.before()
        except Exception as e:                           # noqa: BLE001
            trail.append({"stage": "kalman", "error": f"{type(e).__name__}: {e}"[:300]})
            kal, got = None, None
        trail.append({"stage": "kalman", "seconds": round(time.perf_counter() - t0, 3), "answered": got is not None})
        if got is not None:
            return {**got, "combined2": {"chosen": "kalman", "stages": trail}}
    if "archetypes" in use and stages.short(stocks, run, opts):
        r = stages.archetypes_alone(stocks, run, opts)
        return {**r, "combined2": {"chosen": "archetypes", "stages": trail + [{"stage": "archetypes", "alone": "short"}]}}
    with once() as cached:
        r = base(stocks, run, opts, cfg, cached)
    chosen = (r.get("combined2") or {}).get("chosen")
    info = r.pop("combined2", {})
    for name, fn in (("structures", stages.structures), ("archetypes", stages.archetypes)):
        if name not in use or not r.get("flows"):
            continue
        if name == "structures" and cfg["screens"]:
            data = J.Data(stocks, run, opts.get("injections"), opts.get("inputs"))
            if screens.plain_exact(r["flows"], data, bool(opts.get("eras") and len(opts["eras"]) > 1)):
                trail.append({"stage": name, "skipped": "the chosen model is exact, without pieces"})
                continue
        t0 = time.perf_counter()
        try:
            got = fn(r, stocks, run, opts)
        except Exception as e:                           # noqa: BLE001
            trail.append({"stage": name, "error": f"{type(e).__name__}: {e}"[:300]})
            continue
        took = (got.get("method") == name)
        trail.append({"stage": name, "seconds": round(time.perf_counter() - t0, 3), "replaced": took})
        if took:
            chosen = name
        r = got
    if kal is not None and cfg["screens"]:
        data = J.Data(stocks, run, opts.get("injections"), opts.get("inputs"))
        if screens.fits(r.get("flows") or [], data, bool(opts.get("eras") and len(opts["eras"]) > 1)):
            trail.append({"stage": "kalman after", "skipped": "the pick fits the levels to their noise"})
            kal = None
    if kal is not None:
        try:
            got = kal.after(r)
            if got.get("method") == "kalman_lna":
                chosen = "kalman"
            r = got
        except Exception as e:                           # noqa: BLE001
            trail.append({"stage": "kalman after", "error": f"{type(e).__name__}: {e}"[:300]})
    r["combined2"] = {**info, "chosen": chosen, "stages": trail, "seconds": round(time.perf_counter() - began, 3)}
    return r


def _summary(cands: list[dict], cfg: dict) -> list[dict]:
    out = []
    for c in cands:
        s = {k: c[k] for k in ("name", "seconds", "error", "skipped", "judge_error", "fallback") if k in c}
        if "score" in c:
            s.update({k: round(v, 3) if isinstance(v, float) else v for k, v in c["score"].items()})
        if cfg.get("trace") and c.get("result"):
            s["flows"] = c["result"].get("flows")
        out.append(s)
    return out
