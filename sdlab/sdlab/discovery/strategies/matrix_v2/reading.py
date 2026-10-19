"""What matrix_v2 reads off the matrix beyond flows.read_flows (each behind an option).

- product_flows (products): a row's number on a x c. A loss in a row that is a factor of the product
  (S in S x I) paired with same-unit gains is a move from that row's stock (SIR's infection, Bass's
  adoption; S x S is crowding); the rest is an outflow or a link. With pair_moves, a loss in a row
  that is not a factor pairs with the gains too: a move whatever stock its rate is based on.
- pair_linear (pair_moves): "s drains faster when a is high" (-k in s's row on a) beside a link into b
  at k x a (+k in b's row beyond a's own drain) is one move s -> b at k x a, when the two numbers
  agree within `slack`: read alone, the matrix writes the move's two halves as two flows.
- fold_inflows (falling_inflow, gap_inflow): a negative reading of another stock's level in a row
  with a constant outside inflow is that inflow falling as the stock rises (a goal gap, c - k x a,
  floored at 0 as a whole, never capped by the row's level): censored's link rewrite. gap_inflow also
  folds the row's links from other stocks and measured inputs into the same flow (a gap over several
  stocks and a target, (u - R - E) / tau, one floored linear inflow; structures' gaps), with or
  without a constant. Each fold is kept only if the row's one-step error, with floors and caps as the
  engine applies them, is no worse (the numbers are the same, so where no floor binds the two
  readings tie, and the gap's form is the one written).
"""

from __future__ import annotations

import numpy as np

from ...simulate import Model


def _r(v: float) -> float:
    return float(f"{float(v):.6g}")


def _product_rate(base: int, other: int, k: float, ids: list[str], prev: np.ndarray) -> tuple[dict, list[dict]]:
    """k x base x other as base's proportional rate times a linear effect of other (normal: other's
    mean; its cap, 1000 x the normal, never binds), as structures/write.py writes a bilinear term."""
    n = float(max(1e-9, prev[other].mean()))
    return ({"form": "proportional", "stock": ids[base], "k": _r(k * n)},
            [{"stock": ids[other], "shape": "linear", "normal": _r(n), "min": 0, "max": 1000}])


def product_flows(rows: list[dict], c: int, pairs: list[tuple[int, int]], ids: list[str], unit: dict, prev: np.ndarray,
                  tol: float = 0.003, pair_moves: bool = False) -> list[dict]:
    out = []

    def flow(src, dst, base, other, k, **extra):
        rate, eff = _product_rate(base, other, k, ids, prev)
        out.append({"from": src, "to": dst, "ratio": 1, "rate": rate, "rates": [rate], "effects": eff, "driver": ids[base],
                    "perStep": k * float((prev[base] * prev[other]).mean()), "nearly": [], "bothWays": False, "product": True, **extra})

    for a, cc in pairs:
        name = f"{ids[a]}*{ids[cc]}"
        scale = lambda s: float(prev[cc if s == a else a].mean()) if s in (a, cc) else float(prev[cc].mean())  # noqa: E731
        k = {s: rows[s]["coefL"][c].get(name) or 0.0 for s in range(len(ids))}
        losers = sorted((s for s in k if k[s] < 0 and -k[s] * scale(s) > tol), key=lambda s: k[s])
        gains = {s: k[s] for s in k if k[s] > 0 and k[s] * scale(s) > tol}
        for s in losers:
            left = -k[s]
            base, other = (s, cc if s == a else a) if s in (a, cc) else (a, cc)
            if s in (a, cc) or pair_moves:
                for g in sorted(gains, key=lambda g: -gains[g]):
                    if g == s or unit[ids[g]] != unit[ids[s]] or left <= 0:
                        continue
                    m = min(left, gains[g])
                    flow(ids[s], ids[g], base, other, m)
                    left -= m
                    gains[g] -= m
            if left * scale(s) > tol:
                flow(ids[s], None, base, other, left)
        for g, kg in gains.items():
            if kg * scale(g) > tol:
                base, other = (g, cc if g == a else a) if g in (a, cc) else (a, cc)
                flow(None, ids[g], base, other, kg)
    return out


def _single(f: dict) -> tuple[str, float] | None:
    """(stock, k) of a flow whose rate is linear in one level with no constant, else None."""
    r = f.get("rate") or {}
    if f.get("inflow") or f.get("effects") or f.get("byTime") or r.get("form") != "linear" or len(r.get("terms") or []) != 1 or r.get("c"):
        return None
    return r["terms"][0]["stock"], float(r["terms"][0]["k"])


def _drains_faster(f: dict) -> bool:
    return f.get("to") is None and f.get("from") is not None and "drains faster" in (f.get("note") or "") and _single(f) is not None


def _link(f: dict) -> bool:
    return f.get("from") is None and f.get("to") is not None and not f.get("note") and not f.get("input") and f.get("driver") and _single(f) is not None


def pair_linear(flows: list[dict], unit: dict, slack: float = 0.3) -> list[dict]:
    """Each "s drains faster when a is high" paired with the closest link into a same-unit b at a."""
    used: set = set()
    out = list(flows)
    for i, d in enumerate(flows):
        if not _drains_faster(d):
            continue
        a, kd = _single(d)
        best = None
        for j, g in enumerate(flows):
            if j in used or not _link(g) or g["to"] == d["from"] or unit.get(g["to"]) != unit.get(d["from"]):
                continue
            b, kl = _single(g)
            if b != a:
                continue
            rel = abs(kd - kl) / max(kd, kl)
            if rel <= slack and (best is None or rel < best[1]):
                best = (j, rel, kl)
        if best is None:
            continue
        j, _, kl = best
        used |= {i, j}
        k = _r(0.5 * (kd + kl))
        rate = {"form": "linear", "c": 0, "terms": [{"stock": a, "k": k}]}
        out[i] = {**{x: v for x, v in d.items() if x != "note"}, "to": flows[j]["to"], "rate": rate, "rates": [rate],
                  "perStep": 0.5 * (d.get("perStep", 0) + flows[j].get("perStep", 0)), "driver": a, "note": "a move read off another stock"}
        out[j] = None
    return [f for f in out if f is not None]


def _row_rss(flows: list[dict], ids: list[str], s: int, prev: np.ndarray, dy: np.ndarray, tt: np.ndarray, inputs: dict | None) -> float:
    m = Model(flows, ids, inputs=inputs)
    e = m.step(prev, tt)[s] - prev[s] - dy[s]
    return float(e @ e)


def fold_inflows(flows: list[dict], ids: list[str], prev: np.ndarray, dy: np.ndarray, t: list, inputs: dict | None,
                 gap: bool = False, spread: float = 0.05) -> list[dict]:
    """Each row's negative readings of other levels folded into its outside inflow (see the module)."""
    tt = np.asarray(t, dtype=float)[1:]
    inp = {"t": t, "values": inputs} if inputs else None
    for s, sid in enumerate(ids):
        negs = [f for f in flows if f.get("from") == sid and (_drains_faster(f) or (gap and f.get("input") and f.get("to") is None))]
        if not negs:
            continue
        const = next((f for f in flows if f.get("to") == sid and f.get("from") is None and f.get("inflow")), None)
        c0 = 0.0
        if const is not None:
            vals = np.array([float(g["value"]) for g in const["inflow"]])
            w = np.array([max(1, g["to"] - g["from"] + 1) for g in const["inflow"]], dtype=float)
            mean = float((vals * w).sum() / w.sum())
            sd = float(np.sqrt((w * (vals - mean) ** 2).sum() / w.sum()))
            if mean > 0 and sd <= spread * mean:
                c0 = mean
            else:
                const = None
        pos = [f for f in flows if f.get("to") == sid and f.get("from") is None and (_link(f) or (f.get("input") and _single(f)))] if gap else []
        if const is None and not (gap and pos):
            continue
        terms: dict[str, float] = {}
        for f in pos:
            x, k = _single(f)
            terms[x] = terms.get(x, 0.0) + k
        for f in negs:
            x, k = _single(f)
            terms[x] = terms.get(x, 0.0) - k
        rate = {"form": "linear", "c": _r(c0), "terms": [{"stock": x, "k": _r(k)} for x, k in terms.items()]}
        new = {"from": None, "to": sid, "ratio": 1, "rate": rate, "rates": [rate], "perStep": c0, "nearly": [], "bothWays": False,
               "note": "outside inflow falling as other levels rise", "driver": next(iter(terms))}
        gone = {id(f) for f in negs + pos + ([const] if const is not None else [])}
        trial = [f for f in flows if id(f) not in gone] + [new]
        if _row_rss(trial, ids, s, prev, dy, tt, inp) <= _row_rss(flows, ids, s, prev, dy, tt, inp) * (1 + 1e-9) + 1e-12:
            flows = trial
    return flows
