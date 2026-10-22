"""A measured stock fed from outside through a hidden first-order stage (a DELAY1), read from its row
(k8s-312 round 1, docs/research/fixes/312-engine_forms.md).

Where the levels are exact and a measured stock S's one-step change is still not reproduced by the answer,
S's outside sides are tried as

    dS = g H - out,      H' = in - g H        (H hidden; g a constant fraction; in, out >= 0)

with `out` a floored linear rate, or a floored MIN of two linear rates (max(0, min(u, v))), and `in` a floored
linear rate. Their columns are the measured levels, the measured inputs, a constant, and the answer's own
floored terms (each `max(0, ...)` inside an expression flow of the answer, e.g. a MIN move's room left), so a
stage fed by "what does not fit" reads the same room the answer's move reads.

How it is read, with H never seen:

1. `out` from the steps where S is not rising (dS <= its rounding; no inflow shows there): the floored rate
   (reread._Rows.floored) or the floored MIN (reread._Rows.two_regimes) reproducing max(0, -dS) on every one
   of them.
2. x = dS + out is g H on every step. Where the stage's inflow is 0, x falls by a constant fraction:
   x_{t+1} = (1 - g) x_t. The fraction holding exactly on the most steps is 1 - g.
3. g x in_t = x_{t+1} - (1 - g) x_t: the inflow, read as one floored linear rate reproducing every step.

Written: outside -> H (the inflow), H -> S at g x H (the stage's drain is S's inflow: the conserving drawing of
a DELAY1), S -> outside (out), with H's levels (x / g, stepped from the first) as the result's inferred levels.
Kept only when the stage is needed (S's row is not reproduced without it), S's declared boundary has the
sides it writes (an outside flow reaching S through H is S's inflow), and the written flows, evaluated as the
engine floors them, reproduce the row. Data with noise are left alone. Reads only the levels, inputs, units,
boundary and the answer's own flows. Runs after hidden.py.
"""

from __future__ import annotations

import copy

import numpy as np

from ._kalman import boundary as _boundary
from .hidden import _change, _evaluate
from .reread import ROUND, _quantum, _Rows

NAME = "stage_"         # the hidden stage's name: stage_<S>
FEW = 5                 # the fewest steps a decay, or the steps without inflow, are read from
LARGE = 30.0            # a step reads the decay only where x is above this many roundings
FINE = 1e-2             # the rounding counts where it is below this share of a part's largest amount (reread's
                        # 1e-3 would ask a small outflow, tens of roundings, for 1e-6 precision)


class _Small(_Rows):
    """reread's rows, with the rounding counted down to FINE of a part's largest amount."""

    fine = FINE


def _floored_terms(flows: list[dict]) -> list[str]:
    """Each distinct `max(0, ...)` inside the answer's expression rates (balanced parentheses)."""
    out = []
    for f in flows:
        e = str((f.get("rate") or {}).get("expr") or "") if (f.get("rate") or {}).get("form") == "expr" else ""
        i = 0
        while True:
            i = e.find("max(0,", i)
            if i < 0:
                break
            depth, j = 0, i + 3
            while j < len(e):
                depth += {"(": 1, ")": -1}.get(e[j], 0)
                if depth == 0:
                    break
                j += 1
            term = e[i:j + 1]
            if depth == 0 and term not in out and term != e.strip():
                out.append(term)
            i += 1
    return out


def _lin_text(d: dict, names: list[str], text: dict) -> str:
    parts = [repr(float(v)) if names[i] == "1" else f"{float(v)!r} * {text.get(names[i], names[i])}" for i, v in d.items() if v]
    return " + ".join(parts) or "0"


def _rate(d: dict, names: list[str], text: dict) -> dict:
    """A floored linear rate: linear form when it reads only plain columns, else an expression."""
    if any(names[i] in text for i in d):
        return {"form": "expr", "expr": f"max(0, {_lin_text(d, names, text)})"}
    c = sum(float(v) for i, v in d.items() if names[i] == "1")
    return {"form": "linear", "c": c, "terms": [{"stock": names[i], "k": float(v)} for i, v in d.items() if names[i] != "1" and v]}


def _decay(x: np.ndarray, pairs: np.ndarray, q: float) -> tuple[float, np.ndarray] | None:
    """(1 - g, mask of the pairs it holds on): the fraction x keeps from one step to the next on the most
    pairs (t, t+1) where x_t is clearly above the rounding, refitted on them."""
    a, b = x[pairs], x[pairs + 1]
    big = a > LARGE * max(q, 1e-12)
    if big.sum() < FEW:
        return None
    tol = lambda rho: ROUND * max(q, 1e-12) * (1.0 + rho)  # noqa: E731
    best = None
    for t in np.argsort(-a)[: min(40, int(big.sum()))]:
        rho = b[t] / a[t]
        if not 0.0 < rho < 1.0:
            continue
        hold = big & (np.abs(b - rho * a) <= tol(rho))
        if best is None or hold.sum() > best[1].sum():
            best = (rho, hold)
    if best is None or best[1].sum() < FEW:
        return None
    rho, hold = best
    for _ in range(3):
        rho = float(a[hold] @ b[hold] / (a[hold] @ a[hold]))
        hold = big & (np.abs(b - rho * a) <= tol(rho))
    return (rho, hold) if 0.0 < rho < 1.0 and hold.sum() >= FEW else None


def _min_of_two(o: np.ndarray, rows: _Rows, data) -> tuple[dict, dict] | None:
    """(u, v) as {column index: number} with o = max(0, min(u, v)) on every step, or None. The two linear pieces
    are read where o is clearly above the rounding (LARGE roundings; nearer 0 any column fits), then fitted on
    every step at once, each step on its branch (the floor where o is 0), until the branches stop changing."""
    big = o > LARGE * max(rows.q, 1e-12)
    if big.sum() < 2 * FEW:
        return None
    regs = _Small(data, rows.Z[:, big], rows.names, rows.q).pieces(o[big], relaxed=True)
    on = o > rows.tol(o)
    for (cu, hu), (cv, hv) in [(a, b) for i, a in enumerate(regs) for b in regs[i + 1:]]:
        A, B = rows.Z[cu].T, rows.Z[cv].T
        ku, *_ = np.linalg.lstsq(A[big][hu], o[big][hu], rcond=None)
        kv, *_ = np.linalg.lstsq(B[big][hv], o[big][hv], rcond=None)
        for _ in range(8):
            U, V = A @ ku, B @ kv
            first = on & (U <= V)
            second = on & ~(U <= V)
            if first.sum() <= len(cu) or second.sum() <= len(cv):
                break
            ku, *_ = np.linalg.lstsq(A[first], o[first], rcond=None)
            kv, *_ = np.linalg.lstsq(B[second], o[second], rcond=None)
            U, V = A @ ku, B @ kv
            if float(np.sqrt(np.mean((np.maximum(0.0, np.minimum(U, V)) - o) ** 2))) <= rows.tol(o, np.concatenate([ku, kv])):
                return {i: float(k) for i, k in zip(cu, ku)}, {i: float(k) for i, k in zip(cv, kv)}
            if np.array_equal(first, on & (U <= V)):
                break
    return None


def _outflow(o: np.ndarray, rows: _Rows, names: list[str], text: dict, data=None) -> tuple[dict] | None:
    """(rate,) of a floored linear rate, or a floored MIN of two, reproducing o >= 0 on these rows' steps ({} when o is 0)."""
    if not np.any(o > rows.tol(o)):
        return ({},)
    got = rows.floored(o)
    if got is not None:
        idx, w = got
        return (_rate({i: float(v) for i, v in zip(idx, w)}, names, text),)
    got = _min_of_two(o, rows, data)
    if got is None:
        return None
    u, v = got
    return ({"form": "expr", "expr": f"max(0, min({_lin_text(u, names, text)}, {_lin_text(v, names, text)}))"},)


def _amount(rate: dict, env: dict, T: int) -> np.ndarray:
    """A rate's amounts on every step, floored at 0 as the engine floors them."""
    if rate.get("form") == "expr":
        return _evaluate(str(rate["expr"]), env, T)
    if rate.get("form") == "proportional":
        return np.maximum(0.0, float(rate["k"]) * env[rate["stock"]])
    v = np.full(T, float(rate.get("c") or 0.0))
    for x in rate.get("terms") or []:
        v = v + float(x["k"]) * env[x["stock"]]
    return np.maximum(0.0, v)


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None, log: list | None = None) -> dict:
    """The result with each unexplained exact row read again as a stock fed through a hidden DELAY1 stage
    (module docstring)."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    opts = opts or {}
    data = _boundary.Data(stocks, run, opts)
    if not data.usable:
        return result
    ids, T = data.ids, data.T
    flows = copy.deepcopy(result["flows"])
    t = [float(x) for x in run["t"]]
    at = {x: i for i, x in enumerate(t)}
    extra = {}
    for name, v in (opts.get("inputs") or {}).items():
        if name in ids or str(name).startswith("capmin__"):
            continue
        v = np.asarray(v, dtype=float)
        if len(v) == len(t):
            extra[name] = np.array([v[at[float(x)]] for x in data.tt])
    env = {n: data.L[i] for i, n in enumerate(ids)} | extra
    terms, text = [], {}
    for k, e in enumerate(_floored_terms(flows)):         # the answer's own floored terms, as columns
        try:
            col = _evaluate(e, env, T)
        except Exception:                                 # noqa: BLE001 (it reads what is not measured)
            continue
        terms.append(col)
        text[f"floored{k}"] = f"({e})"
    names = ids + list(extra) + ["1"] + list(text)
    Z = np.vstack([data.L] + [extra[n][None, :] for n in extra] + [np.ones((1, T))] + [c[None, :] for c in terms])
    levels = np.array([np.asarray(run["levels"][i], dtype=float) for i in ids])
    q = _quantum(levels)
    rows = _Rows(data, Z, names, q)
    measured = set(ids)
    final = {s["id"] for s in stocks if s.get("final")}
    b = _boundary.Boundary(run)
    step = np.diff(data.tt)
    pairs = np.flatnonzero(np.abs(step - np.median(step)) <= 1e-9 * max(1.0, abs(float(np.median(step))))) if T > 1 else np.zeros(0, int)
    trace, inferred = [], {}
    for si, S in enumerate(ids):
        if S in final or not b.may(S, "in", "estimate"):
            continue
        mine = [f for f in flows if S in (f.get("from"), f.get("to"))]
        if any(x is not None and x not in measured for f in mine for x in (f.get("from"), f.get("to"))):
            continue                                      # S already has a hidden stock of its own
        own = [f for f in mine if f.get("from") is None or f.get("to") is None]
        if any(f.get("input") for f in own):
            continue
        moves = [f for f in mine if f not in own]
        try:
            ans = _change(mine, data, extra)[si]
            y = data.dy[si] - (_change(moves, data, extra)[si] if moves else 0.0)
        except Exception:                                 # noqa: BLE001
            continue
        tol = rows.tol(data.dy[si])
        if float(np.sqrt(np.mean((data.dy[si] - ans) ** 2))) <= 2 * tol or rows.exact(y) is not None:
            continue                                      # the answer, or a linear row, reproduces it
        quiet = y <= rows.tol(y)
        if quiet.sum() < FEW or quiet.all():
            continue
        sub = _Small(data, Z[:, quiet], names, q)
        got = _outflow(np.maximum(0.0, -y[quiet]), sub, names, text, data)
        if got is None:
            continue
        out_rate = got[0]
        if out_rate and not b.may(S, "out", "estimate"):
            continue
        out_f = {"id": f"delay:{S}:out", "from": S, "to": None, "rate": out_rate} if out_rate else None
        try:
            out_amt = _amount(out_rate, env, T) if out_f else np.zeros(T)
        except Exception:                                 # noqa: BLE001
            continue
        x = y + out_amt                                   # g H on every step
        if np.any(x < -2 * tol) or not np.any(x > rows.tol(x)):
            continue
        dec = _decay(x, pairs, q)
        if dec is None:
            continue
        rho, _ = dec
        g = 1.0 - rho
        inflow = np.zeros(T)
        inflow[pairs] = (x[pairs + 1] - rho * x[pairs]) / g
        prow = _Small(data, Z[:, pairs], names, q)
        got_in = prow.floored(inflow[pairs])
        if got_in is None:
            continue
        idx, w = got_in
        H = NAME + S
        in_f = {"id": f"delay:{H}:in", "from": None, "to": H, "rate": _rate({i: float(v) for i, v in zip(idx, w)}, names, text)}
        drain = {"id": f"delay:{H}:out", "from": H, "to": S, "rate": {"form": "proportional", "stock": H, "k": float(g)}}
        # check: the written flows, floored as the engine floors them, reproduce the row (H stepped from x_0 / g)
        fed = _amount(in_f["rate"], env, T)               # the stage's inflow amounts on every step
        h = np.empty(T + 1)
        h[0] = x[0] / g
        for k in range(T):
            h[k + 1] = h[k] + fed[k] - g * h[k]
        if float(np.sqrt(np.mean((g * h[:T] - out_amt - y) ** 2))) > 2 * tol:
            continue
        flows = [f for f in flows if f not in own] + [in_f, drain] + ([out_f] if out_f else [])
        if len(pairs) == T - 1 and len(t) == T + 1:
            inferred[H] = [float(v) for v in h]
        trace.append(f"{S}: fed through hidden {H} (a DELAY1 of {1.0 / g:.4g} steps)" + (" and an outflow" if out_f else ""))
    if not trace:
        return result
    out = dict(result)
    out["flows"] = flows
    out["delay"] = trace
    if inferred:
        out["inferred_levels"] = {**(result.get("inferred_levels") or {}), **inferred}
    if log is not None:
        log.extend(trace)
    return out
