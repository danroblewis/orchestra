"""Outside terms a matrix fit leaves where the declared boundary has no side (docs/research/k8s-306-s1.md, "What still fails": counts, MIN mis-routed).

A matrix fit that reads the offered MIN series (capmin.py) or a measured input as a column in every row
writes each row's number on it as a flow to or from outside: the limited flow `queue -> inflight` comes
out as `queue -> outside` and `outside -> inflight`, both reading the series. The declared boundary's
guard then re-pairs each outside flow on its own, largest first, and can join the outflow to the wrong
receiver (306 counts-long: the MIN landed on `queue -> retries`, and `retries -> inflight` took the
rest). Two steps, before the guard:

- `pair`: the offered series' outflow from its source and inflow into its receiver (the two rows the
  offer named from the data, capmin.offered) become one move at the mean of the two numbers.
- `unpaired_inputs`: an outside flow reading a measured input on a stock and side the declared boundary
  does not have, with no opposite outside flow outside the boundary reading the same input (which would
  make the two one move), is dropped: the rows may read an input only where the boundary has a side
  (Boundary.inputs_ok, the rule the matrix copies apply in their own rows). 306 counts-short: the pinned
  matrix gave inflight's row `-0.136 x traffic`, which the guard made `inflight -> errors_total = 0.052 x
  traffic`, in place of the 3% error drain.

Nothing reads the case: the source and receiver come from capmin's offer, the sides from the announced
boundary. One identical copy per strategy that uses it (CLAUDE.md rule 11).
"""

from __future__ import annotations

from .capmin import offered, readers


def _k(f: dict, name: str) -> float | None:
    """The number of a flow whose rate is exactly k x name (else None)."""
    r = f.get("rate") or {}
    terms = r.get("terms") or []
    if f.get("byTime") or f.get("inflow") or r.get("form") != "linear" or r.get("c") or len(terms) != 1:
        return None
    return float(terms[0].get("k") or 0.0) if terms[0].get("stock") == name else None


def pair(flows: list[dict], opts: dict | None) -> list[dict]:
    """The flows with each offered series' outflow from its source and inflow into its receiver made one
    move (at the mean of the two numbers); unchanged where there is not exactly one of each."""
    out = list(flows or [])
    for name, (src, to) in offered(opts).items():
        if to is None:
            continue
        outs = [i for i, f in enumerate(out) if f.get("from") == src and f.get("to") is None and _k(f, name) is not None]
        ins = [i for i, f in enumerate(out) if f.get("from") is None and f.get("to") == to and _k(f, name) is not None]
        if len(outs) != 1 or len(ins) != 1:
            continue
        a, b = out[outs[0]], out[ins[0]]
        k = (_k(a, name) + _k(b, name)) / 2
        rate = {"form": "linear", "c": 0, "terms": [{"stock": name, "k": k}]}
        move = {**a, "from": src, "to": to, "rate": rate, "rates": [rate],
                "perStep": (float(a.get("perStep") or 0) + float(b.get("perStep") or 0)) / 2}
        out = [f for i, f in enumerate(out) if i not in (outs[0], ins[0])] + [move]
    return out


def _end(f: dict) -> tuple[str, str] | None:
    """(stock, side) of an outside flow's measured end; None for a move or a flow between no stocks."""
    if f.get("from") is None and f.get("to") is not None:
        return f["to"], "in"
    if f.get("to") is None and f.get("from") is not None:
        return f["from"], "out"
    return None


def _inputs_read(f: dict, inputs: set) -> set:
    out = set()
    for r in [g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]:
        out.add(r.get("stock"))
        out |= {x.get("stock") for x in r.get("terms") or []}
    if f.get("input"):
        out.add(f["input"])
    return out & inputs


def unpaired_inputs(flows: list[dict], b, opts: dict | None) -> list[dict]:
    """The flows without each outside flow that reads a measured input (not an offered series) on a stock
    whose declared boundary has no side for it, unless an opposite outside flow on such a stock reads the
    same input (the two are a move the guard joins). b: the strategy's Boundary."""
    if not b.declared:
        return list(flows or [])
    inputs = {k for k in (opts or {}).get("inputs") or {} if readers(k, opts) is None}
    bad = []
    for i, f in enumerate(flows or []):
        e, read = _end(f), _inputs_read(f, inputs)
        if e and read and not b.inputs_ok(e[0]):
            bad.append((i, e[1], read))
    drop = {i for i, side, read in bad
            if not any(j != i and s2 != side and read & r2 for j, s2, r2 in bad)}
    return [f for i, f in enumerate(flows or []) if i not in drop]
