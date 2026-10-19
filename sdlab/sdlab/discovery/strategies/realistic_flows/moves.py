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
