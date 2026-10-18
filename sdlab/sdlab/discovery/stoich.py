"""Reading the matrix as stoichiometry x rate laws: moves paced by a third stock, and gap inflows.

The matrix's rows are exactly a stoichiometry times rate laws: a move A -> B whose rate reads a third
stock C (B is resolved at 0.5 x agents) is -k in A's entry for C and +k in B's. `flows.read_flows`
reads only moves proportional to their source, so it reads that pair as "A drains faster when C is
high" (an outflow to outside) and a link from C into B: two numbers with no conservation, and a model
that keeps filling B when A is empty. Here:

  - a negative entry in A for driver C, and positive entries for C in same-unit rows B1.. (C neither
    A nor a B), are refitted on the steps where A held clearly more than the move takes (where A ran
    low the move was cut to what A held, which biases both rows); if A's loss and the Bs' gains then
    sum to zero within 2 standard errors they are one move A -> Bi at a linear rate in C;
  - the matched rows' numbers are made to sum to zero exactly (a generalised least squares
    projection: each row's numbers move by their covariance with C's), and those numbers replace the
    rows' own;
  - the move's own proportional part (A's drain into B) joins its rate, and optionally a reverse
    "move" B -> A (A's row gaining from B) joins it as a negative term: a gap on the destination;
  - optionally, a stock's unmatched negative cross terms beside a positive outside inflow become one
    linear inflow (c - k x C, floored at 0): a gap on another stock, not an outflow.
"""

from __future__ import annotations

import itertools

import numpy as np

from .flows import merge_by_label, r4, read_flows


def _wdemean(a: np.ndarray, cuts: list[int] | None, w: np.ndarray) -> np.ndarray:
    """a (columns x steps, or steps) with each piece's weighted mean taken out."""
    if not cuts:
        return a
    out = a.astype(float).copy()
    for lo, hi in zip(cuts[:-1], cuts[1:]):
        ws = w[lo:hi].sum()
        if ws > 0:
            out[..., lo:hi] -= (a[..., lo:hi] * w[lo:hi]).sum(axis=-1, keepdims=True) / ws
    return out


def masked_fit(fit: dict, s: int, mask: np.ndarray, drop: int | None = None) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Row s refitted on the steps in mask (its columns and pieces kept, but the columns of level
    `drop` set to 0): its numbers (in the order of its chosen columns), their covariance, and the
    refit's BIC on those steps. A row whose own drain conservation fixed keeps it fixed (its own
    columns move by nothing)."""
    row, cfg, prev = fit["rows"][s], fit["cfg"], fit["prev"]
    cols = list(row["set"])
    y = fit["dy"][s].astype(float)
    fixed = [i for i, q in enumerate(cols) if row.get("conserved") and row["col"][q][0] == s and drop != s]
    if fixed:
        own = np.array([row["coefL"][c].get(row["id"], 0.0) for c in range(len(fit["labels"]))])
        y = y - own[cfg] * prev[s]
    gone = [i for i, q in enumerate(cols) if i not in fixed and row["col"][q][0] == drop]
    free = [i for i in range(len(cols)) if i not in fixed and i not in gone]
    w = mask.astype(float)
    pieces = len(row["cuts"]) - 1 if row["cuts"] else 0
    dof = w.sum() - len(free) - pieces
    if dof < 10:
        return None
    beta = np.array(row["beta"], dtype=float).copy()
    beta[gone] = 0.0
    V = np.zeros((len(cols), len(cols)))
    yc = _wdemean(y, row["cuts"], w)
    rss = float((yc ** 2 * w).sum())
    if free:
        X = _wdemean(row["X"][[cols[i] for i in free]], row["cuts"], w)
        G = (X * w) @ X.T
        G += 1e-9 * np.diag(np.abs(np.diag(G)) + 1)
        inv = np.linalg.pinv(G)
        b = inv @ ((X * w) @ yc)
        rss = float(((yc - b @ X) ** 2 * w).sum())
        beta[free] = b
        V[np.ix_(free, free)] = inv * rss / dof
    n = w.sum()
    return beta, V, float(n * np.log(max(rss, 1e-12) / n) + len(free) * np.log(n)), drop


def _a(row: dict, j: int, c: int) -> np.ndarray:
    """Which of a row's chosen columns make up its number for level j in configuration c."""
    return np.array([1.0 if row["col"][q][0] == j and (row["col"][q][1] < 0 or row["col"][q][1] == c) else 0.0 for q in row["set"]])


def match(fit: dict, stocks: list[dict], tol: float = 0.003, z: float = 2.0, max_receivers: int = 3, room: float = 2.0) -> list[dict]:
    """Groups {c, j, A, Bs, fits}: in configuration c, A's negative entry for driver j matched by the
    positive entries of same-unit rows Bs (j neither A nor any B), their sum zero within z SE when
    the rows are refitted on the steps where A held at least `room` times what the move takes (with
    or without A's own columns: the closer match)."""
    rows, ids, prev, cfg = fit["rows"], fit["ids"], fit["prev"], fit["cfg"]
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    S, L = len(ids), len(fit["labels"])
    groups = []
    for c in range(L):
        for j in range(S):
            val = {s: rows[s]["coefL"][c].get(ids[j], 0.0) for s in range(S) if s != j}
            used: set[int] = set()
            for A in sorted((s for s in val if val[s] < -tol), key=lambda s: val[s]):
                gain = [s for s in val if val[s] > tol and s != A and s not in used and unit[ids[s]] == unit[ids[A]]]
                if not gain:
                    continue
                mask = prev[A] >= room * (-val[A]) * np.maximum(prev[j], 0)
                if L > 1:
                    mask &= cfg == c
                # with and without A's own columns (where A ran low, the cut-off move looks like a
                # drain of A, in A's row and the receivers'): the reading that matches best
                best = None
                for drop in (None, A):
                    fits = {s: masked_fit(fit, s, mask, drop) for s in [A, *gain]}
                    if any(f is None for f in fits.values()):
                        break
                    num = {s: float(_a(rows[s], j, c) @ fits[s][0]) for s in fits}
                    var = {s: float(_a(rows[s], j, c) @ fits[s][1] @ _a(rows[s], j, c)) for s in fits}
                    for n in range(1, min(max_receivers, len(gain)) + 1):
                        for Bs in itertools.combinations([b for b in gain if num[b] > 0], n):
                            miss = abs(num[A] + sum(num[b] for b in Bs))
                            se = (var[A] + sum(var[b] for b in Bs)) ** 0.5
                            if num[A] < 0 and miss <= z * se and (best is None or miss / max(se, 1e-12) < best[0]):
                                best = (miss / max(se, 1e-12), Bs, fits)
                if best:
                    used.update(best[1])
                    groups.append({"c": c, "j": j, "A": A, "Bs": list(best[1]), "fits": {s: best[2][s] for s in [A, *best[1]]}, "mask": mask})
    return groups


def constrain(fit: dict, groups: list[dict]) -> list[list[dict]]:
    """Per row and configuration, the numbers after each group's joint refit: the group's rows take
    their refitted numbers, projected so that the group's entries sum to zero (generalised least
    squares with the rows' noise independent); a row in several groups takes each one's change."""
    rows, ids = fit["rows"], fit["ids"]
    L = len(fit["labels"])
    coef = [[dict(r["coefL"][c]) for c in range(L)] for r in rows]
    for g in groups:
        members = [g["A"], *g["Bs"]]
        a = {s: _a(rows[s], g["j"], g["c"]) for s in members}
        beta = {s: g["fits"][s][0] for s in members}
        V = {s: g["fits"][s][1] for s in members}
        total = sum(float(a[s] @ beta[s]) for s in members)
        den = sum(float(a[s] @ V[s] @ a[s]) for s in members)
        lam = total / den if den > 0 else 0.0
        for s in members:
            new = beta[s] - (V[s] @ a[s]) * lam
            dropped = g["fits"][s][3]
            for q, dq in zip(rows[s]["set"], new - np.asarray(rows[s]["beta"], dtype=float)):
                jj, lab = rows[s]["col"][q]
                if jj == dropped:
                    for cc in range(L):
                        coef[s][cc].pop(ids[jj], None)
                    continue
                if dq == 0:
                    continue
                for cc in range(L):
                    if lab < 0 or lab == cc:
                        coef[s][cc][ids[jj]] = coef[s][cc].get(ids[jj], 0.0) + float(dq)
    return coef



def remeasure(fit: dict, coef: list[list[dict]], groups: list[dict]) -> list[list[dict]]:
    """Each row's outside inflow pieces; a row in a group measured again with the numbers it ends
    with (as the main line does after conservation), on the steps its groups' sources held enough
    (where a source ran low the move was cut, and the cut would read as more arriving)."""
    rows, ids, prev, dy, cfg, at = fit["rows"], fit["ids"], fit["prev"], fit["dy"], fit["cfg"], fit["at"]
    masks: dict[int, np.ndarray] = {}
    for g in groups:
        for s in (g["A"], *g["Bs"]):
            masks[s] = masks.get(s, np.ones(len(at), bool)) & (g["mask"] | (cfg != g["c"]))
    out = []
    for s, r in enumerate(rows):
        if s not in masks or not r["cuts"]:
            out.append(r["inflow"])
            continue
        res = dy[s].astype(float).copy()
        for c in range(len(fit["labels"])):
            m = cfg == c
            for j, k in coef[s][c].items():
                res[m] -= k * prev[ids.index(j)][m]
        pieces = []
        for a, b in zip(r["cuts"][:-1], r["cuts"][1:]):
            m = masks[s][a:b]
            pieces.append({"from": at[a], "to": at[b - 1], "value": float(res[a:b][m].mean() if m.sum() >= 3 else res[a:b].mean())})
        out.append(pieces)
    return out


def _linear(terms: dict[str, float], c: float = 0.0) -> dict:
    return {"form": "linear", "c": r4(c), "terms": [{"stock": s, "k": r4(k)} for s, k in terms.items()]}


def _flow(src, dst, rate: dict, means: dict, **extra) -> dict:
    per = rate.get("c", 0) + sum(t["k"] * means.get(t["stock"], 0.0) for t in rate["terms"])
    return {"from": src, "to": dst, "ratio": 1, "rate": rate, "rates": [rate], "perStep": per, "nearly": [], "bothWays": False, **extra}


def paced_flows(fit: dict, stocks: list[dict], tol: float = 0.003, destination: bool = False, gaps=False,
                groups: list[dict] | None = None) -> tuple[list[dict], dict]:
    """The flows read with paced moves (and, optionally, gaps on the destination and gap inflows),
    and what was changed ({"moves", "destination", "gaps"}). gaps: True for every gap inflow there
    is, or the pairs "A<C" (A's inflow falls as C rises) to read so."""
    rows, ids, prev = fit["rows"], fit["ids"], fit["prev"]
    L = len(fit["labels"])
    if groups is None:
        groups = match(fit, stocks, tol)
    coef = constrain(fit, groups) if groups else [[dict(r["coefL"][c]) for c in range(L)] for r in rows]
    inflows = remeasure(fit, coef, groups)
    means = {i: float(prev[k].mean()) for k, i in enumerate(ids)}
    paced: list[dict[tuple, dict]] = [{} for _ in range(L)]
    for g in groups:
        c, C = g["c"], ids[g["j"]]
        A = ids[g["A"]]
        coef[g["A"]][c].pop(C, None)
        for b in g["Bs"]:
            k = coef[b][c].pop(C, 0.0)
            if k > tol:
                paced[c].setdefault((A, ids[b]), {})[C] = k
    info = {"moves": sorted({f"{a}>{b}" for p in paced for a, b in p}), "destination": [], "gaps": []}
    per_label = []
    for c in range(L):
        fl = read_flows(stocks, [{"id": r["id"], "coef": coef[s][c], "inflow": inflows[s] if c == 0 else []} for s, r in enumerate(rows)], prev, tol)
        for (A, B), terms in paced[c].items():
            terms = dict(terms)
            for i, f in enumerate(fl):
                if f.get("from") == A and f.get("to") == B and not f.get("driver") and f["rate"]["form"] == "proportional":
                    terms = {A: f["rate"]["k"], **terms}
                    fl.pop(i)
                    break
            if destination:
                for i, f in enumerate(fl):
                    if f.get("from") == B and f.get("to") == A and not f.get("driver") and f["rate"]["form"] == "proportional":
                        terms[B] = -f["rate"]["k"]
                        fl.pop(i)
                        info["destination"].append(f"{A}>{B}")
                        break
            fl.append(_flow(A, B, _linear(terms), means, paced=True))
        per_label.append(fl)
    flows = merge_by_label(per_label, fit["labels"], fit["spans"]) if L > 1 else per_label[0]
    if gaps:
        flows = _gap_inflows(flows, fit, coef, inflows, tol, means, info, None if gaps is True else set(gaps))
    return flows, info


def _gap_inflows(flows: list[dict], fit: dict, coef: list[list[dict]], inflows: list[list[dict]], tol: float, means: dict, info: dict, only: set | None) -> list[dict]:
    """A stock A's unmatched negative cross terms (each driver C) beside its positive outside
    inflow, read as one inflow c - k x C (c following the inflow's pieces, k the configuration's).
    only: the pairs "A<C" to read so (None: every one); info["gaps"] lists the pairs read."""
    rows, ids, cfg, at = fit["rows"], fit["ids"], fit["cfg"], fit["at"]
    L = len(fit["labels"])
    for s, r in enumerate(rows):
        A, pieces = ids[s], inflows[s]
        if not pieces:
            continue
        W = sum(g["to"] - g["from"] + 1 for g in pieces)
        if sum(g["value"] * (g["to"] - g["from"] + 1) for g in pieces) / max(1, W) <= tol:
            continue
        Cs = sorted({j for c in range(L) for j, k in coef[s][c].items() if j != A and k < -tol})
        Cs = [C for C in Cs if all(coef[s][c].get(C, 0.0) <= tol for c in range(L)) and (only is None or f"{A}<{C}" in only)]
        if not Cs:
            continue
        # every step's rate: the piece in force and the configuration's numbers
        froms = np.array([g["from"] for g in pieces])
        vals = [g["value"] for g in pieces]
        segs = []
        for k, time in enumerate(at):
            v = vals[max(0, int(np.searchsorted(froms, time, side="right")) - 1)]
            rate = _linear({C: min(0.0, coef[s][cfg[k]].get(C, 0.0)) for C in Cs}, v)
            if segs and segs[-1]["rate"] == rate:
                segs[-1]["to"] = time
            else:
                segs.append({"from": time, "to": time, "rate": rate})
        drop = lambda f: (f.get("to") == A and not f.get("from") and f.get("inflow")) or (  # noqa: E731
            f.get("from") == A and not f.get("to") and f.get("driver") in Cs and f["rate"]["form"] == "linear")
        flows = [f for f in flows if not drop(f)]
        flows.append(_flow(None, A, segs[0]["rate"], means, byTime=segs, rates=[g["rate"] for g in segs], driver=Cs[0], note=f"{A}'s inflow falls as {', '.join(Cs)} rises"))
        info["gaps"].extend(f"{A}<{C}" for C in Cs)
    return flows
