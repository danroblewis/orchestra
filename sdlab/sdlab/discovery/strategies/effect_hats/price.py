"""A model's price (one-step BIC with pooled inflow values counted once), and pruning by it.

price() is onestep.bic with size() below: every row's one-step fit, every number costs log T; an
outside inflow costs one number per distinct value and one per change (pooled pieces share a value),
an effect flow's table one number per knot.
"""

from __future__ import annotations

import math

import numpy as np

from ...simulate import Model, levels_array
from .inputs import model_inputs
from .joint import _pools, refit


def amounts(flows: list[dict], ids: list[str], run: dict, inputs: dict | None = None) -> np.ndarray:
    """Each flow's mean amount per step on the run's states (what it moves into or out of a stock;
    with the measured inputs it reads)."""
    A = levels_array(run["levels"], ids)
    tt = np.asarray(run["t"], dtype=float)[1:]
    mi = model_inputs(inputs, ids, run["t"])
    out = []
    for f in flows:
        with np.errstate(all="ignore"):
            d = Model([f], ids, inputs=mi).step(A[:, :-1], tt) - A[:, :-1]
        out.append(float(np.nan_to_num(np.abs(d).max(axis=0)).mean()))
    return np.array(out)


def prune(flows: list[dict], ids: list[str], run: dict, opts: dict | None = None, score=None, small: float = 0.25) -> list[dict]:
    """Small flows dropped one at a time, refitting the rest jointly, while the model's price falls
    (score(flows), lower is better: by default price()). Only a flow moving less than `small` x the
    model's median flow amount may go: a large term the price would drop (a gap's feedback, say) is
    left, since inflow values would take over its work and the model would not behave.
    An outflow to outside carried by pieces on a stock X with no drain k x X is also offered as that
    drain in their place, refitted jointly with the rest (kubernetes 304 counts-short: the matrix's
    conservation folds a real outside drain into the move and leaves the excess to 7 constant pieces,
    which a plain drop hands to the input's gain; the drain prices better).
    A link from outside into Y that reads a stock X (outside -> Y = k x X) is also offered as the move
    X -> Y, merged into that move when there is one, refitted jointly, whatever its size (kubernetes 305:
    the matrix's conservation splits a move whose receiver gains more than its source's row loses into
    the move plus a link reading the source, queue -> retries + outside -> retries[queue]; the move alone
    prices better; on counts-short the move prices 0.3 above the link, which it beats once the link
    pays the prior, opts "link_prior" x log T, that rank() in __init__ charges a rate that is not its
    source's level)."""
    inputs = (opts or {}).get("inputs")
    score = score or (lambda fl: price(fl, ids, run, inputs))
    cur = flows
    best = score(cur)
    link_prior = float((opts or {}).get("link_prior", 2.0)) * math.log(max(2, len(run["t"]) - 1))
    while len(cur) > 1:
        size = amounts(cur, ids, run, inputs)
        cutoff = small * float(np.median(size)) if len(size) else 0.0
        trial = None
        for i in range(len(cur)):
            for alt in _drain_for(cur, i, ids):
                fl, _ = refit(cur[:i] + cur[i + 1:] + [alt], ids, run, opts)
                s = score(fl)
                if s < best and (trial is None or s < trial[0]):
                    trial = (s, fl)
            for alt in _move_for(cur, i, ids):
                fl, _ = refit(alt, ids, run, opts)
                s = score(fl)
                # the link paid the strategy's prior for a rate that is not its source's level
                if s - link_prior < best and (trial is None or s < trial[0]):
                    trial = (s, fl)
            if size[i] >= cutoff:
                continue
            fl, _ = refit(cur[:i] + cur[i + 1:], ids, run, opts)
            s = score(fl)
            if s < best and (trial is None or s < trial[0]):
                trial = (s, fl)
        if trial is None:
            break
        best, cur = trial
    return cur

def _drain_for(flows: list[dict], i: int, ids: list[str]) -> list[dict]:
    """[X -> outside = k x X] when flow i is an outflow to outside in pieces from a stock X that has no
    such drain yet; [] otherwise (k starts at 0, the joint refit sets it)."""
    f = flows[i]
    x = f.get("from")
    if not f.get("inflow") or f.get("to") or x not in ids:
        return []
    if any(g.get("from") == x and not g.get("to") and not g.get("inflow") and (g.get("rate") or {}).get("form") == "proportional"
           and (g.get("rate") or {}).get("stock") == x for g in flows):
        return []
    rate = {"form": "proportional", "stock": x, "k": 0.0}
    return [{"from": x, "to": None, "ratio": 1, "rate": rate, "rates": [rate]}]


def _move_for(flows: list[dict], i: int, ids: list[str]) -> list[list[dict]]:
    """[the flows with link i, outside -> Y = k x X (X a stock other than Y), read as the move X -> Y]:
    merged into an existing move X -> Y = k' x X when there is one (the link dropped), else added in
    its place; [] when flow i is no such link."""
    f = flows[i]
    rate = f.get("rate") or {}
    y = f.get("to")
    if f.get("from") or y not in ids or f.get("inflow") or f.get("byTime") or f.get("effects") or f.get("hat") or f.get("uses"):
        return []
    if rate.get("form") == "proportional":
        x, k = rate.get("stock"), rate.get("k")
    elif rate.get("form") == "linear" and not rate.get("c") and len(rate.get("terms") or []) == 1:
        x, k = rate["terms"][0].get("stock"), rate["terms"][0].get("k")
    else:
        return []
    if x not in ids or x == y:
        return []
    rest = flows[:i] + flows[i + 1:]
    if any(g.get("from") == x and g.get("to") == y and not g.get("effects") and not g.get("hat") and not g.get("uses")
           and (g.get("rate") or {}).get("form") == "proportional" and (g.get("rate") or {}).get("stock") == x for g in rest):
        return [rest]
    move = {"from": x, "to": y, "ratio": 1, "rate": {"form": "proportional", "stock": x, "k": float(k or 0)}}
    move["rates"] = [move["rate"]]
    return [rest[:i] + [move] + rest[i:]]


def size(flows: list[dict]) -> int:
    """onestep.size, with an outside inflow priced by its values (pooled pieces share one) and its changes."""
    p = 0
    for f in flows:
        if f.get("inflow"):
            p += len(_pools(f)) + len(f["inflow"]) - 1      # a number per value, and per change
            continue
        rates = [g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]
        p += len({repr(r) for r in rates})
        p += 2 * len(f.get("effects") or []) if not f.get("hat") else len(f["hat"]["knots"]) - 1
    return p


def price(flows: list[dict], ids: list[str], run: dict, inputs: dict | None = None) -> float:
    """onestep.bic with size() above: every row's one-step fit, every number costs log T (stepped
    with the measured inputs, {name: value per step})."""
    A = levels_array(run["levels"], ids)
    T = A.shape[1] - 1
    if T < 2:
        return float("inf")
    nxt = Model(flows, ids, inputs=model_inputs(inputs, ids, run["t"])).step(A[:, :-1], np.asarray(run["t"], dtype=float)[1:])
    rss = ((nxt - A[:, 1:]) ** 2).sum(axis=1)
    return float(sum(T * math.log(max(r, 1e-9) / T) for r in rss) + size(flows) * math.log(T))



def bic(flows: list[dict], ids: list[str], t: list, levels: dict, inputs: dict | None = None) -> float:
    """onestep.bic (sdlab/discovery/onestep.py), stepped with the measured inputs when there are any."""
    from ...onestep import bic as plain, size as plain_size

    mi = model_inputs(inputs, ids, t)
    if mi is None:
        return plain(flows, ids, t, levels)
    A = levels_array(levels, ids)
    T = A.shape[1] - 1
    if T < 2:
        return float("inf")
    nxt = Model(flows, ids, inputs=mi).step(A[:, :-1], np.asarray(t, dtype=float)[1:])
    rss = ((nxt - A[:, 1:]) ** 2).sum(axis=1)
    return float(sum(T * math.log(max(r, 1e-9) / T) for r in rss) + plain_size(flows) * math.log(T))
