"""Experiment mass_balance (docs/research/mass-balance-hidden.md): hidden stocks reconstructed from a
unit's mass balance (sdlab/discovery/balance.py), on top of the main line.

The main line's model is found as usual. Then, while one helps: every pair (A loses to outside, B of
A's unit gets things from outside) is turned into A -> H -> B with H's level reconstructed from the
balance; a pair that does not balance (H drifts, goes negative, or A would send more than it loses)
is rejected before it is judged. A proposal is accepted when the model with it behaves better on the
data than the model it came from with B's arrivals held at their mean (with its pieces, fitted to
this run, the old model always looks better on the run). The found model's unmeasured stocks carry
their own estimated levels (result["inferred_levels"]): what the model itself gives from the
measured levels (sdlab/discovery/observer.py).

opts: "mb_margin" (accept only below margin x the reference's error; default 1.0), "mb_against"
("means": B's arrivals at their mean, the default; "found": the model as found), "mb_max" (hidden
stocks at most; default 3), "mb_rest" (also try keeping what A loses beyond
what H takes as a loss to outside; default False: conservation first, A loses only what H takes, as
the main line reads a drain off what receivers take), "mb_tol" (with mb_rest, the rest is kept only
if that behaves better by more than this share; default 0.05), "mb_all" (try every candidate of the main
line, not only the chosen one; default False), "mb_trace" (print every proposal).
"""

from __future__ import annotations

from orchestra.sdlab.discovery.balance import arrivals, pairs, propose
from orchestra.sdlab.discovery.identify import VARIANTS
from orchestra.sdlab.discovery.identify import identify as main_line
from orchestra.sdlab.discovery.identify import judge as main_judge
from orchestra.sdlab.discovery.matrix import identify_one
from orchestra.sdlab.discovery.observer import observe
from orchestra.sdlab.discovery.simulate import behaviour_error

HORIZONS = (5, 20, 100)


def judge(flows: list[dict], stocks: list[dict], run: dict, inferred: dict | None = None) -> float:
    hs = [h for h in HORIZONS if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    ids = [s["id"] for s in stocks]
    return sum(behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, inferred=inferred) for h in hs) / len(hs)


def at_means(flows: list[dict], idx: list[int]) -> list[dict]:
    """The flows with the arrivals in idx (pieces) held at their mean."""
    out = []
    for i, f in enumerate(flows):
        if i in idx and f.get("inflow"):
            w = [g["to"] - g["from"] + 1 for g in f["inflow"]]
            m = sum(g["value"] * n for g, n in zip(f["inflow"], w)) / max(1, sum(w))
            f = {k: v for k, v in f.items() if k not in ("inflow", "changes")}
            f["rate"] = {"form": "constant", "value": m}
        out.append(f)
    return out


def augment(flows: list[dict], stocks: list[dict], run: dict, opts: dict, tried: list) -> tuple[list[dict], dict, list[str]]:
    """The flows with every hidden stock the balance supports (accepted one at a time, best first),
    their estimated levels, and the receivers whose arrivals they replaced."""
    ids = [s["id"] for s in stocks]
    levels, receivers = {}, []
    trace = opts.get("mb_trace")
    margin = opts.get("mb_margin", 1.0)
    tol = opts.get("mb_tol", 0.05)
    for _ in range(opts.get("mb_max", 3)):
        base = judge(flows, stocks, run, levels)
        best = None
        for a, b in pairs(flows, stocks):
            p = propose(flows, stocks, run, a, b, opts)
            if p is None:
                continue
            rec = p.get("rec") or {}
            if p["flows"] is None:
                tried.append({"pair": f"{a}>{b}", "why": p["why"]})
                if trace:
                    print(f"  {a} -> ? -> {b}: rejected ({p['why']})")
                continue
            h = p["hidden"]
            ref = base if opts.get("mb_against") == "found" else judge(at_means(flows, arrivals(flows, a, b)), stocks, run, levels)
            pick = None
            variants = [("all to H", p.get("alt") or p["flows"])]
            if opts.get("mb_rest") and p.get("alt"):
                variants.append(("rest to outside", p["flows"]))
            for name, fl in variants:
                est = observe(fl, ids, run["t"], run["levels"], [h], {h: p["level"][0]})
                inferred = {**levels, **est}
                e = judge(fl, stocks, run, inferred)
                tried.append({"pair": f"{a}>{b}", "variant": name, "error": e, "against": ref, "alpha": rec.get("alpha"), "d": rec.get("d")})
                if trace:
                    print(f"  {a} -> H -> {b} ({name}): alpha {rec['alpha']:.3f}, d {rec['d']:.4f}, H0 {rec['h0']:.1f}; error {e:.4f} vs {ref:.4f} (found {base:.4f})")
                # conservation first: A loses only what H takes unless the data clearly says otherwise
                if pick is None or (1 + tol) * e < pick[0]:
                    pick = (e, fl, inferred, b)
            if pick and pick[0] < margin * ref and (best is None or pick[0] < best[0]):
                best = pick
        if best is None:
            break
        flows, levels = best[1], best[2]
        receivers.append(best[3])
    return flows, levels, receivers


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    tried: list = []
    if not opts.get("mb_all"):
        r = main_line(stocks, run, opts)
        flows, levels, _ = augment(r["flows"], stocks, run, opts, tried)
    else:
        r, flows, levels = every_candidate(stocks, run, opts, tried)
    r["flows"] = flows
    if levels:
        r["inferred_levels"] = levels
        r["chosen"] = f"{r.get('chosen')} + {len(levels)} hidden from the balance"
    r["balance"] = tried
    return r


def every_candidate(stocks: list[dict], run: dict, opts: dict, tried: list):
    """The balance tried on every candidate of the main line (a constant-inflow candidate may have
    nothing to pair where a changing-inflow one does). The chosen candidate (as the main line chooses)
    is kept unless another candidate with hidden stocks behaves better than it does with the arrivals
    those stocks replaced held at their mean."""
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    cands = []
    for v in VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        c = identify_one(stocks, run, {**opts, **v})
        cands.append((main_judge(c["flows"], stocks, run) if c["flows"] else float("inf"), v["name"], c))
    e0, name0, r = min(cands, key=lambda x: x[0])
    r["chosen"], r["tried"] = name0, [{"name": n, "error": e} for e, n, _ in cands]
    flows, levels, _ = augment(r["flows"], stocks, run, opts, tried)
    best = (judge(flows, stocks, run, levels), flows, levels, name0) if levels else None
    for e, name, c in cands:
        if name == name0 or not c["flows"]:
            continue
        f2, l2, recv = augment(c["flows"], stocks, run, opts, [])
        if not l2:
            continue
        e2 = judge(f2, stocks, run, l2)
        ref = judge(at_means(r["flows"], [i for i, f in enumerate(r["flows"]) if f.get("to") in recv and f.get("from") is None and not f.get("driver")]), stocks, run)
        if opts.get("mb_trace"):
            print(f"  candidate {name}: {len(l2)} hidden, error {e2:.4f} vs chosen at means {ref:.4f}")
        if e2 < ref and (best is None or e2 < best[0]):
            best = (e2, f2, l2, name)
    if best is None:
        return r, r["flows"], {}
    r["chosen"] = best[3]
    return r, best[1], best[2]
