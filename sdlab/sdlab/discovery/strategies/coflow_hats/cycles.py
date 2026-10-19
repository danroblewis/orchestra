"""A link whose strength follows a cycle: S's inflow k(phase) x X, k repeating every P steps.

Posts follow users through the day: the link from X into S is stronger by day than at night. Fitted
with one coefficient it is averaged, and S's drain is read wrong to make up for it (the misfit is
periodic, and S lags it). Here, for a row whose one-step residual under the model, or after its levels
alone, repeats (candidate periods from the shared periodic.candidates, on the residual's fold), and each other stock X, S's
change is regressed on X split by phase (one coefficient per phase of P) beside S's own level and a
constant; the per-phase coefficients are cut into a few phase segments (periodic.segment_profile,
each segment paying its value and its position), and those segments' coefficients refitted. The
candidate replaces the row's outside flows (its inflow and any link into it) with the cyclic link as
eras of the flow (`byTime`, one segment per phase stretch over the run; the joint refit fits one
number per phase segment, joint.py), and the rest is refitted by the caller; a move into S from
another stock is also offered as that stock's drain. The price counts the profile: a number per segment value, per cut and for the period
(`cycle` on the flow, read by price.size).
"""

from __future__ import annotations

import numpy as np

from ...periodic import candidates, phase_labels, segment_profile
from ...simulate import Model


def _residual(flows: list[dict], ids: list[str], prev: np.ndarray, dy: np.ndarray, tt: np.ndarray) -> np.ndarray:
    with np.errstate(all="ignore"):
        moved = Model(flows, ids).step(prev, tt) - prev
    return np.nan_to_num(dy - moved)


def cycle_candidates(flows: list[dict], ids: list[str], prev: np.ndarray, dy: np.ndarray, tt: np.ndarray,
                     most_periods: int = 2) -> list[list[dict]]:
    """Models with one row's outside flows replaced by a cyclic link from another stock (unfitted
    otherwise): [flows]."""
    if any(f.get("byTime") for f in flows) or prev.shape[1] < 60:
        return []
    S, T = prev.shape
    res = _residual(flows, ids, prev, dy, tt)
    # and what each row leaves after its levels and a constant alone (a model's inflow pieces can
    # follow the cycle, leaving nothing that repeats)
    L = np.column_stack([prev.T, np.ones(T)])
    plain = dy - (L @ np.linalg.lstsq(L, dy.T, rcond=None)[0]).T
    out = []
    for s in range(S):
        periods = list(dict.fromkeys(P for P in candidates([res[s]]) + candidates([plain[s]]) if 2 <= P <= T // 4))[:most_periods]
        for P in periods:
            for x in range(S):
                if x == s or np.ptp(prev[x]) <= 0 and float(np.mean(prev[x])) <= 0:
                    continue
                out += _cyclic_link(flows, ids, prev, dy, tt, s, x, P)
    return out


def _cyclic_link(flows, ids, prev, dy, tt, s, x, P) -> list[list[dict]]:
    S, T = prev.shape
    ph = np.arange(T) % P
    own = [prev[s], np.ones(T)]
    # one coefficient per phase on X, beside the row's own level and a constant
    A = np.column_stack([prev[x] * (ph == p) for p in range(P)] + own)
    try:
        theta, *_ = np.linalg.lstsq(A, dy[s], rcond=None)
    except np.linalg.LinAlgError:
        return []
    r = dy[s] - A @ theta
    sigma2 = float(np.mean(r ** 2))
    x2 = float(np.mean(prev[x] ** 2))
    if x2 <= 0:
        return []
    # each step's implied coefficient, so the fold's means are the per-phase coefficients
    k_t = theta[:P][ph]
    segs = segment_profile(k_t, P, max(1e-12, sigma2 / x2))
    if len(segs) < 2:
        return []
    lab = phase_labels(T, P, segs)
    B = np.column_stack([prev[x] * (lab == q) for q in range(len(segs))] + own)
    try:
        beta, *_ = np.linalg.lstsq(B, dy[s], rcond=None)
    except np.linalg.LinAlgError:
        return []
    ks = beta[: len(segs)]
    if np.any(ks <= 0):
        return []
    sid, xid = ids[s], ids[x]
    # eras over the run: a segment of the flow for every stretch of steps in one phase segment
    eras, a = [], 0
    for b in range(1, T + 1):
        if b == T or lab[b] != lab[a]:
            eras.append({"from": int(tt[a]), "to": int(tt[b - 1]), "seg": int(lab[a]),
                         "rate": {"form": "proportional", "stock": xid, "k": float(ks[lab[a]])}})
            a = b
    link = {"from": None, "to": sid, "ratio": 1, "rate": eras[0]["rate"], "byTime": eras, "driver": xid,
            "cycle": {"period": P, "stock": xid, "segments": [[int(u), int(v)] for u, v in segs]}}
    # the row's outside inflow (pieces or a constant) and any link into it give way to the cyclic link
    keep = [f for f in flows if not (f.get("from") is None and f.get("to") == sid)]
    # the row's own drain, if the model has none (started from the regression)
    if not any(f.get("from") == sid and f.get("to") is None for f in keep) and beta[len(segs)] < 0:
        keep.append({"from": sid, "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": sid, "k": float(-beta[len(segs)])}})
    # a move into S from another stock may have been S's misfit's share of that stock's drain: also
    # offered as a drain of its source; a move from X at k x X beside the cyclic link reading X is the
    # same inflow into S counted twice (the link's numbers absorb it), so it is only offered as a drain
    moves = [q for q, f in enumerate(keep) if f.get("to") == sid and f.get("from") in ids and not f.get("uses")]
    same = [q for q in moves if keep[q].get("from") == xid and (keep[q].get("rate") or {}).get("form") == "proportional"
            and keep[q]["rate"].get("stock") == xid and not keep[q].get("effects")]
    out = [] if same else [keep + [link]]
    if moves:
        out.append([{**f, "to": None} if q in moves else f for q, f in enumerate(keep)] + [link])
    return out
