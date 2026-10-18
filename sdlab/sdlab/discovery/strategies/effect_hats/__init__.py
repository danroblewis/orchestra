"""Effects as tent columns: a flow's rate multiplied by a piecewise-linear curve of a stock's level,
found and fitted by least squares (docs/research/effect-hats.md).

1. The matrix method's model is the base.
2. Screen (screen.py): every pair (base, C) as a group of tent columns base x h_j(C) (basis.py) on
   what the rows leave unexplained; a pair that clearly explains one or two rows is a candidate.
3. For each candidate and each way its flow can run between the rows it shows in, the curve's
   weights are fitted jointly in those rows (the shared group with the flow's signs), with the number
   of knots chosen by BIC. The curve becomes a virtual stock base x f(C) offered to the matrix method
   (restricted to those rows), the result is read back into flows with table effects (translate.py),
   and every number, the curve's included, is refitted jointly across all rows (joint.py).
4. The candidate the judge (behaviour on the data) likes best replaces the base only if it behaves
   better by a margin, prices better by BIC, and its curve explains both halves of the data.

opts (also SDLAB_EFFECT_HATS_OPTS, JSON): select ("bic": the lowest BIC among the acceptable; "judge":
the best behaved), margin (a candidate must behave within this ratio of the base, 1.1), prior (BIC
price, in log T, of an effect flow whose rate is not its source's level, 2), knots (curve knot counts
tried, [2, 3, 4, 6, 8]), most (candidates, 3), halves (True), weighted (joint refit weights, True).
"""

from __future__ import annotations

import json
import math
import os

import numpy as np

from ...identify import VARIANTS, judge
from ...identify import identify as matrix_identify
from ...matrix import identify_one, injected
from ...onestep import bic
from .basis import curve, knots
from .joint import price, prune, refit
from .pieces import resegment
from .screen import fit_curve, placements, scan
from .translate import translate

DEFAULTS = {"margin": 1.1, "select": "bic", "prior": 2.0, "knots": [2, 3, 4, 6, 8], "most": 3, "halves": True, "weighted": True, "per_candidate": 2, "prune": True, "pool": True, "finish": 4, "seg_base": True, "seg_margin": 3.0, "guard": 2, "level_price": 2.0}


def _arrays(stocks, run, opts):
    ids = [s["id"] for s in stocks]
    lv = np.nan_to_num(np.array([np.asarray(run["levels"][i], dtype=float) for i in ids]))
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    if opts.get("injections"):
        inj = injected(opts["injections"], ids, run["t"])[:, 1:]
        prev, dy = prev + inj, dy - inj
    return ids, prev, dy


def best_curve(ids, prev, dy, base, stock, frm, to, choices, also=()) -> dict | None:
    """The knot count (and weights) with the lowest BIC for this placement (on the rows of its ends
    and `also`, each row priced by its own noise)."""
    n = prev.shape[1]
    best = None
    for k in choices:
        kn = knots(prev[ids.index(stock)], k)
        fc = fit_curve(ids, prev, dy, base, stock, frm, to, kn, also=also)
        if fc is None:
            continue
        b = float(sum(n * math.log(max(r, 1e-12) / n) for r in fc["row_rss"])) + k * math.log(n)
        if best is None or b < best["bic"]:
            best = {**fc, "knots": kn, "bic": b}
    return best


def _halves(ids, prev, dy, c: dict) -> bool:
    """The curve, fitted on each half of the data alone, says the same thing on the other half's
    states as on its own (a curve fitted to a passing stretch does not)."""
    n = prev.shape[1]
    h = n // 2
    kn = np.asarray(c["knots"])
    fits = []
    for sl in (slice(0, h), slice(h, n)):
        fc = fit_curve(ids, prev[:, sl], dy[:, sl], c["base"], c["stock"], c["frm"], c["to"], kn)
        if fc is None:
            return False
        fits.append(fc["weights"])
    x = prev[ids.index(c["stock"])]
    full = curve(x, kn, c["weights"])
    a, b = curve(x, kn, fits[0]), curve(x, kn, fits[1])
    scale = max(1e-12, float(np.sqrt(np.mean(full ** 2))))
    # both halves must at least agree with the whole on the curve's shape (the part that varies)
    def shape(v):
        return v - v.mean()
    sv = max(1e-12, float(np.sqrt(np.mean(shape(full) ** 2))))
    agree = all(float(np.sqrt(np.mean((shape(v) - shape(full)) ** 2))) < 0.7 * sv for v in (a, b))
    return agree and scale > 0


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = {**json.loads(os.environ.get("SDLAB_EFFECT_HATS_OPTS") or "{}"), **(opts or {})}
    keep = opts.pop("candidates", False)
    o = {**DEFAULTS, **{k: opts.pop(k) for k in list(opts) if k in DEFAULTS}}
    ids = [s["id"] for s in stocks]
    base = matrix_identify(stocks, run, {**opts, "candidates": keep})
    base_e = min((x["error"] for x in base.get("tried") or []), default=float("inf"))
    if len(run["t"]) < 60:
        return base
    ids, prev, dy = _arrays(stocks, run, opts)
    cands = scan(stocks, prev, dy, o)
    base["effects_tried"] = [f"{c['base'] or 1} x f({c['stock']}) in {[r for r, _ in c['rows']]} {c['score']:.0f}" for c in cands]
    fit_opts = {**opts, "weighted": o["weighted"], "guard": o["guard"], "level_price": o["level_price"]}
    # the base as the candidates will be: its outside inflows pooled and re-cut (judged that way too,
    # since the judge feeds a model its own pieces, and fewer pieces always look worse)
    seg = resegment(base["flows"], ids, run, fit_opts) if o["pool"] else base["flows"]
    base_b = price(seg, ids, run)
    fair_e = judge(seg, stocks, run, injections=opts.get("injections")) if o["pool"] else base_e
    base["bic"] = base_b
    base["judged"] = {"base": base_e, "recut": fair_e}
    if not cands:
        return _seg_base(base, seg, o, ids, run, base_e, fair_e)
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    group = {s["id"]: s.get("group") for s in stocks}
    raw, trials = [], []
    seen, shapes = set(), set()
    for cand in cands[: o["most"]]:
        fits = []
        for frm, to in placements(cand):
            c = best_curve(ids, prev, dy, cand["base"], cand["stock"], frm, to, o["knots"], also=tuple(dict.fromkeys([r for r, _ in cand["rows"]] + ([cand["base"]] if cand["base"] else []))))
            if c is None or c["positive"] < 0.9:
                continue
            fits.append({**c, "base": cand["base"], "stock": cand["stock"], "frm": frm, "to": to})
        fits.sort(key=lambda c: c["bic"])
        for c in fits[: o["per_candidate"]]:
            key = (c["base"], c["stock"], c["frm"], c["to"])
            if key in seen:
                continue
            seen.add(key)
            x = prev[ids.index(c["stock"])]
            ref = float(np.interp(float(np.mean(x)), c["knots"], c["weights"])) or 1.0
            wn = np.asarray(c["weights"]) / ref
            meta = {"~0": {"base": c["base"], "stock": c["stock"], "knots": c["knots"], "weights": wn}}
            lvl = np.nan_to_num(np.asarray(run["levels"][c["stock"]], dtype=float))
            bl = np.ones_like(lvl) if c["base"] is None else np.nan_to_num(np.asarray(run["levels"][c["base"]], dtype=float))
            vrun = {**run, "levels": {**run["levels"], "~0": list(bl * curve(lvl, c["knots"], wn))}}
            vstocks = stocks + [{"id": "~0", "unit": "virtual ~0", "final": True, "group": group.get(c["base"] or c["stock"])}]
            rows = {"~0": {r for r in (c["frm"], c["to"], c["base"]) if r}}
            c["halves_ok"] = _halves(ids, prev, dy, c) if o["halves"] else True
            for v in VARIANTS:
                if v.get("split_eras") and not has_eras:
                    continue
                r = identify_one(vstocks, vrun, {**opts, **v, "only_rows": rows})
                flows = translate(r.get("flows") or [], meta, stocks, prev, ids)
                if not flows or not any(f.get("hat") for f in flows):
                    continue
                flows, _ = refit(flows, ids, run, fit_opts)
                sig = _signature(flows)
                if sig in shapes:
                    continue
                shapes.add(sig)
                name = f"effect {c['base'] or 1} x f({c['stock']}) {c['frm'] or 'outside'}->{c['to'] or 'outside'} ({len(c['knots'])} knots), {v['name']}"
                raw.append({"name": name, "bic": bic(flows, ids, run["t"], run["levels"]), "flows": flows, "fit": c, "r": r})
    # the most promising few are finished: inflows pooled and re-cut, flows the data does not need
    # dropped, then judged
    raw.sort(key=lambda t: t["bic"])
    for t in raw[: o["finish"]]:
        flows = t["flows"]
        if o["pool"]:
            flows = resegment(flows, ids, run, fit_opts)
        if o["prune"]:
            flows = prune(flows, ids, run, fit_opts)
        if not any(f.get("hat") for f in flows):
            continue
        e = judge(flows, stocks, run, injections=opts.get("injections"))
        trials.append({**t, "flows": flows, "error": e, "bic": price(flows, ids, run)})
    base["tried"] = list(base.get("tried") or []) + [{"name": t["name"], "error": t["error"], "bic": t["bic"]} for t in trials]
    if keep:
        base.setdefault("candidates", []).extend({"name": t["name"], "error": t["error"], "flows": _clean(t["flows"])} for t in trials)
    ok = [t for t in trials if t["fit"]["halves_ok"] and t["bic"] < base_b and t["error"] < o["margin"] * fair_e]
    if not ok:
        return _seg_base(base, seg, o, ids, run, base_e, fair_e)
    log_t = math.log(max(2, len(run["t"]) - 1))

    def rank(t):
        # SD's usual form: a flow's rate is its source's level (or a constant) times the effect
        f = t["fit"]
        return t["bic"] + (0.0 if f["base"] in (f["frm"], None) else o["prior"] * log_t)
    best = min(ok, key=lambda t: t["error"]) if o["select"] == "judge" else min(ok, key=rank)
    out = {**best["r"], "flows": _clean(best["flows"]), "chosen": best["name"], "tried": base["tried"],
           "effects_tried": base["effects_tried"], "bic": best["bic"], "base_bic": base_b,
           "judged": base["judged"]}
    if keep:
        out["candidates"] = base.get("candidates") or []
    return out


def _seg_base(base: dict, seg: list[dict], o: dict, ids: list[str], run: dict, base_e: float, fair_e: float) -> dict:
    """The base, or (opts["seg_base"]) the base with its inflows pooled and re-cut when that prices
    better and behaves within the margin."""
    if not o["seg_base"] or seg is base["flows"]:
        return base
    if price(seg, ids, run) < price(base["flows"], ids, run) and fair_e < o["seg_margin"] * base_e:
        return {**base, "flows": _clean(seg), "chosen": f"{base.get('chosen')}, inflows re-cut"}
    return base


def _signature(flows: list[dict]) -> str:
    def rnd(x):
        if isinstance(x, float):
            return float(f"{x:.4g}")
        if isinstance(x, dict):
            return {k: rnd(v) for k, v in x.items() if k not in ("rates", "driver", "curve")}
        if isinstance(x, list):
            return [rnd(v) for v in x]
        return x
    return json.dumps(sorted(json.dumps(rnd(f), sort_keys=True) for f in flows))


def _clean(flows: list[dict]) -> list[dict]:
    """Without the fit's own notes; neighbouring pieces of one pool joined."""
    out = []
    for f in flows:
        f = {k: v for k, v in f.items() if k != "hat"}
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
