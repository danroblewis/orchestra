"""Reading stock-and-flow structure off a sparse model's terms (levels and products of levels).

Each term's numbers across the rows are read the way flows.py reads a column of the matrix:

  - the term's source is the factor whose own row loses it (a product A x C lost by A is a flow out
    of A sped up by C); what same-unit stocks gain of it is a move, the rest of the loss leaves;
  - a gain no loss pays for is a link (an outside inflow following the term);
  - a loss in a stock of another unit than the source is a co-flow: that stock is used up by the
    source's flow, `per` of it for each unit moved (otherwise, or without co-flows, a flow out of it
    that follows the term).

The pieces of one flow (same ends, same main stock) are joined: its rate is proportional to the main
stock at the number it has at the other factors' mean levels, times one effect per other factor -
linear (level / normal) when the flow is the product alone, else a table through its values at
the lowest and highest level seen (held beyond them).
"""

from __future__ import annotations

import numpy as np

from .flows import r4
from .library import factors


def read(stocks: list[dict], terms: list[tuple], coef: list[dict], prev: np.ndarray, inflow: list[list[dict]], tol: float = 0.003, uses: bool = True) -> list[dict]:
    """coef: per stock, {term index: number}; inflow: per stock, its pieces {from, to, value}."""
    ids = [s["id"] for s in stocks]
    S = len(ids)
    unit = [s.get("unit") or "" for s in stocks]
    final = {k for k, s in enumerate(stocks) if s.get("final")}
    mean, lo, hi = prev.mean(axis=1), prev.min(axis=1), prev.max(axis=1)
    tmean = [float(np.prod([prev[j] for j in factors(t)], axis=0).mean()) for t in terms]

    def size(f, k):                        # a number as a proportional rate on one factor
        fs = factors(terms[f])
        return abs(k) * (min(mean[j] for j in fs[1:]) if len(fs) > 1 else 1.0)

    groups: dict[tuple, dict] = {}

    def part(src, dst, f, k, main, link=False, note=None):
        fs = list(factors(terms[f]))
        fs.remove(main)
        g = groups.setdefault((src, dst, main, link), {"k0": 0.0, "kc": {}, "terms": {}, "uses": {}, "note": note})
        if fs:
            g["kc"][fs[0]] = g["kc"].get(fs[0], 0.0) + k
        else:
            g["k0"] += k
        g["terms"][f] = g["terms"].get(f, 0.0) + k
        return g

    for f, t in enumerate(terms):
        fs = factors(t)
        v = {s: coef[s].get(f, 0.0) for s in range(S) if size(f, coef[s].get(f, 0.0)) > tol}
        if not v:
            continue
        cands = [a for a in dict.fromkeys(fs) if v.get(a, 0.0) < 0 and a not in final]

        def matched(a):
            got = sum(k for s, k in v.items() if s != a and k > 0 and unit[s] == unit[a])
            return (min(got, -v[a]), -v[a])

        src = max(cands, key=matched) if cands else None
        recv = sorted(((s, k) for s, k in v.items() if src is not None and s != src and k > 0 and unit[s] == unit[src]), key=lambda x: -x[1])
        main_part = None
        if src is not None:
            left = -v[src]
            for s, k in recv:
                m = max(0.0, min(k, left))
                if size(f, m) > tol:
                    g = part(src, s, f, m, src)
                    main_part = main_part or (g, m)
                    left -= m
                if size(f, k - m) > tol:
                    part(None, s, f, k - m, _main(fs, s, unit), link=True)
            if size(f, left) > tol:
                g = part(src, None, f, left, src)
                if main_part is None or left > main_part[1]:
                    main_part = (g, left)
        done = {src} | {s for s, _ in recv}
        for d, k in v.items():
            if d in done:
                continue
            if k > 0:
                part(None, d, f, k, _main(fs, d, unit), link=True, note="grows with itself" if d in fs else None)
            elif uses and main_part is not None and unit[d] != unit[src]:
                g = main_part[0]
                g["uses"][d] = g["uses"].get(d, 0.0) - k * tmean[f]
            else:
                part(d, None, f, -k, d if d in fs else _main(fs, d, unit), link=True, note=f"{ids[d]} drains faster")

    flows = []
    for (src, dst, main, link), g in groups.items():
        K = g["k0"] + sum(k * mean[c] for c, k in g["kc"].items())
        if K <= tol:
            continue
        effects = []
        for c, k in g["kc"].items():
            if g["k0"] == 0 and len(g["kc"]) == 1 and k > 0 and mean[c] > 1e-9:
                effects.append({"stock": ids[c], "shape": "linear", "normal": r4(mean[c]), "min": 0, "max": r4(max(1.0, hi[c] / mean[c]))})
            elif hi[c] > lo[c]:
                at = lambda x: round(float((K + k * (x - mean[c])) / K), 4)  # noqa: E731
                effects.append({"stock": ids[c], "shape": "table", "points": [[r4(lo[c]), at(lo[c])], [r4(hi[c]), at(hi[c])]]})
        moved = sum(k * tmean[f] for f, k in g["terms"].items())
        used = [{"stock": ids[d], "per": r4(u / moved)} for d, u in g["uses"].items() if moved > 0 and u / moved > 1e-4]
        rate = {"form": "linear", "c": 0, "terms": [{"stock": ids[main], "k": r4(K)}]} if link else {"form": "proportional", "stock": ids[main], "k": r4(K)}
        fl = {"from": ids[src] if src is not None else None, "to": ids[dst] if dst is not None else None, "ratio": 1, "rate": rate, "rates": [rate],
              "perStep": K * mean[main], "nearly": [], "bothWays": False}
        if link:
            fl["driver"] = ids[main]
        if g["note"]:
            fl["note"] = g["note"]
        if effects:
            fl["effects"] = effects
        if used:
            fl["uses"] = used
        flows.append(fl)

    for s, pieces in enumerate(inflow):
        if not pieces:
            continue
        W = sum(p["to"] - p["from"] + 1 for p in pieces)
        m = sum(p["value"] * (p["to"] - p["from"] + 1) for p in pieces) / max(1, W)
        if abs(m) <= tol:
            continue
        rate = {"form": "constant", "value": r4(abs(m))}
        base = {"ratio": 1, "rate": rate, "rates": [rate], "perStep": abs(m), "nearly": [], "bothWays": False, "changes": len(pieces) - 1}
        if m > 0:
            flows.append({"from": None, "to": ids[s], **base, "inflow": pieces})
        else:
            flows.append({"from": ids[s], "to": None, **base, "inflow": [{**p, "value": -p["value"]} for p in pieces]})
    return flows


def _main(fs: tuple, d: int, unit: list[str]) -> int:
    """The factor a gain in d follows: one of d's unit if there is one (a product of a queue and a
    stock of another unit is the queue's flow, sped up by the other)."""
    same = [j for j in fs if unit[j] == unit[d]]
    return same[0] if same else fs[0]
