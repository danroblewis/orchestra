"""Effects: a flow's rate multiplied by a curve of a stock's level, found by a constrained search.

SD rates are base equations times effects. The matrix method fits sums of levels, so a flow that
runs at k x A x f(C) is read as links and changing inflows. Here the search is over columns of the
form A x s(C / scale) (A: a measured stock's level, or 1 for a constant rate; C: any measured stock;
s: a curve from the grammar in curves.py): what a row's change leaves unexplained after its levels
(and the pieces of a changing outside inflow) is projected on every such column, and the pairs
(A, C) whose best curve clearly explains it are offered to the matrix method as "virtual stocks"
whose level is A x s(C). A virtual stock is final and of its own unit, so the matrix reads it only
as links into and drains out of real stocks; translate() turns those back into flows of A with an
effect of C (a table sampled from the curve over C's observed range), and pairs a drain with a link
into a stock of the same unit as a move (an effect multiplies a flow: what leaves one stock arrives
in another).
"""

from __future__ import annotations

import math

import numpy as np

from .changes import pelt
from .curves import Curve, grammar
from .regression import demean

SCREEN_STEPS = 4000


def _residualise(Z: np.ndarray, Q: np.ndarray) -> np.ndarray:
    return Z - (Z @ Q) @ Q.T


def screen(stocks: list[dict], run: dict, opts: dict | None = None) -> list[dict]:
    """The (A, C, curve) columns that explain what the rows leave unexplained, chosen greedily (each
    one joins the levels before the next is looked for, so its aliases drop out):
    [{"base": A id or None, "stock": C id, "curve": Curve, "scale", "score", "rows"}]."""
    opts = opts or {}
    ids = [s["id"] for s in stocks]
    S = len(ids)
    lv = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, []), dtype=float) for i in ids]))
    T = lv.shape[1] - 1
    if T < 40 or S < 1:
        return []
    stride = max(1, T // opts.get("screen_steps", SCREEN_STEPS))
    prev, dy = lv[:, :-1][:, ::stride], np.diff(lv, axis=1)[:, ::stride]
    n = prev.shape[1]
    D = [np.ones(n), *prev]
    found, skip = [], set()
    while len(found) < opts.get("most_effects", 3) and len(skip) < 6:
        Q, _ = np.linalg.qr(np.array(D).T)
        f = _scan(stocks, prev, dy, Q, opts, skip)
        if f is None:
            break
        a = np.ones(n) if f["base"] is None else prev[ids.index(f["base"])]
        z = a * f["curve"](prev[ids.index(f["stock"])] / f["scale"])
        # a curve that is really there explains both halves of the data; one that fits a passing
        # stretch (an unannounced change, a transient) does not
        if opts.get("halves", True):
            h = n // 2
            halves = [_gain(np.array(D)[:, sl], dy[:, sl], z[sl]) for sl in (slice(0, h), slice(h, n))]
            f["halves"] = halves
            if min(halves) < max(2 * math.log(h), opts.get("half_share", 0.25) * f["score"]):
                skip.add((f["base"], f["stock"]))
                continue
        found.append(f)
        D.append(z)
    return found


def _gain(D: np.ndarray, dy: np.ndarray, z: np.ndarray) -> float:
    """How much one column explains of the two rows it explains best (as _scan measures it)."""
    Q, _ = np.linalg.qr(D.T)
    R = _residualise(dy, Q)
    zr = z - (z @ Q) @ Q.T
    g = []
    for r in R:
        cuts = pelt(r, 5, 1)
        rd, zd = demean(r, cuts), demean(zr, cuts)
        zz, var = float(zd @ zd), max(1e-12, float((rd ** 2).mean()))
        g.append(float(zd @ rd) ** 2 / zz / var if zz > 1e-12 else 0.0)
    return float(sum(sorted(g)[-2:]))


def _scan(stocks: list[dict], prev: np.ndarray, dy: np.ndarray, Q: np.ndarray, opts: dict, skip: set) -> dict | None:
    ids = [s["id"] for s in stocks]
    S, n = prev.shape
    group = {s["id"]: s.get("group") for s in stocks}
    final = {s["id"] for s in stocks if s.get("final")}
    R = _residualise(dy, Q)
    # each row's changing outside inflow, in fine pieces of what its levels leave unexplained
    cuts = [pelt(R[s], 5, 1) for s in range(S)]
    Rd = np.array([demean(R[s], cuts[s]) for s in range(S)])
    var = np.maximum(1e-12, (Rd ** 2).mean(axis=1))
    log_n = math.log(n)

    def gains_for(a, c, curves, hi):
        """Each row's gain from each curve's column (rows x curves), and the sign of its number."""
        G = np.array([cv(prev[c] / hi) for cv in curves])
        Z = G if a is None else G * prev[a]
        Zr = _residualise(Z, Q)
        zz0 = ((Z - Z.mean(axis=1, keepdims=True)) ** 2).sum(axis=1)
        gains, signs = np.zeros((S, len(curves))), np.zeros((S, len(curves)))
        for s in range(S):
            if ids[s] in final and a == s:
                continue
            Zd = demean(Zr, cuts[s])
            zz = (Zd ** 2).sum(axis=1)
            ok = zz > 1e-6 * np.maximum(zz0, 1e-12)
            zr = Zd @ Rd[s]
            gains[s] = np.where(ok, zr ** 2 / np.where(ok, zz, 1) / var[s], 0.0)
            signs[s] = np.sign(zr)
        # a flow shows in up to two rows (where it leaves, where it arrives)
        return gains, signs, np.sort(gains, axis=0)[::-1][:2].sum(axis=0)

    curves = grammar()
    best = None
    for c in range(S):
        hi = float(np.percentile(prev[c], 99))
        if hi <= 0 or np.ptp(prev[c]) <= 0:
            continue
        for a in [None] + list(range(S)):
            if a is not None and group[ids[a]] and group[ids[c]] and group[ids[a]] != group[ids[c]]:
                continue
            if (None if a is None else ids[a], ids[c]) in skip:
                continue
            _, _, top = gains_for(a, c, curves, hi)
            k = int(np.argmax(top))
            if top[k] > opts.get("screen_gain", 4 * log_n) and (best is None or top[k] > best[0]):
                best = (float(top[k]), a, c, curves[k], hi)
    if best is None:
        return None
    _, a, c, curve, hi = best
    # the shape's parameters, refined around the grammar's grid point
    near = [curve] + [Curve(curve.name, curve.kind, curve.a * fa, curve.b * fb) for fa in (0.6, 0.75, 0.9, 1.1, 1.3, 1.6)
                      for fb in ((0.6, 1, 1.6) if curve.b else (1,)) if opts.get("refine", True) and curve.a]
    gains, signs, top = gains_for(a, c, near, hi)
    k = int(np.argmax(top))
    curve = near[k]
    curve = Curve(f"{curve.kind} {curve.a:.3g}" + (f"/{curve.b:.3g}" if curve.b else ""), curve.kind, curve.a, curve.b) if k else curve
    order = [s for s in np.argsort(-gains[:, k])[:3] if gains[s, k] > 2 * log_n]
    # orientation: the curve is turned over (peak minus curve: the same fit, with the floor
    # column) so that the flow it multiplies leaves its base stock, or arrives where it shows most,
    # with a positive number
    lead = a if a is not None and a in order else order[0] if order else None
    want = -1.0 if a is not None and lead == a else 1.0
    if lead is not None and signs[lead, k] * want < 0:
        curve = curve.turned(float(np.max(curve(prev[c] / hi))))
    return {"base": None if a is None else ids[a], "stock": ids[c], "curve": curve, "scale": hi, "score": float(top[k]), "rows": [ids[s] for s in order]}


def virtual(stocks: list[dict], run: dict, cols: list[dict]) -> tuple[list[dict], dict, dict]:
    """Stocks and run with one virtual stock per column (level A x s(C / scale)), and what each is."""
    group = {s["id"]: s.get("group") for s in stocks}
    levels = dict(run["levels"])
    n = len(run["t"])
    extra, meta = [], {}
    for q, col in enumerate(cols):
        vid = f"~{q}"
        x = np.nan_to_num(np.asarray(run["levels"][col["stock"]], dtype=float))
        a = np.ones(n) if col["base"] is None else np.nan_to_num(np.asarray(run["levels"][col["base"]], dtype=float))
        levels[vid] = list(a * col["curve"](x / col["scale"]))
        extra.append({"id": vid, "unit": f"virtual {vid}", "final": True, "group": group.get(col["base"] or col["stock"])})
        meta[vid] = {**col, "lo": float(np.min(x)), "hi": float(np.max(x))}
    return stocks + extra, {**run, "levels": levels}, meta


def only_rows(meta: dict, ids: list[str], plain: bool = False) -> dict:
    """Where each level may join the matrix: a virtual stock only in the rows the screen saw it in
    (and its base stock's row); unless `plain`, the curved stock's own level stays out of those rows
    (other than its own), since the curve, with its floor, already says how it acts there."""
    out = {v: set(m["rows"]) | ({m["base"]} if m["base"] else set()) for v, m in meta.items()}
    if not plain:
        for m in meta.values():
            c = m["stock"]
            banned = (set(m["rows"]) | ({m["base"]} if m["base"] else set())) - {c}
            out[c] = out.get(c, set(ids)) - banned
    return out


def effect_of(m: dict, points: int = 12) -> tuple[dict, float]:
    """The SD Lab effect a virtual stock's curve stands for, and the factor its number takes (the
    curve sampled over the stock's observed range and scaled to peak at 1)."""
    curve: Curve = m["curve"]
    if curve.kind == "lin":
        return {"stock": m["stock"], "shape": "linear", "normal": r6(m["scale"]), "min": 0, "max": r6(2 * max(1.0, m["hi"] / m["scale"]))}, 1.0
    xs = np.linspace(m["lo"], m["hi"], points)
    g = curve(xs / m["scale"])
    peak = float(np.max(np.abs(g))) or 1.0
    return {"stock": m["stock"], "shape": "table", "points": [[r6(x), r6(v / peak)] for x, v in zip(xs, g)]}, peak


def r6(v: float) -> float:
    return float(f"{float(v):.6g}")


def _vterm(rate: dict, meta: dict) -> tuple[str, float] | None:
    """(virtual stock, number) when a rate is linear in one virtual stock."""
    if rate.get("form") == "linear" and len(rate.get("terms") or []) == 1 and rate["terms"][0]["stock"] in meta and not rate.get("c"):
        return rate["terms"][0]["stock"], float(rate["terms"][0]["k"])
    if rate.get("form") == "proportional" and rate.get("stock") in meta:
        return rate["stock"], float(rate["k"])
    return None


def _base_rate(m: dict, k: float) -> dict:
    if m["base"] is None:
        return {"form": "constant", "value": r6(k)}
    return {"form": "linear", "c": 0, "terms": [{"stock": m["base"], "k": r6(k)}]}


def translate(flows: list[dict], meta: dict, stocks: list[dict]) -> list[dict]:
    """Flows read off a matrix with virtual stocks -> flows of real stocks with effects."""
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    real = [f for f in flows if f.get("from") not in meta and f.get("to") not in meta]
    plain, by_v = [], {}
    for f in real:
        vt = None if f.get("byTime") or f.get("inflow") else _vterm(f.get("rate") or {}, meta)
        if f.get("byTime") and any(_vterm(g["rate"], meta) for g in f["byTime"]):
            vt = next(_vterm(g["rate"], meta) for g in f["byTime"] if _vterm(g["rate"], meta))
            plain.append(_translate_by_time(f, vt[0], meta))
            continue
        if vt is None:
            plain.append(f)
        else:
            by_v.setdefault(vt[0], []).append((f, vt[1]))
    out = list(plain)
    for v, fs in by_v.items():
        m = meta[v]
        effect, peak = effect_of(m)
        outs = [[f, k] for f, k in fs if f.get("to") is None and f.get("from") is not None]
        ins = [[f, k] for f, k in fs if f.get("from") is None and f.get("to") is not None]
        moved = []
        # a drain of the base stock and a link into a stock of its unit are one move
        if m["base"] is not None:
            for o in outs:
                if o[0]["from"] != m["base"]:
                    continue
                for i in sorted(ins, key=lambda i: -i[1]):
                    if unit[i[0]["to"]] == unit[m["base"]] and i[1] > 0 and o[1] > 0:
                        k = min(o[1], i[1])
                        moved.append((m["base"], i[0]["to"], k))
                        o[1] -= k
                        i[1] -= k
        for src, dst, k in moved:
            rate = _base_rate(m, k * peak)
            out.append({"from": src, "to": dst, "ratio": 1, "rate": rate, "rates": [rate], "effects": [effect], "driver": m["base"], "curve": m["curve"].name})
        for f, k in outs + ins:
            if k > 1e-9:
                rate = _base_rate(m, k * peak)
                out.append({**f, "rate": rate, "rates": [rate], "effects": [effect], "driver": m["base"] or m["stock"], "curve": m["curve"].name})
    return merge_floors(out)


def _translate_by_time(f: dict, v: str, meta: dict) -> dict:
    m = meta[v]
    effect, peak = effect_of(m)

    def tr(rate):
        vt = _vterm(rate, meta)
        return _base_rate(m, (vt[1] if vt else 0.0) * peak)

    by_time = [{**g, "rate": tr(g["rate"])} for g in f["byTime"]]
    return {**f, "rate": tr(f["rate"]), "byTime": by_time, "rates": [g["rate"] for g in by_time], "effects": [effect], "driver": m["base"] or m["stock"], "curve": m["curve"].name}


def merge_floors(flows: list[dict]) -> list[dict]:
    """A plain flow k1 x A and a flow k2 x A x g(C) between the same stocks are one flow
    (k1 + k2) x A with the effect's table raised to the floor k1 / (k1 + k2)."""
    def single(f):
        r = f.get("rate") or {}
        if f.get("byTime") or f.get("inflow"):
            return None
        if r.get("form") == "proportional":
            return r.get("stock"), float(r.get("k") or 0)
        if r.get("form") == "linear" and len(r.get("terms") or []) == 1 and not r.get("c"):
            return r["terms"][0]["stock"], float(r["terms"][0]["k"])
        return None

    out = list(flows)
    for e in [f for f in flows if f.get("effects") and len(f["effects"]) == 1 and f["effects"][0]["shape"] == "table"]:
        se = single(e)
        if se is None or e not in out:
            continue
        for p in out:
            if p is e or p.get("effects") or p.get("from") != e.get("from") or p.get("to") != e.get("to"):
                continue
            sp = single(p)
            if sp is None or sp[0] != se[0]:
                continue
            k1, k2 = sp[1], se[1]
            pts = [[x, k1 + k2 * g] for x, g in e["effects"][0]["points"]]
            top = max(v for _, v in pts) or 1.0
            rate = {**e["rate"], "terms": [{"stock": se[0], "k": r6(top)}]} if e["rate"]["form"] == "linear" else {**e["rate"], "k": r6(top)}
            merged = {**e, "rate": rate, "rates": [rate], "effects": [{**e["effects"][0], "points": [[x, r6(v / top)] for x, v in pts]}]}
            out = [merged if f is e else f for f in out if f is not p]
            break
    return out
