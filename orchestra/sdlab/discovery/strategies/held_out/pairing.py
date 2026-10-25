"""The offered capacity series as one move (kubernetes 306, round 3; docs/research/k8s-306-r3-six.md).

capmin.py offers m = MIN(X, theta x Y) as a measured series that only the rows of X and of the flow's
receiver R may read. The matrix this strategy starts from (the pinned identify_one) writes what a row
reads from a series as a flow from or to outside, so the one flow X -> R comes out as two: X -> outside
reading m and outside -> R reading m. Left to the boundary guard, each is replaced on its own, greedily,
and the first replacement is chosen while the other half is still there; on 306 that routed m into the
wrong stock or dropped it, and which one depended on rounding (node2 and the Mac chose differently).

pair() joins the two halves before the guard: where X's outflow and R's inflow both read m, the m terms
become one move X -> R at the mean of the two numbers (the guard's refit then fits it), and what else
those two flows read is kept as it was. Nothing else changes: a half without its partner is left to the
guard as before. The same rule for every case; it reads only what offer() recorded.
"""

from __future__ import annotations

import copy


def _terms(rate: dict) -> list[dict]:
    if rate.get("form") == "proportional":
        return [{"stock": rate.get("stock"), "k": rate.get("k")}]
    if rate.get("form") == "linear":
        return list(rate.get("terms") or [])
    return []


def _part(f: dict, name: str) -> tuple[float | None, dict | None]:
    """(the number f reads m with, f without that term or None when nothing is left); (None, f) when f
    does not read m (or is not a plain linear flow)."""
    if f.get("byTime") or f.get("inflow"):
        return None, f
    r = f.get("rate") or {}
    ts = _terms(r)
    hit = [t for t in ts if t.get("stock") == name]
    if len(hit) != 1 or hit[0].get("k") is None:
        return None, f
    rest = [dict(t) for t in ts if t is not hit[0]]
    c = float(r.get("c") or 0.0) if r.get("form") == "linear" else 0.0
    if not rest and c == 0.0:
        return float(hit[0]["k"]), None
    g = copy.deepcopy(f)
    g["rate"] = {"form": "linear", "c": c, "terms": rest}
    g.pop("rates", None)
    return float(hit[0]["k"]), g


def pair(flows: list[dict], offered: dict) -> list[dict]:
    """flows with each offered series' two outside halves joined into one move (see the module doc).
    offered: {series name: (X, R or None)} (capmin.offered)."""
    out = list(flows)
    for name, (x, r) in sorted(offered.items()):
        if r is None:
            continue
        outs = [i for i, f in enumerate(out) if f.get("from") == x and f.get("to") is None and _part(f, name)[0] is not None]
        ins = [i for i, f in enumerate(out) if f.get("from") is None and f.get("to") == r and _part(f, name)[0] is not None]
        if len(outs) != 1 or len(ins) != 1:
            continue
        ko, fo = _part(out[outs[0]], name)
        ki, fi = _part(out[ins[0]], name)
        if ko <= 0 or ki <= 0:
            continue
        k = 0.5 * (ko + ki)
        move = {"from": x, "to": r, "rate": {"form": "linear", "c": 0, "terms": [{"stock": name, "k": k}]}}
        keep = [f for j, f in enumerate(out) if j not in (outs[0], ins[0])]
        out = keep + [g for g in (fo, fi) if g is not None] + [move]
    return out
