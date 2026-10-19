"""Copied from strategy hidden_transit at commit 376fa34 (its committed __init__, fit, kalman, pairs; imports
rewritten, `identify` turned into `add`, which works on a given model). Original docstring:

Experiment hidden_transit (docs/research/hidden_transit.md): an unmeasured transit stock between
two measured ones (A -> H -> B), with the pair's rows refitted as one model by a Kalman filter's
likelihood, on top of the main line.

The main line's model is found as usual. Then, for every pair (A loses in proportion to its level,
to outside or straight to B; B gets things from outside or from A), the pair's rows are refitted
twice by the same likelihood (kalman.py, fit.py): as a transit stock (A's loss goes into H, H drains
into B at d a step: a delay of 1 / d) and as the plain alternative (B gets a share of A's loss
straight away). Each in variants: A's outside inflow refitted as one constant or kept as found; B with
or without an outside constant. The transit stock is accepted when its best variant beats the best
plain one by BIC (numbers fitted, and pieces kept from the main line, cost log T each) by a margin,
and the model with it behaves better on the data than the main line's with B's outside
inflow held at its mean (its pieces, fitted to this run, would make it look better on it). Pairs are taken greedily,
best first, each stock in one pair at most; never against a move B -> A the main line found (a
transit back along a move is a loop's echo, not a stock).

"All of A's loss goes to H" (kin = kA) is the default: B's response to A alone cannot tell a
delay d with B's drain kb from the mirror (d and kb swapped, kin scaled), but A's balance can.
A share (kin < kA, the rest to outside) is accepted only when it is better by BIC.

The counting noise is used as it is: the data are counts (whole numbers), so each flow's variance is
its rate (scale 1), which also pins the rates' sizes where a short run's mean levels cannot. Data
that are not counts get a concentrated scale.

opts: "ht_margin" (BIC margin in units of log n, n the number of changes: default 4),
"ht_found_ratio" (the model with H may behave at most this many times worse than the model as found,
pieces and all; default 1.5), "ht_slack" (the model may behave this much worse than the
reference on the data, default 0: it must behave better), "ht_max" (hidden stocks at most, default 2), "ht_turns" (H must turn over at least this many
times in the run: delay <= T / ht_turns, default 15), "ht_min_delay" (a shorter delay is a move;
default 1.5 steps), "ht_trace".
"""

from __future__ import annotations

import math

import numpy as np

from ....balance import amounts
from ....simulate import behaviour_error, levels_array
from .fit import fit_plain, fit_transit, screen
from .kalman import Pair
from .pairs import _prop_on as _prop, at_means, build, candidate, echo_merged, exogenous, flow_numbers, one_piece, pieces, split

HORIZONS = (5, 20, 100)


def judge(flows: list[dict], stocks: list[dict], run: dict, inferred: dict | None = None, injections: list[dict] | None = None,
          inputs: dict | None = None) -> float:
    hs = [h for h in HORIZONS if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    ids = [s["id"] for s in stocks]
    return sum(behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, inferred=inferred, injections=injections,
                               inputs=inputs) for h in hs) / len(hs)


def counts(run: dict) -> bool:
    """The data are counts: whole numbers that move (each flow then varies as much as its rate)."""
    moved = False
    for v in run["levels"].values():
        x = np.asarray(v, dtype=float)
        x = x[np.isfinite(x)]
        if x.size and np.abs(x - np.round(x)).max() > 1e-9:
            return False
        moved = moved or (x.size > 1 and np.abs(np.diff(x)).max() > 0)
    return moved


def _injected(injections: list[dict] | None, ids: list[str], t: list) -> np.ndarray:
    """Announced injections as stocks x steps (step k from t[k] to t[k + 1] starts with what was added
    at t[k + 1], before its flows: matrix.injected's convention; copied, not imported, by loop_transit)."""
    out = np.zeros((len(ids), max(0, len(t) - 1)))
    index = {v: i for i, v in enumerate(t)}
    for j in injections or []:
        if j.get("stock") in ids and j["t"] in index and index[j["t"]] >= 1:
            out[ids.index(j["stock"]), index[j["t"]] - 1] += float(j["amount"])
    return out


def _between(flows: list[dict], keep: list[int], ids: list[str], t: list, Ls: np.ndarray, a: str, b: str) -> np.ndarray:
    """loop_transit: the gross amount a step of the kept flows that run straight between A and B (each
    is in both rows, with opposite signs: its noise is shared)."""
    kept = [flows[i] for i in keep if {flows[i].get("from"), flows[i].get("to")} == {a, b}]
    if not kept:
        return np.zeros(Ls.shape[1] - 1)
    return np.abs(amounts(kept, ids, t, Ls)).sum(axis=0)


def try_pair(flows: list[dict], ids: list[str], run: dict, levels: dict, a: str, b: str, scale: float,
             injections: list[dict] | None = None) -> dict | None:
    """The pair's best transit and best plain fits over the variants (A's outside inflow as one
    constant or in the main line's pieces, re-measured; B with or without an outside constant), each
    with its BIC, and the found model's own rows by the same likelihood; None when a least-squares
    screen of B's row finds no sign of a delay."""
    t = run["t"]
    L = levels_array(levels, ids)
    T = L.shape[1] - 1
    logn = math.log(2 * T)
    inj = _injected(injections, ids, t)
    iA, iB = inj[ids.index(a)], inj[ids.index(b)]
    Ls = L.copy()                    # each step's start levels in [:, :-1] (the kept flows run on them)
    Ls[:, :-1] += inj
    _, keep = split(flows, a, b)
    # loop_transit: a return move B -> A (a closed loop) is refitted with the pair: its rate, read by
    # the main line on rows missing H, is biased with them
    back = [i for i in keep if flows[i].get("from") == b and flows[i].get("to") == a and _prop(flows[i], b)]
    move0 = float(flows[back[0]]["rate"].get("k") or (flows[back[0]]["rate"].get("terms") or [{}])[0].get("k") or 0) if len(back) == 1 else 0.0
    if move0 > 0:
        keep = [i for i in keep if i != back[0]]
    xA, gA = exogenous(flows, keep, ids, t, Ls, a)
    xB, gB = exogenous(flows, keep, ids, t, Ls, b)
    seg, spans = pieces(flows, a, t)
    shapes = [one_piece(seg, spans)] + ([(seg, spans)] if seg is not None and len(spans) > 1 else [])
    pairs = [(Pair(L[ids.index(a)], L[ids.index(b)], xA, gA, xB, gB, scale, sg, iA, iB), sp) for sg, sp in shapes]
    shk = _between(flows, keep, ids, t, Ls, a, b)
    for pair, _sp in pairs:
        pair.move = move0 if move0 > 0 else None
        pair.sh = shk
    if not screen(pairs[0][0], T):
        return None
    best_t, best_p = None, None
    for pair, sp in pairs:
        extra = 2 * len(sp) - 1 if sp else 0                   # each piece: its value and its place
        for cB_on in (False, True):
            p = fit_plain(pair, cB_on)
            p_bic = p["nll"] + (p["k"] + extra) * logn
            if best_p is None or p_bic < best_p["bic"]:
                best_p = {**p, "bic": p_bic}
            for kb_on in (True, False):          # loop_transit: B without a drain of its own as well
                f = fit_transit(pair, cB_on, True, kb_on=kb_on)
                if f is None:
                    continue
                bic = f["nll"] + (f["k"] + extra) * logn
                if best_t is None or bic < best_t["bic"]:
                    best_t = {**f, "bic": bic, "cB_on": cB_on, "spans": sp, "pair": pair, "extra": extra, "all_to_h": True, "kb_on": kb_on}
    if best_t is None:
        return None
    # a share of A's loss to H (the rest to outside), on the best variant only
    f = fit_transit(best_t["pair"], best_t["cB_on"], False, kb_on=best_t["kb_on"])
    if f is not None and f["nll"] + (f["k"] + best_t["extra"]) * logn < best_t["bic"]:
        best_t = {**best_t, **f, "bic": f["nll"] + (f["k"] + best_t["extra"]) * logn, "all_to_h": False}
    best_t["keep"] = keep
    # the found model's own rows of A and B, by the same likelihood (its pieces cost their numbers)
    allk = list(range(len(flows)))
    xA, gA = exogenous(flows, allk, ids, t, Ls, a)
    xB, gB = exogenous(flows, allk, ids, t, Ls, b)
    pair = Pair(L[ids.index(a)], L[ids.index(b)], xA, gA, xB, gB, scale, None, iA, iB, _between(flows, allk, ids, t, Ls, a, b))
    k = sum(flow_numbers(f) for f in flows if {a, b} & {f.get("from"), f.get("to")})
    found = {"nll": pair.plain(0.0, 0.0, 0.0, 0.0), "k": k}
    found["bic"] = found["nll"] + k * logn
    other = min(best_p["bic"], found["bic"])
    return {"transit": best_t, "plain": best_p, "found": found, "gain": other - best_t["bic"]}


def _total(res: dict, flows: list[dict], a: str, b: str, run: dict) -> float:
    """The transit's BIC with the numbers of the kept flows that touch A or B counted as well."""
    logn = math.log(2 * (len(run["t"]) - 1))
    f = res["transit"]
    kept = sum(flow_numbers(flows[i]) for i in f["keep"] if {a, b} & {flows[i].get("from"), flows[i].get("to")})
    return f["bic"] + kept * logn


def _size(rate: dict, means: dict) -> float:
    """A rate's mean amount a step at the data's mean levels (proportional and linear rates)."""
    if rate.get("form") == "proportional":
        return abs(float(rate.get("k") or 0) * means.get(rate.get("stock"), 0.0))
    if rate.get("form") == "linear":
        return abs(float(rate.get("c") or 0) + sum(float(t.get("k") or 0) * means.get(t.get("stock"), 0.0) for t in rate.get("terms") or []))
    return 0.0


def used_stock(flows: list[dict], a: str, means: dict) -> bool:
    """A's loss mostly follows other stocks (outflows of A whose rate reads another stock carry more
    than its own-level outflows, at the data's mean levels: a stock used up by other flows, as a
    co-flow's, not a stage's source; sd-brewery's water read as water -> H -> fermenting)."""
    own = other = 0.0
    for f in flows:
        if f.get("from") != a or f.get("to") is None and (f.get("rate") or {}).get("form") == "constant":
            continue
        r = f.get("rate") or {}
        reads = {r.get("stock")} | {t.get("stock") for t in r.get("terms") or []}
        reads.discard(None)
        size = _size(r, means)
        if reads and reads <= {a}:
            own += size
        elif reads:
            other += size
    return other > own


def add(r: dict, stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """realistic_hats: hidden_transit's pairs (as identify below did) on a found model r instead of the
    main line's; a pair whose stocks a flow with an effect or a co-flow touches is left alone (the
    pair's Kalman rows are linear); a pair with a move B -> A is tried too (a closed loop)."""
    opts = dict(opts or {})
    margin = opts.pop("ht_margin", 4.0)
    found_ratio = opts.pop("ht_found_ratio", 1.5)
    slack = opts.pop("ht_slack", 0.0)
    shortest = opts.pop("ht_min_delay", 1.5)
    most = opts.pop("ht_max", 2)
    trace = opts.pop("ht_trace", False)
    turns = opts.pop("ht_turns", 15)
    injections, inputs = opts.get("injections"), opts.get("inputs")
    flows = r["flows"]
    if r.get("inferred_levels"):
        return r
    ids = [s["id"] for s in stocks]
    if len(run["t"]) < 30 or not flows:
        return r
    unit = {s["id"]: (s.get("unit") or "", s.get("group")) for s in stocks}
    final = {s["id"] for s in stocks if s.get("final")}
    scale = 1.0 if counts(run) else 0.0
    inferred: dict[str, list[float]] = {}
    used: set[str] = set()
    base_e = judge(flows, stocks, run, None, injections, inputs)
    means = {k: float(np.nanmean(np.asarray(v, dtype=float))) for k, v in run["levels"].items()}
    tried = []
    for _ in range(most):
        levels = {**run["levels"], **inferred}
        all_ids = ids + list(inferred)
        best = None
        for a in ids:
            for b in ids:
                if a == b or a in final or a in used or b in used or unit[a][0] != unit[b][0]:
                    continue
                if unit[a][1] and unit[b][1] and unit[a][1] != unit[b][1]:
                    continue
                if any((f.get("effects") or f.get("uses")) and {a, b} & {f.get("from"), f.get("to")} for f in flows):
                    continue
                # (hidden_transit also skips a pair with a move B -> A, "a loop's echo"; on a closed loop
                # the return move is real (156, sd-ev-fleet, sd-recycling), and the acceptance below
                # finds no transit on 008, 010 or 012 without that rule)
                if used_stock(flows, a, means):
                    continue
                if not candidate(flows, a, b):
                    continue
                res = try_pair(flows, all_ids, run, levels, a, b, scale, injections)
                if res is not None:
                    res["base"] = flows
                # loop_transit: the pair also on the flows with the return move's echo folded in, the
                # better by BIC with the kept flows' numbers counted (the fold drops one)
                merged = echo_merged(flows, a, b)
                if merged is not None:
                    res_m = try_pair(merged, all_ids, run, levels, a, b, scale, injections)
                    if trace and res_m is not None:
                        print(f"  echo fold {a}>{b}: total {_total(res_m, merged, a, b, run):.1f} vs {_total(res, flows, a, b, run) if res else float('nan'):.1f}; kb {res_m['transit']['kb']:.4f}")
                    if res_m is not None and (res is None or _total(res_m, merged, a, b, run) < _total(res, flows, a, b, run)):
                        res = {**res_m, "base": merged}
                if res is None:
                    continue
                f = res["transit"]
                tried.append({"pair": f"{a}>{b}", "gain": res["gain"], "delay": 1 / f["d"], "kin": f["kin"], "kA": f["kA"], "kb": f["kb"]})
                if trace:
                    print(f"  {a} -> H -> {b}: gain {res['gain']:.1f}; delay {1 / f['d']:.3f}, kin {f['kin']:.4f} of {f['kA']:.4f}, "
                          f"kb {f['kb']:.4f}, A in {np.round(f['values'], 2).tolist()[:6]}, cB {f['cB']:.3f} ({f['cB_on']})")
                # H must turn over many times in the run (a longer delay is a slow drift, which
                # pieces or a schedule explain as well)
                if not shortest <= 1 / f["d"] <= len(run["t"]) / turns:
                    continue
                if res["gain"] > margin * math.log(2 * (len(run["t"]) - 1)) and (best is None or res["gain"] > best[0]["gain"]):
                    best = (res, a, b)
        if best is None:
            break
        res, a, b = best
        f = res["transit"]
        new, h = build(res["base"], f["keep"], a, b, f, f["spans"])
        inf = {**inferred, h: np.maximum(0.0, f["H"]).tolist()}
        # pieces fitted to this run make the found model look good on it: the reference holds B's
        # outside constants (the arrivals H would explain) at their mean
        e = judge(new, stocks, run, inf, injections, inputs)
        # (and A's too when the transit holds A's inflow constant: like against like)
        ref = judge(at_means(flows, {b} | ({a} if len(f["spans"]) <= 1 else set())), stocks, run, inferred or None, injections, inputs)
        if trace:
            print(f"  accept {a} -> H -> {b}? judge {e:.4f} vs {ref:.4f} (as found {base_e:.4f}); plain {res['plain']['bic']:.1f}, found {res['found']['bic']:.1f}, transit {f['bic']:.1f}")
        if not (e <= (1 + slack) * ref + 1e-9 and e <= found_ratio * base_e + 1e-9):
            break
        flows, inferred, base_e = new, inf, e
        used |= {a, b}
    r = {**r, "flows": flows, "transit": tried}
    if inferred:
        r["inferred_levels"] = inferred
        r["chosen"] = f"{r.get('chosen')} + {len(inferred)} transit stock(s)"
    return r
