"""identify(): several ways of estimating the matrix, and the one whose model behaves best on the data.

A model is judged as the goal judges it: run forward from many moments in the measured data and
compared with what was measured (its own estimated outside inflows feed it), over 5, 20 and 100
steps (loops that only mimic an outside input drift apart later). Only the data is used.
With opts["candidates"] the result also lists every candidate (name, judge error, flows), for the
bench to grade each one (tests/bench/candidates.py); nothing else changes.
"""

from __future__ import annotations

from . import boundary
from .earned_rows import reselect, rss_floor
from .matrix import finish, identify_one, known_flows
from ...regression import fit_subset, piece_values, row_sums
from ...simulate import behaviour_error

# each combination of: forward or backward search; outside inflows that change or stay constant;
# trusting the receivers or the rows where stocks are seen receiving more than a stock's own row
# says it loses; and (with announced eras) numbers per configuration
VARIANTS: list[dict] = []
for search in ({"name": "forward"}, {"name": "backward", "backward_max": 20}):
    for inflow in ({"name": "changing inflows"}, {"name": "constant inflows", "changes": False}):
        for recv in ({"name": "trust receivers"}, {"name": "trust rows", "trust_receivers": False}):
            for era in ({"name": ""}, {"name": ", numbers per era", "split_eras": True}):
                VARIANTS.append({**search, **inflow, **recv, **era, "name": f"{search['name']}, {inflow['name']}, {recv['name']}{era['name']}"})


def judge(flows: list[dict], stocks: list[dict], run: dict, horizons=(5, 20, 100), injections: list[dict] | None = None,
          inputs: dict | None = None) -> float:
    """inputs (optional): measured inputs, {name: value per step aligned with t}, that the flows may read."""
    hs = [h for h in horizons if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    ids = [s["id"] for s in stocks]
    return sum(behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, injections=injections, inputs=inputs) for h in hs) / len(hs)


def earn(stocks: list[dict], r: dict, opts: dict, bd: boundary.Boundary | None = None) -> dict:
    """The candidate with each row's pieces earned (earned_rows.reselect, a copy of earned_pieces'
    rows.py): a row's outside-inflow pieces are dropped, its levels chosen again beside them, when a
    constant (or no) inflow leaves white residuals and a lower BIC with every change priced as a value
    and a place; then the model is read off again by finish (the shared noise's move-or-link test and
    conservation, as before). Without it, chance pieces on a stock with no outside inflow could win the
    in-sample judge (302 counts-short, docs/research/k8s-302.md).

    Inside the announced boundary bd (boundary.py, as matrix/earned.refit): a row has an outside term
    (constant or pieces) only where its stock may have an estimated outside flow, reads a measured
    input only where it may have a measured one, and reads a stock of another unit (a link from or a
    drain to outside) only where it may have an estimated one; a matrix row that breaks these is
    replaced by the best row inside them."""
    bd = bd or boundary.Boundary({})
    rows, ctx = r.get("raw_rows"), r.get("ctx")
    if not rows or not ctx:
        return r
    ids, prev, dy, cfg, L = ctx["ids"], ctx["prev"], ctx["dy"], ctx["cfg"], ctx["L"]
    names, columns = ctx.get("names") or ids, ctx.get("columns", prev)
    if ctx.get("extras") or len(names) != columns.shape[0]:
        return r
    inputs = list(range(len(ids), len(names))) if ctx.get("inputs") else []
    floor = rss_floor(prev, dy.shape[1])
    unit = {x["id"]: x.get("unit") or "" for x in stocks}

    def exclude(s: int) -> tuple:
        out = [] if bd.inputs_ok(ids[s]) else list(inputs)
        if not bd.links_ok(ids[s]):
            out += [j for j in range(len(ids)) if unit[ids[j]] != unit[ids[s]]]
        return tuple(out)

    changed, new = False, []
    for s, row in enumerate(rows):
        b = reselect(row, s, ids, stocks, columns if inputs else prev, dy, cfg, L, 2, 0.01, floor, "beside", inputs,
                     pieces_ok=bd.pieces_ok(ids[s]), exclude=exclude(s))
        if b["name"] == "matrix":
            new.append(row)
            continue
        changed = True
        nr = b["row"]
        X, chosen, cuts = nr["X"], nr["set"], nr["cuts"]
        f = fit_subset(row_sums(dy[s], X, cuts), chosen)
        coef_l: list[dict] = [{} for _ in range(L)]
        for q, v in zip(chosen, f.beta):
            j, lab = nr["col"][q]
            for c in range(L):
                if lab < 0 or lab == c:
                    coef_l[c][names[j]] = coef_l[c].get(names[j], 0.0) + float(v)
        inflow = [{"from": ctx["at"](p["a"]), "to": ctx["at"](p["b"] - 1), "value": p["v"]} for p in piece_values(dy[s], X, chosen, f.beta, cuts)] if cuts else []
        new.append({**nr, "coefL": coef_l, "beta": f.beta, "inflow": inflow, "rss": f.rss})
    if not changed:
        return r
    return finish(new, ctx, opts)


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    keep = opts.pop("candidates", False)                 # the bench grades every candidate

    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    best, tried, candidates = None, [], []
    bd = boundary.Boundary(run)              # the announced boundary (boundary.py)
    # known changes (opts["known"]) are part of every candidate's behaviour when it is judged
    extra = known_flows(opts["known"], [s["id"] for s in stocks], run["t"]) if opts.get("known") else []
    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        r = identify_one(stocks, run, {**opts, **v, "keep_rows": True, "input_columns": True})
        r = earn(stocks, r, {**opts, **v}, bd)
        for k in ("raw_rows", "ctx"):
            r.pop(k, None)
        if bd.declared and r.get("flows"):        # no candidate with an outside flow the case does not declare
            r = boundary.apply(r, stocks, run, opts, final=False)
        e = judge(r["flows"] + extra if r["flows"] else [], stocks, run, injections=opts.get("injections"),
                  inputs=opts.get("inputs"))
        tried.append({"name": v["name"], "error": e})
        if keep:
            candidates.append({"name": v["name"], "error": e, "flows": r["flows"]})
        if best is None or e < best[1]:
            best = (r, e, v["name"])
    r = best[0]
    r["chosen"], r["tried"] = best[2], tried
    if keep:
        r["candidates"] = candidates
    return r
