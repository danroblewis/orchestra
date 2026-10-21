"""realistic_flows: realistic_hats with coflow_hats' co-flow stages, for the mechanisms where most
realistic skill is lost (docs/research/realistic-flows.md; triage in docs/research/realistic-triage.md).

A copy of strategy realistic_hats at commit 06b0062 (every module, transit/ included), with
coflow_hats' coflows.py, cycles.py, joint.py, price.py, search.py and translate.py copied at 9d891b0
(coflow_hats is effect_hats at 89adae4 plus its co-flow changes, so these replace realistic_hats'
effect_hats copies) and its co-flow stage (_inflow_coflows) run inside the anytime cap. Changes of
its own are listed in docs/research/realistic-flows.md and marked "(realistic_flows)" in the code.

realistic_hats' description follows. What it adds to effect_hats:

- Anytime. After the base (the matrix method's model), the search runs under a cap of `share` of
  what the caller's timer leaves; the best answer so far (the base, its re-cut inflows, then each
  accepted effect) is kept, and when the cap fires that answer is returned instead of the whole run
  timing out (effect_hats timed out on 9 of the 62 realistic runs, which then had no model at all).
- Hidden transit stocks (`transit`, default on): on the answer, hidden_transit's pair search
  (transit/: A's loss into an unmeasured H that drains into B, fitted by a Kalman likelihood, kept
  when it beats the plain alternative by BIC and the model with it behaves better than the model
  without it with B's arrivals held at their mean), in the time left. Pairs a flow with an effect or
  a co-flow touches are left alone. The triage found a missed hidden stage in 19 of 33 realistic
  cases (distilled: 015, 156, 161).

effect_hats' own description follows.

Effects as tent columns: a flow's rate multiplied by a piecewise-linear curve of a stock's level,
found and fitted by least squares (docs/research/effect-hats.md).

1. The matrix method's model is the base.
2. Screen (screen.py): every pair (base, C) as a group of tent columns base x h_j(C) (basis.py) on
   what the rows leave unexplained; a pair that clearly explains one or two rows is a candidate.
3. Search (search.py): for each candidate and each way its flow can run (between the rows it shows
   in, or out of its base stock), the curve's weights are fitted jointly in those rows (the shared
   group with the flow's signs; knot count by BIC), and the placements compared on the same rows.
   The curve becomes a virtual stock base x f(C) offered to the matrix method in those rows; the
   result is read back into flows with table effects, a drain on the same curve as a move becoming
   its co-flow (translate.py), and every number, the curves' included, refitted jointly across all
   rows (joint.py).
4. The best few are finished: outside inflows pooled into a few values and re-cut where they change
   (pieces.py; per-stretch pieces read a drain up to 20% fast under counting noise), flows the joint
   BIC does not need dropped, and judged.
5. A candidate replaces the base only if its curve explains both halves of the data, it prices better
   (one-step BIC, pooled pieces counted once) than the base with its inflows re-cut the same way, and
   behaves within `margin` of it; among those, the lowest price wins (a flow whose rate is not its
   source's level pays `prior` x log T). With `rounds` > 1 the screen runs again with the accepted
   effects' columns taken out. Without an accepted effect, the base with its inflows re-cut is
   returned when it prices better and behaves within `seg_margin` (seg_base).

opts (also SDLAB_REALISTIC_FLOWS_OPTS, JSON), defaults in DEFAULTS: share, transit, margin, select ("bic" or "judge"),
prior, knots (knot counts tried), most (candidates per round), per_candidate (placements), finish
(models finished per round), halves, weighted (rows weighted by their noise), prune, pool (re-cut
inflows), guard (steps next to an inflow change left out of the fit), level_price (extra price of
an inflow value, in log T), seg_base, seg_margin, rounds.

(realistic_flows) The base is the main line with each candidate's pieces earned (earned.py,
earned_rows.py, earned_joint.py: strategy matrix's copy of earned_pieces' refit, taken unchanged from
matrix at 49e4ca7), where it was identify.identify: on 303 counts-short the plain main line kept a
5-piece drain of 30 per step on the final counter (inflight's drain read 8% fast), the cause A that
k8s-302.md fixed in 18 other strategies (docs/research/k8s-303-realistic-flows.md). The own-drains
run stays on the plain main line (identify.identify): the earned refit re-decides each row and its
conservation, which undoes "own drains" (distilled 153, 154 none-short fell to fail). The existing
choice between the base and the own-drains run (own_gain, by the judge) is unchanged.

Measured inputs (opts "inputs", inputs.py) are columns in every fit (the matrix's, the screen's, each
curve's, the joint refit's) and every model is priced and judged stepped with them.
"""

from __future__ import annotations

import json
import math
import os
import time

import numpy as np

from ...addition import addition_test
from ...identify import VARIANTS
from ...identify import identify as plain_identify
from .earned import main_line as matrix_identify   # (realistic_flows) the main line with pieces earned (earned.py)
from ...matrix import injected
from ...simulate import behaviour_error
from . import boundary, search, transit
from .deadline import Overrun, deadline, outer_left
from .inputs import rows as input_rows
from .coflows import cross_coflow_candidates, inflow_coflow_candidates, starved_candidates
from .cycles import cycle_candidates
from .joint import refit
from .moves import drains_into_moves, third_stock_moves
from .price import price, prune
from .pieces import resegment
from .screen import scan

DEFAULTS = {"margin": 1.1, "select": "bic", "prior": 2.0, "knots": [2, 3, 4, 6, 8], "most": 3, "halves": True,
            "weighted": True, "per_candidate": 2, "prune": True, "pool": True, "finish": 4, "seg_base": True,
            "seg_margin": 3.0, "guard": 2, "level_price": 2.0, "rounds": 1, "harm": None, "no_self_links": True, "pair": True, "coflows": True, "share": 0.85, "transit": True,
            "inflow_coflows": True, "starved": True, "cycles": True, "extra_most": 4, "cycle_gain": 0.9, "coflow_gain": 2.0, "extras_max_steps": 3000,
            "drain_coflows": True, "own_drains": True, "own_tol": 1e-6, "own_gain": 0.95, "readings": 3, "drain_tie": 2.0, "reading_margin": 1.002}


def judge(flows: list[dict], stocks: list[dict], run: dict, horizons=(5, 20, 100), injections: list[dict] | None = None,
          inputs: dict | None = None) -> float:
    """The main line's judge (identify.judge), with the measured inputs the flows read."""
    hs = [h for h in horizons if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    ids = [s["id"] for s in stocks]
    return sum(behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, injections=injections, inputs=inputs) for h in hs) / len(hs)


def _arrays(stocks, run, opts):
    ids = [s["id"] for s in stocks]
    lv = np.nan_to_num(np.array([np.asarray(run["levels"][i], dtype=float) for i in ids]))
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    if opts.get("injections"):
        inj = injected(opts["injections"], ids, run["t"])[:, 1:]
        prev, dy = prev + inj, dy - inj
    return ids, prev, dy


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """effect_hats' search, anytime: the best answer so far is kept, and when the time runs short
    (`share` of what the caller's timer leaves after the base) the search stops and that answer is
    returned instead of the whole run timing out."""
    opts = {**json.loads(os.environ.get("SDLAB_REALISTIC_FLOWS_OPTS") or "{}"), **(opts or {})}
    keep = opts.pop("candidates", False)
    o = {**DEFAULTS, **{k: opts.pop(k) for k in list(opts) if k in DEFAULTS}}
    t0 = time.perf_counter()
    base = matrix_identify(stocks, run, {**opts, "candidates": keep})
    if o["own_drains"] and not opts.get("variants"):
        # (realistic_flows) the matrix's variants again, each with its rows' own numbers kept: no
        # conservation within `slack` (a link from a stock of the same unit is not taken out of its
        # drain unless the row's BIC agrees) and no floor on a number (0.001 x a level of 20,000 is 20 a
        # step); the judge picks among all (distilled 153, 154: the drain left after a move, or a link,
        # was dropped and the stock's outside inflow took its place). Only when the time left allows it.
        took, left = time.perf_counter() - t0, outer_left()
        if left is None or 1.5 * took < 0.25 * left:
            try:
                with deadline(None if left is None else max(1.0, 0.25 * left)):
                    own = plain_identify(stocks, run, {**opts, "candidates": keep, "variants": [
                        {**v, "slack": 0.0, "tol": o["own_tol"], "name": f"{v['name']}, own drains"} for v in VARIANTS]})
                err = lambda r: min((x["error"] for x in r.get("tried") or []), default=float("inf"))  # noqa: E731
                tried = list(base.get("tried") or []) + list(own.get("tried") or [])
                if os.environ.get("SDLAB_RF_TRACE"):
                    print(f"  own drains: judge {err(own):.6g} ({own.get('chosen')}) vs {err(base):.6g} ({base.get('chosen')})")
                # it must behave clearly better (`own_gain`): on near ties (sd-hospital short 2%, sd-emergency
                # long 0.3%) the effect search built on it found effects that behave far worse off the data
                if err(own) < o["own_gain"] * err(base):
                    base = own
                base["tried"] = tried
            except Overrun:
                pass
    if len(run["t"]) < 60:
        return base
    state = {"answer": base}
    left = outer_left()
    cap = None if left is None else max(1.0, o["share"] * left - 2.0)
    began = time.perf_counter()
    try:
        with deadline(cap):
            answer = _search(stocks, run, opts, o, keep, base, state)
    except Overrun:
        a = state["answer"]
        return {**a, "chosen": f"{a.get('chosen')} (search stopped: out of time)"}
    if not o["transit"]:
        return answer
    # hidden transit stocks between measured pairs (transit/, hidden_transit's method), on the answer;
    # (realistic_flows) when the co-flow stage changed the answer, also on the answer before it (a
    # pair a co-flow touches is not tried, and a co-flow can stand in for a hidden stage's exit: 161),
    # and the one that behaves better on the data is kept
    tries = [answer] + ([state["pre_coflow"]] if state.get("pre_coflow") is not None else [])
    found = []
    for a in tries:
        rest = None if cap is None else cap - (time.perf_counter() - began)
        if rest is not None and rest < 5:
            break
        try:
            with deadline(rest):
                found.append(transit.add(a, stocks, run, opts))
        except Overrun:
            break
        except Exception as e:                               # noqa: BLE001
            found.append({**a, "transit_error": f"{type(e).__name__}: {e}"[:300]})
    if len(found) < 2:
        return found[0] if found else answer
    errs = [transit.judge(r["flows"], stocks, run, r.get("inferred_levels"), opts.get("injections"), opts.get("inputs")) for r in found]
    return found[int(np.argmin(errs))]


def _search(stocks: list[dict], run: dict, opts: dict, o: dict, keep, base: dict, state: dict) -> dict:
    base_e = min((x["error"] for x in base.get("tried") or []), default=float("inf"))
    # the declared boundary (boundary.py, docs/research/declared-boundary.md): the base kept inside it
    # (the earned main line already is; the guard catches what else reached it), and the search below
    # offers outside flows only on declared sides
    bnd = boundary.Boundary(run)
    if bnd.declared and base.get("flows") and not boundary.inside(base["flows"], stocks, run, opts):
        log: list = []
        base = {**base, "flows": boundary.keep_inside(base["flows"], stocks, run, opts, log), "boundary_guard": log}
        base_e = judge(base["flows"], stocks, run, injections=opts.get("injections"), inputs=opts.get("inputs") or None)
    ids, prev, dy = _arrays(stocks, run, opts)
    # measured inputs: their rows (columns of the screen and the curves' fits) and the judge's series
    in_names, in_rows = input_rows(opts.get("inputs"), ids, prev.shape[1])
    xin = in_rows if in_names else None
    inputs = opts.get("inputs") or None
    if inputs:
        # the matrix's judge steps its candidates without the inputs: its chosen model judged again
        base_e = judge(base["flows"], stocks, run, injections=opts.get("injections"), inputs=inputs)
    fit_opts = {**opts, "weighted": o["weighted"], "guard": o["guard"], "level_price": o["level_price"], "no_self_links": o["no_self_links"],
                "pair": o["pair"], "coflows": o["coflows"], "drain_coflows": o["drain_coflows"]}
    # the base as the candidates will be: its outside inflows pooled and re-cut (judged that way too,
    # since the judge feeds a model its own pieces, and fewer pieces always look worse)
    seg = resegment(base["flows"], ids, run, fit_opts) if o["pool"] else base["flows"]
    base_b = price(seg, ids, run, inputs)
    fair_e = judge(seg, stocks, run, injections=opts.get("injections"), inputs=inputs) if o["pool"] else base_e
    base.update(bic=base_b, judged={"base": base_e, "recut": fair_e}, effects_tried=[])
    state["answer"] = _seg_base(base, seg, o, ids, run, base_e, fair_e, stocks, inputs)
    log_t = math.log(max(2, len(run["t"]) - 1))
    accepted, best, chosen, cur_b, cur_e = [], None, None, base_b, fair_e
    tried, shapes, skip = [], set(), set()
    for _ in range(o["rounds"]):
        extra = [search.column(c, run)[0][:-1] for c in accepted] + (list(xin) if xin is not None else [])
        cands = scan(stocks, prev, dy, o, extra=extra, skip=skip)
        base["effects_tried"] += [f"{c['base'] or 1} x f({c['stock']}) in {[r for r, _ in c['rows']]} {c['score']:.0f}" for c in cands]
        raw = []
        for cand in cands[: o["most"]]:
            for c in search.placement_fits(cand, ids, prev, dy, o, xin, bnd):
                raw += [{**t, "fit": c} for t in search.trials(accepted + [c], stocks, run, prev, ids, opts, fit_opts, shapes)]
        # the most promising few are finished: inflows pooled and re-cut, flows the data does not
        # need dropped, then judged
        raw.sort(key=lambda t: t["bic"])
        done = []
        for t in raw[: o["finish"]]:
            flows = boundary.keep_inside(t["flows"], stocks, run, opts)      # the declared boundary (boundary.py)
            flows = resegment(flows, ids, run, fit_opts) if o["pool"] else flows
            if o["prune"]:
                flows = prune(flows, ids, run, fit_opts)
            if sum(1 for f in flows if f.get("hat")) < len(accepted) + 1:
                continue
            done.append({**t, "flows": flows, "error": judge(flows, stocks, run, injections=opts.get("injections"), inputs=inputs),
                         "bic": price(flows, ids, run, inputs)})
        tried += done
        def rank(t):
            # SD's usual form: a flow's rate is its source's level (or a constant) times the effect
            f = t["fit"]
            return t["bic"] + (0.0 if f["base"] in (f["frm"], None) else o["prior"] * log_t)
        # the best-priced model is the round's pick, and is then accepted or not: falling back to a
        # worse-priced one that happens to pass the judge picks wrong structures (a link read as a move)
        ok = [t for t in done if t["fit"]["halves_ok"] and t["bic"] < cur_b]
        if o["select"] == "judge":
            ok = [t for t in ok if t["error"] < o["margin"] * cur_e]
            best = min(ok, key=lambda t: t["error"]) if ok else None
        else:
            best = min(ok, key=rank) if ok else None
            if best is not None and not best["error"] < o["margin"] * cur_e:
                best = None
        # (opts["harm"]) and no worse than the base when each is fed a coarse inflow re-measured under
        # its own dynamics (addition.py, "refit")
        if best is not None and o["harm"] is not None and _fair(base["flows"], best["flows"], stocks, run) < -o["harm"]:
            best = None
        if best is None:
            best = chosen
            break
        chosen = best
        state["answer"] = {**best["r"], "flows": _clean(best["flows"]), "chosen": best["name"], "tried": base.get("tried"),
                           "effects_tried": base["effects_tried"], "bic": best["bic"], "base_bic": base_b, "judged": base["judged"]}
        accepted.append(best["fit"])
        skip.add((best["fit"]["base"], best["fit"]["stock"]))
        cur_b, cur_e = best["bic"], best["error"]
    base["tried"] = list(base.get("tried") or []) + [{"name": t["name"], "error": t["error"], "bic": t["bic"]} for t in tried]
    if keep:
        base.setdefault("candidates", []).extend({"name": t["name"], "error": t["error"], "flows": _clean(t["flows"])} for t in tried)
    if best is None:
        out = _seg_base(base, seg, o, ids, run, base_e, fair_e, stocks, inputs)
        cur_b, cur_e = price(out["flows"], ids, run, inputs), (fair_e if out["flows"] is not base["flows"] else base_e)
    else:
        out = {**best["r"], "flows": best["flows"], "chosen": best["name"], "tried": base["tried"],
               "effects_tried": base["effects_tried"], "bic": best["bic"], "base_bic": base_b, "judged": base["judged"]}
        if keep:
            out["candidates"] = base.get("candidates") or []
    state["answer"] = {**out, "flows": _clean(out["flows"])}
    # (realistic_flows) other readings of the flows (a move driven by a third stock), before the
    # co-flow stage reads the same drains as co-flows
    if o["readings"]:
        out, cur_b, cur_e = _readings(out, cur_b, cur_e, o, ids, run, stocks, fit_opts, inputs, opts.get("injections"), state)
    pre = state["answer"]
    # (coflow_hats) the co-flow stages, only on runs of at most `extras_max_steps` steps; each accepted
    # co-flow becomes the answer so far
    if o["inflow_coflows"] and len(run["t"]) <= o["extras_max_steps"]:
        out = _inflow_coflows(out, cur_b, cur_e, o, ids, run, stocks, fit_opts, inputs, opts.get("injections"),
                              starved=(prev, opts, base["flows"]) if o["starved"] else None, state=state)
        if out["flows"] is not pre["flows"] and len(out["flows"]) and out.get("chosen") != pre.get("chosen"):
            state["pre_coflow"] = pre
    return {**out, "flows": _clean(out["flows"])}


def _inflow_coflows(out: dict, cur_b: float, cur_e: float, o: dict, ids, run, stocks, fit_opts, inputs, injections,
                    starved: tuple | None = None, state: dict | None = None) -> dict:
    """The model with co-flows (coflows.py: an outside inflow's on another row's inflow, or a drain
    following another stock read as a co-flow on that stock's flow), taken one at a time while one
    prices better and behaves within `margin` of the model without it. With `starved` (prev, the
    matrix's opts, other models whose structure to try), the first round also offers co-flows whose used stock runs dry (starved_candidates),
    already fitted."""
    tried = []
    for rnd in range(2):
        done = [("co-flow whose used stock runs dry", c) for c in starved_candidates(stocks, run, starved[0], starved[1], fit_opts, o["pool"],
                                                                                      models=[out["flows"]] + list(starved[2:]))] \
            if starved is not None and rnd == 0 else []
        cands = [("co-flow on an outside inflow", c) for c in inflow_coflow_candidates(out["flows"], ids, run)]
        cands += [("drain following a stock read as a co-flow", c)
                  for c in cross_coflow_candidates(out["flows"], ids, *_prev_tt(stocks, run, fit_opts))]
        if o["cycles"]:
            pv, tt = _prev_tt(stocks, run, fit_opts)
            cands += [("a link whose strength follows a cycle", c)
                      for c in cycle_candidates(out["flows"], ids, pv, _arrays(stocks, run, fit_opts)[2], tt)]
        # (the declared boundary, boundary.py) a candidate with an outside flow the case does not declare
        # is not offered
        cands = [(name, c) for name, c in cands if boundary.inside(c, stocks, run, fit_opts)]
        done = [(name, c) for name, c in done if boundary.inside(c, stocks, run, fit_opts)]
        # the candidates refitted (numbers only) and priced; only the best few are re-cut and judged
        pre = []
        for name, cand in cands:
            fl = refit(cand, ids, run, fit_opts)[0]
            pre.append((price(fl, ids, run, inputs), name, cand))
        pre.sort(key=lambda x: x[0])
        cands = [(name, cand) for _, name, cand in pre[: o["extra_most"]]]
        pick = None
        for name, cand in done + cands:
            fl = cand if any(cand is c for _, c in done) else resegment(cand, ids, run, fit_opts) if o["pool"] else refit(cand, ids, run, fit_opts)[0]
            if not all(float(u.get("per") or 0) > 0 for f in fl for u in f.get("uses") or []):
                continue
            b = price(fl, ids, run, inputs)
            e = judge(fl, stocks, run, injections=injections, inputs=inputs)
            tried.append({"name": name, "error": e, "bic": b})
            # a cyclic link that replaces inflow pieces following the cycle step by step is held to the
            # re-cut base's looser margin (seg_margin: the judge feeds each model its own pieces); one that
            # replaces anything else must behave clearly better (cycle_gain), since a profile of phase
            # values fits noise-free data as exactly as what it replaces
            margin = o["margin"]
            if name.startswith("a link whose strength"):
                cyc = next(f["cycle"] for f in fl if f.get("cycle"))
                margin = o["seg_margin"] if cyc.get("follows") else o["cycle_gain"]
            # a drain read as a co-flow has as many numbers as the drain: it must price clearly better
            need = o["coflow_gain"] * math.log(max(2, len(run["t"]) - 1)) if name.startswith("drain following") else 0.0
            if b < cur_b - need and e < margin * cur_e and (pick is None or b < pick[0]):
                pick = (b, e, fl, name)
        if pick is None:
            break
        cur_b, cur_e = pick[0], pick[1]
        out = {**out, "flows": pick[2], "chosen": f"{out.get('chosen')}, {pick[3]}", "bic": cur_b}
        if state is not None:
            state["answer"] = {**out, "flows": _clean(out["flows"])}
    return {**out, "tried": list(out.get("tried") or []) + tried}


def _prev_tt(stocks, run, opts):
    """The levels at the start of each step (injections added) and the steps' end times."""
    return _arrays(stocks, run, opts)[1], np.asarray(run["t"], dtype=float)[1:]


def _readings(out: dict, cur_b: float, cur_e: float, o: dict, ids, run, stocks, fit_opts, inputs, injections, state: dict):
    """(realistic_flows) Other readings of the answer's flows (moves.py: a move driven by a third stock),
    on runs of any length, each refitted, its inflows re-cut, priced and judged; taken one at a time
    while one prices better and behaves no worse (`reading_margin`, 0.2%, for the judge's rounding) than the model without it (a
    reading that prices better but behaves worse cost sd-kanban 11 points). Returns the model and
    its price and judged error."""
    tried = []
    for _ in range(o["readings"]):
        pick = None
        cands = [("a move driven by a third stock", c, 0.0) for c in third_stock_moves(out["flows"], stocks)]
        # a drain moved onto a move has the same number of numbers and steps the same: it is kept unless
        # it prices clearly worse (`drain_tie`), as the model with one outside flow fewer
        cands += [("a constant drain read as part of a move", c, o["drain_tie"]) for c in drains_into_moves(out["flows"], stocks)]
        cands = [x for x in cands if boundary.inside(x[1], stocks, run, fit_opts)]   # (the declared boundary, boundary.py)
        for name, cand, tie in cands:
            fl = resegment(cand, ids, run, fit_opts) if o["pool"] else refit(cand, ids, run, fit_opts)[0]
            b = price(fl, ids, run, inputs)
            e = judge(fl, stocks, run, injections=injections, inputs=inputs)
            tried.append({"name": name, "error": e, "bic": b})
            if os.environ.get("SDLAB_RF_TRACE"):
                print(f"  reading {name}: bic {b - cur_b:+.1f}, error {e:.6g} vs {cur_e:.6g}")
            if b < cur_b + tie and e <= o["reading_margin"] * cur_e + 1e-9 and (pick is None or b - tie < pick[0] - pick[4]):
                pick = (b, e, fl, name, tie)
        if pick is None:
            break
        cur_b, cur_e = pick[0], pick[1]
        out = {**out, "flows": pick[2], "chosen": f"{out.get('chosen')}, {pick[3]}", "bic": cur_b}
        state["answer"] = {**out, "flows": _clean(out["flows"])}
    return {**out, "tried": list(out.get("tried") or []) + tried}, cur_b, cur_e


def _fair(base: list[dict], cand: list[dict], stocks: list[dict], run: dict) -> float:
    """The candidate's gain over the base (relative error over 5/20/100 steps), each fed a coarse
    outside inflow re-measured under its own dynamics."""
    return float(addition_test(base, cand, stocks, run, inflow="refit")["gain"])


def _seg_base(base: dict, seg: list[dict], o: dict, ids: list[str], run: dict, base_e: float, fair_e: float,
              stocks: list[dict] | None = None, inputs: dict | None = None) -> dict:
    """The base, or (opts["seg_base"]) the base with its inflows pooled and re-cut when that prices
    better, behaves within `seg_margin` of it, and is no worse with re-measured coarse inflows."""
    if not o["seg_base"] or seg is base["flows"]:
        return base
    if price(seg, ids, run, inputs) < price(base["flows"], ids, run, inputs) and fair_e < o["seg_margin"] * base_e \
            and (o["harm"] is None or _fair(base["flows"], seg, stocks, run) >= -o["harm"]):
        return {**base, "flows": _clean(seg), "chosen": f"{base.get('chosen')}, inflows re-cut"}
    return base


def _clean(flows: list[dict]) -> list[dict]:
    """Without the fit's own notes; neighbouring pieces of one pool joined."""
    out = []
    for f in flows:
        f = {k: v for k, v in f.items() if k not in ("hat", "cycle")}
        if f.get("byTime"):
            f["byTime"] = [{k: v for k, v in g.items() if k != "seg"} for g in f["byTime"]]
        if f.get("inflow"):
            segs = []
            for g in f["inflow"]:
                if segs and g.get("pool") is not None and segs[-1].get("pool") == g.get("pool") and segs[-1]["to"] + 1 >= g["from"]:
                    segs[-1] = {**segs[-1], "to": g["to"]}
                else:
                    segs.append(dict(g))
            f["inflow"] = [{k: v for k, v in g.items() if k != "pool"} for g in segs]
        out.append(f)
    return out


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (eiv.py), then kept inside the announced boundary (boundary.py,
    docs/research/declared-boundary.md): the guard where one is declared, then the moves and (none
    declared) the priced boundary claims in at most half the time left."""
    from .eiv import apply

    r = apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)
    if not isinstance(r, dict) or r.get("flows") is None:
        return r
    r = boundary.apply(r, stocks, run, opts, final=False)
    left = outer_left()
    try:
        with deadline(None if left is None else max(1.0, 0.5 * left)):
            return boundary.apply(r, stocks, run, opts)
    except Overrun:
        b = boundary.Boundary(run)
        ids = [s["id"] for s in stocks]
        return {**r, "boundary": {**b.summary(), "changed": list(r.get("boundary_guard") or []) + ["passes stopped: out of time"]},
                "boundary_claims": boundary.claims(r["flows"], ids, b, set((opts or {}).get("inputs") or {}))}


# A capacity limit offered to the fit (capmin.py, docs/research/k8s-306-s1.md, 2026-10-21): identify above
# runs with the regime-clipped series MIN(X, theta x Y) as one more measured input where the data show a
# limit, and every term that reads it is written back as MIN(a x X, a theta x Y).
from . import capmin as _capmin  # noqa: E402

_identify_linear = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    return _capmin.wrap(_identify_linear, stocks, run, opts, *args, **kw)
