"""Fitted terms -> SD Lab flows, in the forms the model format and the answer key use:

- a stock's outside inflow (its in, link and gap terms) is one flow, c + sum k x level (gap terms
  with k < 0), floored at 0 as a whole: a goal gap over several stocks, (target - R - E) / 6, is
  one flow reading all of them;
- a bilinear term theta x a x c is a's proportional rate times a linear effect of c (normal: c's
  mean; its cap, 1000 x the normal, never binds): k x a x c / normal with k = theta x normal;
  a link scaled by a product reads its first stock with an effect of the second;
- a hidden chain is n inferred stocks: the source (or an outside inflow c + sum k x level) into the
  first, each stage draining at n / tau into the next, the last into the destination; a chain of
  more than one stage is marked as the case format marks a compiled DELAYn ("delay": {id, stage,
  of, time}), so the answer key reads it as one hidden path of delay tau.
"""

from __future__ import annotations

import numpy as np

from .terms import Rows, Term, stage_contents


def r6(v: float) -> float:
    return float(f"{float(v):.6g}")


def _flow(src, dst, rate, **extra) -> dict:
    return {"from": src, "to": dst, "ratio": 1, "rate": rate, "rates": [rate], **extra}


def _product_rate(a: int, c: int, theta: float, names: list[str], rows: Rows) -> tuple[dict, dict]:
    n = float(max(1e-9, rows.R[c].mean()))
    rate = {"form": "proportional", "stock": names[a], "k": r6(theta * n)}
    effect = {"stock": names[c], "shape": "linear", "normal": r6(n), "min": 0, "max": 1000}
    return rate, effect


def to_flows(live: list[tuple[Term, float]], names: list[str], rows: Rows, S: int, times: list | None = None) -> tuple[list[dict], dict]:
    """(flows, inferred levels of the hidden stocks)."""
    name = lambda i: None if i is None else names[i]  # noqa: E731
    flows: list[dict] = []
    pools: dict[int, list[tuple[Term, float]]] = {}
    chains: dict[tuple, list[tuple[Term, float]]] = {}
    for t, th in live:
        if t.pooled:
            pools.setdefault(t.dst, []).append((t, th))
        elif t.kind in ("chain", "init"):
            chains.setdefault(t.chain_key(), []).append((t, th))
        elif len(t.x) == 2:
            i, j = t.x
            if t.kind == "plink":                # read as the destination's own rate when it is a factor (births of Y at X x Y)
                a, c = (t.dst, j if i == t.dst else i) if t.dst in (i, j) else (i, j)
                src, dst = None, t.dst
            else:
                a = t.src
                c = j if i == a else i
                src, dst = t.src, t.dst
            rate, effect = _product_rate(a, c, th, names, rows)
            flows.append(_flow(name(src), name(dst), rate, effects=[effect], driver=names[a]))
        elif t.kind in ("out", "move"):
            flows.append(_flow(name(t.src), name(t.dst), {"form": "proportional", "stock": names[t.x[0]], "k": r6(th)}))
        elif t.kind == "drain":
            flows.append(_flow(name(t.src), None, {"form": "linear", "c": 0, "terms": [{"stock": names[t.x[0]], "k": r6(th)}]}, driver=names[t.x[0]]))
    for b, items in pools.items():
        pieces = sorted(((t.span, th) for t, th in items if t.span is not None), key=lambda x: x[0])
        rest = [(t, th) for t, th in items if t.span is None]
        if pieces:                     # a piecewise constant inflow, as lna writes one (at(k) = t[k + 1])
            at = (lambda k: times[k + 1]) if times is not None else (lambda k: k + 1)
            W = sum(sp[1] - sp[0] for sp, _ in pieces)
            mean = sum(v * (sp[1] - sp[0]) for sp, v in pieces) / max(1, W)
            inflow = [{"from": at(sp[0]), "to": at(sp[1] - 1), "value": r6(v)} for sp, v in pieces]
            flows.append(_flow(None, names[b], {"form": "constant", "value": r6(mean)}, inflow=inflow, changes=len(pieces) - 1))
        if rest:
            flows.append(_flow(None, names[b], _linear(rest, names), note="outside inflow"))
    inferred: dict[str, list[float]] = {}
    for n_chain, (key, items) in enumerate(chains.items()):
        f, h = _chain(key, items, names, rows, n_chain)
        flows += f
        inferred.update(h)
    return flows, inferred


def _linear(items: list[tuple[Term, float]], names: list[str]) -> dict:
    c = sum(th for t, th in items if not t.x)
    ks: dict[str, float] = {}
    for t, th in items:
        if t.kind == "goal":
            for i, j in enumerate(t.x):
                ks[names[j]] = ks.get(names[j], 0.0) + (th if i == 0 else -th)
        elif t.x:
            ks[names[t.x[0]]] = ks.get(names[t.x[0]], 0.0) + (-th if t.kind == "gap" else th)
    if not ks:
        return {"form": "constant", "value": r6(c)}
    return {"form": "linear", "c": r6(c), "terms": [{"stock": s, "k": r6(k)} for s, k in ks.items()]}


def _chain(key: tuple, items: list[tuple[Term, float]], names: list[str], rows: Rows, n_chain: int) -> tuple[list[dict], dict]:
    src, dst, n, tau = key
    tag = f"{names[src] if src is not None else 'outside'}~{names[dst]}"
    hidden = [f"{tag}~h{n_chain + 1}" if n == 1 else f"{tag}~h{n_chain + 1}s{s + 1}" for s in range(n)]
    feed = [(t, th) for t, th in items if t.kind == "chain"]
    init = np.zeros(n)
    for t, th in items:
        if t.kind == "init":
            init[t.stage] += th
    k = r6(n / tau)
    mark = (lambda s: {"delay": {"id": tag, "stage": s, "of": n, "time": r6(tau)}}) if n > 1 else (lambda s: {})
    out = []
    if src is not None:
        th = sum(th for _, th in feed)
        out.append(_flow(names[src], hidden[0], {"form": "proportional", "stock": names[src], "k": r6(th)}, **mark(0)))
    else:
        c = sum(th * t.sign for t, th in feed if not t.x)
        ks: dict[str, float] = {}
        for t, th in feed:
            if t.x:
                ks[names[t.x[0]]] = ks.get(names[t.x[0]], 0.0) + t.sign * th
        rate = {"form": "linear", "c": r6(c), "terms": [{"stock": s, "k": r6(v)} for s, v in ks.items()]} if ks else {"form": "constant", "value": r6(c)}
        out.append(_flow(None, hidden[0], rate, **mark(0)))
    for s in range(n):
        to = hidden[s + 1] if s + 1 < n else names[dst]
        out.append(_flow(hidden[s], to, {"form": "proportional", "stock": hidden[s], "k": k}, **mark(s + 1)))
    inflow = np.zeros(rows.T)
    for t, th in feed:
        z = rows.z(t.x)
        inflow += t.sign * th * z
    H = stage_contents(np.maximum(inflow, 0.0), init, n, tau)
    return out, {h: [float(v) for v in np.maximum(H[s], 0.0)] for s, h in enumerate(hidden)}
