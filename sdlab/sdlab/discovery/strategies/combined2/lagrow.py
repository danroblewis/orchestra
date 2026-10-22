"""A hidden first-order stage on a stock's outside inflow (docs/research/fixes/312-combined2.md, 2026-10-22).

Some outside inflows arrive through a stage nobody measures: a node the cluster autoscaler orders joins after a
provisioning delay (a DELAY1: an order enters the hidden stage H, which empties into the stock at H / tau a
step). Fitted as a plain rate, such an inflow is smeared into a linear drift on whatever levels happen to lead
it (kubernetes 312: `outside -> nodes = -4.99 - 0.001 errors_total + 0.013 mem + 0.003 traffic`).

For each measured, non-final stock S whose outside inflow side is open (declared `in`, not a measured input,
and a side the model has) and whose row the model leaves well above rounding, S's row (its one-step change less
the moves between S and other stocks) is refitted as

    in_t = H_t / tau,   H_{t+1} = H_t + u_t - H_t / tau,   u = max(0, c + w . Z)
    out  = max(0, c' + w' . Z')            or, with a second arm,  max(0, min(c1 + w1 . Z1, c' + w' . Z'))

H starts at 0 (or at a fitted h0 >= 0). For a fixed tau and a fixed set of steps where u > 0, in_t is linear in
(c, w) through the filter, so u is fitted by active-set least squares (as hinge.hfit, the filter applied to each
active column); tau on a grid, then golden section. The Z are measured levels and inputs, and the rooms of the
capacity limits the model already has (`max(0, a Y + b Z)` in `min(k X, max(0, a Y + b Z))`: the demand a full
pool turns away, kubernetes 312's unplaceable pods, is the demand less that room). The columns are chosen by
forward selection on BIC (at most MAX_COLS). The out side is refitted with the in side held (hinge.fit_side), and
the two alternate ROUNDS times from two starts (the model's own out side; one fitted on the row's falls). An out
side whose single floor overshoots on some steps is offered a second arm, a min of two floored linear forms
(`0.05 max(0, nodes - max(2, pods / 2))` = `max(0, min(0.05 nodes - 0.1, 0.05 nodes - 0.025 pods))`).
The rewrite is kept only where S's row's BIC falls by more than GAIN log n against both the model's own sides and
the same refit without the stage (tau -> 1: u read directly).

Adopting it: copy this file (it needs hinge.py's columns / row_error / delta / fit_side / allowed_sides and
minrefit.parse) and call `apply(result, stocks, run, opts)` on the answer (combined2: last); it adds
`inferred_levels` for the hidden stages.
"""

from __future__ import annotations

import copy
import math

import numpy as np
from scipy.signal import lfilter

from . import hinge
from .minrefit import parse as _parse_limit

GAIN = 2.0
FLOOR_REL = 1e-9
SKIP_REL = 1e-6        # a row the model explains to this share of its change's energy is left alone
MAX_COLS = 3
ROUNDS = 4
ITERS = 40
TAUS = (1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 9.0, 14.0)
INITS = (1e-6, 0.25, 0.5)
WIDE = 24              # (2026-10-22, k8s-317) more columns than this: the active-set paths are not re-walked (_lagfit fast)
TAU_MIN = 1.15         # a stage empties at most 1 / TAU_MIN a step (a faster one is a one-step lag of a plain rate)
MIN_ON = 5             # steps a fitted order u (or an arm) must be positive on


def _bic(sse: float, k: int, n: int, floor: float) -> float:
    return n * math.log(max(sse, floor) / n) + k * math.log(n)


def _filt(x: np.ndarray, tau: float | None) -> np.ndarray:
    """in_t = H_t / tau for H_{t+1} = (1 - 1/tau) H_t + x_t, H_0 = 0; tau None: no stage, in_t = x_t."""
    if tau is None:
        return np.asarray(x, dtype=float)
    return lfilter([0.0, 1.0], [1.0, -(1.0 - 1.0 / tau)], x) / tau


def _start(n: int, tau: float) -> np.ndarray:
    """in_t of H_0 = 1 with no orders: (1 - 1/tau)^t / tau."""
    return (1.0 - 1.0 / tau) ** np.arange(n) / tau


def _out_regimes(arms: list[np.ndarray], coefs: list[np.ndarray]) -> list[np.ndarray]:
    """Each arm's active steps for max(0, min(arm_1, ...)): the smallest arm, where it is positive."""
    v = np.column_stack([Z @ c for Z, c in zip(arms, coefs)])
    lo = v.argmin(axis=1)
    on = v.min(axis=1) > 0
    return [on & (lo == i) for i in range(len(arms))]


def _lagfit(Z: np.ndarray, y: np.ndarray, tau: float | None, h0: bool, arms: list[np.ndarray] | None = None,
            coefs: list[np.ndarray] | None = None, fast: bool = False) -> dict | None:
    """min over (b, out arms' numbers, h0 >= 0) of sum (filt(max(0, Z b)) + h0 start - max(0, min(arms)) - y)^2
    by active-set least squares (the in side's and every arm's active steps recomputed from the fit until they
    settle), from several starts. {"sse", "b", "h0", "coefs", "in", "out", "order"}."""
    n, m = Z.shape
    arms = arms or []
    top = float(np.max(y + (np.maximum(0.0, np.min(np.column_stack([A @ c for A, c in zip(arms, coefs)]), axis=1))
                            if arms else 0.0)))
    if top <= 0:
        return None
    h0 = h0 and tau is not None
    s = _start(n, tau) if h0 else None
    best = None
    done: set = set()                                     # (fast, k8s-317) active sets an earlier start already solved
    for t0 in INITS:
        yy = y + (np.maximum(0.0, np.min(np.column_stack([A @ c for A, c in zip(arms, coefs)]), axis=1)) if arms else 0.0)
        A = np.r_[yy[1:] > t0 * top, False] if tau is not None else yy > t0 * top
        R = _out_regimes(arms, coefs) if arms else []
        b = None
        mine: set = set()
        for _ in range(ITERS):
            if A.sum() < max(MIN_ON, m + 1):
                b = None
                break
            if fast:                                      # a path an earlier start took (its end is scored), or a cycle
                key = A.tobytes() + b"".join(x.tobytes() for x in R)
                if key in done:
                    b = None
                    break
                if key in mine:
                    break
                mine.add(key)
            M = [_filt(Z[:, j] * A, tau) for j in range(m)] + ([s] if h0 else [])
            for Zk, Rk in zip(arms, R):
                M += [-(Zk[:, j] * Rk) for j in range(Zk.shape[1])]
            coef, *_ = np.linalg.lstsq(np.column_stack(M), y, rcond=None)
            b, h = coef[:m], (float(coef[m]) if h0 else 0.0)
            i, cs = m + (1 if h0 else 0), []
            for Zk in arms:
                cs.append(coef[i: i + Zk.shape[1]])
                i += Zk.shape[1]
            A2 = Z @ b > 0
            R2 = _out_regimes(arms, cs) if arms else []
            if np.array_equal(A2, A) and all(np.array_equal(x, z) for x, z in zip(R, R2)):
                break
            A, R = A2, R2
        done |= mine
        if b is None or (h0 and h < 0) or int((Z @ b > 0).sum()) < MIN_ON:
            continue
        order = np.maximum(0.0, Z @ b)
        inn = _filt(order, tau) + (h * s if h0 else 0.0)
        out = np.maximum(0.0, np.min(np.column_stack([Zk @ c for Zk, c in zip(arms, cs)]), axis=1)) if arms else np.zeros(n)
        e = inn - out - y
        sse = float(e @ e)
        if best is None or sse < best["sse"]:
            best = {"sse": sse, "b": b, "h0": h, "coefs": cs, "in": inn, "out": out, "order": order}
    return best


def _golden(f, lo: float, hi: float, iters: int = 20) -> float:
    g = (math.sqrt(5) - 1) / 2
    a, b = math.log(lo), math.log(hi)
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = f(math.exp(c)), f(math.exp(d))
    for _ in range(iters):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = f(math.exp(c))
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = f(math.exp(d))
    return math.exp((a + b) / 2)


def _design(names: tuple, const: bool, pool: dict, n: int) -> np.ndarray:
    return np.column_stack([pool[k][:n] for k in names] + ([np.ones(n)] if const else []))


def fit_in(y: np.ndarray, pool: dict, n: int, floor: float, taus=TAUS, out: dict | None = None) -> dict | None:
    """The best staged inflow for y (the row; the out side `out`'s arms refitted with it, their columns held):
    forward selection of at most MAX_COLS columns (each with and without a constant, with and without a start),
    tau on the grid, then golden section for the chosen columns. taus (None,): no stage.
    {"bic", "sse", "k", "tau", "names", "const", "b", "h0", "in", "order", "out"}."""
    arms = [_design(nm, cst, pool, n) for nm, cst, _ in (out or {}).get("arms") or []]
    coefs = [np.asarray(cf, dtype=float) for _, _, cf in (out or {}).get("arms") or []]
    k_out = sum(Z.shape[1] for Z in arms)

    def one(names, const, tau):
        Z = _design(names, const, pool, n)
        best1 = None
        for h0 in (False, True) if tau is not None else (False,):
            got = _lagfit(Z, y, tau, h0, arms, coefs, fast=len(pool) > WIDE)
            if got is None:
                continue
            k = Z.shape[1] + (1 if h0 else 0) + (1 if tau is not None else 0) + k_out
            bic = _bic(got["sse"], k, n, floor)
            if best1 is None or bic < best1["bic"] - 1e-9:
                best1 = {**got, "bic": bic, "k": k, "tau": tau, "names": tuple(names), "const": const}
        return best1

    best = None
    chosen: tuple = ()
    for _ in range(MAX_COLS):
        step = None
        for x in pool:
            if x in chosen:
                continue
            for const in (False, True):
                for tau in taus:
                    got = one(chosen + (x,), const, tau)
                    if got is not None and (step is None or got["bic"] < step["bic"]):
                        step = got
        if step is None or (best is not None and not step["bic"] < best["bic"] - GAIN * math.log(n)):
            break
        best, chosen = step, step["names"]
    if best is None:
        return None
    if len(taus) > 1:
        lo, hi = TAU_MIN, max(taus) * 1.5
        tau = _golden(lambda v: (one(best["names"], best["const"], v) or {"bic": math.inf})["bic"], lo, hi)
        got = one(best["names"], best["const"], tau)
        if got is not None and got["bic"] < best["bic"]:
            best = got
    if out:
        best["out_fit"] = {"arms": [(nm, cst, cf) for (nm, cst, _), cf in zip(out["arms"], best["coefs"])], "k": k_out,
                           "amount": best["out"]}
    return best


def _two_arm(y: np.ndarray, single: dict, pool: dict, n: int, floor: float) -> dict | None:
    """max(0, min(arm1, arm2)) with arm2 the single floored fit's columns and arm1 at most one column and a
    constant: regimes (off, arm1, arm2) by active-set least squares, started from the steps where the single fit
    overshoots."""
    (names2, const2, b2), = single["arms"]
    Z2 = _design(names2, const2, pool, n)
    over0 = np.maximum(0.0, Z2 @ b2) - y
    if not (over0 > 1e-9 * max(1e-12, float(np.abs(y).max()))).any():
        return None
    best = None
    for x in [None, *pool]:
        nm1 = (x,) if x else ()
        Z1 = _design(nm1, True, pool, n)
        for q in (0.5, 0.8, 0.95):
            thr = float(np.quantile(over0[over0 > 0], q))
            R1 = (over0 >= thr) & (y > 0)
            if R1.sum() < max(MIN_ON, Z1.shape[1] + 1):
                continue
            c2 = np.asarray(b2, dtype=float).copy()
            c1 = None
            for _ in range(ITERS):
                R2 = (~R1) & ((Z2 @ c2) > 0) & (y > 0)
                if R1.sum() < Z1.shape[1] + 1 or R2.sum() < Z2.shape[1] + 1:
                    c1 = None
                    break
                c1, *_ = np.linalg.lstsq(Z1[R1], y[R1], rcond=None)
                c2, *_ = np.linalg.lstsq(Z2[R2], y[R2], rcond=None)
                N1 = _out_regimes([Z1, Z2], [c1, c2])[0]
                if np.array_equal(N1, R1):
                    break
                R1 = N1
            if c1 is None:
                continue
            a1, a2 = Z1 @ c1, Z2 @ c2
            if _out_regimes([Z1, Z2], [c1, c2])[0].sum() < MIN_ON:
                continue
            amt = np.maximum(0.0, np.minimum(a1, a2))
            e = amt - y
            sse = float(e @ e)
            k = Z1.shape[1] + Z2.shape[1]
            bic = _bic(sse, k, n, floor)
            if best is None or bic < best["bic"] - 1e-9:
                best = {"bic": bic, "sse": sse, "k": k, "arms": [(nm1, True, c1), (tuple(names2), const2, c2)], "amount": amt}
    if best is None:
        return None
    (nm1, _, c1), arm2 = best["arms"]
    Z1 = _design(nm1, True, pool, n)
    for _ in range(3):                                   # arm2's columns re-chosen off arm1's steps, then the regimes again
        R1 = _out_regimes([Z1, _design(arm2[0], arm2[1], pool, n)], [c1, arm2[2]])[0]
        keep = ~R1
        got = hinge.fit_side(y[keep], {k_: v[:n][keep] for k_, v in pool.items()}, int(keep.sum()), floor)
        if got is None:
            break
        nm2, cst2 = tuple(got["w"]), bool(got["c"])
        Zn = _design(nm2, cst2, pool, n)
        c2n = np.array(list(got["w"].values()) + ([got["c"]] if cst2 else []))
        c1n = c1
        for _ in range(ITERS):
            R1n, R2n = _out_regimes([Z1, Zn], [c1n, c2n])
            if R1n.sum() < Z1.shape[1] + 1 or R2n.sum() < Zn.shape[1] + 1:
                break
            a_, *_ = np.linalg.lstsq(Z1[R1n], y[R1n], rcond=None)
            b_, *_ = np.linalg.lstsq(Zn[R2n], y[R2n], rcond=None)
            if np.allclose(a_, c1n) and np.allclose(b_, c2n):
                break
            c1n, c2n = a_, b_
        if _out_regimes([Z1, Zn], [c1n, c2n])[0].sum() < MIN_ON:
            break
        amt = np.maximum(0.0, np.minimum(Z1 @ c1n, Zn @ c2n))
        e = amt - y
        sse = float(e @ e)
        k = Z1.shape[1] + Zn.shape[1]
        bic = _bic(sse, k, n, floor)
        if not bic < best["bic"] - 1e-9:
            break
        best = {"bic": bic, "sse": sse, "k": k, "arms": [(nm1, True, c1n), (nm2, cst2, c2n)], "amount": amt}
        c1, arm2 = c1n, (nm2, cst2, c2n)
    return best


def fit_out(y: np.ndarray, pool: dict, n: int, floor: float) -> dict | None:
    """The best floored out side for y (hinge.fit_side), with a second arm where that lowers the BIC by more
    than GAIN log n. {"bic", "sse", "k", "arms": [(names, const, coefs)], "amount"}."""
    got = hinge.fit_side(y, pool, n, floor)
    if got is None:
        return None
    names, const = tuple(got["w"]), bool(got["c"])
    b = np.array(list(got["w"].values()) + ([got["c"]] if const else []))
    single = {"bic": got["bic"], "sse": got["sse"], "k": got["k"], "arms": [(names, const, b)],
              "amount": np.maximum(0.0, _design(names, const, pool, n) @ b)}
    two = _two_arm(y, single, pool, n, floor)
    if two is not None and two["bic"] < single["bic"] - GAIN * math.log(n):
        return two
    return single


def _lin_text(names, const: bool, coef, exprs: dict) -> str:
    parts = [f"{float(v)!r} * {exprs.get(k, k)}" for k, v in zip(names, coef)] + ([repr(float(coef[-1]))] if const else [])
    return " + ".join(parts) or "0.0"


def _out_rate(fit: dict, exprs: dict) -> dict:
    arms = fit["arms"]
    if len(arms) > 1:
        return {"form": "expr", "expr": f"max(0, min({', '.join(_lin_text(nm, c, cf, exprs) for nm, c, cf in arms)}))"}
    (names, const, coef), = arms
    if any(k in exprs for k in names):
        return {"form": "expr", "expr": f"max(0, {_lin_text(names, const, coef, exprs)})"}
    return {"form": "linear", "c": float(coef[-1]) if const else 0.0, "terms": [{"stock": k, "k": float(v)} for k, v in zip(names, coef)]}


def _rooms(flows: list[dict], cols: dict, n: int) -> dict:
    """{text: series} for each room `max(0, a Y + b Z)` of the model's capacity limits."""
    out = {}
    for f in flows:
        p = _parse_limit((f.get("rate") or {}).get("expr")) if (f.get("rate") or {}).get("form") == "expr" else None
        if not p or not p["room"]:
            continue
        (a, y), (b, z) = p["cap"]
        if y not in cols or z not in cols:
            continue
        text = f"max(0, {a!r} * {y} + {b!r} * {z})"
        v = np.maximum(0.0, a * cols[y][:n] + b * cols[z][:n])
        if np.std(v) > 0:
            out[text] = v
    return out


def _one(s: str, flows: list[dict], levels: dict, cols: dict, n: int, pool: dict, with_out: bool):
    got = hinge.row_error(s, flows, levels, cols, n)
    if got is None:
        return None
    r, sides = got
    energy = float(np.sum(hinge.delta(levels, s, n) ** 2))
    sse_cur = float(np.sum((r - sides["in"] + sides["out"]) ** 2))
    if sse_cur <= SKIP_REL * energy:
        return None
    scale = max(1e-12, float(np.abs(hinge.delta(levels, s, n)).max()))
    floor = n * (FLOOR_REL * scale) ** 2
    k_cur = sum(hinge._k(f) for f in flows if hinge._side(f, s))
    bic_cur = _bic(sse_cur, k_cur, n, floor)

    def alternate(out0, taus):
        """The in side fitted with the out side's arms (numbers refitted jointly), then the out side's columns
        re-chosen on what the in side leaves, ROUNDS times."""
        fout, fin, best = out0, None, None
        for _ in range(ROUNDS if with_out else 1):
            fin = fit_in(r, pool, n, floor, taus, fout if with_out else None)
            if fin is None:
                break
            if best is None or fin["bic"] < best["bic"] - 1e-9:
                best = fin
            elif best is not None:
                break
            if not with_out:
                break
            fo = fit_out(fin["in"] - r, pool, n, floor)
            if fo is None:
                break
            fout = fo
        return best

    best = None
    starts = [None]
    if with_out:
        starts = []
        for target in (np.maximum(0.0, -r), sides["out"]):
            fo = fit_out(target, pool, n, floor)
            if fo is not None:
                starts.append(fo)
    for out0 in starts:
        got = alternate(out0, TAUS)
        if got is not None and (best is None or got["bic"] < best["bic"]):
            best = got
    if best is None or (with_out and not best.get("out_fit")) or best["tau"] <= TAU_MIN * 1.01:
        return None                                     # a stage at the fastest allowed is no evidence of one
    # the same refit without the stage (the order read directly, at the step's start)
    plain = alternate(best.get("out_fit"), (None,))
    bic_plain = plain["bic"] if plain is not None else math.inf
    if not best["bic"] < min(bic_cur, bic_plain) - GAIN * math.log(n):
        return None
    return {**best, "bic_before": bic_cur, "sse_before": sse_cur, "bic_plain": bic_plain}


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer with each stock whose outside inflow arrives through a hidden stage rewritten (module docstring)."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    levels, cols, n = hinge.columns(run, opts)
    if n < 20:
        return result
    finals = {s["id"] for s in stocks if s.get("final")}
    out = copy.deepcopy(result)
    flows = out["flows"]
    names = {x for f in flows for x in (f.get("from"), f.get("to")) if x}
    pool = {c: cols[c][:n] for c in cols if c not in finals and np.std(cols[c][:n]) > 0}
    notes = []
    for s in sorted(levels):
        if s in finals or "in" not in hinge.allowed_sides(s, run, flows) or not any(hinge._side(f, s) == "in" for f in flows):
            continue                                    # a side the model has is rewritten, never one invented
        kinds = ((run.get("boundary") or {}).get(s) or {}).get("in") or []
        if run.get("boundary_declared") and "input" in kinds:
            continue                                    # a measured input is the inflow, fixed at 1 x series
        if any(s in (f.get("from"), f.get("to")) and any(x and x not in levels for x in (f.get("from"), f.get("to"))) for f in flows):
            continue                                    # S already exchanges with a hidden stock
        with_out = "out" in hinge.allowed_sides(s, run, flows)
        rooms = _rooms(flows, cols, n)
        got = _one(s, flows, levels, cols, n, {**pool, **rooms}, with_out)
        if got is None:
            continue
        h = f"{s}_stage"
        while h in levels or h in names:
            h += "_"
        fin, fout = got, got.get("out_fit")
        exprs = {k: k for k in rooms}
        order = {"form": "expr", "expr": f"max(0, {_lin_text(fin['names'], fin['const'], fin['b'], exprs)})"}
        keep = [f for f in flows if not hinge._side(f, s)]
        keep += [
            {"id": f"{h}_order", "from": None, "to": h, "ratio": 1, "rate": order},
            {"id": f"{h}_arrive", "from": h, "to": s, "ratio": 1, "rate": {"form": "proportional", "stock": h, "k": 1.0 / fin["tau"]}},
        ]
        if fout is not None:
            keep.append({"id": f"staged_{s}_out", "from": s, "to": None, "ratio": 1, "rate": _out_rate(fout, exprs)})
        flows[:] = keep
        names |= {h}
        H = np.zeros(n + 1)
        H[0] = fin["h0"]
        a = 1.0 - 1.0 / fin["tau"]
        for t in range(n):
            H[t + 1] = a * H[t] + fin["order"][t]
        out.setdefault("inferred_levels", {})[h] = [float(v) for v in H]
        notes.append({"stock": s, "hidden": h, "tau": fin["tau"], "reads": list(fin["names"]), "two_arm": bool(fout and len(fout["arms"]) > 1),
                      **{k: got[k] for k in ("sse_before", "sse", "bic_before", "bic", "bic_plain")}})
    if notes:
        out["staged_rows"] = notes
    return out
