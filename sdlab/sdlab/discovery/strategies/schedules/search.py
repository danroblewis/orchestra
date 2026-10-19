"""A beam search over the structure of a whole model, every candidate refitted jointly (refit.py)
and priced by its one-step BIC in the engine's form.

Steps offered at each round (the best one taken while it lowers the BIC):
- drop a flow (a spurious loop or drain that only one era needed, 157);
- one number for every era (a flow the announced eras do not change);
- numbers per announced era for a flow that has one (a move that changes at an era);
- a constant on a move between measured stocks, with or without the constant outside flow at either
  end that it replaces (an affine release, -6 + 0.02 x A, read as A's inflow plus 6 and B's drain
  of 6: 158);
and after each, adjacent pieces of an outside inflow merged while that lowers the BIC (pieces that
only copied the eras' effect).

The BIC counts each number (refit.count) and, beside them, `flow_price` x log T per flow: of two
models that fit the data equally, the one with fewer flows is chosen.
"""

from __future__ import annotations

import math
import time

import numpy as np

from ...simulate import Model
from .refit import Context, _piece_masks, count, piece_row, refit, refittable


def rss(flows: list[dict], ctx: Context) -> np.ndarray:
    d = Model(flows, ctx.ids, inputs=ctx.inputs).change(ctx.prev, ctx.times) if flows else np.zeros_like(ctx.prev)
    return ((ctx.dy - d) ** 2).sum(axis=1)


def bic(flows: list[dict], ctx: Context, floor: np.ndarray, flow_price: float) -> float:
    T = ctx.T
    r = np.maximum(rss(flows, ctx), floor)
    return float(sum(T * math.log(x / T) for x in r) + (count(flows, ctx) + flow_price * len(flows)) * math.log(T))


def _plain(f: dict) -> dict:
    g = {k: v for k, v in f.items() if k not in ("byTime", "rates")}
    g["rate"] = f["byTime"][0]["rate"]
    return g


def _split(f: dict, spans: list[dict]) -> dict:
    r = f.get("rate") or {}
    return {**f, "byTime": [{"from": sp["from"], "to": sp["to"], "rate": r} for sp in spans]}


def _affine(f: dict) -> dict | None:
    """The move with a constant column (its rate linear in its source); None if it has one."""
    if f.get("byTime") or f.get("free_c"):
        return None
    r = f.get("rate") or {}
    if r.get("form") == "proportional":
        if r.get("stock") != f.get("from"):
            return None
        return {**f, "rate": {"form": "linear", "c": 0, "terms": [{"stock": r["stock"], "k": r.get("k") or 0}]}, "free_c": True}
    if r.get("form") == "linear" and not float(r.get("c") or 0):
        return {**f, "free_c": True}
    return None


def _no_constant(f: dict) -> dict:
    g = {k: v for k, v in f.items() if k != "free_c"}
    zero = lambda r: {**r, "c": 0}  # noqa: E731
    if g.get("byTime"):
        g["byTime"] = [{**s, "rate": zero(s["rate"])} for s in g["byTime"]]
        g["rate"] = g["byTime"][0]["rate"]
    else:
        g["rate"] = zero(g.get("rate") or {})
    return g


def _constant_outside(f: dict, stock: str) -> bool:
    """An outside flow into or out of `stock` that is one constant (or one piece)."""
    if not ((f.get("from") is None and f.get("to") == stock) or (f.get("from") == stock and f.get("to") is None)):
        return False
    if f.get("inflow"):
        return len(f["inflow"]) <= 3
    return (f.get("rate") or {}).get("form") == "constant" and not f.get("byTime")


def _reads_only(f: dict, constant: bool = False) -> str | None:
    """The one level a proportional or one-term linear rate reads (with `constant`, also one with a
    constant), else None."""
    rates = [g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]
    got = set()
    for r in rates:
        if r.get("form") == "proportional":
            got.add(r.get("stock"))
        elif r.get("form") == "linear" and len(r.get("terms") or []) == 1 and (constant or not float(r.get("c") or 0)):
            got.add(r["terms"][0].get("stock"))
        else:
            return None
    return got.pop() if len(got) == 1 else None


def _reads(f: dict, x: str) -> bool:
    """Whether the flow's rate reads the level x."""
    rates = [g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]
    for r in rates:
        if r.get("stock") == x or any(t.get("stock") == x for t in r.get("terms") or []):
            return True
    return False


def _as_move(drain: dict, link: dict, spans) -> dict:
    """A move from the drain's stock into the link's, at the drain's rate (per era if either had eras)."""
    x = drain["from"]
    dr = drain["byTime"][0]["rate"] if drain.get("byTime") else drain.get("rate") or {}
    k0 = dr.get("k") if dr.get("form") == "proportional" else (dr.get("terms") or [{}])[0].get("k")
    r = {"form": "proportional", "stock": x, "k": float(k0 or 0.0)}
    f = {"from": x, "to": link["to"], "ratio": 1, "rate": r}
    if (drain.get("byTime") or link.get("byTime")) and spans:
        f["byTime"] = [{"from": sp["from"], "to": sp["to"], "rate": dict(r)} for sp in spans]
    return f


def best_period(r: np.ndarray, most: int = 60) -> tuple[int, int, float] | None:
    """The period P and phase of one-step pulses that best explain a residual (the steps k = phase
    mod P given their own mean): (P, phase, the rss it removes), over P = 2..most."""
    T = len(r)
    tot_n, tot_s = T, float(r.sum())
    best = None
    idx = np.arange(T)
    for P in range(2, min(most, T // 4) + 1):
        n1 = np.bincount(idx % P, minlength=P).astype(float)
        s1 = np.bincount(idx % P, weights=r, minlength=P)
        n0, s0 = tot_n - n1, tot_s - s1
        gain = n1 * n0 / tot_n * (s1 / np.maximum(n1, 1) - s0 / np.maximum(n0, 1)) ** 2
        ph = int(np.argmax(gain))
        if best is None or gain[ph] > best[2] * (1 + 1e-9):
            best = (P, ph, float(gain[ph]))
    return best


def _periodic(f: dict, ctx: Context, P: int, phase: int, own: bool) -> dict:
    """The outside flow as one-step pulses every P steps (from step `phase`) and a constant between,
    each with one set of numbers; with `own`, the pulse reads the stock it fills (c + k x own: a
    top-up to a level on a schedule)."""
    stock = f.get("to") or f.get("from")
    pulse = {"form": "linear", "c": 0.0, "terms": [{"stock": stock, "k": 0.0}]} if own else {"form": "constant", "value": 0.0}
    rest = {"form": "constant", "value": 0.0}
    times, segs, k = ctx.times, [], 0
    while k < ctx.T:
        if k % P == phase:
            segs.append({"from": float(times[k]), "to": float(times[k]), "label": "pulse", "rate": dict(pulse, **({"terms": [dict(pulse["terms"][0])]} if own else {}))})
            k += 1
        else:
            j = k
            while j + 1 < ctx.T and (j + 1) % P != phase:
                j += 1
            segs.append({"from": float(times[k]), "to": float(times[j]), "label": "rest", "rate": dict(rest)})
            k = j + 1
    g = {k2: v for k2, v in f.items() if k2 not in ("inflow", "changes", "rates")}
    g.update({"byTime": segs, "rate": segs[0]["rate"], "period": P, "phase": phase, "period_params": 2})
    if own:
        g["free_c"] = True
    return g


def _fusions(flows: list[dict], ctx: Context, spans):
    """(the other flows, the move, why) for each drain of x beside a link into y that reads x."""
    ids = set(ctx.ids)
    for i, d in enumerate(flows):
        x = d.get("from")
        if x not in ids or d.get("to") is not None or not refittable(d) or d.get("inflow") or _reads_only(d) != x or d.get("uses"):
            continue
        for j, k in enumerate(flows):
            if (k.get("from") is None and k.get("to") in ids and k.get("to") != x and refittable(k) and not k.get("inflow")
                    and _reads_only(k, constant=True) == x and not k.get("uses")):
                rest = [f for q, f in enumerate(flows) if q not in (i, j)]
                yield rest, _as_move(d, k, spans), f" for a drain of {x} and a link into {k['to']}"


def candidates(flows: list[dict], ctx: Context, spans: list[dict] | None):
    """(name, flows, adds numbers?) for every step offered."""
    ids = set(ctx.ids)
    # an outside flow in pieces as pulses on a fixed period (a planning pulse every 14 steps, a
    # capacity topped up to a level every 14: 159)
    for i, f in enumerate(flows):
        if not (f.get("inflow") and refittable(f) and piece_row(f, ctx) is not None):
            continue
        if any(g.get("period") and (g.get("to") or g.get("from")) == (f.get("to") or f.get("from")) for g in flows):
            continue
        s, sign = piece_row(f, ctx)
        others = flows[:i] + flows[i + 1 :]
        d = Model(others, ctx.ids, inputs=ctx.inputs).change(ctx.prev, ctx.times)[s] if others else np.zeros(ctx.T)
        bp = best_period((ctx.dy[s] - d) / sign)
        if bp is None or bp[2] <= 0:
            continue
        P, ph, _ = bp
        label = f"{f.get('from') or 'outside'} -> {f.get('to') or 'outside'}"
        for own in (False, True):
            g = _periodic(f, ctx, P, ph, own)
            yield f"{label} as pulses every {P} steps" + (" topping its stock up" if own else ""), others[:i] + [g] + others[i:], True
    # a stock whose row the model leaves with a periodic residual: a new outside flow of pulses
    # (or its constant outside inflow replaced by them)
    if flows:
        full = Model(flows, ctx.ids, inputs=ctx.inputs).change(ctx.prev, ctx.times)
        for s, x in enumerate(ctx.ids):
            bp = best_period(ctx.dy[s] - full[s])
            if bp is None or bp[2] <= 0:
                continue
            P, ph, _ = bp
            if any(f.get("to") == x and f.get("period") for f in flows):     # one schedule of pulses per stock
                continue
            consts = [q for q, f in enumerate(flows) if f.get("from") is None and f.get("to") == x and refittable(f)
                      and (f.get("inflow") or ((f.get("rate") or {}).get("form") == "constant" and not f.get("byTime")))]
            for own in (False, True):
                g = _periodic({"from": None, "to": x, "ratio": 1}, ctx, P, ph, own)
                yield f"pulses every {P} steps into {x}" + (" topping it up" if own else ""), flows + [g], True
                for q in consts:
                    yield f"pulses every {P} steps into {x} for its inflow" + (" topping it up" if own else ""), [f for k2, f in enumerate(flows) if k2 != q] + [g], True
    # a move x -> y where x has an outflow and y an inflow that both read x (the move's two ends
    # written as separate flows); and a move that uses up a third stock u as it goes (a co-flow:
    # u loses what moves, `per` of it each), its `per` read off u's row
    res = ctx.dy - (Model(flows, ctx.ids, inputs=ctx.inputs).change(ctx.prev, ctx.times) if flows else 0.0)
    for x in ctx.ids:
        drains = [f for f in flows if f.get("from") == x and _reads(f, x)]
        if not drains:
            continue
        xi = ctx.index[x]
        for y in ctx.ids:
            if y == x or any(f.get("from") == x and f.get("to") == y for f in flows):
                continue
            yi = ctx.index[y]
            # y gains with x: an inflow into y that reads x, or y's residual rising with x (t > 3)
            reads = any(f.get("to") == y and f.get("from") != x and _reads(f, x) for f in flows)
            if not reads:
                Xc = np.array([np.ones(ctx.T), ctx.prev[xi]]).T
                b, rs = np.linalg.lstsq(Xc, res[yi], rcond=None)[:2]
                sig = math.sqrt(max(float(rs[0]) if len(rs) else 0.0, 1e-300) / max(ctx.T - 2, 1))
                sd = sig / max(float(np.std(ctx.prev[xi])) * math.sqrt(ctx.T), 1e-300)
                reads = b[1] > 3 * sd
            if reads:
                yield f"a move {x} -> {y}", flows + [{"from": x, "to": y, "ratio": 1, "rate": {"form": "proportional", "stock": x, "k": 0.0}}], True
    # moves to try co-flows on: the model's own, and those a drain of x and a link into y reading x make
    options = [(flows[:i] + flows[i + 1 :], f, "") for i, f in enumerate(flows)
               if f.get("from") in ids and f.get("to") in ids and refittable(f) and not f.get("uses") and not f.get("inflow")]
    for rest, m, why in _fusions(flows, ctx, spans):
        options.append((rest, m, why))
    for rest, f, why in options:
        a = Model([f], ctx.ids, inputs=ctx.inputs).change(ctx.prev, ctx.times)[ctx.index[f["to"]]]
        if not np.any(a > 0):
            continue
        for u in ctx.ids:
            if u in (f["from"], f["to"]):
                continue
            uu = ctx.index[u]
            cols = np.array([-a, np.ones(ctx.T), ctx.prev[uu]]).T
            per = float(np.linalg.lstsq(cols, ctx.dy[uu], rcond=None)[0][0])
            for p_ in sorted({1.0, round(per, 4)}):
                if p_ <= 0:
                    continue
                g = {**f, "uses": [{"stock": u, "per": p_}]}
                yield f"{f['from']} -> {f['to']} uses {u} ({p_:g} each){why}", rest + [g], True
                # the same, with what the model had u lose otherwise dropped (the co-flow is its loss)
                kept = [h for h in rest if h.get("from") != u]
                if len(kept) < len(rest):
                    yield f"{f['from']} -> {f['to']} uses {u} ({p_:g} each) for {u}'s outflows{why}", kept + [g], False
    # a drain of x that reads another level z, beside x's constant inflow: one inflow c - k z
    # (a goal gap or a falling link the main line wrote as "x drains faster when z is high")
    for i, d in enumerate(flows):
        x, z = d.get("from"), _reads_only(d)
        if x not in ids or d.get("to") is not None or not refittable(d) or d.get("inflow") or d.get("byTime") or z in (None, x) or d.get("uses"):
            continue
        for j, h in enumerate(flows):
            if j != i and h.get("from") is None and h.get("to") == x and (_constant_outside(h, x) or bool(h.get("inflow"))) and refittable(h) and not h.get("byTime"):
                link = {"from": None, "to": x, "ratio": 1, "rate": {"form": "linear", "c": 0.0, "terms": [{"stock": z, "k": 0.0}]}, "free_c": True}
                rest = [f for q, f in enumerate(flows) if q not in (i, j)]
                yield f"an inflow into {x} falling with {z} for its drain on {z}", rest + [link], False
    # a drain of x beside a link into y that reads x: the move x -> y (the same levels, one flow fewer)
    for rest, m, why in _fusions(flows, ctx, spans):
        yield f"move {m['from']} -> {m['to']}{why}", rest + [m], False
    for i, f in enumerate(flows):
        rest = flows[:i] + flows[i + 1 :]
        label = f"{f.get('from') or 'outside'} -> {f.get('to') or 'outside'}"
        yield f"drop {label}", rest, False
        if not refittable(f):
            continue
        if f.get("period") and f.get("free_c"):
            g = _periodic(f, ctx, f["period"], f["phase"], False)
            g.pop("free_c", None)
            yield f"{label}'s pulses not reading its stock", rest[:i] + [g] + rest[i:], False
        elif f.get("free_c"):
            yield f"no constant on {label}", rest[:i] + [_no_constant(f)] + rest[i:], False
        if f.get("byTime") and spans and len(spans) > 1:
            # its eras handed to the flows that share its ends (a drain per era beside a move
            # with one number: the move per era instead)
            ends = {f.get("from"), f.get("to")} - {None}
            near = [q for q, g in enumerate(rest) if refittable(g) and not g.get("inflow") and not g.get("byTime")
                    and ({g.get("from"), g.get("to")} & ends)]
            if near:
                yield f"drop {label}, its eras to the flows beside it", [_split(g, spans) if q in near else g for q, g in enumerate(rest)], False
        if f.get("byTime") and not f.get("inflow"):
            yield f"one number for {label} in every era", rest[:i] + [_plain(f)] + rest[i:], False
        elif spans and len(spans) > 1 and not f.get("inflow"):
            yield f"numbers per era for {label}", rest[:i] + [_split(f, spans)] + rest[i:], True
        if f.get("from") in ids and f.get("to") in ids:
            g = _affine(f)
            if g is None:
                continue
            yield f"a constant on {label}", rest[:i] + [g] + rest[i:], True
            for j, h in enumerate(flows):
                if j != i and (_constant_outside(h, f["from"]) or _constant_outside(h, f["to"])):
                    others = [x for k, x in enumerate(flows) if k not in (i, j)]
                    yield f"a constant on {label} for {h.get('from') or 'outside'} -> {h.get('to') or 'outside'}", others + [g], False


def merge_pieces(flows: list[dict], ctx: Context, floor: np.ndarray, flow_price: float, score: float,
                 scale: np.ndarray | None = None) -> tuple[list[dict], float, int]:
    """Adjacent pieces of each outside inflow merged while that lowers the row's BIC (the other
    numbers held: merging two pieces adds n_a n_b / (n_a + n_b) (m_a - m_b)^2 to the row's rss),
    then the whole model refitted; kept only if its BIC falls."""
    T, log_t = ctx.T, math.log(ctx.T)
    out, merged = list(flows), 0
    for i, f in enumerate(flows):
        if not f.get("inflow") or len(f["inflow"]) < 2 or not refittable(f) or piece_row(f, ctx) is None:
            continue
        s, sign = piece_row(f, ctx)
        others = out[:i] + out[i + 1 :]
        d = Model(others, ctx.ids, inputs=ctx.inputs).change(ctx.prev, ctx.times)[s] if others else np.zeros(T)
        r = (ctx.dy[s] - d) / sign
        ms = _piece_masks(f, ctx)
        segs = [[p["from"], p["to"], int(m.sum()), float(r[m].sum())] for p, m in zip(f["inflow"], ms)]
        base = float(sum(((r[m] - r[m].mean()) ** 2).sum() for m in ms if m.any()))
        cur = max(base, floor[s])
        n0 = len(segs)
        while len(segs) > 1:
            costs = []
            for p in range(len(segs) - 1):
                (_, _, na, sa), (_, _, nb, sb) = segs[p], segs[p + 1]
                costs.append(na * nb / (na + nb) * (sa / na - sb / nb) ** 2 if na and nb else 0.0)
            p = int(np.argmin(costs))
            new = max(cur + costs[p], floor[s])
            if T * math.log(new / cur) - 2 * log_t >= 0:
                break
            cur = new
            a, b = segs[p], segs[p + 1]
            segs[p : p + 2] = [[a[0], b[1], a[2] + b[2], a[3] + b[3]]]
        if len(segs) < n0:
            out[i] = {**f, "inflow": [{"from": a, "to": b, "value": (sm / n if n else 0.0)} for a, b, n, sm in segs]}
            merged += n0 - len(segs)
    if not merged:
        return flows, score, 0
    cand = refit(out, ctx, scale)
    sc = bic(cand, ctx, floor, flow_price)
    return (cand, sc, merged) if sc < score else (flows, score, 0)


def tot_of(x: np.ndarray) -> float:
    return float(((x - x.mean()) ** 2).sum()) if len(x) else 0.0


def _best_split(v: np.ndarray):
    """The best way to cut one piece: (gain, k) for one cut after position k, or (gain / 2, (start,
    width)) for a short burst of 1-3 steps inside it (two cuts at once: what one cut cannot find,
    since either cut alone barely helps, as with a planning pulse every 14 steps: 159); None if too short."""
    N = len(v)
    if N < 4:
        return None
    c1, c2 = np.cumsum(v), np.cumsum(v ** 2)
    n = np.arange(1, N)
    left = c2[:-1] - c1[:-1] ** 2 / n
    right = (c2[-1] - c2[:-1]) - (c1[-1] - c1[:-1]) ** 2 / (N - n)
    tot = c2[-1] - c1[-1] ** 2 / N
    gain = tot - (left + right)
    gain[:1] = gain[-1:] = -1                    # at least two steps a side
    k = int(np.argmax(gain))
    best = (float(gain[k]), k)
    P1, P2 = np.concatenate([[0.0], c1]), np.concatenate([[0.0], c2])
    for w in (1, 2, 3):
        if N < w + 4:
            continue
        st = np.arange(2, N - w - 1)
        i, j = st, st + w
        g3 = tot - ((P2[i] - P1[i] ** 2 / i) + ((P2[j] - P2[i]) - (P1[j] - P1[i]) ** 2 / w)
                    + ((P2[N] - P2[j]) - (P1[N] - P1[j]) ** 2 / (N - j)))
        q = int(np.argmax(g3))
        if float(g3[q]) / 2 > best[0]:
            best = (float(g3[q]) / 2, (int(st[q]), w))
    return best


def split_pieces(flows: list[dict], ctx: Context, floor: np.ndarray, flow_price: float, score: float, margin: float,
                 scale: np.ndarray | None = None) -> tuple[list[dict], float, int]:
    """Cuts added to each outside inflow, the best single cut in any piece at a time (the other numbers
    held), while it lowers the row's BIC by more than `margin` x log T; then the whole model refitted,
    kept only if its BIC falls."""
    T, log_t = ctx.T, math.log(ctx.T)
    out, added = list(flows), 0
    for i, f in enumerate(flows):
        if not f.get("inflow") or not refittable(f) or piece_row(f, ctx) is None:
            continue
        s, sign = piece_row(f, ctx)
        others = out[:i] + out[i + 1 :]
        d = Model(others, ctx.ids, inputs=ctx.inputs).change(ctx.prev, ctx.times)[s] if others else np.zeros(T)
        r = (ctx.dy[s] - d) / sign
        ms = _piece_masks(f, ctx)
        pieces = [(p["from"], p["to"], np.flatnonzero(m)) for p, m in zip(f["inflow"], ms)]
        cur = max(float(sum(((r[ix] - r[ix].mean()) ** 2).sum() for _, _, ix in pieces if len(ix))), floor[s])
        n0 = len(pieces)
        path = [(T * math.log(cur) + 2 * (n0 - 1) * log_t, list(pieces))]
        cache: list = [_best_split(r[ix]) for _, _, ix in pieces]
        stop = path[0][0]
        while len(pieces) < min(400, n0 + T // 3):
            best = None
            for q, c in enumerate(cache):
                if c is not None and (best is None or c[0] > best[1]):
                    best = (q, c[0], c[1])
            if best is None or best[1] <= 0:
                break
            q, gain, k = best
            a, b, ix = pieces[q]
            v = r[ix]
            if isinstance(k, tuple):
                st, w = k
                real = tot_of(v) - sum(tot_of(x) for x in (v[:st], v[st : st + w], v[st + w :]))
                c1, c2 = float(ctx.times[ix[st]]), float(ctx.times[ix[st + w]])
                new = [(a, c1 - 1, ix[:st]), (c1, c2 - 1, ix[st : st + w]), (c2, b, ix[st + w :])]
            else:
                real = tot_of(v) - tot_of(v[: k + 1]) - tot_of(v[k + 1 :])
                cut = float(ctx.times[ix[k + 1]])
                new = [(a, cut - 1, ix[: k + 1]), (cut, b, ix[k + 1 :])]
            pieces[q : q + 1] = new
            cache[q : q + 1] = [_best_split(r[x[2]]) for x in new]
            cur = max(cur - real, floor[s])
            path.append((T * math.log(cur) + 2 * (len(pieces) - 1) * log_t, list(pieces)))
            stop = min(stop, path[-1][0])
            if path[-1][0] > stop + 30 * log_t:        # far past the best point: no way back down
                break
        # the best point on the path (each cut priced 2 log T, and `margin` x log T more beyond the start)
        top = min(path, key=lambda x: x[0] + (margin * log_t * (len(x[1]) - n0) / 2 if len(x[1]) > n0 else 0))
        pieces = top[1]
        if len(pieces) > n0:
            out[i] = {**f, "inflow": [{"from": a, "to": b, "value": float(r[ix].mean()) if len(ix) else 0.0} for a, b, ix in pieces]}
            added += len(pieces) - n0
    if not added:
        return flows, score, 0
    cand = refit(out, ctx, scale)
    sc = bic(cand, ctx, floor, flow_price)
    return (cand, sc, added) if sc < score else (flows, score, 0)


def _pieces(flows, ctx, floor, flow_price, score, margin, scale, taken):
    flows, score, n = merge_pieces(flows, ctx, floor, flow_price, score, scale)
    if n:
        taken.append({"step": f"{n} pieces merged", "bic": round(score, 2)})
    flows, score, n = split_pieces(flows, ctx, floor, flow_price, score, margin, scale)
    if n:
        taken.append({"step": f"{n} cuts added", "bic": round(score, 2)})
    return flows, score


def _lean(flows: list[dict]) -> list[dict]:
    """Every outside inflow in pieces as one constant piece."""
    return [{**f, "inflow": [{"from": f["inflow"][0]["from"], "to": f["inflow"][-1]["to"], "value": float(np.mean([p["value"] for p in f["inflow"]]))}]}
            if f.get("inflow") and refittable(f) else f for f in flows]


def _key(flows: list[dict]) -> tuple:
    """A model's structure: its flows' ends, forms, era splits and constants, and its pieces."""
    out = []
    for f in flows:
        r = f.get("rate") or {}
        out.append((f.get("from") or "", f.get("to") or "", r.get("form") or "", bool(f.get("byTime")), bool(f.get("free_c")),
                    len(f.get("inflow") or []), tuple(sorted(t.get("stock") or "" for t in r.get("terms") or []))))
    return tuple(sorted(out))


def beam(flows, ctx, floor, spans, margin, flow_price, deadline, scale, taken, width=4, tie=0.25):
    """A beam search: the `width` best models (by BIC) are each offered every step; the best
    `width` of them and their children go on, until a round finds nothing better than the best."""
    score = bic(flows, ctx, floor, flow_price)
    first = refit(flows, ctx, scale)
    s1 = bic(first, ctx, floor, flow_price)
    steps = list(taken)
    if s1 < score:
        flows, score = first, s1
        steps.append({"step": "numbers refitted jointly", "bic": round(score, 2)})
    flows, score = _pieces(flows, ctx, floor, flow_price, score, margin, scale, steps)
    log_t = math.log(ctx.T)
    states = [(score, flows, steps)]
    seen = {_key(flows)}
    best = states[0]
    while time.perf_counter() < deadline:
        children = []
        for sc0, fl, st in states:
            for name, cand, adds in candidates(fl, ctx, spans):
                if time.perf_counter() > deadline:
                    break
                k = _key(cand)
                if k in seen:
                    continue
                seen.add(k)
                c = refit(cand, ctx, scale)
                sc = bic(c, ctx, floor, flow_price)
                if sc < sc0 - (margin * log_t if adds else tie * log_t):
                    children.append((sc, c, st + [{"step": name, "bic": round(sc, 2)}]))
        if not children:
            break
        children.sort(key=lambda x: x[0])
        polished = []
        for sc, c, st in children[:width]:
            st = list(st)
            c, sc = _pieces(c, ctx, floor, flow_price, sc, margin, scale, st)
            seen.add(_key(c))
            polished.append((sc, c, st))
        states = sorted(polished + states, key=lambda x: x[0])[:width]
        if states[0][0] < best[0]:
            best = states[0]
        else:
            break
    taken[:] = best[2]
    return best[1], best[0]


def search(flows: list[dict], ctx: Context, floor: np.ndarray, spans: list[dict] | None, margin: float = 2.0,
           flow_price: float = 0.5, budget: float = 60.0, scale: np.ndarray | None = None, width: int = 4) -> tuple[list[dict], list[dict]]:
    """The model after the beam search from two starts (the given model, and the same with every
    pieced inflow as one constant, its cuts found again), the one with the lower BIC; and its steps."""
    began = time.perf_counter()
    s0 = bic(flows, ctx, floor, flow_price)
    starts = [("", flows), ("every inflow as one piece", _lean(flows)),
              ("only the flows linear in their numbers, every inflow as one piece", _lean([f for f in flows if refittable(f)]))]
    keys, runs = set(), []
    for k, (name, start) in enumerate(starts):
        key = _key(start)
        if key in keys or not start:
            continue
        keys.add(key)
        taken = [{"step": name, "bic": None}] if name else []
        left = budget - (time.perf_counter() - began)
        f, sc = beam(start, ctx, floor, spans, margin, flow_price, time.perf_counter() + left / (len(starts) - k), scale, taken, width)
        runs.append((sc, f, taken))
    sc, f, taken = min(runs, key=lambda x: x[0])
    if sc >= s0 or not [x for x in taken if x["bic"] is not None]:
        return flows, []
    return f, taken
