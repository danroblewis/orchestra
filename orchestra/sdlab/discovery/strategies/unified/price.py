"""The prices of code table v1 (unified-design.md, 4.1 and 4.3), committed before any objective-test
result was read. A change is a new CODE_TABLE version, re-run on every set.

P_num = sum_j 1/2 ln N_j over the structural numbers j, N_j the reports of the measured stocks whose
one-step mean number j moves (its flow's from, to and `uses` stocks; a hidden stock stands for the
measured stocks one flow away from it), counted only over the grid steps where j acts (a schedule
segment's value: its own steps). The noise character eta has the same slots in every model on a cell,
so its price cancels and is left out.

P_struct is the prefix code of the table in section 4.3, with gamma(n) the Elias-gamma length in nats.
"""

from __future__ import annotations

import math

import numpy as np

from .frontend import Grid, Structure

CODE_TABLE = "v1"
EPSILON = 0.5          # the tie band of J, nats
N_KINDS = 7            # base-term kinds in the grammar


def gamma(n: int) -> float:
    n = max(1, int(n))
    return (2 * math.floor(math.log2(n)) + 1) * math.log(2)


def _measured_for(st: Structure, stocks: tuple) -> set[int]:
    """The measured stocks (indices) a number on these stocks moves; hidden ones stand for their
    measured neighbours."""
    Sm = st.n_measured
    idx = {s: i for i, s in enumerate(st.ids)}
    out: set[int] = set()
    for s in stocks:
        i = idx.get(s)
        if i is None:
            continue
        if i < Sm:
            out.add(i)
            continue
        for f in st.flows:
            ends = {f.get("from"), f.get("to")} | {u.get("stock") for u in f.get("uses") or []}
            reads = {(f.get("rate") or {}).get("stock")}
            if s in ends or s in reads:
                out |= {idx[x] for x in ends | reads if x in idx and idx[x] < Sm}
    return out


def n_of_slots(st: Structure, grid: Grid) -> np.ndarray:
    """N_j for every slot."""
    rep = np.isfinite(grid.y)
    rep[0] = False                                       # the first report is not scored
    total = int(rep.sum())
    out = []
    for sl in st.slots:
        ms = _measured_for(st, sl.stocks)
        if not ms:
            out.append(max(1, total))
            continue
        rows = rep if sl.steps is None else rep[sl.steps]
        out.append(max(1, int(rows[:, sorted(ms)].sum())))
    return np.array(out, dtype=float)


def p_num(st: Structure, grid: Grid) -> float:
    return float(0.5 * np.log(n_of_slots(st, grid)).sum())


def p_struct(st: Structure) -> dict:
    """The structure code, itemised (nats)."""
    s = st.struct
    S, U, T, F, H = s["S"], s["U"], max(1, s["T"]), s["F"], s["H"]
    items = {
        "flows": gamma(F + 1),
        "endpoints": F * math.log((S + 1) ** 2),
        "two_way": F * math.log(2),
        "term_kinds": sum(s["terms"]) * math.log(N_KINDS),
        "term_readers": sum(s["readers"]) * math.log(max(2, S + U)),
        "terms_per_flow": sum(gamma(n) for n in s["terms"]),
        "effects": sum(math.log(max(2, S + U)) + gamma(K - 1) for _, K in s["effects"]),
        "uses": s["uses"] * math.log(max(2, S)),
        "hidden": gamma(H + 1) + H * gamma(1),
        "scheduled": s["scheduled"] * math.log(s["n_coef"] + 1),
        "cuts": sum(gamma(m + 1) + _log_choose(T - 1, m) for m in s["unannounced_cuts"]),
        "substeps": math.log(3),
    }
    items["total"] = float(sum(items.values()))
    return items


def _log_choose(n: int, k: int) -> float:
    if k <= 0 or n <= 0:
        return 0.0
    k = min(k, n)
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def complexity(st: Structure) -> dict:
    """What a model has (for the report and the E subtypes)."""
    s = st.struct
    return {"flows": s["F"], "numbers": st.P, "hidden": s["H"], "scheduled": s["scheduled"],
            "cuts": int(sum(s["unannounced_cuts"]) + s["announced_cuts"]), "effects": len(s["effects"]),
            "uses": s["uses"]}
