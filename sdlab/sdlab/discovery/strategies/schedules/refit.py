"""The numbers of a whole model refitted together by one-step least squares, all rows at once.

A move's number shows in two rows (what leaves its source, what reaches its destination), a co-flow's
in the stock it uses too; the main line fits each row alone and conservation reconciles them
afterwards. Here every flow whose rate is linear in its numbers (constant, proportional, linear, per
announced era with `byTime`, or an outside inflow in pieces) is one set of columns of a single least
squares over all rows, each row weighted by its residual scale; the other flows (floors, gaps,
effects) are held as they are and their amounts subtracted. A piece's value touches only the row
it flows into, so the pieces are profiled out (each row's data and columns are centred within its
pieces) and measured afterwards as the mean residual over the piece.

The structure is the caller's: `free_c` marks flows whose linear rate gets a constant column, and the
number of free columns is what the search prices (`count`).
"""

from __future__ import annotations

import numpy as np

from ...simulate import Model, _Segments

LINEAR = ("constant", "proportional", "linear")


def _stocks_of(r: dict) -> list[str]:
    if r.get("form") == "proportional":
        return [r.get("stock")]
    if r.get("form") == "linear":
        return [x.get("stock") for x in r.get("terms") or []]
    return []


def refittable(f: dict) -> bool:
    """Whether the flow's numbers enter its amount linearly (and nothing else shapes it)."""
    if f.get("effects") or f.get("threshold_params") or f.get("hinge") or f.get("floor") or f.get("cap"):
        return False
    if f.get("inflow"):
        return (f.get("from") is None) != (f.get("to") is None) and not f.get("uses")
    rates = [g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]
    return all(r.get("form") in LINEAR for r in rates)


class Context:
    """The data a refit reads: levels at each step's start (stocks x T, injections added), the
    changes, the columns by name (stocks, then measured inputs), the step times, the era labels."""

    def __init__(self, ids, t, prev, dy, names, X, inputs, spans):
        self.ids, self.t, self.prev, self.dy, self.names, self.X, self.inputs = ids, t, prev, dy, names, X, inputs
        self.T = prev.shape[1]
        self.times = np.asarray(t, dtype=float)[1 : self.T + 1]
        self.span_label = {sp["from"]: sp["label"] for sp in spans or []}
        self.index = {s: i for i, s in enumerate(ids)}

    def col(self, name: str) -> np.ndarray:
        return self.X[self.names.index(name)] if name in self.names else np.zeros(self.T)


def _groups(f: dict, ctx: Context) -> list[tuple[np.ndarray, list[int]]]:
    """The flow's rate segments as (steps mask, segment indices sharing one set of numbers)."""
    if not f.get("byTime"):
        return [(np.ones(ctx.T, bool), [0])]
    segs = f["byTime"]
    at = _Segments(segs)(ctx.times)
    by: dict = {}
    for i, g in enumerate(segs):
        by.setdefault(g.get("label") or ctx.span_label.get(g["from"], f"#{i}"), []).append(i)
    return [(np.isin(at, ix), ix) for ix in by.values()]


def _stoich(f: dict, ctx: Context) -> list[tuple[int, float]]:
    out = []
    if f.get("from") in ctx.index:
        out.append((ctx.index[f["from"]], -float(f.get("ratio") or 1)))
    if f.get("to") in ctx.index:
        out.append((ctx.index[f["to"]], 1.0))
    for u in f.get("uses") or []:
        if u.get("stock") in ctx.index:
            out.append((ctx.index[u["stock"]], -float(u["per"])))
    return out


def _columns(f: dict, ctx: Context) -> list[tuple[np.ndarray, tuple]]:
    """(column over steps, where its number goes) for each free number of a non-piece flow."""
    out = []
    for mask, ix in _groups(f, ctx):
        r = (f["byTime"][ix[0]]["rate"] if f.get("byTime") else f.get("rate")) or {}
        m = mask.astype(float)
        if r.get("form") == "constant":
            out.append((m, (ix, "value", None)))
        elif r.get("form") == "proportional":
            out.append((m * ctx.col(r["stock"]), (ix, "k", None)))
        else:
            if f.get("free_c") or float(r.get("c") or 0) != 0:
                out.append((m, (ix, "c", None)))
            for q, term in enumerate(r.get("terms") or []):
                out.append((m * ctx.col(term["stock"]), (ix, "k", q)))
    return out


def count(flows: list[dict], ctx: Context) -> int:
    """The numbers the model carries: free columns of refittable flows (per era group), a piece's
    value and its cut each one, and the others' numbers as onestep.params counts them."""
    n = 0
    for f in flows:
        if f.get("inflow"):
            n += 2 * len(f["inflow"]) - 1
        elif refittable(f):
            n += len(_columns(f, ctx)) + int(f.get("period_params") or 0)
        else:
            r = f.get("rate") or {}
            n += {"constant": 1, "proportional": 1, "gap": 2}.get(r.get("form"), 1 + len(r.get("terms") or []))
            n += int(f.get("threshold_params") or 0) + len(f.get("effects") or [])
    return n


def piece_row(f: dict, ctx: Context) -> tuple[int, float] | None:
    """The row a pieced outside flow moves, and its sign there (+1 into it, -ratio out of it)."""
    if f.get("from") is None and f.get("to") in ctx.index:
        return ctx.index[f["to"]], 1.0
    if f.get("to") is None and f.get("from") in ctx.index:
        return ctx.index[f["from"]], -float(f.get("ratio") or 1)
    return None


def _piece_masks(f: dict, ctx: Context) -> list[np.ndarray]:
    at = _Segments(f["inflow"])(ctx.times)
    return [at == p for p in range(len(f["inflow"]))]


def _set(f: dict, where: tuple, v: float) -> None:
    ix, key, q = where
    targets = [f["byTime"][i]["rate"] for i in ix] if f.get("byTime") else [f["rate"]]
    for r in targets:
        if q is None:
            r[key] = v
        else:
            r["terms"][q]["k"] = v


def _copy(f: dict) -> dict:
    g = {**f}
    if f.get("rate") is not None:
        g["rate"] = {**f["rate"], **({"terms": [dict(x) for x in f["rate"]["terms"]]} if f["rate"].get("terms") else {})}
    if f.get("byTime"):
        g["byTime"] = [{**s, "rate": {**s["rate"], **({"terms": [dict(x) for x in s["rate"]["terms"]]} if s["rate"].get("terms") else {})}} for s in f["byTime"]]
    if f.get("inflow"):
        g["inflow"] = [dict(p) for p in f["inflow"]]
    return g


def binding(flows: list[dict], ctx: Context) -> np.ndarray:
    """The steps where some stock's flows (with what co-flows use of it) want more than it holds, so
    the engine shares the level out and the rows are not the flows' equations there."""
    out = np.zeros(ctx.T, bool)
    if not flows:
        return out
    model = Model(flows, ctx.ids, inputs=ctx.inputs)
    R = model._read(ctx.prev, ctx.times)
    zero = np.zeros(ctx.T, int)
    want = np.zeros_like(ctx.prev)
    amounts = []
    for src, dst, ratio, segs, rate, vals in model.parts:
        seg = segs(ctx.times) if segs is not None else zero
        a = np.nan_to_num(np.asarray(vals[seg] if vals is not None else rate(R, seg), dtype=float))
        amounts.append(a)
    for i, effect in model.effects:
        amounts[i] = amounts[i] * effect(R)
    for (src, _dst, ratio, *_rest), a in zip(model.parts, amounts):
        if src is not None:
            want[src] += a * ratio
    for i, c, per in model.uses:
        want[c] += amounts[i] * per
    return ((want > ctx.prev + 1e-9) & (want > 0)).any(axis=0)


def refit(flows: list[dict], ctx: Context, scale: np.ndarray | None = None, nonneg: bool = True) -> list[dict]:
    """The flows with every refittable number fitted jointly (a copy; the structure unchanged).
    `scale`: each row's residual size (weights 1 / scale); `nonneg`: a proportional rate's number
    that comes out negative is set to 0 and the rest refitted (a rate is floored at 0 anyway)."""
    keep = ~binding(flows, ctx)
    if keep.sum() < 0.5 * ctx.T:
        keep[:] = True
    flows = [_copy(f) for f in flows]
    S, T = len(ctx.ids), ctx.T
    w = 1.0 / np.maximum(scale if scale is not None else np.ones(S), 1e-12)
    fixed = [f for f in flows if not refittable(f)]
    y = ctx.dy - (Model(fixed, ctx.ids, inputs=ctx.inputs).change(ctx.prev, ctx.times) if fixed else 0.0)
    pieces = [(f, _piece_masks(f, ctx)) for f in flows if f.get("inflow") and refittable(f) and piece_row(f, ctx) is not None]
    prow: dict = {}
    for f, ms in pieces:
        prow.setdefault(piece_row(f, ctx)[0], []).append((f, ms))
    cols, where = [], []
    for fi, f in enumerate(flows):
        if not refittable(f) or f.get("inflow"):
            continue
        st = _stoich(f, ctx)
        for c, wh in _columns(f, ctx):
            full = np.zeros((S, T))
            for s, a in st:
                full[s] += a * c
            cols.append(full)
            where.append((fi, wh))

    def centre(M: np.ndarray, s: int) -> np.ndarray:
        """Row s of M (… x T) with its mean over each piece of the inflows into s taken out."""
        out = M.copy()
        for _, ms in prow.get(s, []):
            for m in ms:
                mk = m & keep
                if mk.any():
                    out[..., m] -= out[..., mk].mean(axis=-1, keepdims=True)
        out[..., ~keep] = 0.0
        return out

    active = list(range(len(cols)))
    beta = np.zeros(len(cols))
    if cols:
        for _ in range(4):
            A = np.zeros((S * T, len(active)))
            b = np.zeros(S * T)
            for s in range(S):
                sl = slice(s * T, (s + 1) * T)
                b[sl] = w[s] * centre(y[s], s)
                if active:
                    A[sl] = w[s] * centre(np.array([cols[q][s] for q in active]), s).T
            sol = np.linalg.lstsq(A, b, rcond=None)[0] if active else np.zeros(0)
            beta[:] = 0
            beta[active] = sol
            neg = [q for q in active if nonneg and sol[active.index(q)] < 0 and where[q][1][1] in ("k", "value")
                   and _is_rate_number(flows[where[q][0]], where[q][1])]
            if not neg:
                break
            active = [q for q in active if q not in neg]
    for q, (fi, wh) in enumerate(where):
        _set(flows[fi], wh, round(float(beta[q]), 6))
    # the pieces: the mean over each piece of what is left in their row, the other flows stepped as
    # the engine steps them (an outflow cut short by an emptied stock moves what it moved)
    pieced = {id(f) for f, _ in pieces}
    others = [f for f in flows if id(f) not in pieced]
    rest = ctx.dy - (Model(others, ctx.ids, inputs=ctx.inputs).change(ctx.prev, ctx.times) if others else 0.0)
    for s, lst in prow.items():
        r = rest[s].copy()
        for f, ms in lst:                        # (one inflow per row in practice; several share it in turn)
            sign = piece_row(f, ctx)[1]
            for p, m in zip(f["inflow"], ms):
                p["value"] = float(r[m].mean()) / sign if m.any() else float(p["value"])
                r[m] -= sign * p["value"]
    for f in flows:
        if f.get("byTime"):
            f["rate"] = f["byTime"][0]["rate"]
            if f.get("rates") is not None:
                f["rates"] = [g["rate"] for g in f["byTime"]]
        if f.get("inflow"):
            vals = [p["value"] for p in f["inflow"]]
            f["rate"] = {"form": "constant", "value": round(float(np.mean(vals)), 4)}
            f["changes"] = len(vals) - 1
    return flows


def _is_rate_number(f: dict, wh: tuple) -> bool:
    """A proportional rate or a constant (not a linear term, whose sign is free)."""
    ix, key, q = wh
    r = (f["byTime"][ix[0]]["rate"] if f.get("byTime") else f.get("rate")) or {}
    return q is None and key in ("k", "value") and r.get("form") in ("constant", "proportional")
