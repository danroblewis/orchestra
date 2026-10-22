# sindy's copy of engine_forms/hidden.py at 2bca23f (rule 11: copied, never imported; port-sindy, 2026-10-22).
"""A row that reads a hidden integrator, written as the model's own hidden stock (k8s-310 round 1,
docs/research/fixes/310-engine_forms.md).

Since 2026-10-21 (the user) the scorer credits a found model's own hidden stock (sdlab/ladder/hidden_match.py),
so a stock nothing scrapes can be written as a stock instead of a time schedule (a schedule standing in for
hidden state is "fits", not robust).

Where the levels are exact and a measured stock S's one-step change is still not reproduced by the answer, S's
outside sides are read again from its row (its moves in the answer kept as they are):

    dS = c + sum_j k_j X_j + k_r X_a / max(1, X_b) + b H,       H' = 1 - g H

- X_j: the measured levels and inputs (S's own level among them);
- at most one per-unit column X_a / max(1, X_b) (X_b a measured stock that is never negative);
- H a hidden stock filled at a constant rate (1 a step; its scale is b's) and drained by g, one of: nothing, a
  constant fraction (a grid, refined by golden section), or the per-unit fraction of a flow of the answer that
  carries an effect table (k x prod effects: e.g. the share of pods an OOM kill takes, which frees their leak).
  For a given g, H is linear in its unknown start and its inflow, so the row reads two columns (h0, h1).

The smallest such row that reproduces every step to the data's rounding (backward elimination from all
columns, the hidden pair and the per-unit column kept as groups) is written as: one inflow on S's outside side
(an expression when it reads the per-unit column or H), one outflow (the negative terms, linear), the hidden
stock's inflow (constant 1), its drain (g's form), with H's start left to the data (b x h0's coefficient). Kept
only when the hidden pair is needed (without it no row is exact), when S's declared boundary has the sides it
writes, and when the written flows, evaluated here as the engine floors them, reproduce the row. Data with
noise are left alone (no row is reproduced to its rounding). Reads only the levels, inputs, units, boundary
and the answer's own flows. Runs last (the strategy's own simulator does not step a hidden stock or an
expression).
"""

from __future__ import annotations

import copy
import math

import numpy as np

from . import boundary as _boundary
from .reread import _quantum, _Rows

DECAYS = 20            # constant drain fractions on the grid (log-spaced), and 0
NAME = "hidden_"       # the hidden stock's name: hidden_<S>


def _effect(e: dict, data: _boundary.Data, extra: dict) -> np.ndarray | None:
    col = _col(e.get("stock"), data, extra)
    if col is None or e.get("shape") != "table" or not e.get("points"):
        return None
    pts = sorted((float(a), float(b)) for a, b in e["points"])
    return np.interp(col, [p[0] for p in pts], [p[1] for p in pts])


def _col(name, data: _boundary.Data, extra: dict) -> np.ndarray | None:
    if name in data.ids:
        return data.L[data.ids.index(name)]
    return extra.get(name)


def _drains(flows: list[dict], data: _boundary.Data, extra: dict) -> list[tuple[str, np.ndarray, dict]]:
    """(label, g per step, the drain's rate and effects for H) for each drain tried."""
    out = [("none", np.zeros(data.T), None)]
    seen = []
    for f in flows:
        r = f.get("rate") or {}
        if not f.get("effects") or r.get("form") != "proportional":
            continue
        g = np.full(data.T, float(r.get("k") or 0.0))
        for e in f["effects"]:
            v = _effect(e, data, extra)
            if v is None:
                g = None
                break
            g = g * v
        if g is None or not np.any(g > 0) or any(np.allclose(g, s) for s in seen):
            continue
        seen.append(g)
        out.append((f"fraction of {f.get('from')} -> {f.get('to')}", g,
                    {"rate": {"form": "proportional", "k": float(r.get("k") or 0.0)}, "effects": copy.deepcopy(f["effects"])}))
    return out


def _integrator(g: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(response to a unit start, response to a unit inflow a step) of h_{k+1} = h_k + 1 - g_k h_k, at each step's start."""
    T = len(g)
    m = np.clip(1.0 - g, 0.0, None)
    h0, h1 = np.empty(T), np.empty(T)
    x0, x1 = 1.0, 0.0
    for k in range(T):
        h0[k], h1[k] = x0, x1
        x0, x1 = x0 * m[k], x1 * m[k] + 1.0
    return h0, h1


def _lstsq(A: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    k, *_ = np.linalg.lstsq(A, y, rcond=None)
    r = y - A @ k
    return k, float(np.sqrt(np.mean(r ** 2)))


def _smallest(groups: list[list[int]], keep: set[int], Z: np.ndarray, y: np.ndarray, ok) -> list[int] | None:
    """Backward elimination over column groups (indices into Z's columns): drop the group whose removal keeps
    the row exact with the smallest residual, until none can go; groups in `keep` stay. The columns kept, or
    None when all of them do not reproduce y."""
    live = list(range(len(groups)))
    cols = lambda gs: [c for g in gs for c in groups[g]]   # noqa: E731
    k, rms = _lstsq(Z[:, cols(live)], y)
    if not ok(rms, k):
        return None
    while True:
        best = None
        for g in live:
            if g in keep:
                continue
            rest = [x for x in live if x != g]
            if not rest:
                continue
            k, rms = _lstsq(Z[:, cols(rest)], y)
            if ok(rms, k) and (best is None or rms < best[0]):
                best = (rms, g)
        if best is None:
            return cols(live)
        live.remove(best[1])


def _golden(f, a: float, b: float, rounds: int = 40) -> float:
    gr = (math.sqrt(5) - 1) / 2
    c1, c2 = b - gr * (b - a), a + gr * (b - a)
    f1, f2 = f(c1), f(c2)
    for _ in range(rounds):
        if f1 < f2:
            b, c2, f2 = c2, c1, f1
            c1 = b - gr * (b - a)
            f1 = f(c1)
        else:
            a, c1, f1 = c1, c2, f2
            c2 = a + gr * (b - a)
            f2 = f(c2)
    return (a + b) / 2


def _ratio_expr(a: str, b: str) -> str:
    return f"{a} / max(1, {b})"


def _evaluate(expr: str, env: dict, T: int) -> np.ndarray:
    out = np.empty(T)
    fns = {"max": max, "min": min, "ceil": math.ceil, "floor": math.floor, "abs": abs}
    for k in range(T):
        out[k] = max(0.0, float(eval(expr, {"__builtins__": {}}, {**fns, **{n: v[k] for n, v in env.items()}})))
    return out


def _change(flows: list[dict], data: _boundary.Data, extra: dict) -> np.ndarray:
    """Each stock's one-step change under these flows: the strategy's simulator, with expression rates (a MIN
    written back, a controller's rule) evaluated here as the engine evaluates them (floored at 0)."""
    plain = [f for f in flows if (f.get("rate") or {}).get("form") != "expr" or f.get("byTime") or f.get("inflow")]
    out = data.change(plain) if plain else np.zeros_like(data.dy)
    env = {n: data.L[i] for i, n in enumerate(data.ids)} | extra
    for f in flows:
        if f in plain:
            continue
        amt = _evaluate(str(f["rate"].get("expr")), env, data.T)
        for e in f.get("effects") or []:
            amt = amt * _effect(e, data, extra)
        if f.get("from") in data.ids:
            out[data.ids.index(f["from"])] -= amt
        if f.get("to") in data.ids:
            out[data.ids.index(f["to"])] += amt
    return out


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None, log: list | None = None) -> dict:
    """The result with each unexplained exact row read again with a per-unit column and a hidden integrator
    (module docstring)."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    opts = opts or {}
    data = _boundary.Data(stocks, run, opts)
    if not data.usable:
        return result
    ids, T = data.ids, data.T
    flows = copy.deepcopy(result["flows"])
    if any(x not in ids and x is not None for f in flows for x in (f.get("from"), f.get("to"))):
        return result                                       # the answer already has a hidden stock
    t = [float(x) for x in run["t"]]
    at = {x: i for i, x in enumerate(t)}
    extra = {}
    for name, v in (opts.get("inputs") or {}).items():
        if name in ids or str(name).startswith("capmin__"):
            continue
        v = np.asarray(v, dtype=float)
        if len(v) == len(t):
            extra[name] = np.array([v[at[float(x)]] for x in data.tt])
    levels = np.array([np.asarray(run["levels"][i], dtype=float) for i in ids])
    q = _quantum(levels)
    names = ids + list(extra) + ["1"]
    Z0 = np.vstack([data.L] + [extra[n][None, :] for n in extra] + [np.ones((1, T))]).T
    rows = _Rows(data, Z0.T, names, q)
    try:
        moved = _change(flows, data, extra)
    except Exception:                                       # noqa: BLE001 (a flow the simulator cannot evaluate)
        return result
    final = {s["id"] for s in stocks if s.get("final")}
    per = [i for i in range(len(ids)) if np.ptp(data.L[i]) > 0 and np.all(data.L[i] >= 0)]   # what a per-unit column divides by
    b = _boundary.Boundary(run)
    trace = []
    for si, S in enumerate(ids):
        if S in final:
            continue
        resid = data.dy[si] - moved[si]
        if float(np.sqrt(np.mean(resid ** 2))) <= rows.tol(data.dy[si]):
            continue                                        # the answer reproduces S's row
        own_out = [f for f in flows if f.get("from") == S and f.get("to") is None]
        own_in = [f for f in flows if f.get("to") == S and f.get("from") is None]
        if any(f.get("input") for f in own_in):
            continue                                        # an inflow fixed at a measured input
        moves = [f for f in flows if f not in own_out and f not in own_in and S in (f.get("from"), f.get("to"))]
        try:
            y = (_change(moves, data, extra)[si] if moves else np.zeros(T))
        except Exception:                                   # noqa: BLE001
            continue
        y = data.dy[si] - y                                 # what S's outside sides carry
        if rows.exact(y) is not None:
            continue                                        # a linear row reproduces it: reread's business
        tol = rows.tol(y)                                   # the row's rounding (not scaled by the numbers: collinear
        ok = lambda rms, k: rms <= tol                      # columns' huge numbers would excuse any row)  # noqa: E731
        ratios = [(None, None)] + [(_ratio_expr(ids[a], ids[c]), data.L[a] / np.maximum(1.0, data.L[c]))
                                   for c in per for a in range(len(ids)) if a != c]
        drains = _drains(flows, data, extra)
        best = None

        def fit(g, ratio_col):
            h0, h1 = _integrator(g)
            cols = [Z0, h0[:, None], h1[:, None]] + ([ratio_col[:, None]] if ratio_col is not None else [])
            return np.hstack(cols), h0, h1

        tried = []
        for label, g, form in drains:
            tried.append((label, g, form))
        for d in np.geomspace(1e-4, 0.9, DECAYS):           # constant drains: refined below where they come close
            tried.append((f"constant {d:.3g}", np.full(T, d), {"rate": {"form": "proportional", "k": float(d)}}))
        scan = []
        Rm = np.vstack([c for _, c in ratios[1:]]).T if len(ratios) > 1 else np.zeros((T, 0))
        for label, g, form in tried:                        # every per-unit column at once: what it adds beyond the rest
            A, _, _ = fit(g, None)
            k, *_ = np.linalg.lstsq(A, np.hstack([y[:, None], Rm]), rcond=None)
            E = np.hstack([y[:, None], Rm]) - A @ k
            res, Rp = E[:, 0], E[:, 1:]
            sse = float(res @ res)
            scan.append((math.sqrt(sse / T), label, g, form, None, None))
            nn = np.einsum("ij,ij->j", Rp, Rp)
            gain = np.where(nn > 1e-12 * (np.einsum("ij,ij->j", Rm, Rm) + 1e-300), (res @ Rp) ** 2 / np.maximum(nn, 1e-300), 0.0)
            for j in np.argsort(-gain)[:5]:
                scan.append((math.sqrt(max(0.0, sse - float(gain[j])) / T), label, g, form, *ratios[1 + j]))
        scan.sort(key=lambda s: s[0])
        refined = []
        for rms, label, g, form, rexpr, rcol in [x for x in scan if ok(x[0], None)][:12] or scan[:3]:
            if label.startswith("constant"):
                d0 = float(form["rate"]["k"])

                def sse(lg, rcol=rcol):
                    return _lstsq(fit(np.full(T, math.exp(lg)), rcol)[0], y)[1]

                d = math.exp(_golden(sse, math.log(d0) - 0.6, min(math.log(0.99), math.log(d0) + 0.6)))
                g = np.full(T, d)
                form = {"rate": {"form": "proportional", "k": d}}
                label = f"constant {d:.6g}"
            refined.append((label, g, form, rexpr, rcol))
        for label, g, form, rexpr, rcol in refined:
            A, h0, h1 = fit(g, rcol)
            n0 = Z0.shape[1]
            groups = [[j] for j in range(n0)] + [[n0, n0 + 1]] + ([[n0 + 2]] if rcol is not None else [])
            keep = {n0} | ({n0 + 1} if rcol is not None else set())
            cols = _smallest(groups, keep, A, y, ok)
            if cols is None:
                continue
            k_, rms_ = _lstsq(A[:, [j for j in range(A.shape[1]) if j not in (n0, n0 + 1)]], y)
            if ok(rms_, k_):
                continue                                    # exact without the hidden stock: not this mechanism
            k, rms = _lstsq(A[:, cols], y)
            cost = len(cols)
            if best is None or (cost, rms) < (best[0], best[1]):
                best = (cost, rms, label, form, rexpr, dict(zip(cols, map(float, k))), n0, h0, h1)
        if best is None:
            continue
        cost, rms, label, form, rexpr, coef, n0, h0, h1 = best
        bh0, bh1 = coef.pop(n0, 0.0), coef.pop(n0 + 1, 0.0)
        kr = coef.pop(n0 + 2, 0.0)
        if not bh1:
            continue
        H = NAME + S
        pos = {names[j]: v for j, v in coef.items() if v > 0}
        neg = {names[j]: -v for j, v in coef.items() if v < 0}
        parts_in = [f"{v!r} * {n}" for n, v in pos.items() if n != "1"]
        c_in = pos.pop("1", 0.0)
        c_out = neg.pop("1", 0.0)
        if bh1 > 0:
            parts_in.append(f"{bh1!r} * {H}")
        else:
            neg[H] = -bh1
        if kr > 0:
            parts_in.append(f"{kr!r} * ({rexpr})")
        elif kr < 0:
            continue                                        # a per-unit column read negatively: not written
        if parts_in or c_in:
            inflow = {"id": f"hidden:{S}:in", "from": None, "to": S, "rate": {"form": "expr", "expr": " + ".join([repr(float(c_in))] + parts_in)}}
        else:
            inflow = None
        outflow = None
        if neg or c_out:
            terms = [{"stock": n, "k": float(v)} for n, v in neg.items()]
            outflow = {"id": f"hidden:{S}:out", "from": S, "to": None, "rate": {"form": "linear", "c": float(c_out), "terms": terms}}
        if (inflow and not b.may(S, "in", "estimate")) or (outflow and not b.may(S, "out", "estimate")):
            continue                                        # a side the declared boundary lacks
        hflows = [{"id": f"hidden:{H}:in", "from": None, "to": H, "rate": {"form": "constant", "value": 1.0}}]
        if form is not None:
            hflows.append({"id": f"hidden:{H}:out", "from": H, "to": None, "rate": {**form["rate"], "stock": H}, **({"effects": form["effects"]} if form.get("effects") else {})})
        # check: the written flows, floored as the engine floors them, reproduce the row (H from its fitted start)
        g = _g(form, data, extra, T)
        h = _integrator(g)
        hl = (bh0 / bh1) * h[0] + h[1]
        env = {n: data.L[i] for i, n in enumerate(ids)} | extra | {H: hl}
        got = np.zeros(T)
        if inflow:
            got += _evaluate(inflow["rate"]["expr"], env, T)
        if outflow:
            o = np.full(T, float(c_out))
            for x in outflow["rate"]["terms"]:
                o = o + x["k"] * env[x["stock"]]
            got -= np.maximum(0.0, o)
        if float(np.sqrt(np.mean((got - y) ** 2))) > 2 * tol:
            continue
        flows = [f for f in flows if f not in own_in and f not in own_out] + [x for x in (inflow, outflow) if x] + hflows
        trace.append(f"{S}: outside sides re-read with hidden {H} (drain: {label})" + (f" and {rexpr}" if rexpr and kr else ""))
    if not trace:
        return result
    out = dict(result)
    out["flows"] = flows
    out["hidden"] = trace
    if log is not None:
        log.extend(trace)
    return out


def _g(form: dict | None, data: _boundary.Data, extra: dict, T: int) -> np.ndarray:
    if form is None:
        return np.zeros(T)
    g = np.full(T, float(form["rate"].get("k") or 0.0))
    for e in form.get("effects") or []:
        g = g * _effect(e, data, extra)
    return g
