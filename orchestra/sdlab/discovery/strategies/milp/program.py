"""The mixed-integer program (docs/research/milp.md, "Formulation"), solved by HiGHS.

Every candidate is a column: a flow (src -> dst, either end possibly outside) whose amount per step is
v x f[k], f a known series and 0 <= v <= ub z, z binary (the column is in the model):

- a linear term: f = what it reads (the source's level, a link's stock, an input, 1); an estimated
  outside inflow may also read its own stock's level with a negative number (a goal gap, c - k x level);
- with announced eras, an era's change of a term: f = the term's series in that era (0 elsewhere), v
  signed, and the term's rate in the era (base + change) never negative;
- a capacity-limited flow MIN(a x src, b x cap) at threshold theta = b / a: f = MIN(src, theta x cap)
  and v = a. A MIN's regime (which side is the lesser at step k) is a threshold on src / cap (the
  demand is the lesser exactly when src[k] / cap[k] <= theta), so a per-step regime binary with its
  big-M links is the same as choosing theta among the gaps between the sorted ratios; the program
  chooses it among GRID of them (a group: at most one theta per MIN flow), and the refit then frees it.

On the steps K the program reads, for every stock s and step k:

    dy[s,k] = sum_columns sign(col, s) v_col f_col[k] + p[s,k] - n[s,k],   p, n >= 0

Objective: the Laplace -2 log likelihood of the changes (sum 2 |e| / scale, scaled up to the whole
run when K is a sample of its steps) + log T per number (a MIN has two) + CLAIM_PRICE log T per
outside flow where no boundary is declared. HiGHS solves mixed-integer *linear* programs, so the
misfit is absolute; the least-squares refit (refit.py) comes after, on every step.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import highspy
import numpy as np
from scipy.sparse import coo_matrix

CLAIM_PRICE = 2.0     # an outside flow where no boundary is declared pays this many log T beyond its numbers (as matrix's boundary.py)
INF = highspy.kHighsInf
NODES = 100           # branch-and-bound nodes per solve (deterministic, unlike the time limit; the root alone often uses the time on a slow machine)
HEURISTICS = 0.05     # HiGHS's share of MIP effort on primal heuristics (its default; more stalls at the root)


@dataclass
class Column:
    src: str | None
    dst: str | None
    f: np.ndarray            # the series the number multiplies (every step)
    ub: float
    numbers: float           # BIC price: this many log T
    group: tuple | None      # at most one column of a group (a MIN flow's thresholds)
    claim: tuple | None      # the outside flow it is part of (priced once where no boundary is declared)
    what: tuple              # ("term", reader), ("neg", reader), ("era", reader, era) or ("min", cap, theta)
    signed: bool = False     # -ub z <= v <= ub z (an era's change of a rate)
    base: int | None = None  # the column whose rate this one changes in its era: their sum is never negative


def solve(ids: list[str], dy: np.ndarray, cols: list[Column], K: np.ndarray, scale: np.ndarray, T: int,
          claim: bool, time_limit: float, gap: float, start: list | None = None, near: int | None = None,
          forced: list | None = None) -> dict:
    """The program on steps K (dy: stocks x every step; scale: stocks x K); the chosen columns with
    their numbers, and the solver's report."""
    S, nK, nc = len(ids), len(K), len(cols)
    logT = math.log(max(T, 2))
    pos = {s: i for i, s in enumerate(ids)}
    claims = sorted({c.claim for c in cols if claim and c.claim is not None}, key=str)
    cl = {k: i for i, k in enumerate(claims)}
    groups = sorted({c.group for c in cols if c.group is not None}, key=str)
    # columns: v (nc), z (nc), claim binaries, p (S nK), n (S nK)
    o_z, o_c = nc, 2 * nc
    o_p = o_c + len(claims)
    o_n = o_p + S * nK
    ncol = o_n + S * nK
    w = (2.0 * (T / nK) / scale).ravel()
    cost = np.concatenate([np.zeros(nc), [logT * c.numbers for c in cols], np.full(len(claims), CLAIM_PRICE * logT), w, w])
    lo = np.zeros(ncol)
    lo[:nc] = [-c.ub if c.signed else 0.0 for c in cols]
    hi = np.concatenate([[c.ub for c in cols], np.ones(nc + len(claims)), np.full(2 * S * nK, INF)])
    integ = np.concatenate([np.zeros(nc), np.ones(nc + len(claims)), np.zeros(2 * S * nK)])
    R, C, V, rlo, rhi = [], [], [], [], []
    # balance rows (s, k): r = s nK + k
    for j, c in enumerate(cols):
        fk = c.f[K]
        for end, sign in ((c.src, -1.0), (c.dst, 1.0)):
            if end in pos:
                R.append(pos[end] * nK + np.arange(nK))
                C.append(np.full(nK, j))
                V.append(sign * fk)
    R.append(np.arange(S * nK)); C.append(o_p + np.arange(S * nK)); V.append(np.ones(S * nK))
    R.append(np.arange(S * nK)); C.append(o_n + np.arange(S * nK)); V.append(-np.ones(S * nK))
    b = dy[:, K].ravel()
    rlo.append(b); rhi.append(b)
    r = S * nK
    # v <= ub z
    R += [r + np.arange(nc)] * 2
    C += [np.arange(nc), o_z + np.arange(nc)]
    V += [np.ones(nc), -np.array([c.ub for c in cols])]
    rlo.append(np.full(nc, -INF)); rhi.append(np.zeros(nc))
    r += nc
    # signed: v >= -ub z; an era's change: base + change >= 0
    for j, c in enumerate(cols):
        if c.signed:
            R += [np.array([r, r])]; C += [np.array([j, o_z + j])]; V += [np.array([1.0, c.ub])]
            rlo.append([0.0]); rhi.append([INF])
            r += 1
        if c.base is not None:
            R += [np.array([r, r])]; C += [np.array([j, c.base])]; V += [np.array([1.0, 1.0])]
            rlo.append([0.0]); rhi.append([INF])
            r += 1
    # a declared outside flow is a given: at least one of its plain columns is in the model
    for key in forced or []:
        js = [j for j, c in enumerate(cols) if (c.src, c.dst) == key and not c.signed]
        if js:
            R.append(np.full(len(js), r)); C.append(o_z + np.array(js)); V.append(np.ones(len(js)))
            rlo.append([1.0]); rhi.append([INF])
            r += 1
    # local branching (Fischetti and Lodi 2003): at most `near` switches flipped from the start's
    if start and near is not None:
        centre = {(c.src, c.dst, c.what) for c, _ in start}
        on = np.array([(c.src, c.dst, c.what) in centre for c in cols])
        R.append(np.full(nc, r)); C.append(o_z + np.arange(nc)); V.append(np.where(on, -1.0, 1.0))
        rlo.append([-INF]); rhi.append([float(near - on.sum())])
        r += 1
    # z <= its claim
    for j, c in enumerate(cols):
        if c.claim in cl:
            R += [np.array([r, r])]; C += [np.array([o_z + j, o_c + cl[c.claim]])]; V += [np.array([1.0, -1.0])]
            rlo.append([-INF]); rhi.append([0.0])
            r += 1
    # at most one of a group
    for g in groups:
        js = [j for j, c in enumerate(cols) if c.group == g]
        if len(js) > 1:
            R.append(np.full(len(js), r)); C.append(o_z + np.array(js)); V.append(np.ones(len(js)))
            rlo.append([-INF]); rhi.append([1.0])
            r += 1
    R, C, V = np.concatenate(R), np.concatenate(C), np.concatenate(V)
    rlo, rhi = np.concatenate([np.asarray(x, float) for x in rlo]), np.concatenate([np.asarray(x, float) for x in rhi])
    keep = V != 0
    A = coo_matrix((V[keep], (R[keep], C[keep])), shape=(r, ncol)).tocsc()
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = ncol, r
    lp.col_cost_, lp.col_lower_, lp.col_upper_ = cost, lo, hi
    lp.row_lower_, lp.row_upper_ = rlo, rhi
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_ = A.indptr.astype(np.int32)
    lp.a_matrix_.index_ = A.indices.astype(np.int32)
    lp.a_matrix_.value_ = A.data.astype(float)
    lp.a_matrix_.num_col_, lp.a_matrix_.num_row_ = ncol, r
    lp.integrality_ = [highspy.HighsVarType.kInteger if i else highspy.HighsVarType.kContinuous for i in integ]
    h = highspy.Highs()
    h.setOptionValue("output_flag", bool(__import__("os").environ.get("MILP_HIGHS_LOG")))
    h.setOptionValue("threads", 1)
    h.setOptionValue("random_seed", 0)
    h.setOptionValue("time_limit", float(time_limit))
    h.setOptionValue("mip_rel_gap", float(gap))
    h.setOptionValue("mip_heuristic_effort", HEURISTICS)
    if NODES:
        h.setOptionValue("mip_max_nodes", int(NODES))
    h.passModel(lp)
    if start:                                                   # a feasible start: the last solve's columns that are offered again
        x0 = np.zeros(ncol)
        want = {(c.src, c.dst, c.what): v for c, v in start}
        for j, c in enumerate(cols):
            v = want.get((c.src, c.dst, c.what))
            if v is not None:
                x0[j], x0[o_z + j] = min(v, c.ub), 1.0
                if c.claim in cl:
                    x0[o_c + cl[c.claim]] = 1.0
        e = (b - A[:S * nK, :nc] @ x0[:nc])
        x0[o_p:o_p + S * nK], x0[o_n:o_n + S * nK] = np.maximum(e, 0), np.maximum(-e, 0)
        sol = highspy.HighsSolution()
        sol.col_value = list(x0)
        h.setSolution(sol)
    began = time.perf_counter()
    h.run()
    took = time.perf_counter() - began
    info = h.getInfo()
    status = h.modelStatusToString(h.getModelStatus())
    x = np.array(h.getSolution().col_value) if info.primal_solution_status else None
    rep = {"status": status, "seconds": round(took, 3), "gap": float(info.mip_gap), "objective": float(info.objective_function_value),
           "bound": float(info.mip_dual_bound), "nodes": int(info.mip_node_count), "columns": int(ncol), "rows": int(r), "binaries": int(integ.sum()), "found": x is not None}
    chosen = [] if x is None else [(c, float(x[j])) for j, c in enumerate(cols) if x[o_z + j] > 0.5 and x[j] != 0]
    return {"chosen": chosen, "report": rep}
