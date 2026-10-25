"""Co-flows found where the used stock runs dry.

A flow that uses up another stock as it moves (a co-flow: `per` of C for each unit moved) cannot
move more than C holds. While C is dry the flow is cut to what C holds, so its source A piles up and
A's row, fitted through both regimes, gets a drain a fraction of the truth (the inflow pieces absorb
the rest). Fitted only on the steps where C is not dry, the rows are linear again: A drains at its
rate k, and C's row shows the co-flow as a cross term "C drains faster when A is high" at per x k.
That term, read as `uses` on A's outflow, lets the simulator apply the cap itself.

    stocks_running_dry(levels)     the stocks that might be used up: low for a while
    starved_steps(...)             the steps where C held less than its users wanted
    as_coflows(...)                cross terms -> `uses` on the source's outflow, checked against A's
                                   residual on C's dry steps (per from the cross term, or from what
                                   the flow moved where the cap bound)
    fill_gaps, remeasure_inflows   outside inflows over the steps left out: measured again on every
                                   step with the found model's capped flows run one step

Used by the strategy `starved_coflows` (experiment docs/research/starved-coflows.md).
"""

from __future__ import annotations

import numpy as np

from .changes import pelt
from .simulate import Model


def stocks_running_dry(lv: np.ndarray, ids: list[str], low: float = 0.1, min_share: float = 0.01, min_steps: int = 5) -> list[str]:
    """Stocks whose level at the start of a step falls below `low` x their median on at least
    `min_share` of the steps (and `min_steps` steps): the candidates for a stock that runs dry."""
    out = []
    prev = lv[:, :-1]
    for k, i in enumerate(ids):
        med = float(np.median(prev[k]))
        if med <= 0:
            continue
        n = int((prev[k] < low * med).sum())
        if n >= max(min_steps, min_share * prev.shape[1]):
            out.append(i)
    return out


def first_mask(lv: np.ndarray, ids: list[str], used: list[str], low: float = 0.1) -> np.ndarray:
    """Steps (index i: from level i to i + 1) where any used stock starts below `low` x its median."""
    prev = lv[:, :-1]
    m = np.zeros(prev.shape[1], bool)
    for c in used:
        k = ids.index(c)
        m |= prev[k] < low * float(np.median(prev[k]))
    return m


def demand(rows: list[dict], ids: list[str], prev: np.ndarray, c: str, users: set[str] | None = None) -> np.ndarray:
    """What C's row says other stocks take from it each step: the sum of its negative cross terms
    (per x k x level of A, for A among `users` when given), per step."""
    row = next(r for r in rows if r["id"] == c)
    need = np.zeros(prev.shape[1])
    for j, k in row["coef"].items():
        if j != c and k < 0 and (users is None or j in users):
            need += -k * prev[ids.index(j)]
    return need


def starved_steps(lv: np.ndarray, ids: list[str], rows: list[dict], c: str, margin: float = 1.5,
                  users: set[str] | None = None) -> np.ndarray | None:
    """Steps where C held less than `margin` x what its users want (by the rows fitted on the steps
    where it did not run dry); None when C's row shows no users."""
    prev = lv[:, :-1]
    need = demand(rows, ids, prev, c, users)
    return prev[ids.index(c)] < margin * need if need.any() else None


def row_residual(row: dict, ids: list[str], prev: np.ndarray, dy: np.ndarray, t: list) -> np.ndarray:
    """A's change minus what its row (levels and outside inflow) says, at every step."""
    s = ids.index(row["id"])
    fit = np.zeros(prev.shape[1])
    for j, k in row["coef"].items():
        fit += k * prev[ids.index(j)]
    pieces = sorted(row.get("inflow") or [], key=lambda g: g["from"])
    if pieces:
        times = np.asarray(t[1:], dtype=float)
        froms = np.array([g["from"] for g in pieces], dtype=float)
        pos = np.clip(np.searchsorted(froms, times, side="right") - 1, 0, None)
        fit += np.array([g["value"] for g in pieces])[pos]
    return dy[s] - fit


def as_coflows(flows: list[dict], rows: list[dict], stocks: list[dict], lv: np.ndarray, t: list, mask: np.ndarray,
               used: list[str], min_t: float = 2.0, moves_only: bool = True, per_from: str = "cross",
               same_unit: bool = False) -> tuple[list[dict], list[dict]]:
    """The cross terms "C drains faster when A is high" (C one of `used`) turned into `uses` of C on A's
    outflow, with per = (per x k) / k. Accepted only if A drains less than its row says on the steps
    where C was dry (A's residual there positive, t > min_t). With `moves_only`, only a move between
    two stocks (A -> B) may use C. Returns the new flows and what was found."""
    ids = [s["id"] for s in stocks]
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    out = [dict(f) for f in flows]
    found, drop = [], set()
    for n, f in enumerate(out):
        c, a = f.get("from"), f.get("driver")
        if c not in used or f.get("to") is not None or not a or "drains faster" not in (f.get("note") or ""):
            continue
        if not same_unit and unit[c] == unit[a]:
            continue                                        # things of one kind move; another kind is used
        rate = f["rate"]
        k_cross = float(rate["terms"][0]["k"]) if rate.get("form") == "linear" and len(rate.get("terms") or []) == 1 else 0.0
        if k_cross <= 0:
            continue
        # A's outflow: a move to a stock of its own unit first (the largest), else a drain to outside
        outs = [(m, g) for m, g in enumerate(out) if g.get("from") == a and not g.get("driver") and not g.get("inflow")
                and (g.get("rate") or {}).get("form") == "proportional" and float(g["rate"].get("k") or 0) > 0
                and g.get("to") != c and (g.get("to") is not None or not moves_only)]
        if not outs:
            continue
        outs.sort(key=lambda mg: (mg[1].get("to") is None, -float(mg[1]["rate"]["k"])))
        m, g = outs[0]
        k = float(g["rate"]["k"])
        row = next((r for r in rows if r["id"] == a), None)
        if row is None or not mask.any():
            continue
        resid = row_residual(row, ids, prev, dy, t)
        res = resid[mask]
        tstat = float(res.mean() / (res.std(ddof=1) / np.sqrt(len(res)))) if len(res) > 2 and res.std() > 0 else 0.0
        per = k_cross / k
        # where the cap binds (C below what its users want), the flow moved what C held / per: its
        # amount (A's change with the flow's own drain added back) against C's level gives per
        # without the cross term's collinearity; only for a C with this one user
        users = sum(1 for h in out if h.get("from") == c and h.get("driver") and "drains faster" in (h.get("note") or ""))
        per_dry = None
        if users == 1:
            ci = ids.index(c)
            bind = mask & (prev[ci] < k_cross * prev[ids.index(a)])
            amount, held = -(resid[bind] - k * prev[ids.index(a)][bind]), prev[ci][bind]
            if bind.sum() >= 5 and (held * held).sum() > 0:
                slope = float((amount * held).sum() / (held * held).sum())
                per_dry = 1 / slope if slope > 0 else None
        found.append({"stock": c, "source": a, "flow_to": g.get("to"), "per": per, "per_dry": per_dry, "k": k, "t": tstat, "starved": int(mask.sum())})
        if tstat <= min_t:
            continue
        if per_from == "dry" and per_dry is not None:
            per = per_dry
        out[m] = {**g, "uses": [*(g.get("uses") or []), {"stock": c, "per": round(per, 4)}]}
        drop.add(n)
    return [f for n, f in enumerate(out) if n not in drop], found


def fill_gaps(flows: list[dict], t: list) -> list[dict]:
    """Outside inflows fitted on some steps only: each piece holds until the next one starts (and
    the first from the start), so the steps left out take their neighbour's value."""
    out = []
    for f in flows:
        if f.get("inflow"):
            segs = sorted((dict(g) for g in f["inflow"]), key=lambda g: g["from"])
            segs[0]["from"] = min(segs[0]["from"], t[0])
            for g, h in zip(segs, segs[1:]):
                g["to"] = h["from"] - 1
            segs[-1]["to"] = max(segs[-1]["to"], t[-1])
            f = {**f, "inflow": segs}
        out.append(f)
    return out


def remeasure_inflows(flows: list[dict], stocks: list[dict], lv: np.ndarray, t: list, min_piece: int = 5, changes: bool = True) -> list[dict]:
    """The outside inflows measured again on every step, the left-out ones included, with the found
    model's own flows run one step from each measured state (the co-flows capped where a used stock
    is dry): while C is dry its users take all it holds, so what it receives shows in its level,
    which the fit on the kept steps could not see."""
    ids = [s["id"] for s in stocks]
    pieces = [n for n, f in enumerate(flows) if f.get("inflow") and bool(f.get("from")) != bool(f.get("to"))]
    if not pieces:
        return flows
    rest = [f for n, f in enumerate(flows) if n not in pieces]
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    moved = Model(rest, ids).step(prev, np.asarray(t[1:], dtype=float)) - prev
    out = list(flows)
    for n in pieces:
        f = flows[n]
        s = ids.index(f.get("to") or f.get("from"))
        sign = 1.0 if f.get("to") else -1.0
        res = sign * (dy[s] - moved[s])
        cuts = pelt(res, min_piece, 1) if changes else [0, len(res)]
        segs = [{"from": t[a + 1], "to": t[b], "value": float(res[a:b].mean())} for a, b in zip(cuts[:-1], cuts[1:])]
        out[n] = {**f, "inflow": segs, "changes": len(segs) - 1}
    return out
