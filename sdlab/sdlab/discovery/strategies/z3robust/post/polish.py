"""Every plain flow refitted on every row (k8s-312, 2026-10-22).

The program's numbers are fitted on a sample of the steps beside its own misfits (a capacity read from the wrong level,
a row it could not explain), and each later pass refits only the flows on the rows it touches. So numbers on rows no
pass touches stay a little off (inflight -> responses_total at 0.499986 for 0.5, a move of 0.0006 that is not there),
and an effect search on those rows then fits what they leave (on 312 a slope of 2e-6 on queue's row).

The mechanism: every plain flow (one linear rate: no schedule, no effects, no expression) between measured stocks or
outside, refitted jointly on the one-step changes of every measured stock with the other flows held at their amounts,
the engine's floor at 0 applied (hinge._Fit; a move's number on its own source not negative). Written back when the
BIC over the rows falls (it adds no numbers); a move refitted to nothing is dropped.
"""

from __future__ import annotations

import re

import numpy as np
from scipy.optimize import least_squares

from .hinge import FLOOR, _Fit, _amount, _env, _plain, _rate, _resolution
from .steps import Steps

DEBUG = bool(__import__("os").environ.get("Z3ROBUST_DEBUG"))


_MIN = re.compile(r"^min\(([-\d.e+]+) \* (\w+), ([-\d.e+]+) \* (\w+)\)$")
_ROOM = re.compile(r"^min\(([-\d.e+]+) \* (\w+), max\(0, ([-\d.e+]+) \* (\w+) - (\w+)\)\)$")


def _shaped(f: dict, pos: dict, inputs) -> tuple | None:
    """("min", S, Y, a, b) for min(a * S, b * Y), ("room", S, Y, a, b, D) for min(a * S, max(0, b * Y - D)), else None."""
    if f.get("byTime") or f.get("effects"):
        return None
    e = str((f.get("rate") or {}).get("expr") or "").strip()
    ok = lambda x: x in pos or x in inputs  # noqa: E731
    m = _MIN.match(e)
    if m and ok(m.group(2)) and ok(m.group(4)):
        return ("min", m.group(2), m.group(4), float(m.group(1)), float(m.group(3)))
    m = _ROOM.match(e)
    if m and ok(m.group(2)) and ok(m.group(4)) and m.group(5) in pos:
        return ("room", m.group(2), m.group(4), float(m.group(1)), float(m.group(3)), m.group(5))
    return None


def _tabled(f: dict, pos: dict, inputs) -> tuple | None:
    """(k8s-312 r2) (reader, k, effect stock, knots, heights) for k * reader x table(effect stock): one table effect on a
    proportional rate, else None. Its amount is linear in the table's heights."""
    r = f.get("rate") or {}
    eff = f.get("effects") or []
    if f.get("byTime") or r.get("form") != "proportional" or len(eff) != 1 or eff[0].get("shape") != "table" or not eff[0].get("points"):
        return None
    if r.get("stock") not in pos and r.get("stock") not in inputs or eff[0].get("stock") not in pos:
        return None
    pts = sorted((float(a), float(b)) for a, b in eff[0]["points"])
    return (r["stock"], float(r["k"]), eff[0]["stock"], tuple(p[0] for p in pts), tuple(p[1] for p in pts))


def refine(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None, skip=(), tables: bool = False) -> tuple[list[dict], dict]:
    """tables (k8s-312 r2, joint-polish-tables): also the heights of each table effect (flows that share a table, a
    move and the counter that counts it, share its heights), fitted with the rest: a table polished alone takes
    the misfit of a room or gap next to it, which then bends to fit the table."""
    opts = opts or {}
    st = Steps(stocks, run, opts)
    if st.T < 10 or not st.ids:
        return flows, {}
    env = _env(st)
    pos = {s: i for i, s in enumerate(st.ids)}
    skip = set(skip)
    flows = list(flows or [])
    free_at, free, th0 = [], [], []
    shaped_at, shaped = [], []
    tab_at, tab, tkeys, theights = [], [], [], []           # flows with a table effect, the table each uses; the tables
    fixed = np.zeros_like(st.dy)
    bd = run.get("boundary") or {}
    amounts = [_amount(f, st, env) for f in flows]
    blind = {x for f, a in zip(flows, amounts) if a is None for x in (f.get("from"), f.get("to")) if x in pos}
    skip |= blind                                            # rows a flow on them cannot be run for (a hidden stock's reader): left out
    for i, f in enumerate(flows):
        a, b = f.get("from"), f.get("to")
        ends_ok = all(x is None or x in pos for x in (a, b)) and not ({a, b} & skip)
        held = a is None and "input" in ((bd.get(b) or {}).get("in") or [])   # a declared input inflow is the series itself
        d = _plain(f) if ends_ok and not held else None
        if d is not None and all(r is None or r in pos or r in st.inputs for r in d):
            free_at.append(i)
            free.append((a, b, list(d)))
            th0.append(np.array(list(d.values()), float))
            continue
        sh = _shaped(f, pos, st.inputs) if ends_ok and a in pos and b in pos else None
        if sh is not None:
            shaped_at.append(i)
            shaped.append(sh)
            continue
        tb = _tabled(f, pos, st.inputs) if tables and ends_ok and not held else None
        if tb is not None:
            key = tb[:4]
            if key not in tkeys:
                tkeys.append(key)
                theights.append(tb[4])
            tab_at.append(i)
            tab.append(tkeys.index(key))
            continue
        amt = amounts[i]
        if amt is None:
            continue
        if a in pos:
            fixed[pos[a]] -= amt
        if b in pos:
            fixed[pos[b]] += amt
    if tab and not tables:
        tab_at, tab = [], []
    if not free and not shaped:
        return flows, {}
    tab_base, tfree = [], []
    for j, (key, hs) in enumerate(zip(tkeys, theights)):
        x = np.asarray(env.get(key[2]), float)
        base = np.maximum(0.0, key[1] * np.asarray(st.series(key[0]), float))
        tfree.append([m for m, h in enumerate(hs) if h != 0.0])   # a knot the effect search put at 0 (a flat) stays there
        basis = np.zeros((len(tfree[-1]), st.T))
        for r, m in enumerate(tfree[-1]):                    # the interpolation weight of knot m on each step
            e = np.zeros(len(key[3]))
            e[m] = 1.0
            basis[r] = np.interp(x, key[3], e) * base
        tab_base.append(basis)
    nt = sum(len(h) for h in tfree)
    toff = np.cumsum([0] + [len(h) for h in tfree])
    rows = [pos[s] for s in st.ids if s not in skip]
    scale = np.sqrt(np.mean(st.dy ** 2, axis=1)) + 1e-12
    res = np.zeros(len(st.ids)) if st.counts else np.array([_resolution(st.L[i]) for i in range(len(st.ids))])
    floor = np.maximum(FLOOR, res / np.sqrt(6.0) / scale)
    fit = _Fit(st, rows, fixed, scale, floor)
    nf = sum(len(r) for _, _, r in free)

    def shaped_net(p):
        out = np.zeros_like(st.dy)
        for j, sh in enumerate(shaped):
            x, y = st.series(sh[1]), st.series(sh[2])
            a, b = p[2 * j], p[2 * j + 1]
            amt = np.minimum(a * x, b * y) if sh[0] == "min" else np.minimum(a * x, np.maximum(0.0, b * y - st.series(sh[5])))
            src, dst = flows[shaped_at[j]]["from"], flows[shaped_at[j]]["to"]
            out[pos[src]] -= amt
            out[pos[dst]] += amt
        return out

    def table_net(p):
        out = np.zeros_like(st.dy)
        for i, j in zip(tab_at, tab):
            amt = np.maximum(0.0, p[toff[j]:toff[j + 1]]) @ tab_base[j]
            src, dst = flows[i].get("from"), flows[i].get("to")
            if src in pos:
                out[pos[src]] -= amt
            if dst in pos:
                out[pos[dst]] += amt
        return out

    ns = 2 * len(shaped)

    def resid(th):
        e = (st.dy - fit.predict(free, th[:nf]) - shaped_net(th[nf:nf + ns]) - (table_net(th[nf + ns:]) if tab else 0.0))[rows]
        return (e / scale[rows, None]).ravel()

    def bic(th):
        e = resid(th).reshape(len(rows), st.T)
        rss = np.maximum(np.sum(e * e, axis=1), st.T * floor[rows] ** 2)
        return float(np.sum(st.T * np.log(rss / st.T)))

    t0 = np.concatenate(th0 + [np.array([v for sh in shaped for v in sh[3:5]], float)]
                        + [np.array([h[m] for h, fr in zip(theights, tfree) for m in fr], float) if tab else np.zeros(0)])
    lo = np.r_[[0.0 if (x in pos and y in pos and r == x) else -np.inf for x, y, rd in free for r in rd], np.full(2 * len(shaped), 1e-12),
               np.zeros(nt if tab else 0)]
    t0 = np.maximum(np.where(np.isfinite(t0), t0, 0.0), lo + 1e-12 * np.isfinite(lo))
    b0 = bic(t0)
    r = least_squares(resid, t0, method="trf", x_scale="jac", max_nfev=400, bounds=(lo, np.full(len(lo), np.inf)),
                      ftol=1e-15, xtol=1e-15, gtol=1e-15)
    th = r.x
    b1 = bic(th)
    if DEBUG:
        print("polish", round(b0, 1), "->", round(b1, 1), len(t0))
    if not b1 < b0:
        return flows, {}
    out, n, drop = [dict(f) for f in flows], 0, set()
    for i, (a, b, rd) in zip(free_at, free):
        rr = _rate({x: float(v) for x, v in zip(rd, th[n:n + len(rd)])})
        n += len(rd)
        if rr.get("form") == "constant" and not rr.get("value") and a is not None and b is not None:
            drop.add(i)
            continue
        out[i] = {**out[i], "rate": rr}
    for j, (i, sh) in enumerate(zip(shaped_at, shaped)):
        a, b = _num(float(th[nf + 2 * j])), _num(float(th[nf + 2 * j + 1]))
        expr = f"min({a!r} * {sh[1]}, {b!r} * {sh[2]})" if sh[0] == "min" else f"min({a!r} * {sh[1]}, max(0, {b!r} * {sh[2]} - {sh[5]}))"
        out[i] = {**out[i], "rate": {"form": "expr", "expr": expr}}
        if sh[0] == "room" and out[i].get("room_fit"):
            out[i]["room_fit"] = {**out[i]["room_fit"], "a": float(th[nf + 2 * j]), "b": float(th[nf + 2 * j + 1])}
    for i, j in zip(tab_at, tab):
        key, hs = tkeys[j], list(theights[j])
        for m, h in zip(tfree[j], th[nf + ns + toff[j]:nf + ns + toff[j + 1]]):
            hs[m] = float(h)
        e = dict(out[i]["effects"][0])
        e["points"] = [[_num(float(k)), _num(float(max(0.0, h)))] for k, h in zip(key[3], hs)]
        out[i] = {**out[i], "effects": [e]}
    out = [f for i, f in enumerate(out) if i not in drop]
    return out, {"bic": [round(b0, 1), round(b1, 1)], "numbers": int(len(t0)), "shaped": len(shaped), "tables": len(tkeys) if tab else 0,
                 "dropped": len(drop)}


def _num(v: float) -> float:
    return float(f"{v:.6g}")
