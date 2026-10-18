"""A generous structure for the gradient fit to prune: optional effects and co-flows on every flow.

  - an effect table of every measured stock on every flow that is not a found outside inflow:
    `knots` points spread over the stock's measured range, all at 1 (no effect) to start;
  - a co-flow (`uses`) of every measured stock other than its ends on every such flow, ratio 0 to
    start; a found "drains faster" link (stock s loses in proportion to stock a's level, nothing
    arrives anywhere) becomes a co-flow of s on the flow that takes from a, at the ratio the link
    implies, and the link is dropped: the same loss while both have something, but a co-flow stops
    its flow when s runs out.
"""

from __future__ import annotations

import copy

import numpy as np


def typical_amounts(spec, A: np.ndarray) -> np.ndarray:
    """Each flow's mean rate over the data (floored, effects left out)."""
    n = A.shape[1]
    L = np.vstack([A, np.zeros((spec.S - A.shape[0], n))])
    f = np.arange(spec.F)[:, None]
    tix = np.arange(n)
    r = spec.init["C"][f, spec.seg[:, tix]] + np.einsum("fms,sm->fm", spec.init["K"][f, spec.seg[:, tix]], L)
    if len(spec.init["pieces"]):
        r = np.where(spec.piece[:, tix] >= 0, spec.init["pieces"][np.maximum(spec.piece[:, tix], 0)], r)
    return np.maximum(0.0, r).mean(axis=1)


def candidates(flows: list[dict], ids: list[str], data, spec_of, knots: int = 5, drop_links: bool = False):
    flows = copy.deepcopy(flows)
    A, sd = data.A, data.sd
    lo, hi = np.percentile(A, 1, axis=1), np.percentile(A, 99, axis=1)
    inner = [i for i, f in enumerate(flows) if not f.get("inflow")]
    # "drains faster" links -> co-flows on the flow that takes from the driver
    amounts = typical_amounts(spec_of(flows), A)
    seeded: dict[int, dict[str, float]] = {}
    drop = set()
    for g, f in enumerate(flows):
        r = f.get("rate") or {}
        if f.get("inflow") or f.get("to") or not f.get("from") or not f.get("driver") or f.get("byTime") or r.get("form") != "linear":
            continue
        a, s, kk = f["driver"], f["from"], sum(t["k"] for t in r.get("terms") or [] if t.get("stock") == f["driver"])
        takers = [i for i in inner if i != g and flows[i].get("from") == a and not flows[i].get("driver")]
        if not takers or kk <= 0:
            continue
        i = max(takers, key=lambda i: amounts[i])
        level = max(1e-9, A[ids.index(a)].mean())
        k_i = amounts[i] / level
        if k_i <= 0:
            continue
        seeded.setdefault(i, {})[s] = kk / k_i
        drop.add(g)
    if drop_links:
        drop |= {g for g, f in enumerate(flows) if f.get("driver") and not f.get("inflow")}
    keep = [i for i in range(len(flows)) if i not in drop]
    remap = {old: new for new, old in enumerate(keep)}
    flows = [flows[i] for i in keep]
    seeded = {remap[i]: v for i, v in seeded.items()}
    inner = [remap[i] for i in inner if i in remap]

    extra_e, extra_u = {}, {}
    for i in inner:
        f = flows[i]
        has_e = {e.get("stock") for e in f.get("effects") or []}
        extra_e[i] = [{"stock": s, "x": np.linspace(lo[j], hi[j], knots), "y": np.ones(knots)} for j, s in enumerate(ids)
                      if s not in has_e and hi[j] > lo[j]]
        has_u = {u.get("stock") for u in f.get("uses") or []}
        extra_u[i] = [{"stock": s, "per": seeded.get(i, {}).get(s, 0.0)} for s in ids if s not in (f.get("from"), f.get("to")) and s not in has_u]

    def groups(spec):
        out = []
        for i, es in extra_e.items():
            n0 = len(flows[i].get("effects") or [])
            out += [(i, n0 + j) for j in range(len(es))]
        return out

    def price(spec):
        """Per unit of ratio, what a co-flow takes from its stock in a typical step, in the stock's spread."""
        m = typical_amounts(spec, A)
        P = np.zeros(spec.uses.shape)
        for i, us in extra_u.items():
            n0 = sum(1 for u in flows[i].get("uses") or [] if u.get("stock") in ids and float(u.get("per") or 0) > 0)
            for j, u in enumerate(us):
                P[i, n0 + j] = m[i] / sd[ids.index(u["stock"])]
        return P

    def rate_price(spec):
        """Per unit of each rate number, what it moves in a typical step, in the spread of the stock it
        empties (or fills): an L1 price so that flows the effects make unnecessary can go."""
        mean = np.concatenate([A.mean(axis=1), np.ones(spec.S - A.shape[0])])
        sds = np.concatenate([sd, np.ones(spec.S - A.shape[0])])
        end = np.where(spec.src >= 0, spec.src, spec.dst)
        w = np.where(end >= 0, 1 / sds[np.maximum(end, 0)], 0.0)
        w = np.where(spec.inflow, 0.0, w)
        return {"C": np.broadcast_to(w[:, None], spec.init["C"].shape).copy(), "K": w[:, None, None] * mean[None, None, :] * np.ones(spec.init["K"].shape)}

    return flows, extra_e, extra_u, groups, price, rate_price


def prune_report(flows: list[dict], spec, p: dict, data, ids: list[str], use_min: float = 0.005) -> tuple[list[dict], dict]:
    """Co-flows whose typical take is below use_min of the stock's spread a step are dropped; what
    survives (effects and co-flows) is reported."""
    m = typical_amounts(spec, data.A)
    out, notes = [], {"effects": [], "uses": []}
    for i, f in enumerate(flows):
        g = dict(f)
        uses = [u for u in g.get("uses") or [] if u["per"] * m[i] / data.sd[ids.index(u["stock"])] >= use_min] if u_in(g, ids) else g.get("uses")
        if uses:
            g["uses"] = uses
        else:
            g.pop("uses", None)
        name = f"{g.get('from') or 'outside'}->{g.get('to') or 'outside'}"
        notes["uses"] += [f"{name} uses {u['stock']} {u['per']:.3g}" for u in g.get("uses") or []]
        notes["effects"] += [f"{name} x {e['stock']}" for e in g.get("effects") or []]
        out.append(g)
    return out, notes


def u_in(f: dict, ids: list[str]) -> bool:
    return all(u.get("stock") in ids for u in f.get("uses") or [])


def drop_small(flows: list[dict], spec, p: dict, data, share: float = 0.005) -> list[dict]:
    """Flows (not found outside inflows) whose typical amount a step is below `share` of the spread
    of the stock they empty (or fill) are dropped."""
    import jax.numpy as jnp  # noqa: F401  (p may hold jax arrays)

    P = {k: np.asarray(v) for k, v in p.items()}
    A = data.A
    n = A.shape[1]
    L = np.vstack([A, np.zeros((spec.S - A.shape[0], n))])
    f = np.arange(spec.F)[:, None]
    tix = np.arange(n)
    r = np.maximum(0.0, P["C"][f, spec.seg[:, tix]] + np.einsum("fms,sm->fm", P["K"][f, spec.seg[:, tix]], L)).mean(axis=1)
    sds = np.concatenate([data.sd, np.ones(spec.S - A.shape[0])])
    end = np.where(spec.src >= 0, spec.src, spec.dst)
    keep = [g for i, g in enumerate(flows) if spec.inflow[i] or end[i] < 0 or r[i] / sds[end[i]] >= share]
    return keep
