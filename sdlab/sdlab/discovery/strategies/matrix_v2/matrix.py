"""The matrix method (one-step regression per stock, structure read off the matrix), with the fixes
other strategies proposed for it, each behind an option (docs/research/matrix_v2.md).

Copied from sdlab/discovery/matrix.py at commit aad5c7b (last changed there in cb97c26). Left out:
the paths only other strategies reach (extra columns and hinges, delayed copies, shared noise,
kept rows, step masks, start sets, the gate, dy adjustments, traces). With every option off, this is
the matrix's identify_one for every option identify() passes (eras, injections, inputs, known, and
the variants' search, changes, trust_receivers, split_eras).

The options (opts; defaults in __init__.OPTIONS):
  rss_floor     every BIC's rss floored at the data's rounding (T q^2 / 6; earned_pieces)
  pelt_mult     a change in the outside inflow costs pelt_mult x log n x the noise variance after the
                first, fine pass (the matrix: 1; censored's re-cut: 2)
  white         a row's final form keeps no inflow or a constant unless what that leaves is not white
                (Ljung-Box), instead of pieces whenever they beat it at 1 parameter a change
  pool          a row's pieces pooled into a few values and re-cut (Viterbi; pieces.py), kept when that
                prices better than the pieces and leaves residuals as white as they did
  tie_se        conservation ties a drain to what the receivers take unless the two differ by more
                than sqrt(log T) standard errors of both (the source's row and the receivers' rows)
  exact         common_cause's exact-data fix: rss and PELT's noise variance floored at the data's
                float precision, an exact fit walked along exact ties to the plainest set
  products      columns a x c for every pair of stocks (c may be a, or the row's own stock), joining a
                row only by product_gain x log T (reading.product_flows)
  pair_moves    a drain of one stock and a link into another at the same level (or product) read as one
                move, whatever stock the rate is based on (reading.pair_linear, product_flows)
  falling_inflow, gap_inflow
                a negative reading of another level folded into the row's outside inflow, floored at 0
                as a whole; gap_inflow folds the row's links and inputs too (reading.fold_inflows)
"""

from __future__ import annotations

import math

import numpy as np

from .changes import pelt
from .flows import merge_by_label, read_flows
from .pieces import pool_recut, white
from .reading import fold_inflows, pair_linear, product_flows
from .regression import fit_subset, piece_values, stepwise
from .regression import row_sums as _row_sums


REL = 1e-8           # (exact) the floor on a fit's mean square residual, relative to the changes' mean square


def resolution(levels: np.ndarray) -> float:
    """The data's quantum: the largest power of ten (1 down to 1e-8) every level is a whole multiple
    of (1 for counts; 1e-4 for levels rounded to four decimals), 0 when there is none.
    (From earned_pieces/rows.py at commit aad5c7b.)"""
    a = np.abs(np.asarray(levels, dtype=float).ravel())
    a = a[np.isfinite(a)]
    for e in range(0, 9):
        q = 10.0 ** -e
        if np.all(np.abs(a / q - np.round(a / q)) < 1e-6):
            return q
    return 0.0


def configurations(eras: list[dict] | None, t: list) -> tuple[list[str], np.ndarray, list[dict]] | None:
    """The distinct era labels, the configuration in force at each step (index into the labels),
    and the eras as time spans; None without two labels."""
    eras = sorted((e for e in eras or [] if e and e.get("start") is not None), key=lambda e: e["start"])
    name = lambda e: e.get("label") or str(e["start"])  # noqa: E731
    labels = list(dict.fromkeys(name(e) for e in eras))
    if len(labels) < 2:
        return None

    def cfg_at(time):
        c = None
        for e in eras:
            if time >= e["start"]:
                c = name(e)
        return c if c is not None else labels[0]

    T = len(t) - 1
    cfg = np.array([labels.index(cfg_at(t[k + 1])) for k in range(T)], dtype=int)
    spans = [{"from": e["start"], "to": eras[i + 1]["start"] - 1 if i + 1 < len(eras) else t[-1], "label": name(e)} for i, e in enumerate(eras)]
    if spans and spans[0]["from"] > t[0]:
        spans.insert(0, {"from": t[0], "to": spans[0]["from"] - 1, "label": cfg_at(t[0])})
    return labels, cfg, spans


def known_changes(known: dict, ids: list[str], n: int) -> np.ndarray:
    """The known change of each stock at each step (stocks x steps), 0 where nothing is known."""
    out = np.zeros((len(ids), n))
    for k, i in enumerate(ids):
        v = known.get(i)
        if v is not None:
            a = np.nan_to_num(np.asarray(v, dtype=float))[:n]
            out[k, : len(a)] = a
    return out


def product_pairs(ids: list[str], final: set, most: int) -> list[tuple[int, int]]:
    """Every pair (i <= j) of stocks that are not final (a final stock's level is close to a running
    sum of another's outflow and makes aliases), or none when there are more than `most` pairs."""
    live = [k for k, i in enumerate(ids) if i not in final]
    pairs = [(a, c) for x, a in enumerate(live) for c in live[x:]]
    return pairs if len(pairs) <= most else []


def identify_one(stocks: list[dict], run: dict, opts: dict) -> dict:
    ids = [s["id"] for s in stocks]
    S = len(ids)
    t = run["t"]
    T = len(t) - 1
    if T < 20:
        return {"flows": [], "note": "Too few steps."}
    lv = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, [0] * len(t)), dtype=float) for i in ids]))
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    if opts.get("known"):
        # what is already known (measured flows, the model's own equations) is taken out first, so
        # the rows explain the rest: known[s][i] is the known change of s from step i - 1 to i
        dy = dy - known_changes(opts["known"], ids, len(t))[:, 1:]
    if opts.get("injections"):
        # an announced injection is added at the start of its step, before that step's flows: the
        # step starts from the level plus the injection, and its change less the injection is the flows'
        inj = injected(opts["injections"], ids, t)[:, 1:]
        prev, dy = prev + inj, dy - inj
    at = lambda k: t[k + 1]  # noqa: E731
    conf = configurations(opts.get("eras"), t) if opts.get("split_eras") else None
    labels, cfg = (conf[0], conf[1]) if conf else ([None], np.zeros(T, dtype=int))
    L = len(labels)
    final = {s["id"] for s in stocks if s.get("final")}
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    group = {s["id"]: s.get("group") for s in stocks}
    log_t = math.log(T)
    # (rss_floor) below the data's rounding a row's rss says nothing: each change carries two roundings
    floor = T * resolution(lv) ** 2 / 6 if opts.get("rss_floor") else 0.0
    # (exact) common_cause's exact-data fix: no fit below the data's float precision (REL x the mean
    # square of the changes), PELT's noise variance never below 100 x it, exact ties walked to the plainest set
    ex = REL * float(np.mean(np.diff(lv, axis=1) ** 2)) if opts.get("exact") else 0.0
    row_sums = lambda y, X, c: _row_sums(y, X, c, ex)  # noqa: E731
    bic = lambda rss, p: T * math.log(max(rss, floor, 1e-12) / T) + p * log_t  # noqa: E731
    add_gain = opts.get("add_gain", log_t)                                # a level joins a row only if clearly nonzero
    min_piece = opts.get("min_piece", 5)
    mult = float(opts.get("pelt_mult", 1))
    # parameters a change in the outside inflow counts for in the BIC comparisons (a constant is 1)
    per_change = {k: opts.get(f"{k}_change_params", 1) for k in ("level", "form")}
    # how changes in the outside inflow are found in a residual series; phase is "fine" (the first
    # pass), "pass" (later passes), "level" (a level tried in place of pieces) or "conserve"
    scan = lambda r, phase: pelt(r, min_piece, 0.5 if phase == "fine" else mult, 1e2 * ex)  # noqa: E731

    # (opts "inputs") measured inputs, {name: value per step aligned with t}: each a column after the
    # levels, its value during the step (t[k] to t[k + 1]: the value at t[k + 1]); any row may take one
    inputs = [(k, np.nan_to_num(np.asarray(v, dtype=float))[1: len(t)]) for k, v in (opts.get("inputs") or {}).items() if k not in ids]
    # (products) a x c for pairs of stocks, after the inputs
    pairs = product_pairs(ids, final, int(opts.get("product_most", 36))) if opts.get("products") else []
    names = ids + [k for k, _ in inputs] + [f"{ids[a]}*{ids[c]}" for a, c in pairs]
    base = list(range(S)) + [0] * len(inputs) + [a for a, _ in pairs]
    rows_x = [prev] + [v[None, :] for _, v in inputs] + [(prev[a] * prev[c])[None, :] for a, c in pairs]
    columns = np.vstack(rows_x) if len(rows_x) > 1 else prev
    N = len(names)
    F = S                                                                 # the levels end here
    I0 = S                                                                # the inputs start here
    P0 = S + len(inputs)                                                  # the products start here
    gain = {P0 + q: float(opts.get("product_gain", 3)) * log_t for q in range(len(pairs))}

    def may_affect(j, s):
        a, b = group[ids[j]], group[ids[s]]
        return j == s or not a or not b or a == b

    def fit_row(s: int) -> dict:
        sid, y = ids[s], dy[s]
        X = [columns[j] for j in range(N)]
        col = [(j, -1) for j in range(N)]
        allowed = [j for j in range(F) if may_affect(base[j], s) and not (sid in final and base[j] == s)]
        allowed += list(range(I0, P0))
        prods = [P0 + q for q, (a, c) in enumerate(pairs) if may_affect(a, s) and may_affect(c, s)
                 and not (sid in final and s in (a, c))]
        late = opts.get("products") == "after"             # products offered only to the finished row
        if not late:
            allowed += prods
        own = s in allowed
        Xa = np.array(X)

        def step(sums, start):
            return stepwise(sums, start, allowed, add_gain, 4 * len(X), floor, gain, key)

        def key(cols):
            # (exact) how plain an exact row is: fewer columns, then fewer reading other stocks, then
            # those nearer the row's own stock in the page's order, then those listed before it
            cross = [col[q][0] - s for q in cols if col[q][0] != s]
            return (len(cols), len(cross), sum(abs(d) for d in cross), sum(d > 0 for d in cross))

        # fine pieces first (so the levels' numbers are not biased by unexplained changes), then the
        # usual price; the pieces are found in what the levels leave unexplained. Start from every
        # level when there are few (backward elimination), from none when there are many.
        cuts = [0, T]
        chosen = list(allowed) if len(allowed) <= opts.get("backward_max", 0) else []
        for p in range(5):
            sums = row_sums(y, Xa, cuts)
            chosen = step(sums, chosen)
            if p == 0 and L > 1:
                # the levels this row uses (and its own) may have a number per configuration; they
                # join before any change in the outside inflow is looked for
                js = list(dict.fromkeys([col[q][0] for q in chosen if col[q][0] < F] + ([s] if own else [])))
                for j in js:
                    for c in range(L):
                        X.append(np.where(cfg == c, columns[j], 0.0))
                        col.append((j, c))
                        allowed.append(len(X) - 1)
                Xa = np.array(X)
                sums = row_sums(y, Xa, cuts)
                chosen = step(sums, chosen)
            f = fit_subset(sums, chosen)
            res = y - (f.beta @ Xa[chosen] if chosen else 0)
            nxt = [0, T] if opts.get("changes") is False else scan(res, "fine" if p == 0 else "pass")
            if nxt == cuts and p >= 2:
                break
            cuts = nxt

        # a level that changes slowly looks like a series of changes in the outside inflow, and the
        # fine pieces take it before the level is tried: the two levels whose means over the pieces
        # follow the pieces' values best are tried in place of pieces, and kept if the row with it,
        # and the pieces it still needs, is clearly better
        if opts.get("changes") is not False and len(cuts) > 2:
            def fit_on(cols, c):
                f = fit_subset(row_sums(y, Xa[cols], c), list(range(len(cols))))
                return f, bic(f.rss, len(cols) + 1 + per_change["level"] * (len(c) - 2))

            def pieces_for(cols, c):
                f, _ = fit_on(cols, c)
                return scan(y - (f.beta @ Xa[cols] if cols else 0), "level")

            cur = fit_on(chosen, cuts)[1]
            for _ in range(3):
                f, _ = fit_on(chosen, cuts)
                pv = piece_values(y, Xa, chosen, f.beta, cuts)
                w = np.array([p_["w"] for p_ in pv], dtype=float)
                v = np.array([p_["v"] for p_ in pv])
                starts = np.array(cuts[:-1])

                def follows(j):
                    m = np.add.reduceat(Xa[j], starts) / w
                    mm, mv = (w * m).sum() / w.sum(), (w * v).sum() / w.sum()
                    sxy, sxx, syy = (w * (m - mm) * (v - mv)).sum(), (w * (m - mm) ** 2).sum(), (w * (v - mv) ** 2).sum()
                    return sxy * sxy / (sxx * syy) if sxx and syy else 0.0

                tries = sorted((j for j in allowed if j not in chosen and col[j][1] < 0 and col[j][0] < P0), key=lambda j: -follows(j))[:2]
                best = None
                for j in tries:
                    cols = chosen + [j]
                    c = pieces_for(cols, pieces_for(cols, [0, T]))
                    sc = fit_on(cols, c)[1]
                    if sc < cur - log_t and (best is None or sc < best[2]):
                        best = (cols, c, sc)
                if best is None:
                    break
                chosen, cuts, cur = best

        # the outside inflow: none, constant, or changing (only a stock with an inflow on average
        # clearly one way may have it change); the levels chosen alongside the pieces stay
        def try_form(c, extra):
            sums = row_sums(y, Xa, c)
            f = fit_subset(sums, chosen)
            return {"cuts": c, "f": f, "sc": bic(f.rss, len(chosen) + extra)}

        raw = row_sums(y, Xa, None)
        f_none = fit_subset(raw, chosen)
        none = {"cuts": None, "f": f_none, "sc": bic(f_none.rss, len(chosen))}
        constant = try_form([0, T], 1)
        pick = none if none["sc"] <= constant["sc"] else constant
        if len(cuts) > 2:
            # (white) no inflow or a constant one is kept unless what it leaves is not white: chance
            # pieces leave white residuals behind, an inflow that really changes a slow pattern
            keep_simple = False
            if opts.get("white"):
                e = y - (pick["f"].beta @ Xa[chosen] if chosen else 0.0)
                keep_simple = white(e - (e.mean() if pick["cuts"] else 0.0), float(opts.get("white_alpha", 0.01)))
            if not keep_simple:
                pieces = try_form(cuts, 1 + per_change["form"] * (len(cuts) - 2))
                vals = piece_values(y, Xa, chosen, pieces["f"].beta, cuts)
                W = sum(p_["w"] for p_ in vals)
                mean = sum(p_["v"] * p_["w"] for p_ in vals) / W
                sd = math.sqrt(sum(p_["w"] * (p_["v"] - mean) ** 2 for p_ in vals) / W)
                clear = abs(mean) > 0.5 * sd
                if (pick is constant or clear) and pieces["sc"] < pick["sc"]:
                    pick = pieces
        if late and prods:
            # (products "after") the finished row, with its inflow's final form, may take products of
            # levels (and give up levels for them) where each product pays product_gain x log T: a
            # product offered beside the fine pieces stands in for levels and pieces (chains lost)
            sums = row_sums(y, Xa, pick["cuts"])
            got = stepwise(sums, chosen, allowed + prods, add_gain, 4 * len(X), floor, gain, key)
            if any(q in prods for q in got):
                chosen = got
                f = fit_subset(sums, chosen)
                pick = {**pick, "f": f}
        beta, rss, se = pick["f"].beta, pick["f"].rss, pick["f"].se
        pcuts, pooled = pick["cuts"], None
        if opts.get("pool") and pcuts and len(pcuts) > 2:
            # (pool) the pieces pooled into a few values and re-cut where the inflow really changes
            got = pool_recut(y, Xa[chosen], pcuts, max(floor, ex * T), int(opts.get("pool_most", 4)), float(opts.get("pool_change", 2)),
                             int(opts.get("pool_guard", 2)), float(opts.get("pool_level_price", 2)), float(opts.get("white_alpha", 0.01)),
                             bool(opts.get("pool_white")))
            if got is not None:
                beta, rss, se, pcuts, pooled = got["beta"], got["rss"], got["se"], got["cuts"], got
        # each configuration's numbers: the shared one plus the configuration's own
        coef_l: list[dict] = [{} for _ in range(L)]
        var_l: list[dict] = [{} for _ in range(L)]
        for q, b, e in zip(chosen, beta, se):
            j, lab = col[q]
            for c in range(L):
                if lab < 0 or lab == c:
                    coef_l[c][names[j]] = coef_l[c].get(names[j], 0.0) + float(b)
                    var_l[c][names[j]] = var_l[c].get(names[j], 0.0) + float(e) ** 2
        inflow = []
        if pooled is not None:
            inflow = [{"from": at(a), "to": at(b - 1), "value": v} for a, b, v in pooled["segments"]]
        elif pcuts:
            inflow = [{"from": at(p_["a"]), "to": at(p_["b"] - 1), "value": p_["v"]} for p_ in piece_values(y, Xa, chosen, beta, pcuts)]
        return {"id": sid, "coefL": coef_l, "varL": var_l, "X": Xa, "col": col, "set": chosen, "beta": beta, "inflow": inflow,
                "cuts": pcuts, "pooled": pooled, "rss": rss, "p": len(chosen) + (len(pcuts) - 1 if pcuts else 0)}

    rows = [fit_row(s) for s in range(S)]
    ctx = {"stocks": stocks, "ids": ids, "t": t, "final": final, "unit": unit, "prev": prev, "dy": dy, "cfg": cfg, "L": L,
           "labels": labels, "conf": conf, "bic": bic, "log_t": log_t, "T": T, "at": at,
           "names": names, "columns": columns, "inputs": [k for k, _ in inputs], "pairs": pairs, "P0": P0, "exact": ex}
    return finish(rows, ctx, opts)


def finish(rows: list[dict], ctx: dict, opts: dict) -> dict:
    """From fitted rows (one per stock, changed in place) to the model: conservation, the outside
    inflows re-measured where it changed a row, and the structure read off the matrix."""
    stocks, ids, t, prev, dy, cfg, L = ctx["stocks"], ctx["ids"], ctx["t"], ctx["prev"], ctx["dy"], ctx["cfg"], ctx["L"]
    labels, conf, at, names, columns = ctx["labels"], ctx["conf"], ctx["at"], ctx["names"], ctx["columns"]
    conserve(rows, ids, ctx["final"], ctx["unit"], prev, dy, cfg, L, ctx["bic"], ctx["log_t"], opts, scan_mult=float(opts.get("pelt_mult", 1)),
             exact=ctx.get("exact", 0.0))

    # a row whose numbers conservation changed: its outside inflow's pieces are measured again with
    # the numbers it ends with (the pieces were measured beside the row's own, biased, drain)
    for s, row in enumerate(rows):
        if not row.get("conserved") or not row["cuts"]:
            continue
        res = dy[s].copy()
        for c in range(L):
            m = cfg == c
            for j, k in row["coefL"][c].items():
                res[m] -= k * columns[names.index(j)][m]
        if row.get("pooled") is not None:
            # a pooled inflow keeps its pools: each pool's value is the mean of what its steps leave
            lab, segs = row["pooled"]["labels"], row["pooled"]["segments"]
            val = {q: float(res[lab == q].mean()) for q in np.unique(lab)}
            row["inflow"] = [{"from": at(a), "to": at(b - 1), "value": val[int(lab[a])]} for a, b, _ in segs]
        else:
            row["inflow"] = [{"from": at(p_["a"]), "to": at(p_["b"] - 1), "value": p_["v"]} for p_ in piece_values(res, prev, [], np.zeros(0), row["cuts"])]

    per_label = [read_flows(stocks, [{"id": r["id"], "coef": r["coefL"][c], "inflow": r["inflow"] if c == 0 else []} for r in rows], prev, opts.get("tol", 0.003))
                 for c in range(L)]
    for c, fl in enumerate(per_label):                    # (opts "inputs") a row's number on a measured input
        fl += input_flows(rows, c, ctx.get("inputs") or [], columns, names)
        if ctx.get("pairs"):                              # (products) a row's number on a x c
            fl += product_flows(rows, c, ctx["pairs"], ids, ctx["unit"], prev, opts.get("tol", 0.003) / 100, opts.get("pair_moves", False))
    flows = merge_by_label(per_label, labels, conf[2]) if L > 1 else per_label[0]
    if L == 1 and opts.get("pair_moves"):                 # a move read off another stock's level
        flows = pair_linear(flows, ctx["unit"], float(opts.get("pair_slack", 0.3)))
    if L == 1 and (opts.get("falling_inflow") or opts.get("gap_inflow")):     # a goal gap: an inflow falling as levels rise
        flows = fold_inflows(flows, ids, prev, dy, t, opts.get("inputs") or None, gap=bool(opts.get("gap_inflow")), strict=bool(opts.get("fold_strict")))
    matrix = [{k: v for k, v in r.items() if k not in ("X", "col", "set", "beta", "pooled", "varL")} for r in rows]
    for r in matrix:
        r["coef"] = r["coefL"][0]
    out = {"flows": flows, "matrix": matrix, "method": "identify", "windows": ctx["T"], "window": 1}
    if L > 1:
        out["eras"] = labels
    return out


def conserve(rows, ids, final, unit, prev, dy, cfg, L, bic, log_t, opts, scan_mult: float = 1.0, exact: float = 0.0) -> None:
    """Conservation unless the data clearly says otherwise: a stock's drain is what same-unit stocks
    are seen to receive from it (measured, often more precisely, in their rows). Per configuration,
    tested together: setting the drain to what the receivers take must cost the row no more than
    log T in BIC (refitting the rest), or, for a row with a changing inflow (which cannot separate
    its drain from the changes), be within 30%.

    (tie_se) Instead: the drain and what the receivers take are two measurements of one number, so
    the tie holds unless they differ by more than sqrt(log T) standard errors of their difference
    (the source row's and every receiver row's, z^2 <= log T: a tie saves one number, priced as BIC
    prices it; without the matrix's extra log T). A receiver is a row that gains from the source (a
    negative reading is a link, never a receiver). Only for a row whose inflow does not change: one in
    pieces keeps the matrix's test (its refit finds the pieces again beside the tied drain), since the
    pieces bias its own drain beyond its standard error (040-random-chain-2#3 counts-long: 0.435 +-
    0.01 against the receiver's 0.353; 042-random-two-chains-of-two#7 counts-long)."""
    for s, row in enumerate(rows):
        a = row["id"]
        if a in final:
            continue
        drain = [-(c.get(a) or 0.0) for c in row["coefL"]]
        recv = [[r for r in rows if r["id"] != a and (r["coefL"][c].get(a) or 0) > 0 and unit[r["id"]] == unit[a]] for c in range(L)]
        moves = [sum(r["coefL"][c][a] for r in recv[c]) for c in range(L)]
        # a row whose outside inflow changes cannot separate its drain from the changes
        changing = bool(row["cuts"]) and len(row["cuts"]) > 2
        trust = opts.get("trust_receivers") is not False
        cand = [c for c in range(L) if moves[c] > 0 and ((changing and moves[c] > drain[c] and trust) or drain[c] > moves[c])]
        if not cand:
            continue
        slack = opts.get("slack", 0.3)
        near = changing and all(abs(drain[c] - moves[c]) / max(drain[c], moves[c]) < slack for c in cand)
        if opts.get("tie_se") and not changing:
            ok = True
            for c in cand:
                var = (row["varL"][c].get(a) or 0.0) + sum(r["varL"][c].get(a) or 0.0 for r in recv[c])
                if (drain[c] - moves[c]) ** 2 > log_t * max(var, 1e-300):
                    ok = False
            if ok:
                for c in cand:
                    row["coefL"][c][a] = -moves[c]
                row["conserved"] = True
            continue
        in_cand = np.zeros(L, bool)
        in_cand[cand] = True
        mv = np.array(moves)
        y2 = dy[s] + np.where(in_cand[cfg], mv[cfg] * prev[s], 0.0)
        others = [(q, i) for i, q in enumerate(row["set"]) if row["col"][q][0] != s]
        Xf = [row["X"][q] for q, _ in others]
        if len(cand) < L:
            Xf.append(np.where(in_cand[cfg], 0.0, prev[s]))
        Xf = np.array(Xf) if Xf else np.zeros((0, len(y2)))
        idx = list(range(len(Xf)))
        if changing:
            fixed_part = sum((row["beta"][i] * row["X"][q] for q, i in others), np.zeros(len(y2)))
            cuts2 = pelt(y2 - fixed_part, opts.get("min_piece", 5), scan_mult, 1e2 * exact)
        else:
            cuts2 = row["cuts"]
        sums = _row_sums(y2, Xf, cuts2, exact)
        fixed = fit_subset(sums, idx).rss
        p2 = len(idx) + (len(cuts2) - 1 if cuts2 else 0)
        if bic(fixed, p2) <= bic(row["rss"], row["p"]) + log_t or near:
            for c in cand:
                row["coefL"][c][a] = -moves[c]
            row["conserved"] = True


def input_flows(rows: list[dict], c: int, inputs: list[str], columns: np.ndarray, names: list[str]) -> list[dict]:
    """Flows reading measured inputs, from the rows' numbers on them in configuration c: k > 0 an
    inflow from outside at k x input, k < 0 an outflow to outside at -k x input."""
    out = []
    for r in rows:
        for name in inputs:
            k = r["coefL"][c].get(name) or 0.0
            if not k:
                continue
            rate = {"form": "linear", "c": 0, "terms": [{"stock": name, "k": round(abs(k), 6)}]}
            ends = {"from": None, "to": r["id"]} if k > 0 else {"from": r["id"], "to": None}
            out.append({**ends, "ratio": 1, "rate": rate, "rates": [rate], "perStep": abs(k) * float(columns[names.index(name)].mean()),
                        "nearly": [], "bothWays": False, "input": name})
    return out


def injected(injections: list[dict], ids: list[str], t: list) -> np.ndarray:
    """Announced injections ({t, stock, amount}) as stocks x steps: what was added at the start of
    each step."""
    out = np.zeros((len(ids), len(t)))
    index = {v: i for i, v in enumerate(t)}
    for j in injections:
        if j.get("stock") in ids and j["t"] in index:
            out[ids.index(j["stock"]), index[j["t"]]] += float(j["amount"])
    return out


def known_flows(known: dict, ids: list[str], t: list) -> list[dict]:
    """The known changes as flows the simulator runs: per stock, what arrives (an inflow from
    outside) and what leaves (an outflow to outside), step by step."""
    ch = known_changes(known, ids, len(t))
    out = []
    for k, i in enumerate(ids):
        if not ch[k].any():
            continue
        for sign, ends in ((1, {"from": None, "to": i}), (-1, {"from": i, "to": None})):
            v = np.maximum(0.0, sign * ch[k])
            if v.any():
                out.append({**ends, "ratio": 1, "inflow": [{"from": t[s], "to": t[s], "value": float(v[s])} for s in range(len(t))], "known": True})
    return out
