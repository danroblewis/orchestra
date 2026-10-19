"""(realistic_flows) Readings of the matrix that split one flow into several, offered as candidates.

1. A move driven by a third stock (mechanism E; distilled 152, from sd-fishery and sd-manufacturing).
   A -> B at k x S, S neither A nor B, is -k S in A's row and +k S in B's row. The matrix's reader
   writes it as "A drains faster when S is high" (A -> outside, k x S) and, in B's row, a gain from
   S: since B and S share a unit, S's own drain is read as a move S -> B as far as it goes and the rest
   as a link outside -> B reading S. Here such a set (A's drain reading S, and B's gain from S, within a
   factor 2 of each other) becomes one move A -> B at k x S, and S's drain goes back to outside.

The caller refits every number, prices and judges each candidate, and keeps one only if it prices
better and behaves no worse.
"""

from __future__ import annotations


def _reads(f: dict) -> tuple[str, float] | None:
    """(stock, k) for a rate k x one stock's level (proportional or linear with one term, no constant)."""
    r = f.get("rate") or {}
    if f.get("effects") or f.get("uses") or f.get("byTime") or f.get("inflow") or f.get("hat") or f.get("via"):
        return None
    if r.get("form") == "proportional":
        return r.get("stock"), float(r.get("k") or 0.0)
    if r.get("form") == "linear" and not r.get("c") and len(r.get("terms") or []) == 1:
        t = r["terms"][0]
        return t.get("stock"), float(t.get("k") or 0.0)
    return None


def _linear(stock: str, k: float) -> dict:
    return {"form": "linear", "c": 0, "terms": [{"stock": stock, "k": float(k)}]}


def third_stock_moves(flows: list[dict], stocks: list[dict]) -> list[list[dict]]:
    """Candidates: the model with one set of A's drain reading S and B's gain from S read as a move
    A -> B at k x S (S's own drain restored)."""
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    ids = list(unit)
    out = []
    for i, fa in enumerate(flows):
        ra = _reads(fa)
        if ra is None or fa.get("to") is not None or fa.get("from") not in unit:
            continue
        s, ka = ra
        a = fa["from"]
        if s == a or s not in unit or ka <= 0:
            continue
        for b in ids:
            if b in (a, s) or unit[b] != unit[a]:
                continue
            # B's gain from S: a move S -> B (S's drain, read as going to B) and a link outside -> B
            gains = [j for j, f in enumerate(flows) if j != i and f.get("to") == b and f.get("from") in (s, None)
                     and (_reads(f) or (None, 0))[0] == s and (_reads(f) or (None, 0))[1] > 0]
            if not gains:
                continue
            kb = sum(_reads(flows[j])[1] for j in gains)
            if not 0.5 <= ka / kb <= 2.0:
                continue
            drain = sum(_reads(flows[j])[1] for j in gains if flows[j].get("from") == s)
            new = [f for j, f in enumerate(flows) if j != i and j not in gains]
            new.append({"from": a, "to": b, "ratio": 1, "rate": _linear(s, 0.5 * (ka + kb)), "rates": [_linear(s, 0.5 * (ka + kb))],
                        "perStep": fa.get("perStep"), "nearly": [], "bothWays": False, "driver": s})
            if drain > 0:
                own = next((f for f in new if f.get("from") == s and f.get("to") is None and (f.get("rate") or {}).get("form") == "proportional"
                            and (f["rate"].get("stock") == s) and not f.get("uses") and not f.get("effects")), None)
                if own is not None:
                    k = float(own["rate"]["k"]) + drain
                    new = [({**f, "rate": {**f["rate"], "k": k}, "rates": [{**f["rate"], "k": k}]} if f is own else f) for f in new]
                else:
                    rate = {"form": "proportional", "stock": s, "k": float(drain)}
                    new.append({"from": s, "to": None, "ratio": 1, "rate": rate, "rates": [rate], "nearly": [], "bothWays": False})
            out.append(new)
    return out


def _inflow_of(flows: list[dict], x: str) -> dict | None:
    return next((f for f in flows if f.get("from") is None and f.get("to") == x and f.get("inflow") is not None
                 and (f.get("rate") or {}).get("form") == "constant"), None)


def drains_into_moves(flows: list[dict], stocks: list[dict]) -> list[list[dict]]:
    """2. A constant drain of Y read as a constant part of the move X -> Y (mechanism B; distilled 131,
    from sd-learning-curve, sd-print-shop, sd-moderation). A move whose rate is k x X - c (an effect
    linearised, a release above a threshold, 158) is read by the matrix as k x X with c twice: in
    X's outside inflow (c more than X gets from outside) and as a constant drain of Y. Both readings
    step the same; the one with the constant on the move has one outside flow fewer, and keeps X's
    outside inflow as what arrives from outside. Candidates: Y's constant drain (one value, no
    pieces) moved onto each move X -> Y whose source has an outside inflow, as far as the smallest of
    X's inflow values allows."""
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    out = []
    for i, d in enumerate(flows):
        y = d.get("from")
        if y not in unit or d.get("to") is not None or (d.get("rate") or {}).get("form") != "constant":
            continue
        pieces = d.get("inflow") or []
        if len({round(float(g.get("value") or 0.0), 9) for g in pieces}) > 1:
            continue
        c = float(d["rate"].get("value") or 0.0)
        if c <= 0:
            continue
        for j, m in enumerate(flows):
            x = m.get("from")
            if m.get("to") != y or x not in unit or unit[x] != unit[y] or m.get("uses") or m.get("effects") or m.get("byTime") or m.get("hat"):
                continue
            r = m.get("rate") or {}
            if r.get("form") != "proportional" or r.get("stock") != x:
                continue
            fin = _inflow_of(flows, x)
            if fin is None:
                continue
            vals = [float(g.get("value") or 0.0) for g in fin["inflow"]]
            move_c = min(c, min(vals) if vals else 0.0)
            if move_c <= 0:
                continue
            rate = {"form": "linear", "c": -move_c, "terms": [{"stock": x, "k": float(r["k"])}]}
            new = []
            for q, f in enumerate(flows):
                if q == i:
                    if c - move_c > 1e-9 * c:
                        left = {"form": "constant", "value": c - move_c}
                        new.append({**f, "rate": left, "rates": [left], "inflow": [{**g, "value": c - move_c} for g in pieces]})
                elif q == j:
                    new.append({**f, "rate": rate, "rates": [rate]})
                elif f is fin:
                    ins = [{**g, "value": float(g.get("value") or 0.0) - move_c} for g in f["inflow"]]
                    v = {"form": "constant", "value": float(f["rate"]["value"]) - move_c}
                    new.append({**f, "rate": v, "rates": [v], "inflow": ins})
                else:
                    new.append(f)
            out.append(new)
    return out
