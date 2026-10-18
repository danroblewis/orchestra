"""Every number of a model fitted at once, across all the stocks' rows (stacked least squares).

The matrix method fits each stock's row on its own, so a move's number is read twice (where it leaves,
where it arrives) and the two readings disagree under noise; an effect's curve, offered as one fixed
column, keeps whatever shape it was offered with. Here the structure is held and the numbers are
refitted together: each flow is a few columns (its rate's numbers; an effect flow's tents, base x
h_j(C), basis.py), each column entering every row the flow touches with the flow's sign (from: -ratio,
to: +1, a co-flow's used stock: -per). Outside inflow pieces keep their times and get new values.
Flows of another kind (era segments, gaps) are held as they are and taken off the changes first.
Rows are weighted by their own noise (a second pass), so a quiet row is not drowned by a loud one.
"""

from __future__ import annotations

import numpy as np

from ...matrix import injected
from ...simulate import Model
from .basis import hats


def r6(v: float) -> float:
    return float(f"{float(v):.6g}")


def _base(rate: dict) -> tuple[str, str | None] | None:
    """('one', None) for a constant rate, ('stock', id) for k x level; None otherwise."""
    form = rate.get("form")
    if form == "constant":
        return "one", None
    if form == "proportional":
        return "stock", rate.get("stock")
    if form == "linear" and not rate.get("c") and len(rate.get("terms") or []) == 1:
        return "stock", rate["terms"][0]["stock"]
    return None


def _columns(f: dict, prev: np.ndarray, idx: dict, tt: np.ndarray) -> tuple[list[np.ndarray], str] | None:
    """The flow's columns (time series) and how to write them back; None to hold it as it is."""
    if f.get("byTime") or f.get("via"):
        return None
    if any(s not in idx for s in (f.get("from"), f.get("to")) if s):
        return None
    rate = f.get("rate") or {}
    if f.get("hat"):
        b = _base(rate)
        if b is None or f["hat"]["stock"] not in idx:
            return None
        base = np.ones(prev.shape[1]) if b[0] == "one" else prev[idx[b[1]]]
        H = hats(prev[idx[f["hat"]["stock"]]], np.asarray(f["hat"]["knots"], dtype=float))
        return [base * h for h in H], "hat"
    if f.get("effects"):
        return None
    if f.get("inflow"):
        cols = []
        for g in f["inflow"]:
            cols.append(((tt >= g["from"]) & (tt <= g["to"])).astype(float))
        # a time no piece covers takes the last piece
        covered = np.sum(cols, axis=0) > 0
        if len(cols):
            cols[-1] = np.where(covered, cols[-1], 1.0)
        # pieces of one pool (pool_pieces) share a value: one column
        pools = _pools(f)
        return [np.sum([cols[i] for i in members], axis=0) for members in pools], "inflow"
    form = rate.get("form")
    if form == "constant":
        return [np.ones(prev.shape[1])], "constant"
    if form == "proportional" and rate.get("stock") in idx:
        return [prev[idx[rate["stock"]]]], "proportional"
    if form == "linear" and all(x.get("stock") in idx for x in rate.get("terms") or []):
        cols = [prev[idx[x["stock"]]] for x in rate.get("terms") or []]
        if rate.get("c"):
            cols = [np.ones(prev.shape[1])] + cols
        return cols, "linear"
    return None


def _repers(X, owned, spans, theta, res, pers, idx, S, T, use):
    X = X.copy()
    for q, ((f, _), (a, b, _)) in enumerate(zip(owned, spans)):
        if not pers[q]:
            continue
        cols = X[:, a:b]
        st = _stoich(f, idx, S)
        # the flow's amount per step: its columns in a row it enters with a known sign
        r0 = int(np.flatnonzero((st != 0) & ~np.isin(np.arange(S), [idx[u["stock"]] for u in f["uses"] if u.get("stock") in idx]))[0])
        amount = (cols.reshape(S, T, -1)[r0] @ theta[a:b]) / st[r0]
        for k, u in enumerate(f["uses"]):
            if u.get("stock") not in idx:
                continue
            j = idx[u["stock"]]
            aa = float((amount * amount * use) @ np.ones(T))
            if aa <= 1e-12:
                continue
            new = max(0.0, pers[q][k] + float(((-res[j]) * amount * use).sum()) / aa)
            block = cols.reshape(S, T, -1)
            unit = block[r0] / st[r0]
            block[j] = block[j] + (pers[q][k] - new) * unit
            pers[q][k] = new
            X[:, a:b] = block.reshape(S * T, -1)
            cols = X[:, a:b]
    return X


def _pools(f: dict) -> list[list[int]]:
    """The pieces of an outside inflow grouped by their pool (each its own without one)."""
    groups: dict = {}
    for i, g in enumerate(f["inflow"]):
        groups.setdefault(g.get("pool", ("own", i)), []).append(i)
    return list(groups.values())


def _stoich(f: dict, idx: dict, S: int) -> np.ndarray:
    v = np.zeros(S)
    if f.get("from") in idx:
        v[idx[f["from"]]] -= float(f.get("ratio") or 1)
    if f.get("to") in idx:
        v[idx[f["to"]]] += 1.0
    for u in f.get("uses") or []:
        if u.get("stock") in idx:
            v[idx[u["stock"]]] -= float(u.get("per") or 0)
    return v


def _write(f: dict, how: str, theta: np.ndarray, prev: np.ndarray, idx: dict) -> dict:
    rate = dict(f.get("rate") or {})
    if how == "hat":
        kn = np.asarray(f["hat"]["knots"], dtype=float)
        x = prev[idx[f["hat"]["stock"]]]
        ref = float(np.interp(float(np.mean(x)), kn, theta))
        if abs(ref) < 1e-9 * max(1e-12, float(np.max(np.abs(theta)))) or abs(ref) < 1e-12:
            ref = float(np.max(np.abs(theta))) or 1.0
        pts = [[r6(a), r6(w / ref)] for a, w in zip(kn, theta)]
        if rate.get("form") == "constant":
            rate["value"] = r6(ref)
        elif rate.get("form") == "proportional":
            rate["k"] = r6(ref)
        else:
            rate["terms"] = [{**rate["terms"][0], "k": r6(ref)}]
        eff = {"stock": f["hat"]["stock"], "shape": "table", "points": pts}
        return {**f, "rate": rate, "rates": [rate], "effects": [eff], "hat": {**f["hat"], "weights": [float(w) for w in theta]}}
    if how == "inflow":
        value = {}
        for v, members in zip(theta, _pools(f)):
            for i in members:
                value[i] = float(v)
        pieces = [{**g, "value": value[i]} for i, g in enumerate(f["inflow"])]
        theta = np.array([value[i] for i in range(len(pieces))])
        lens = np.array([max(1, g["to"] - g["from"] + 1) for g in pieces], dtype=float)
        rate = {**rate, "form": "constant", "value": r6(float(np.dot(lens, theta) / lens.sum()))}
        return {**f, "inflow": pieces, "rate": rate, "rates": [rate]}
    if how == "constant":
        rate["value"] = r6(theta[0])
    elif how == "proportional":
        rate["k"] = r6(theta[0])
    else:
        th = list(theta)
        if rate.get("c"):
            rate["c"] = r6(th.pop(0))
        rate["terms"] = [{**x, "k": r6(k)} for x, k in zip(rate.get("terms") or [], th)]
    return {**f, "rate": rate, "rates": [rate]}


def refit(flows: list[dict], ids: list[str], run: dict, opts: dict | None = None) -> tuple[list[dict], dict]:
    """The flows with every number they own refitted jointly; and {rss (per row), sigma, params}."""
    opts = opts or {}
    idx = {s: i for i, s in enumerate(ids)}
    S = len(ids)
    t = run["t"]
    lv = np.nan_to_num(np.array([np.asarray(run["levels"][i], dtype=float) for i in ids]))
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    if opts.get("injections"):
        inj = injected(opts["injections"], ids, t)[:, 1:]
        prev, dy = prev + inj, dy - inj
    tt = np.asarray(t, dtype=float)[1:]
    T = prev.shape[1]
    held, owned = [], []
    for f in flows:
        c = _columns(f, prev, idx, tt)
        (held if c is None else owned).append((f, c))
    target = dy.copy()
    if held:
        hf = [f for f, _ in held]
        target = target - (Model(hf, ids).step(prev, tt) - prev)
    blocks, spans = [], []
    for f, (cols, how) in owned:
        st = _stoich(f, idx, S)
        start = len(blocks)
        for c in cols:
            blocks.append(np.outer(st, c).reshape(-1))      # stocks x steps, stacked by stock
        spans.append((start, len(blocks), how))
    if not blocks:
        return flows, {"rss": (target ** 2).sum(axis=1), "params": 0, "res": target}
    X = np.array(blocks).T                                   # (S*T) x P
    y = target.reshape(-1)
    w = np.ones(S)
    pers = [[float(u.get("per") or 0) for u in (f.get("uses") or [])] for f, _ in owned]
    # steps left out of the fit (opts["skip"]: a boolean per step), and (opts["guard"]: g) the steps
    # within g of a change in an outside inflow: where a change's step is uncertain by a step or two,
    # those steps decide a drain's number more than all the others (a cut one step late reads it 10%
    # faster), so they are left to the pieces alone
    skip = np.zeros(T, dtype=bool) if opts.get("skip") is None else np.asarray(opts["skip"], dtype=bool).copy()
    if opts.get("guard"):
        g = int(opts["guard"])
        for f in flows:
            segs = f.get("inflow") or []
            for a, b in zip(segs, segs[1:]):
                if a.get("pool") is None or a.get("pool") != b.get("pool"):
                    skip |= (tt >= b["from"] - g) & (tt <= b["from"] + g - 1)
    if skip.mean() > 0.5:
        skip[:] = False
    use = (~skip).astype(float)
    theta = None
    coflow = any(pers_f for pers_f in pers) and opts.get("coflow_per", True)
    for it in range((2 if opts.get("weighted", True) else 1) + (3 if coflow else 0)):
        W = np.repeat(w, T) * np.tile(use, S)
        theta = np.linalg.lstsq(X * W[:, None], y * W, rcond=None)[0]
        res = (y - X @ theta).reshape(S, T)
        sig = np.sqrt((res ** 2 * use).sum(axis=1) / max(1.0, use.sum()))
        floor = max(1e-9, 1e-3 * float(np.median(sig[sig > 0])) if np.any(sig > 0) else 1e-9)
        w = 1.0 / np.maximum(sig, floor)
        if coflow:
            # a co-flow's per (how much of the used stock goes with each unit moved) is a number of
            # the stoichiometry, not of the rate: re-read it from the used stock's row, then refit
            X = _repers(X, owned, spans, theta, res, pers, idx, S, T, use)
    out = []
    oi = 0
    for f in flows:
        if any(f is g for g, _ in held):
            out.append(f)
            continue
        a, b, how = spans[oi]
        g = _write(f, how, theta[a:b], prev, idx)
        if pers[oi]:
            g = {**g, "uses": [{**u, "per": r6(p)} for u, p in zip(f["uses"], pers[oi])]}
        out.append(g)
        oi += 1
    res = (y - X @ theta).reshape(S, T)
    return out, {"rss": (res ** 2).sum(axis=1), "params": X.shape[1], "res": res}


def prune(flows: list[dict], ids: list[str], run: dict, opts: dict | None = None, score=None) -> list[dict]:
    """Flows dropped one at a time, refitting the rest jointly, while the model's price falls
    (score(flows), lower is better: by default the one-step BIC over every row). An effect flow and
    a stock's only outside inflow are dropped like any other flow."""
    score = score or (lambda fl: price(fl, ids, run))
    cur = flows
    best = score(cur)
    while len(cur) > 1:
        trial = None
        for i in range(len(cur)):
            fl, _ = refit(cur[:i] + cur[i + 1:], ids, run, opts)
            s = score(fl)
            if s < best and (trial is None or s < trial[0]):
                trial = (s, fl)
        if trial is None:
            break
        best, cur = trial
    return cur


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


def price(flows: list[dict], ids: list[str], run: dict) -> float:
    """onestep.bic with size() above: every row's one-step fit, every number costs log T."""
    import math

    from ...simulate import levels_array

    A = levels_array(run["levels"], ids)
    T = A.shape[1] - 1
    if T < 2:
        return float("inf")
    nxt = Model(flows, ids).step(A[:, :-1], np.asarray(run["t"], dtype=float)[1:])
    rss = ((nxt - A[:, 1:]) ** 2).sum(axis=1)
    return float(sum(T * math.log(max(r, 1e-9) / T) for r in rss) + size(flows) * math.log(T))

