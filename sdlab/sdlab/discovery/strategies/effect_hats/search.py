"""From a screened candidate to fitted models: the curve per placement, then the matrix method with
virtual stocks (one per effect: base x f(C), the effects already accepted and the new one), read back
into flows with table effects and refitted jointly."""

from __future__ import annotations

import math

import numpy as np

from ...identify import VARIANTS
from ...matrix import identify_one
from ...onestep import bic
from .basis import curve, knots
from .joint import refit
from .screen import fit_curve, placements
from .translate import translate


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


def halves(ids, prev, dy, c: dict) -> bool:
    """The curve, fitted on each half of the data alone, has the same shape (the part that varies)
    as on the whole, within 70% of that shape's size (a curve fitted to a passing stretch does not)."""
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

    def shape(v):
        return v - v.mean()
    full = shape(curve(x, kn, c["weights"]))
    size = max(1e-12, float(np.sqrt(np.mean(full ** 2))))
    return all(float(np.sqrt(np.mean((shape(curve(x, kn, w)) - full) ** 2))) < 0.7 * size for w in fits)


def placement_fits(cand: dict, ids, prev, dy, o: dict) -> list[dict]:
    """The candidate's best placements (lowest BIC first, at most o["per_candidate"]), each with its
    curve; a curve that is not mostly positive (a rate cannot be negative) is dropped."""
    also = tuple(dict.fromkeys([r for r, _ in cand["rows"]] + ([cand["base"]] if cand["base"] else [])))
    fits = []
    for frm, to in placements(cand):
        c = best_curve(ids, prev, dy, cand["base"], cand["stock"], frm, to, o["knots"], also=also)
        if c is None or c["positive"] < 0.9:
            continue
        fits.append({**c, "base": cand["base"], "stock": cand["stock"], "frm": frm, "to": to})
    fits.sort(key=lambda c: c["bic"])
    out = fits[: o["per_candidate"]]
    for c in out:
        c["halves_ok"] = halves(ids, prev, dy, c) if o["halves"] else True
    return out


def column(c: dict, run: dict, normalised: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """The effect's virtual level base x f(C) over the run, and its weights scaled to f = 1 at C's
    mean level."""
    lvl = np.nan_to_num(np.asarray(run["levels"][c["stock"]], dtype=float))
    ref = float(np.interp(float(np.mean(lvl[:-1])), c["knots"], c["weights"])) or 1.0
    wn = np.asarray(c["weights"]) / ref if normalised else np.asarray(c["weights"])
    bl = np.ones_like(lvl) if c["base"] is None else np.nan_to_num(np.asarray(run["levels"][c["base"]], dtype=float))
    return bl * curve(lvl, c["knots"], wn), wn


def trials(effects: list[dict], stocks, run, prev, ids, opts, fit_opts, shapes: set) -> list[dict]:
    """Every matrix variant with one virtual stock per effect, read back, refitted: [{name, bic,
    flows, r}] (a model seen already, by `shapes`, is skipped)."""
    group = {s["id"]: s.get("group") for s in stocks}
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    meta, levels, vstocks, rows = {}, dict(run["levels"]), list(stocks), {}
    for q, c in enumerate(effects):
        vid = f"~{q}"
        series, wn = column(c, run)
        meta[vid] = {"base": c["base"], "stock": c["stock"], "knots": c["knots"], "weights": wn}
        levels[vid] = list(series)
        vstocks.append({"id": vid, "unit": f"virtual {vid}", "final": True, "group": group.get(c["base"] or c["stock"])})
        rows[vid] = {r for r in (c["frm"], c["to"], c["base"]) if r}
    vrun = {**run, "levels": levels}
    out = []
    for v in VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        r = identify_one(vstocks, vrun, {**opts, **v, "only_rows": rows})
        flows = translate(r.get("flows") or [], meta, stocks, prev, ids)
        if not flows or not any(f.get("hat") for f in flows):
            continue
        flows, _ = refit(flows, ids, run, fit_opts)
        sig = signature(flows)
        if sig in shapes:
            continue
        shapes.add(sig)
        names = " and ".join(f"{c['base'] or 1} x f({c['stock']}) {c['frm'] or 'outside'}->{c['to'] or 'outside'} ({len(c['knots'])} knots)"
                             for c in effects)
        out.append({"name": f"effect {names}, {v['name']}", "bic": bic(flows, ids, run["t"], run["levels"]), "flows": flows, "r": r})
    return out


def signature(flows: list[dict]) -> str:
    import json

    def rnd(x):
        if isinstance(x, float):
            return float(f"{x:.4g}")
        if isinstance(x, dict):
            return {k: rnd(v) for k, v in x.items() if k not in ("rates", "driver", "curve")}
        if isinstance(x, list):
            return [rnd(v) for v in x]
        return x
    return json.dumps(sorted(json.dumps(rnd(f), sort_keys=True) for f in flows))
