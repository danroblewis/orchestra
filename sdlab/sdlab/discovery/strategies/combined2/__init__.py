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
8. The declared boundary (boundary.py, a copy of matrix's; docs/research/declared-boundary.md): where the
   case declares one, outside flows are offered only on its declared sides by the searches this
   composite carries (lna's atoms, shared by six specialists, and kalman's; structures' and
   archetypes' terms), every candidate and every stage's model is kept inside it before it is
   judged (the guard), and the answer passes the guard and the moves once more at the end. With none
   declared, every outside flow is a boundary claim priced 2 log T (-2 log L scale) by the judge and
   by structures' and archetypes' criteria.

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

import numpy as np

from sdlab.discovery.identify import identify as _main_line

from . import blocks
from . import boundary
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
from .boundary import claim_price, inside_candidates   # (boundary, this composite's copy: docs/research/declared-boundary.md)

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
    return inside_candidates(out, stocks, run, opts)   # (boundary, this composite's copy: docs/research/declared-boundary.md): each model inside a declared boundary


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
        claim = claim_price(r["flows"], data.ids, run, math.log(max(2, data.T)))   # (boundary, this composite's copy: docs/research/declared-boundary.md)
        if claim:                                        # outside flows with no boundary declared: boundary claims
            s = {**s, "bic": s["bic"] + claim, "claims": claim}
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
    # (2026-10-22, k8s-312 round 2, docs/research/fixes/312-combined2-r2.md) a unit's block of rows that another
    # candidate explains to the levels' rounding, where the pick does not, is taken from it (blocks.py)
    r = blocks.compose(r, [{"name": c["name"], **c["result"]} for c in cands if c is not best and c.get("result")], stocks, run, opts)
    r["combined2"] = {"chosen": best["name"], "candidates": _summary(cands, cfg),
                      **({"blocks_taken": r.pop("blocks_taken")} if r.get("blocks_taken") else {})}
    return r


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    env = json.loads(os.environ.get("SDLAB_COMBINED2") or "{}")
    own = {k: opts.pop(k) for k in list(opts) if k in DEFAULTS or k == "specialists"}
    cfg = {**DEFAULTS, **own, **env}
    use = set(cfg["stages"] or [])
    began = time.perf_counter()
    trail: list = []
    kal, filtered = None, None
    if "kalman" in use:
        t0 = time.perf_counter()
        try:
            kal = stages.Kalman(stocks, run, opts)
            got = kal.before()
        except Exception as e:                           # noqa: BLE001
            trail.append({"stage": "kalman", "error": f"{type(e).__name__}: {e}"[:300]})
            kal, got = None, None
        trail.append({"stage": "kalman", "seconds": round(time.perf_counter() - t0, 3), "answered": got is not None})
        if got is not None and (got.get("kalman") or {}).get("reading") != "meas":
            return {**got, "combined2": {"chosen": "kalman", "stages": trail}}
        # the filter's model for a measurement error is weighed against the pick below (_closer)
        filtered = got
    if filtered is not None and stages.short(stocks, run, opts):
        return {**filtered, "combined2": {"chosen": "kalman", "stages": trail}}
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
        if took:                                         # (boundary) a stage's model, too, inside a declared boundary
            got = boundary.apply(got, stocks, run, opts, final=False)
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
    if filtered is not None and not _closer(filtered, r, stocks, run, opts):
        r, chosen = filtered, "kalman"
    r["combined2"] = {**info, "chosen": chosen, "stages": trail, "seconds": round(time.perf_counter() - began, 3)}
    return r


CLOSER = 1.25         # the pick replaces the filter's model only when the filter's multi-step error is this
                      # many times the pick's (on the ladder, models that are both sound differ by up to ~1.15)


def _closer(filtered: dict, picked: dict, stocks: list[dict], run: dict, opts: dict) -> bool:
    """Whether the pick, its numbers refitted for a measurement error (eiv.py), runs closer to the data
    over 5, 20 and 100 steps than the Kalman filter's model, whose atoms read no measured input (the
    judge's multi-step error, which a measurement error does not bias). A filter's model with a stock
    nobody measures is kept: the judge runs on the measured levels only."""
    from .eiv import _known, judge, refit

    ids = [s["id"] for s in stocks]
    if not _known(filtered.get("flows") or [], set(ids) | set(opts.get("inputs") or {})):
        return False
    mine = judge(filtered.get("flows") or [], ids, run, opts)
    return judge(refit(picked.get("flows") or [], stocks, run, opts)[0], ids, run, opts) * CLOSER < mine


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


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py)."""
    from .eiv import apply

    from . import boundary as B

    # the declared boundary (boundary.py, docs/research/declared-boundary.md): the guard and the moves where one
    # is declared, each outside flow priced as a boundary claim where none is (every path above, kalman's too)
    return B.apply(apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts), stocks, run, opts)


# A capacity limit offered to the fit (capmin.py, docs/research/k8s-306-s1.md, 2026-10-21): identify above
# runs with the regime-clipped series MIN(X, theta x Y) as one more measured input where the data show a
# limit, and every term that reads it is written back as MIN(a x X, a theta x Y).
from . import capmin as _capmin  # noqa: E402


def idle_dropped(result: dict, run: dict, opts: dict | None) -> dict:
    """(2026-10-22, k8s-312) The answer without its flows between measured stocks (or outside) whose amount is 0 on
    every step of the record (hinge.amount; a flow it cannot evaluate is kept)."""
    from . import hinge

    flows = (result or {}).get("flows") or []
    levels, cols, n = hinge.columns(run, opts)
    if n < 10:
        return result
    idle = []
    for f in flows:
        if any(x and x not in levels for x in (f.get("from"), f.get("to"))):
            continue
        a = hinge.amount(f, cols, n)
        if a is not None and not np.any(a > 0):
            idle.append(f)
    if not idle:
        return result
    out = dict(result)
    out["flows"] = [f for f in flows if not any(f is g for g in idle)]
    out["idle_dropped"] = [f"{f.get('from') or 'outside'} -> {f.get('to') or 'outside'}" for f in idle]
    return out


def one_unit_moves(result: dict, stocks: list[dict]) -> dict:
    """The answer without its moves between two measured stocks of different declared units (a move carries one
    thing, the user's rule); the dropped ones are listed under "cross_unit_dropped"."""
    unit = {s["id"]: s.get("unit") for s in stocks if s.get("unit")}
    flows = (result or {}).get("flows") or []
    bad = [f for f in flows if f.get("from") in unit and f.get("to") in unit and unit[f["from"]] != unit[f["to"]]]
    if not bad:
        return result
    out = dict(result)
    out["flows"] = [f for f in flows if not any(f is b for b in bad)]
    out["cross_unit_dropped"] = [f"{f['from']} -> {f['to']}" for f in bad]
    return out

_identify_linear = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    """(2026-10-21, k8s-306 round 3, docs/research/k8s-306-r3-oefit.md) Between the fit and the MIN
    written back, where the levels carry measurement error, the numbers are refitted and the structure
    revised on the output error (oefit.py: the model run through the whole record against the measured
    levels)."""
    from . import counted
    from . import hiddenrow
    from . import hinge
    from . import lagrow
    from . import minrefit
    from . import oefit
    from . import rowrepair
    from . import switch

    o, cap = _capmin.offer(stocks, run, opts)
    # (2026-10-22, k8s-311) each offered limit read only by the flow it limits (capmin.place)
    r = _capmin.place(_identify_linear(stocks, run, o, *args, **kw), cap)
    # (2026-10-22, k8s-312, docs/research/fixes/312-combined2.md) a move carries one thing: a move between stocks of
    # different units is dropped, and the passes below refit the rows it touched (312 none-long: lna's nodes -> ready)
    r = one_unit_moves(r, stocks)
    # (2026-10-21, k8s-308, docs/research/fixes/308-combined2.md) a discrete actuator's outside flows written
    # as switches on the levels (switch.py) before the output-error refit, which otherwise bends the
    # stocks the actuator drives to make up for its smeared linear rate
    # (2026-10-21, k8s-309, docs/research/fixes/309-combined2.md) and each stock's outside sides refitted as
    # floored linear rates (hinge.py: max(0, c + w . Z), a gap that closes) where its row says so
    plain = lambda name: not _capmin.level_series(name)   # noqa: E731
    r = hinge.apply(switch.apply(r, stocks, run, o, readable=plain), stocks, run, o, readable=plain)
    r = oefit.refit(r, stocks, run, o, _capmin.plain_cap(cap))
    r = hinge.apply(switch.apply(_capmin.restore(r, cap), stocks, run, opts), stocks, run, opts)
    # (2026-10-21, k8s-310, docs/research/fixes/310-combined2.md) a counter that counts another flow: that
    # flow read off the counter's increase (counted.py: k x A x table(X), placed as a move by the rows it
    # repairs), and the floored sides refitted once more with it held
    # (2026-10-22, k8s-310 round 2) a block of one unit whose rows the pick leaves unexplained gets the moves
    # it lacks, fitted together by non-negative least squares (rowrepair.py)
    r = hinge.apply(rowrepair.apply(counted.apply(r, stocks, run, opts), stocks, run, opts), stocks, run, opts)
    # (2026-10-22, k8s-311, docs/research/fixes/311-combined2.md) each capacity limit's numbers refitted on its
    # rows now that the block's other flows are placed (minrefit.py: capmin offered it on rows still carrying them)
    r = minrefit.apply(r, stocks, run, opts)
    # (2026-10-22, k8s-310 round 2) a stock's inflow that reads a hidden integrator (a leak freed by the
    # same event a counted flow measures) written as a hidden stock, which the scorer now credits (hiddenrow.py)
    r = hiddenrow.apply(r, stocks, run, opts)
    # (2026-10-22, k8s-312, docs/research/fixes/312-combined2.md) a stock's outside inflow that arrives through a
    # hidden first-order stage (a node ordered joins after a provisioning delay) written as that stage (lagrow.py),
    # and a flow that carries nothing on the record (a limit whose room is never open) is no flow
    return idle_dropped(lagrow.apply(r, stocks, run, opts), run, opts)

