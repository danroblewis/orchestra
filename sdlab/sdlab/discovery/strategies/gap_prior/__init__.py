"""gap_prior: lna, with readings the data cannot tell apart written the way SD models write them.

Without noise, a goal gap in b's outside inflow (c - k x a) and b's constant inflow c beside a drain
of b that reads another stock a (b loses k x a) are the same equation for b: the matrix returns the
drain. SD models do not drain a stock by another stock's level alone (an outflow reads its own
stock); a stock's inflow that falls as another stock rises is a goal gap. So, where the data are
noise-free (lna returned the matrix's reading), each such drain beside a single constant inflow is
written as the gap it equals: one flow instead of two, the same behaviour. With counting noise lna's
likelihood tells the two apart (its gap swaps) and its reading stands.

This is a convention for an unidentifiable choice, not identification; it comes from
docs/research/identifiability.md and judge-ties.md (ties broken by the simpler, conventional model)
and is measured in docs/research/revisit.md.
"""

from __future__ import annotations

from ..lna import identify as _lna


def _reads(rate: dict) -> dict[str, float] | None:
    """A rate that is k x stocks with no constant: {stock: k}; else None."""
    form = rate.get("form")
    if form == "proportional":
        return {rate["stock"]: float(rate.get("k") or 0)}
    if form == "linear" and not rate.get("c"):
        return {t["stock"]: float(t.get("k") or 0) for t in rate.get("terms") or []}
    return None


def _plain(f: dict) -> bool:
    return not (f.get("inflow") or f.get("byTime") or f.get("effects") or f.get("uses") or f.get("via"))


def one_number(pieces: list[dict] | None, rel: float = 1e-4) -> bool:
    """Inflow pieces that are one number (the matrix can cut a constant into pieces that differ
    only in rounding)."""
    vals = [float(p.get("value") or 0) for p in pieces or []]
    return not vals or max(vals) - min(vals) <= rel * max(1e-9, max(abs(v) for v in vals))


def as_gaps(flows: list[dict]) -> list[dict]:
    """Each drain of b reading only other stocks, beside b's one constant outside inflow (in one
    piece), folded into that inflow as a goal gap (c - k x a)."""
    out = [dict(f) for f in flows]
    for drain in list(out):
        b = drain.get("from")
        if b is None or drain.get("to") is not None or not _plain(drain) or float(drain.get("ratio") or 1) != 1:
            continue
        reads = _reads(drain.get("rate") or {})
        if not reads or b in reads or any(k <= 0 for k in reads.values()):
            continue
        ins = [f for f in out if f.get("from") is None and f.get("to") == b]
        if len(ins) != 1 or (ins[0].get("rate") or {}).get("form") != "constant":
            continue
        inflow = {k: v for k, v in ins[0].items() if not (k == "inflow" and one_number(v))}
        if not _plain(inflow):
            continue
        pcs = ins[0].get("inflow") or []
        w = [max(1, int(p["to"]) - int(p["from"]) + 1) for p in pcs]
        c = sum(float(p["value"]) * k for p, k in zip(pcs, w)) / sum(w) if pcs else float(inflow["rate"].get("value") or 0)
        rate = {"form": "linear", "c": c, "terms": [{"stock": s, "k": -k} for s, k in reads.items()]}
        per_step = float(inflow.get("perStep") or 0) - float(drain.get("perStep") or 0)
        out[out.index(ins[0])] = {**inflow, "rate": rate, "rates": [rate], "perStep": per_step, "note": "goal gap (written as SD writes it)"}
        out.remove(drain)
    return out


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    found = _lna(stocks, run, opts)
    if found.get("method") == "lna":
        return found                    # counting noise: the likelihood chose between them
    flows = as_gaps(found.get("flows") or [])
    if len(flows) == len(found.get("flows") or []):
        return found
    return {**found, "flows": flows, "gap_prior": True}
