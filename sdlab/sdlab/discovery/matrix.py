"""Identifying a system dynamics model from its stocks' levels: the matrix method.

In a model whose flows are linear in the levels (constant, proportional, gap and linear forms),
every stock's change in a step is a linear function of the levels at the start of the step, plus
what arrives from outside:

    change of s at t  =  u_s(t)  +  sum_j  B[s][j] x level of j at t-1   (+ noise)

So the whole system is the matrix B and the outside inflows u. This module estimates them one stock
at a time, by least squares on single steps, then reads stock-and-flow structure off B (flows.py).

Announced eras: each distinct era label is a configuration of the system. The structure is shared:
one regression per stock, in which a level's number may differ in a configuration (a column "level
of j while configuration c holds" joins the search, and stays only if it pays for itself).
"""

from __future__ import annotations

import math

import numpy as np

from .changes import pelt
from .flows import merge_by_label, read_flows
from .regression import fit_subset, piece_values, row_sums, stepwise


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
    bic = lambda rss, p: T * math.log(max(rss, 1e-12) / T) + p * log_t  # noqa: E731
    add_gain = opts.get("add_gain", log_t)                                # a level joins a row only if clearly nonzero
    min_piece = opts.get("min_piece", 5)

    def may_affect(j, s):
        a, b = group[ids[j]], group[ids[s]]
        return j == s or not a or not b or a == b

    def fit_row(s: int) -> dict:
        sid, y = ids[s], dy[s]
        X = [prev[j] for j in range(S)]
        col = [(j, -1) for j in range(S)]
        allowed = [j for j in range(S) if may_affect(j, s) and not (sid in final and j == s)]
        own = s in allowed
        Xa = np.array(X)

        def step(sums, start):
            return stepwise(sums, start, allowed, add_gain, 4 * len(X))

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
                js = list(dict.fromkeys([col[q][0] for q in chosen] + ([s] if own else [])))
                if opts.get("era_levels") == "allowed":
                    # (an option) every level the row may use, not only those it chose without eras:
                    # a level that barely moves is chosen only once its number may follow the configuration
                    js = list(dict.fromkeys(js + [q for q in allowed if col[q][1] < 0]))
                for j in js:
                    for c in range(L):
                        X.append(np.where(cfg == c, prev[j], 0.0))
                        col.append((j, c))
                        allowed.append(len(X) - 1)
                Xa = np.array(X)
                sums = row_sums(y, Xa, cuts)
                chosen = step(sums, chosen)
            f = fit_subset(sums, chosen)
            res = y - (f.beta @ Xa[chosen] if chosen else 0)
            nxt = [0, T] if opts.get("changes") is False else pelt(res, min_piece, 0.5 if p == 0 else 1)
            if opts.get("trace") == sid:
                print(f"  {sid} pass {p}: {len(cuts) - 1} pieces;", ", ".join(f"{ids[col[q][0]]}{'@' + str(col[q][1]) if col[q][1] >= 0 else ''} {b:.4f}" for q, b in zip(chosen, f.beta)), f"-> {len(nxt) - 1}")
            if nxt == cuts and p >= 2:
                break
            cuts = nxt

        # a level that changes slowly looks like a series of changes in the outside inflow, and the
        # fine pieces take it before the level is tried: the two levels whose means over the pieces
        # follow the pieces' values best are tried in place of pieces, and kept if the row with it,
        # and the pieces it still needs, is clearly better
        if opts.get("level_for_pieces", True) and opts.get("changes") is not False and len(cuts) > 2:
            def fit_on(cols, c):
                f = fit_subset(row_sums(y, Xa[cols], c), list(range(len(cols))))
                return f, bic(f.rss, len(cols) + len(c) - 1)

            def pieces_for(cols, c):
                f, _ = fit_on(cols, c)
                return pelt(y - (f.beta @ Xa[cols] if cols else 0), min_piece, 1)

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

                tries = sorted((j for j in allowed if j not in chosen and col[j][1] < 0), key=lambda j: -follows(j))[:2]
                best = None
                for j in tries:
                    cols = chosen + [j]
                    c = pieces_for(cols, pieces_for(cols, [0, T]))
                    sc = fit_on(cols, c)[1]
                    if sc < cur - log_t and (best is None or sc < best[2]):
                        best = (cols, c, sc)
                if best is None:
                    break
                if opts.get("trace") == sid:
                    print(f"  {sid}: {ids[col[best[0][-1]][0]]} in place of pieces: {len(cuts) - 1} -> {len(best[1]) - 1}")
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
            pieces = try_form(cuts, len(cuts) - 1)
            vals = piece_values(y, Xa, chosen, pieces["f"].beta, cuts)
            W = sum(p_["w"] for p_ in vals)
            mean = sum(p_["v"] * p_["w"] for p_ in vals) / W
            sd = math.sqrt(sum(p_["w"] * (p_["v"] - mean) ** 2 for p_ in vals) / W)
            if (pick is constant or abs(mean) > 0.5 * sd) and pieces["sc"] < pick["sc"]:
                pick = pieces
        # each configuration's numbers: the shared one plus the configuration's own
        beta = pick["f"].beta
        coef_l: list[dict] = [{} for _ in range(L)]
        for q, b in zip(chosen, beta):
            j, lab = col[q]
            for c in range(L):
                if lab < 0 or lab == c:
                    coef_l[c][ids[j]] = coef_l[c].get(ids[j], 0.0) + float(b)
        inflow = []
        if pick["cuts"]:
            inflow = [{"from": at(p_["a"]), "to": at(p_["b"] - 1), "value": p_["v"]} for p_ in piece_values(y, Xa, chosen, beta, pick["cuts"])]
        return {"id": sid, "coefL": coef_l, "X": Xa, "col": col, "set": chosen, "beta": beta, "inflow": inflow,
                "cuts": pick["cuts"], "rss": pick["f"].rss, "p": len(chosen) + (len(pick["cuts"]) - 1 if pick["cuts"] else 0)}

    rows = [fit_row(s) for s in range(S)]
    conserve(rows, ids, final, unit, prev, dy, cfg, L, bic, log_t, opts)

    # a row whose numbers conservation changed: its outside inflow's pieces are measured again with
    # the numbers it ends with (the pieces were measured beside the row's own, biased, drain)
    for s, row in enumerate(rows):
        if not row.get("conserved") or not row["cuts"] or opts.get("remeasure") is False:
            continue
        res = dy[s].copy()
        for c in range(L):
            m = cfg == c
            for j, k in row["coefL"][c].items():
                res[m] -= k * prev[ids.index(j)][m]
        row["inflow"] = [{"from": at(p_["a"]), "to": at(p_["b"] - 1), "value": p_["v"]} for p_ in piece_values(res, prev, [], np.zeros(0), row["cuts"])]

    per_label = [read_flows(stocks, [{"id": r["id"], "coef": r["coefL"][c], "inflow": r["inflow"] if c == 0 else []} for r in rows], prev, opts.get("tol", 0.003)) for c in range(L)]
    flows = merge_by_label(per_label, labels, conf[2]) if L > 1 else per_label[0]
    matrix = [{k: v for k, v in r.items() if k not in ("X", "col", "set", "beta")} for r in rows]
    for r in matrix:
        r["coef"] = r["coefL"][0]
    out = {"flows": flows, "matrix": matrix, "method": "identify", "windows": T, "window": 1}
    if L > 1:
        out["eras"] = labels
    return out


def conserve(rows, ids, final, unit, prev, dy, cfg, L, bic, log_t, opts) -> None:
    """Conservation unless the data clearly says otherwise: a stock's drain is what same-unit stocks
    are seen to receive from it (measured, often more precisely, in their rows). Per configuration,
    tested together: setting the drain to what the receivers take must cost the row no more than
    log T in BIC (refitting the rest), or, for a row with a changing inflow (which cannot separate
    its drain from the changes), be within 30%."""
    for s, row in enumerate(rows):
        a = row["id"]
        if a in final:
            continue
        drain = [-(c.get(a) or 0.0) for c in row["coefL"]]
        moves = [sum(r["coefL"][c][a] for r in rows if r["id"] != a and (r["coefL"][c].get(a) or 0) > 0 and unit[r["id"]] == unit[a]) for c in range(L)]
        # a row whose outside inflow changes (in pieces, or one a strategy knows varies: opts
        # "varying_inflow", stock ids) cannot separate its drain from the changes
        changing = (bool(row["cuts"]) and len(row["cuts"]) > 2) or a in (opts.get("varying_inflow") or ())
        cand = [c for c in range(L) if moves[c] > 0 and ((changing and moves[c] > drain[c] and opts.get("trust_receivers") is not False) or drain[c] > moves[c])]
        if not cand:
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
            cuts2 = pelt(y2 - fixed_part, opts.get("min_piece", 5), 1)
        else:
            cuts2 = row["cuts"]
        sums = row_sums(y2, Xf, cuts2)
        fixed = fit_subset(sums, idx).rss
        p2 = len(idx) + (len(cuts2) - 1 if cuts2 else 0)
        slack = opts.get("slack", 0.3)
        if bic(fixed, p2) <= bic(row["rss"], row["p"]) + log_t or (changing and all(abs(drain[c] - moves[c]) / max(drain[c], moves[c]) < slack for c in cand)):
            for c in cand:
                row["coefL"][c][a] = -moves[c]
            row["conserved"] = True


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
