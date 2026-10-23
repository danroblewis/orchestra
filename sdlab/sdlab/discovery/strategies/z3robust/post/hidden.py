"""(Copied from milp's hidden.py at a72bb0d for z3robust, post/__init__.py: flow ids "z3robust:", debug flag Z3ROBUST_DEBUG.)

A hidden integrator read by a measured stock's outside inflow (k8s-310, 2026-10-21; the user: "credit a
strategy's hidden stock", a schedule standing in for hidden state is "fits", not robust).

A stock's inflow may read something nothing measures: a memory leak that grows a fixed amount a step and
is freed when the pods holding it are killed. The program's columns are the measured levels, so it writes
such an inflow as a schedule (constants stepping at change points) and bends the stock's drain to make up
for what the steps miss.

The mechanism, the same for every stock S with an outside inflow side declared "estimate":
- the row's target is S's change less every flow on S other than its own outside flows;
- a hidden stock H (filled from outside at 1 a step: its scale is free, so the inflow's coefficient on H
  carries it) drains by a per-step fraction E: none (a ramp), a constant a (scanned, then polished), or the
  per-unit rate of a flow already in the model whose rate is proportional to its own measured source
  (with its effects): H leaves with what leaves that source, as the leak goes with the killed pods. H's
  level is stepped from 0 on the measured levels;
- the inflow is linear in H and columns chosen by forward selection (BIC) over the constant, the measured
  levels and inputs, and per-unit ratios X / max(1, Y) of measured stocks; S's own drain (where its outside
  outflow side is declared) is fitted with it. The same selection without H is a candidate too, so a
  hidden stock is written only where it beats every model without one;
- the best candidate replaces S's outside flows when its BIC over S's row beats theirs (each schedule
  piece's numbers counted) by more than MARGIN and it explains at least SHARE of what they leave.
Written as flows `outside -> H` (constant 1), `H -> outside` (proportional to H, with the source flow's
effects), `outside -> S` (linear, or an expression for ratios) and `S -> outside`.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize_scalar

from .hinge import _amount, _env, _resolution
from .steps import Steps

MARGIN = 10.0        # BIC units the hidden model must win by
SHARE = 0.5          # and it explains at least this share of the current misfit
QUIET = 0.01         # a row whose misfit is within this share of its noise is left alone (models of one row on the
                     # same steps differ by far less than the noise's own spread, so BIC decides above it)
MAX_COLS = 8         # columns forward selection adds at most
A_GRID = np.logspace(-4, 0, 13)
DEBUG = bool(__import__("os").environ.get("Z3ROBUST_DEBUG"))


def _num(v: float) -> float:
    return float(f"{v:.6g}")


def _numbers(f: dict) -> int:
    """The numbers a flow carries (each schedule segment's)."""
    def n(r):
        r = r or {}
        if r.get("form") == "linear":
            return len(r.get("terms") or []) + (1 if r.get("c") else 0)
        return 1
    segs = f.get("byTime") or [{"rate": f.get("rate")}]
    return sum(n(g.get("rate")) for g in segs) + sum(len(e.get("points") or []) for e in f.get("effects") or [])


def _integrate(E: np.ndarray | None) -> np.ndarray:
    """H_k with H_0 = 0 and H_{k+1} = H_k + 1 - E_k H_k (H read by step k is H_k)."""
    T = len(E) if E is not None else 0
    H = np.zeros(T)
    for k in range(T - 1):
        H[k + 1] = max(0.0, H[k] + 1.0 - (E[k] * H[k]))
    return H


def _select(y: np.ndarray, base: list, pool: list, floor2: float) -> tuple[float, list, np.ndarray, np.ndarray]:
    """Forward selection by BIC: the base columns always, pool columns added while BIC falls.
    (bic, chosen pool indexes, coefficients over base + chosen, residual)."""
    n = len(y)

    def fit(cols):
        A = np.column_stack(cols)
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
        e = y - A @ beta
        rss = max(float(e @ e), n * floor2)
        return n * np.log(rss / n) + A.shape[1] * np.log(n), beta, e

    chosen: list = []
    best = fit(base)
    for _ in range(MAX_COLS):
        trial = None
        for j, c in enumerate(pool):
            if j in chosen:
                continue
            r = fit(base + [pool[i] for i in chosen] + [c])
            if trial is None or r[0] < trial[0][0]:
                trial = (r, j)
        if trial is None or trial[0][0] >= best[0] - 2.0:
            break
        chosen.append(trial[1])
        best = trial[0]
    return best[0], chosen, best[1], best[2]


def _scaled(effects: list, s: float, dx: float) -> list:
    """Table effects with every point's value times s and its level shifted by dx."""
    return [{**e, "points": [[_num(float(x) + dx), _num(float(y) * s)] for x, y in e["points"]]}
            if e.get("shape") == "table" and e.get("points") else dict(e) for e in effects]


def _polish(src: dict, st: Steps, env: dict, target: np.ndarray, base: list, chosen: list, floor2: float):
    """The drain's tables (borrowed from src, a flow proportional to its source) refitted on S's row: one value
    scale and one level shift for all of them (Nelder-Mead), the inflow's chosen columns held. (polished effects,
    (bic, coefficients, residual, H)) or (None, None)."""
    from scipy.optimize import minimize

    lv = env[src["from"]]
    n = len(target)
    span = float(np.ptp(np.concatenate([np.asarray(env[e["stock"]], float) for e in src["effects"] if e.get("stock") in env]) if src["effects"] else [1.0])) or 1.0

    def run(p):
        eff = _scaled(src["effects"], float(np.exp(p[0])), float(p[1]) * span)
        amt = _amount({**src, "effects": eff}, st, env)
        if amt is None:
            return None
        E = np.where(lv > 1e-9, amt / np.maximum(lv, 1e-9), 0.0)
        H = _integrate(E)
        A = np.column_stack(base[0] + [H] + chosen)
        beta, *_ = np.linalg.lstsq(A, target, rcond=None)
        e = target - A @ beta
        rss = max(float(e @ e), n * floor2)
        return n * np.log(rss / n) + (A.shape[1] + 2) * np.log(n), beta, e, H, eff

    def cost(p):
        r = run(p)
        return np.inf if r is None else r[0]

    m = minimize(cost, np.zeros(2), method="Nelder-Mead", options={"xatol": 1e-6, "fatol": 1e-6, "maxiter": 400,
                                                                       "initial_simplex": [[0, 0], [0.05, 0], [0, 0.01]]})
    r = run(m.x)
    if r is None:
        return None, None
    # the coefficients in the caller's order: base columns, then H, then the chosen ones (as _select orders them)
    k = len(base[0])
    beta = np.r_[r[1][:k], r[1][k], r[1][k + 1:]]
    return r[4], (r[0], beta, r[2], r[3])


def refine(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None, skip=()) -> tuple[list[dict], dict]:
    opts = opts or {}
    bd = run.get("boundary") or {}
    if not run.get("boundary_declared"):
        return flows, {}
    st = Steps(stocks, run, opts)
    if st.T < 20:
        return flows, {}
    env = _env(st)
    pos = {s: i for i, s in enumerate(st.ids)}
    measured = [s for s in st.ids if s not in st.final]
    notes: list = []
    out = list(flows)
    for S in st.ids:
        if S in st.final or S in (skip or ()) or "estimate" not in ((bd.get(S) or {}).get("in") or []):
            continue
        has_out = "estimate" in ((bd.get(S) or {}).get("out") or [])
        own = [i for i, f in enumerate(out) if (f.get("from") is None and f.get("to") == S) or (has_out and f.get("from") == S and f.get("to") is None)]
        amounts = [_amount(f, st, env) for f in out]
        if any(amounts[i] is None for i in range(len(out))):
            return out, {"note": "a flow could not be evaluated"}
        j = pos[S]
        target = st.dy[j].copy()
        for i, f in enumerate(out):
            if i in own:
                continue
            if f.get("from") == S:
                target += amounts[i]
            if f.get("to") == S:
                target -= amounts[i]
        cur = target - sum((amounts[i] if out[i].get("to") == S else -amounts[i]) for i in own) if own else target
        n = st.T
        res = _resolution(np.asarray(run["levels"][S], dtype=float))
        floor2 = max((res / np.sqrt(6.0)) ** 2, (1e-6 * float(np.mean(np.abs(st.L[j])) + 1e-12)) ** 2)
        p_cur = sum(_numbers(out[i]) for i in own)
        bic_cur = n * np.log(max(float(cur @ cur), n * floor2) / n) + p_cur * np.log(n)
        rss_cur = float(cur @ cur)
        noise = n * floor2                                   # the misfit no model explains: the levels' rounding, and for
        if st.counts:                                        # counts the Poisson scatter of what moves through S in a step
            gross = sum(np.abs(amounts[i]) for i, f in enumerate(out) if S in (f.get("from"), f.get("to")))
            noise = max(noise, float(np.sum(gross)))
        if DEBUG:
            print("hidden", S, "rss", rss_cur, "noise", noise, "n", n)
        if rss_cur <= noise * (1 + QUIET):                   # the row is explained to its noise: nothing to look for (a time saver)
            continue
        # the drains H may have
        drains: list = [("none", None, None)]
        for i, f in enumerate(out):
            r = f.get("rate") or {}
            src = f.get("from")
            if src in pos and src != S and not f.get("byTime") and r.get("form") == "proportional" and r.get("stock") == src:
                lv = st.L[pos[src]]
                E = np.where(lv > 1e-9, amounts[i] / np.maximum(lv, 1e-9), 0.0)
                if np.max(E) > 0 and not any(d[1] is not None and np.allclose(d[1], E) for d in drains):
                    drains.append(("flow", E, i))
        # the inflow's columns
        pool, names = [np.ones(n)], [("c", None)]
        for s in measured + sorted(st.inputs):
            if s == S:
                continue
            pool.append(st.series(s))
            names.append(("x", s))
        for a in measured:
            for b in measured:
                if a != b and a != S and b != S:
                    pool.append(st.series(a) / np.maximum(1.0, st.series(b)))
                    names.append(("r", (a, b)))
        drain_col = [-st.L[j]] if has_out else []

        def candidate(E):
            if E is None:                      # no hidden stock
                bic, ch, beta, e = _select(target, drain_col + [pool[0]], pool[1:], floor2)
                return bic, [0] + [c + 1 for c in ch], beta, e, None
            H = _integrate(E)
            if np.ptp(H) <= 0:
                return None
            bic, ch, beta, e = _select(target, drain_col + [pool[0], H], pool[1:], floor2)
            return bic, [0] + [c + 1 for c in ch], beta, e, H

        tried = []
        r = candidate(None)
        tried.append((r[0], "no hidden stock", None, r))
        for kind, E, i in drains:
            if kind == "none":
                E = np.zeros(n)
            r = candidate(E)
            if r is not None:
                tried.append((r[0], kind, (E, i), r))
        # a constant drain: scanned, then polished on the best's columns
        scan = [(candidate(np.full(n, a)), a) for a in A_GRID]
        scan = [(r, a) for r, a in scan if r is not None]
        if scan:
            r0, a0 = min(scan, key=lambda z: z[0][0])
            k = list(A_GRID).index(a0)
            lo, hi = A_GRID[max(0, k - 1)], A_GRID[min(len(A_GRID) - 1, k + 1)]
            m = minimize_scalar(lambda la: (lambda r: r[0] if r else np.inf)(candidate(np.full(n, np.exp(la)))),
                                bounds=(np.log(lo), np.log(hi)), method="bounded", options={"xatol": 1e-4})
            a = float(np.exp(m.x))
            r = candidate(np.full(n, a))
            if r is not None and r[0] < r0[0]:
                r0, a0 = r, a
            tried.append((r0[0], "constant", (np.full(n, a0), a0), r0))
        tried.sort(key=lambda z: z[0])
        bic, kind, info, (bic_, cols, beta, e, H) = tried[0]
        effects = None
        if kind == "flow" and out[info[1]].get("effects"):     # the borrowed drain's tables polished on S's own row,
            src = out[info[1]]                                  # then the inflow's columns chosen again on the polished H
            for _ in range(2):
                eff, r = _polish(src, st, env, target, [drain_col + [pool[0]]], [pool[c] for c in cols[1:]], floor2)
                if r is None or r[0] >= bic:
                    break
                src, effects = {**src, "effects": eff}, eff
                b2, ch, beta, e = _select(target, drain_col + [pool[0], r[3]], pool[1:], floor2)
                bic, cols, H = b2 + 2 * np.log(n), [0] + [c + 1 for c in ch], r[3]
        if DEBUG:
            print("hidden", S, "current", round(bic_cur, 1), p_cur, [(round(t[0], 1), t[1]) for t in tried[:6]])
        rss_new = float(e @ e)
        excess = max(rss_cur - noise, 1e-300)
        if DEBUG:
            print("hidden", S, "decide", round(bic, 1), round(bic_cur, 1), "rss", rss_cur, rss_new, "noise", noise)
        if bic >= bic_cur - MARGIN or rss_cur - rss_new < SHARE * excess or H is None:
            notes.append({"stock": S, "kept": False, "bic": round(bic, 1), "current": round(bic_cur, 1), "best": kind})
            continue
        # write it
        hname = f"{S}_hidden"
        while hname in pos:
            hname += "_"
        k0 = len(drain_col)
        a_drain = float(beta[0]) if has_out else None
        c0, g = float(beta[k0]), float(beta[k0 + 1])
        if g <= 0:
            notes.append({"stock": S, "kept": False, "note": "the inflow reads its hidden stock negatively"})
            continue
        terms, ratios = [(hname, g)], []
        for c, b in zip(cols[1:], beta[k0 + 2:]):
            what, x = names[c]
            if what == "x":
                terms.append((x, float(b)))
            else:
                ratios.append((x, float(b)))
        if ratios:
            parts = [f"{_num(c0):g}"] + [f"{_num(b):g} * {x}" for x, b in terms] + [f"{_num(b):g} * {a} / max(1, {d})" for (a, d), b in ratios]
            rate_in = {"form": "expr", "expr": " + ".join(parts).replace("+ -", "- ")}
        else:
            rate_in = {"form": "linear", "c": _num(c0), "terms": [{"stock": x, "k": _num(b)} for x, b in terms]}
        new = [{"from": None, "to": hname, "ratio": 1, "rate": {"form": "constant", "value": 1.0}}]
        if kind == "flow":
            src = out[info[1]]
            eff = effects if effects is not None else [dict(x) for x in src.get("effects") or []]
            new.append({"from": hname, "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": hname, "k": src["rate"]["k"]},
                        **({"effects": eff} if eff else {})})
        elif kind == "constant":
            new.append({"from": hname, "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": hname, "k": _num(info[1])}})
        new.append({"from": None, "to": S, "ratio": 1, "rate": rate_in})
        if has_out and a_drain is not None and a_drain > 0:
            new.append({"from": S, "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": S, "k": _num(a_drain)}})
        out = [f for i, f in enumerate(out) if i not in own] + new
        for n_, f in enumerate(out):
            if not f.get("id"):
                f["id"] = f"z3robust:hidden:{f['from'] or 'outside'}->{f['to'] or 'outside'}:{n_}"
        notes.append({"stock": S, "kept": True, "hidden": hname, "drain": kind, "bic": round(bic, 1), "current": round(bic_cur, 1),
                      "share": round((rss_cur - rss_new) / excess, 4)})
    return out, ({"rows": notes} if notes else {})
