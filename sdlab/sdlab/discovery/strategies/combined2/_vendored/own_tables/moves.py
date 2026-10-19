# Vendored for combined2 from sdlab/discovery/strategies/own_tables/moves.py at commit 67a604b (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""A move between two measured stocks as a table of its source's level.

Water runs from an upper tank into a lower one at k sqrt(upper level) (phys-coupled-tanks;
196-concave-move-between-tanks): the main line writes a straight move k x upper, and the bend goes
into pieces on both ends. A move's amount shows on its destination's row (it arrives there whatever
the source's other flows do), so the curve m(x_src) is fitted on the destination's row, beside the
destination's own level (its drain) and a constant (its steady inflow), with the destination's other
flows to and from outside replaced and its moves from other stocks kept. The move is then one flow
src -> dst at c x table(src). Two versions are offered: with the source's own flows to and from
outside kept, and with those that read nothing but itself dropped (constants, pieces and drains that
only copied the bend; then both rows are fitted together); the caller's BIC chooses, and
the source's outside flows are then offered their own rewrite as any row's.
"""

from __future__ import annotations

import math

import numpy as np

from . import curve, onestep, split


def _flow(src, dst, rate: dict, **extra) -> dict:
    return {"from": src, "to": dst, "ratio": 1, "rate": rate, "rates": [rate], "nearly": [], "bothWays": False, **extra}


def _outside(f: dict, row: str) -> bool:
    return (f.get("from") is None and f.get("to") == row) or (f.get("from") == row and f.get("to") is None)


def _reads(f: dict) -> list[str]:
    r = f.get("rate") or {}
    if r.get("form") in ("proportional", "gap"):
        return [r.get("stock")]
    if r.get("form") == "linear":
        return [x.get("stock") for x in r.get("terms") or []]
    return []


def _column_flows(row, names, cols, b, inputs, tol=1e-12):
    """Other columns' numbers as links into the row (b > 0) or drains of it reading them (b < 0)."""
    out = []
    for m, k in zip(cols, b):
        mark = {"input": names[m]} if names[m] in inputs else {}
        rate = {"form": "linear", "c": 0, "terms": [{"stock": names[m], "k": float(f"{abs(float(k)):.6g}")}]}
        if k > tol:
            out.append(_flow(None, row, rate, driver=names[m], **mark))
        elif k < -tol:
            out.append(_flow(row, None, rate, driver=names[m], **mark))
    return out


def _reads_source(f: dict) -> bool:
    r = f.get("rate") or {}
    src = f.get("from")
    if r.get("form") == "proportional":
        return r.get("stock") == src
    if r.get("form") == "linear":
        return [x.get("stock") for x in r.get("terms") or []] == [src]
    return False


def candidates(flows, ids, t, prev, dy, floor_rss, o, inp=None) -> list[tuple[list[dict], str]]:
    """inp: the measured inputs (model_inputs(), names, values names x T) or None; the levels and inputs
    the destination's replaced outside flows read stay columns of its fit, written back as links."""
    mi, names, X = (inp[0], ids + inp[1], np.vstack([prev, inp[2]])) if inp else (None, ids, prev)
    out = []
    pairs = {(f["from"], f["to"]) for f in flows if f.get("from") in ids and f.get("to") in ids and not f.get("byTime")
             and not f.get("effects") and not f.get("uses") and _reads_source(f)}
    for src, dst in sorted(pairs):
        i, j = ids.index(src), ids.index(dst)
        if any(f.get("byTime") or f.get("effects") or f.get("uses") for f in flows if _outside(f, dst)):
            continue
        replaced = [f for f in flows if (f.get("from"), f.get("to")) == (src, dst) or _outside(f, dst)]
        rest = [f for f in flows if not any(f is g for g in replaced)]
        y = dy[j] - onestep.changes(rest, ids, t, prev, mi)[j]
        x = prev[i]
        T = len(y)
        if np.ptp(x) <= 0:
            continue
        cols = sorted({names.index(s) for f in replaced if _outside(f, dst) for s in _reads(f) if s in names and s not in (src, dst)})
        Z = np.vstack([prev[j], np.ones(T)] + [X[m] for m in cols])
        name = f"move {src} -> {dst} as a table of {src}"
        # kept: the curve from the destination's row alone; dropped: the source's row says the same
        # curve with the opposite sign (nothing else moves it), so both rows are fitted together
        fits = [(rest, y, x, Z, name)]
        # dropped: the source's outside flows that read nothing but itself (constants, pieces, its
        # drain), or all of them; with them gone the source's row says the curve with the opposite
        # sign, so both rows are fitted together
        drops = [([g for g in rest if not (_outside(g, src) and set(_reads(g)) <= {src})], "those reading only itself"),
                 ([g for g in rest if not _outside(g, src)], "all")]
        for rest_d, what in drops:
            if len(rest_d) == len(rest) or (what == "all" and len(rest_d) == len(drops[0][0])):
                continue
            y_i = dy[i] - onestep.changes(rest_d, ids, t, prev, mi)[i]
            fits.append((rest_d, np.concatenate([y, -y_i]), np.concatenate([x, x]), np.hstack([Z, np.zeros_like(Z)]),
                         name + f", {src}'s outside flows dropped ({what})"))
        for base, yy, xx, ZZ, nm in fits:
            mine = _fit(yy, xx, ZZ, floor_rss[j], o, src, dst)
            if mine is not None:
                links = _column_flows(dst, names, cols, mine[2][2:], names[len(ids):])
                out.append((base + mine[0] + links, f"{nm} ({mine[1]} points)"))
    return out


def _fit(y, x, Z, floor_rss, o, src, dst):
    cv = curve.search(y, x, Z, floor_rss, most=o["most"])
    if cv is None or len(cv["knots"]) <= 2:
        return None
    if cv["bic"] > cv["line_bic"] - o["margin"] * math.log(len(y)):
        return None
    # the curve and the constant share one level (the tents sum to 1): the move is taken as 0 at its
    # lowest point and the rest of that level is the destination's steady inflow (or outflow)
    m = np.asarray(cv["values"], dtype=float)
    base = float(m.min())
    m = m - base
    c = float(cv["z"][1]) + base
    d = -float(cv["z"][0])
    f = split.table_flow(src, dst, src, cv["knots"], m)
    if f is None or np.diff(m).sum() <= 0:
        return None
    mine = [f]
    if d > 0:
        mine.append(_flow(dst, None, {"form": "proportional", "stock": dst, "k": float(f"{d:.6g}")}))
    if c > 1e-9:
        mine.append(_flow(None, dst, {"form": "constant", "value": float(f"{c:.6g}")}))
    elif c < -1e-9:
        mine.append(_flow(dst, None, {"form": "constant", "value": float(f"{-c:.6g}")}))
    return mine, len(cv["knots"]), cv["z"]
