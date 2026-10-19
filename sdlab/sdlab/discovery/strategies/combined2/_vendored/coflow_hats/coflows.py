# Vendored for combined2 from sdlab/discovery/strategies/coflow_hats/coflows.py at commit 9d891b0 (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""Co-flows found after the model is chosen: a flow that uses up another stock D as it moves.

1. On an outside inflow: arrivals into V that each use up `per` of D.
A flow that uses up D as it moves shows in D's row as a drain that follows the flow. When the flow is
an outside inflow into V (walk-ins each taking a dose), the matrix reads it as D's own outside inflow
stepping down whenever V's steps up: D's pieces carry every change of V's inflow as well as its own.
Here, for every pair of changing outside inflows (into V, into D), the jumps of D's inflow at the
times V's inflow jumps are compared: if D's falls as V's rises (the median ratio, the start of the
`per`, is positive), V's inflow gets `uses` of D at that per, D's inflow is rebuilt without V's
part (its values plus per x V's), and the model refitted (the per re-read from D's row by the joint
fit), D's inflow pooled and re-cut.
2. A drain of D that follows another stock V (the matrix's "D drains faster when V is high"): read
as a co-flow of D on each flow into or out of V in turn.
The caller keeps a candidate only if it prices better and behaves no worse.
"""

from __future__ import annotations

import numpy as np

from sdlab.discovery.identify import VARIANTS
from sdlab.discovery.matrix import identify_one
from sdlab.discovery.simulate import Model
from sdlab.discovery.starvation import fill_gaps, first_mask, remeasure_inflows, stocks_running_dry
from .joint import refit
from .pieces import _now, resegment
from .price import price
from .search import signature


def _jumps(x: np.ndarray, tol: float) -> list[int]:
    """Steps where the piecewise series x changes by more than tol."""
    d = np.abs(np.diff(x))
    return [int(i) + 1 for i in np.flatnonzero(d > tol)]


def per_from_jumps(f: np.ndarray, g: np.ndarray, w: int = 3) -> float | None:
    """How much g falls for each unit f rises at f's jumps (over a window of w steps either side, so
    pieces cut a step apart still match): the median ratio, None unless positive. Only a start: the
    joint refit re-reads the per, and the price decides whether the co-flow stays."""
    scale = float(np.max(np.abs(f))) or 1.0
    js = _jumps(f, 0.05 * scale)
    # jumps within w of each other are one jump
    merged: list[int] = []
    for j in js:
        if merged and j - merged[-1] <= 2 * w:
            continue
        merged.append(j)
    ratios = []
    n = len(f)
    for j in merged:
        a, b = max(0, j - w), min(n - 1, j + w - 1)
        df, dg = f[b] - f[a], g[b] - g[a]
        if abs(df) < 0.05 * scale:
            continue
        ratios.append(-dg / df)
    if not ratios:
        return None
    p = float(np.median(ratios))
    return p if p > 0 else None


def inflow_coflow_candidates(flows: list[dict], ids: list[str], run: dict) -> list[list[dict]]:
    """Models with one outside inflow given a co-flow on another row's outside inflow (see the module
    docstring), unfitted: [flows]."""
    tt = np.asarray(run["t"], dtype=float)[1:]
    ins = [i for i, f in enumerate(flows) if f.get("from") is None and f.get("to") in ids and f.get("inflow") and len(f["inflow"]) >= 2
           and not f.get("uses")]
    out = []
    for i in ins:
        for j in ins:
            F, G = flows[i], flows[j]
            if i == j or F["to"] == G["to"]:
                continue
            f, g = _now(F, tt), _now(G, tt)
            p = per_from_jumps(f, g)
            if p is None:
                continue
            h = g + p * f
            # D's own inflow: cut where either inflow was cut, each piece the mean of g + per x f
            cuts = sorted({0, len(tt)} | {int(np.searchsorted(tt, s["from"])) for s in F["inflow"] + G["inflow"]})
            segs = []
            for a, b in zip(cuts, cuts[1:]):
                if b <= a:
                    continue
                segs.append({"from": int(tt[a]), "to": int(tt[b - 1]), "value": float(np.mean(h[a:b]))})
            new_g = {**G, "inflow": segs}
            new_f = {**F, "uses": [{"stock": G["to"], "per": p}]}
            out.append([new_f if q == i else new_g if q == j else x for q, x in enumerate(flows)])
    return out


def _cross(f: dict, ids: list[str]) -> str | None:
    """V when f is a drain of its source D at k x V (V another stock, k > 0), else None."""
    if f.get("to") is not None or f.get("from") not in ids or f.get("effects") or f.get("inflow") or f.get("byTime") or f.get("uses"):
        return None
    r = f.get("rate") or {}
    if r.get("form") == "proportional":
        v, k = r.get("stock"), r.get("k")
    elif r.get("form") == "linear" and not r.get("c") and len(r.get("terms") or []) == 1:
        v, k = r["terms"][0].get("stock"), r["terms"][0].get("k")
    else:
        return None
    return v if v in ids and v != f["from"] and float(k or 0) > 0 else None


def _rate(f: dict, prev: np.ndarray, idx: dict, tt: np.ndarray) -> np.ndarray | None:
    """The flow's rate at each step as its equation says (no cap, no floor); None for a flow with
    effects, eras or a rate this does not read."""
    if f.get("effects") or f.get("byTime"):
        return None
    if f.get("inflow"):
        return _now(f, tt)
    r = f.get("rate") or {}
    if r.get("form") == "constant":
        return np.full(prev.shape[1], float(r.get("value") or 0))
    if r.get("form") == "proportional" and r.get("stock") in idx:
        return float(r.get("k") or 0) * prev[idx[r["stock"]]]
    if r.get("form") == "linear" and all(x.get("stock") in idx for x in r.get("terms") or []):
        return float(r.get("c") or 0) + sum(float(x.get("k") or 0) * prev[idx[x["stock"]]] for x in r.get("terms") or [])
    return None


def cross_coflow_candidates(flows: list[dict], ids: list[str], prev: np.ndarray, tt: np.ndarray, used: str | None = None) -> list[list[dict]]:
    """Models where a drain of D that follows another stock V ("D drains faster when V is high") is
    read as a co-flow of D on a flow into or out of V (what V's flows move is what uses D up), its per
    started at the ratio of the two rates' means (as their equations say); unfitted: [flows]."""
    idx = {s: i for i, s in enumerate(ids)}
    out = []
    for i0, x0 in enumerate(flows):
        v = _cross(x0, ids)
        if v is None or (used is not None and x0["from"] != used):
            continue
        d = x0["from"]
        fl = list(flows)
        # V's own drain (k x V, started at the cross term's k): the flow most likely to use D up, offered
        # when the model has none (its row may have been read as something else)
        if not any(f.get("from") == v and _base_of(f) == v for f in fl):
            k0 = float(np.mean(_rate(x0, prev, idx, tt)) / max(1e-12, float(np.mean(prev[idx[v]]))))
            fl.append({"from": v, "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": v, "k": k0}})
        rates = [_rate(f, prev, idx, tt) for f in fl]
        i, x = i0, x0
        for j, f in enumerate(fl):
            if j == i or f.get("uses") or v not in (f.get("from"), f.get("to")) or d in (f.get("from"), f.get("to")):
                continue
            if rates[i] is None or rates[j] is None or float(np.mean(rates[j])) <= 1e-12:
                continue
            new_f = {**f, "uses": [{"stock": d, "per": float(np.mean(rates[i]) / np.mean(rates[j]))}]}
            out.append([new_f if q == j else g for q, g in enumerate(fl) if q != i])
    return out


def _base_of(f: dict) -> str | None:
    """The stock a plain flow's rate is proportional to (k x level), else None."""
    r = f.get("rate") or {}
    if f.get("inflow") or f.get("byTime"):
        return None
    if r.get("form") == "proportional":
        return r.get("stock")
    if r.get("form") == "linear" and not r.get("c") and len(r.get("terms") or []) == 1:
        return r["terms"][0].get("stock")
    return None


def _self_growth(f: dict) -> bool:
    """An outside inflow into X at k x X (k > 0): X feeding itself, a misread drain."""
    return f.get("from") is None and f.get("to") is not None and _base_of(f) == f["to"] and not f.get("effects") \
        and float(((f.get("rate") or {}).get("k") or ((f.get("rate") or {}).get("terms") or [{}])[0].get("k") or 0)) > 0


def dry_steps(flows: list[dict], ids: list[str], prev: np.ndarray, c: str, margin: float = 1.2) -> np.ndarray:
    """Steps where C held less than `margin` x what the flows using it (and draining it) want: there
    the simulator's cap moves less than the rates say."""
    k = ids.index(c)
    want = np.zeros(prev.shape[1])
    for f in flows:
        if f.get("inflow") or f.get("byTime"):
            continue
        per = (float(f.get("ratio") or 1) if f.get("from") == c else 0.0) + sum(float(u.get("per") or 0) for u in f.get("uses") or [] if u.get("stock") == c)
        if per <= 0:
            continue
        with np.errstate(all="ignore"):
            amt = Model([{k2: v for k2, v in f.items() if k2 != "uses"}], ids).change(prev, np.zeros(prev.shape[1]))
        moved = np.nan_to_num(np.abs(amt).max(axis=0))
        want += per * moved
    return prev[k] < margin * want


def starved_candidates(stocks: list[dict], run: dict, prev: np.ndarray, opts: dict, fit_opts: dict, pool: bool,
                       models: list[list[dict]] = (), most: int = 2) -> list[list[dict]]:
    """Co-flows whose used stock runs dry. For each stock C that runs low for a while (at most three),
    the matrix is fitted (its forward variants without eras) on the steps where C is above its median
    (its rows linear there), and each drain of C that follows another stock is read as a co-flow on
    that stock's flows (cross_coflow_candidates; also on each of `models`, their structure only). Each
    candidate's inflows are measured again on every step with the model stepped with its cap
    (starvation.remeasure_inflows), its numbers refitted without the steps where C held less than its
    users want, and priced (if its cap still binds); for the `most` best over all such stocks, twice: the dry steps found again
    from the model and every number refitted without them, the second time with the inflows pooled
    and re-cut (residuals on the left-out steps from the model stepped with its cap). Kept only where
    the cap binds on at least 1% of the steps (5 at least)."""
    ids = [s["id"] for s in stocks]
    lv = np.nan_to_num(np.array([np.asarray(run["levels"][i], dtype=float) for i in ids]))
    final = {s["id"] for s in stocks if s.get("final")}
    out, first = [], []
    T = prev.shape[1]
    fo = {**fit_opts, "capped_res": True, "max_skip": 0.8}
    for c in stocks_running_dry(lv, ids, low=opts.get("dry_low", 0.5))[:3]:
        if c in final:
            continue
        m = first_mask(lv, ids, [c], low=1.0)
        if (~m).sum() < 20:
            continue
        tt = np.asarray(run["t"], dtype=float)[1:]
        seen = set()
        cands = [x for v in VARIANTS if not v.get("split_eras") and v["name"].startswith("forward")
                 for x in _kept_candidates(stocks, run, {**opts, **v, "keep": np.flatnonzero(~m)}, ids, prev, tt, c)]
        cands += [x for fl in models for x in cross_coflow_candidates(fl, ids, prev, tt, used=c)]
        for cand in cands:
            key = signature(cand)
            if key in seen:
                continue
            seen.add(key)
            # the inflows measured again on every step, the model's co-flows capped (remeasure_inflows),
            # and the numbers refitted without the dry steps: priced, so only the best few go on
            cand = remeasure_inflows(cand, stocks, lv, run["t"])
            skip = dry_steps(cand, ids, prev, c)
            if skip.mean() > 0.5:
                continue
            cand = refit(cand, ids, run, {**fo, "skip": skip})[0]
            if dry_steps(cand, ids, prev, c).sum() < max(5, 0.01 * T):
                continue                                    # its cap does not bind: not running dry
            first.append((price(cand, ids, run, fit_opts.get("inputs")), len(first), c, cand))
    first.sort(key=lambda x: (x[0], x[1]))
    for _, _, c, cand in first[:most]:
        for r in range(2):
            skip = dry_steps(cand, ids, prev, c)
            if skip.mean() > 0.5:
                break
            cand = refit(cand, ids, run, {**fo, "skip": skip})[0]
            if pool and r == 1:
                cand = resegment(cand, ids, run, {**fo, "skip": skip})
        # a co-flow whose cap never binds is not one that runs dry (cross_coflow_candidates offers it)
        if dry_steps(cand, ids, prev, c).sum() < max(5, 0.01 * T):
            continue
        out.append(cand)
    return out


def _kept_candidates(stocks, run, opts, ids, prev, tt, c) -> list[list[dict]]:
    """The matrix fitted on the kept steps (opts["keep"]), its pieces filled over the others, and each
    drain of C that follows another stock read as a co-flow (cross_coflow_candidates)."""
    r = identify_one(stocks, run, opts)
    if not r.get("flows"):
        return []
    flows = fill_gaps(r["flows"], run["t"])
    # a row read as growing with itself while a constant in pieces drains it is a row the pieces made
    # ambiguous (near its balance any such pair fits): the pieces are read back as its outside inflow,
    # and its drain offered by cross_coflow_candidates
    grows = {f["to"] for f in flows if _self_growth(f)}
    flows = [{**f, "from": None, "to": f["from"], "inflow": [{**g, "value": -float(g["value"])} for g in f["inflow"]]}
             if f.get("from") in grows and f.get("to") is None and f.get("inflow") else f for f in flows if not _self_growth(f)]
    return cross_coflow_candidates(flows, ids, prev, tt, used=c)
