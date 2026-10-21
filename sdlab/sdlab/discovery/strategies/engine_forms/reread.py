"""An exact re-read of noise-free rows (k8s-309, docs/research/fixes/309-engine_forms.md).

Where the levels are known exactly, the true flows reproduce every stock's one-step change to the
data's rounding. When the answer leaves some stock's changes clearly unexplained, the stocks of that
stock's unit (the only ones a move can join) are read again row by row, from the levels alone:

1. Each row is the smallest set of columns (every measured level, every measured input, a constant)
   whose least-squares fit reproduces it exactly (best subset, up to MAX_TERMS columns).
2. A row no linear set reproduces is tried as a linear part plus one floored linear flow (the engine
   floors every rate at 0): the linear part (up to 3 columns) is exact on at least half of the steps,
   the rest of the change has one sign (an inflow, or an outflow), and on the steps where it is not
   zero it is a linear function of the columns (up to MAX_TERMS) that is <= 0 on every other step.
   It is written as that linear rate on the declared side: the engine's floor makes it the hinge.
3. The rows' linear terms are joined into flows column by column: a column read negatively by its own
   stock's row (or by one row only) is a source, and the rows of the same unit that read it
   positively receive moves from it, up to what it gives; the rest of each term is an outside flow
   on that stock's side. Terms of one pair are merged into one flow (one flow per pair and side).
4. A row neither form reproduces keeps its own outside flows from the answer (its moves go).

The block is replaced only when every row the answer explained is still explained, at least one row
it did not explain now is, and nothing leaves the declared boundary. On data with noise no row is
reproduced to its rounding, so nothing changes there. Reads only the levels, inputs, units and the
boundary.
"""

from __future__ import annotations

import copy
import itertools

import numpy as np

from ._kalman import boundary as _boundary

MAX_TERMS = 4          # columns one rate may read
BASE_TERMS = 3         # columns of a hinge row's linear part
REL = 1e-6             # a row is reproduced when its rms residual is below this share of its rms change ...
ROUND = 3.0            # ... or below ROUND x the rounding of what it reads (where rounding is fine: FINE)
FINE = 1e-3            # the rounding counts only where it is below this share of the row's largest change
SNAP = 1e-4           # a term's remainder below this share of the column's largest number is the fit's precision
QUIET = 0.5            # a hinge's linear part holds exactly on at least this share of the steps


def _quantum(a: np.ndarray) -> float:
    a = np.abs(a[np.isfinite(a)])
    for e in range(0, 9):
        q = 10.0 ** -e
        if np.all(np.abs(a / q - np.round(a / q)) < 1e-6):
            return q
    return 0.0


class _Rows:
    def __init__(self, data, cols: np.ndarray, names: list[str], q: float):
        self.data, self.Z, self.names, self.q = data, cols, names, q

    def tol(self, y: np.ndarray, k: np.ndarray | None = None) -> float:
        """The rms residual below which y counts as reproduced (k: the numbers its fit reads)."""
        scale = float(np.sqrt(np.mean(y ** 2)))
        t = REL * scale
        if self.q and self.q <= FINE * float(np.max(np.abs(y))):
            t = max(t, ROUND * self.q * (1.0 + (float(np.sum(np.abs(k))) if k is not None else 0.0)))
        return t

    def exact(self, y: np.ndarray, rows: np.ndarray | None = None, most: int = MAX_TERMS, least: int = 0):
        """The smallest column set reproducing y (on rows), as (indices, numbers), or None."""
        Z = self.Z if rows is None else self.Z[:, rows]
        yy = y if rows is None else y[rows]
        if len(yy) < 5:
            return None
        for n in range(least, most + 1):
            best = None
            for sub in itertools.combinations(range(Z.shape[0]), n):
                if n == 0:
                    k, r = np.zeros(0), yy
                else:
                    A = Z[list(sub)].T
                    k, *_ = np.linalg.lstsq(A, yy, rcond=None)
                    r = yy - A @ k
                rms = float(np.sqrt(np.mean(r ** 2)))
                if rms <= self.tol(yy, k) and (best is None or rms < best[2]):
                    best = (list(sub), k, rms)
            if best is not None:
                return best[0], best[1]
        return None

    def floored(self, r: np.ndarray, most: int = MAX_TERMS):
        """The smallest column set w with max(0, Z w) = r on every step, as (indices, numbers), or None.
        Fitted by censored least squares: every step at first, then without the steps where r is 0 and
        Z w is clearly below 0 (the floor binds there), until they stop changing."""
        T = len(r)
        zero = np.abs(r) <= self.tol(r)
        for n in range(1, most + 1):
            best = None
            for sub in itertools.combinations(range(self.Z.shape[0]), n):
                A = self.Z[list(sub)].T
                use = np.ones(T, bool)
                for _ in range(12):
                    w, *_ = np.linalg.lstsq(A[use], r[use], rcond=None)
                    h = A @ w
                    new = ~(zero & (h < -self.tol(r, w)))
                    if np.array_equal(new, use) or new.sum() < n + 2:
                        break
                    use = new
                rms = float(np.sqrt(np.mean((np.maximum(0.0, h) - r) ** 2)))
                if rms <= self.tol(r, w) and (best is None or rms < best[2]):
                    best = (list(sub), w, rms)
            if best is not None:
                return best[0], best[1]
        return None

    def hinge(self, y: np.ndarray):
        """(linear part, sign, hinge part) for y = linear + sign x max(0, hinge), or None."""
        T = len(y)
        best = None
        for n in range(0, BASE_TERMS + 1):
            for sub in itertools.combinations(range(self.Z.shape[0]), n):
                A = self.Z[list(sub)].T if n else np.zeros((T, 0))
                keep = np.ones(T, bool)
                k = np.zeros(n)
                while n:                                # backward trimming: the steps where the hinge is 0
                    k, *_ = np.linalg.lstsq(A[keep], y[keep], rcond=None)
                    r = y - A @ k
                    if np.sqrt(np.mean(r[keep] ** 2)) <= self.tol(y[keep], k) or keep.sum() < QUIET * T:
                        break
                    on = np.flatnonzero(keep)
                    drop = on[np.argsort(-np.abs(r[on]), kind="stable")[:max(1, len(on) // 20)]]
                    keep[drop] = False
                r = y - (A @ k if n else 0.0)
                keep = np.abs(r) <= max(self.tol(y[keep], k), 1e-300)
                if keep.sum() < QUIET * T or keep.all():
                    continue
                rest = r[~keep]
                sign = 1.0 if np.all(rest > 0) else (-1.0 if np.all(rest < 0) else 0.0)
                if not sign:
                    continue
                got = self.floored(sign * r)
                if got is None:
                    continue
                idx, w = got
                cost = n + len(idx)
                if best is None or cost < best[0]:
                    best = (cost, (list(sub), k), sign, (idx, w))
            if best is not None and best[0] <= n + 1:
                break
        return None if best is None else best[1:]


def _rate(terms: dict, names: list[str]) -> dict:
    c = float(terms.pop("1", 0.0))
    ts = [{"stock": k, "k": float(v)} for k, v in terms.items() if v]
    if not c and len(ts) == 1:
        return {"form": "proportional", "stock": ts[0]["stock"], "k": ts[0]["k"]}
    if not ts:
        return {"form": "constant", "value": c}
    return {"form": "linear", "c": c, "terms": ts}


def _flow(a, b, rate: dict, inputs: set) -> dict:
    f = {"from": a, "to": b, "rate": rate}
    reads = {rate.get("stock")} | {t.get("stock") for t in rate.get("terms") or []}
    reads.discard(None)
    if a is None and len(reads) == 1 and reads <= inputs and rate.get("form") == "proportional":
        f["input"] = next(iter(reads))
    return f


def _block(block: list[str], y: dict, rows: _Rows, unit: dict, final: set, inputs: set, fixed=()):
    """The block's flows from its rows, and the rows they do not reproduce."""
    names = rows.names
    lin, hinges, left, tols = {}, {}, [], {}
    for s in block:
        got = rows.exact(y[s])
        if got is not None:
            lin[s] = {names[i]: float(k) for i, k in zip(*got)}
            tols[s] = rows.tol(y[s], got[1])
            continue
        if s in final:
            left.append(s)
            continue
        h = rows.hinge(y[s])
        if h is None:
            left.append(s)
            continue
        (sub, k), sign, (idx, w) = h
        lin[s] = {names[i]: float(v) for i, v in zip(sub, k)}
        hinges[s] = (sign, {names[i]: float(v) for i, v in zip(idx, w)})
        tols[s] = rows.tol(y[s], np.concatenate([k, w]))
    pair: dict = {}

    def add(a, b, col, v):
        pair.setdefault((a, b), {})
        pair[(a, b)][col] = pair[(a, b)].get(col, 0.0) + v

    cols = sorted({c for d in lin.values() for c in d})
    for col in cols:
        got = {s: d[col] for s, d in lin.items() if abs(d.get(col, 0.0)) > 0}
        lin_col = dict(got)
        neg = [s for s, v in got.items() if v < 0]
        pos = [s for s, v in got.items() if v > 0]
        src = col if col in neg else (neg[0] if len(neg) == 1 else None)
        if src is not None and src in final:
            src = None
        if src is not None:
            give = -got[src]
            for p in sorted(pos, key=lambda s: -got[s]):
                if unit.get(p) != unit.get(src) or give <= 0:
                    continue
                m = min(got[p], give)
                add(src, p, col, m)
                give -= m
                got[p] -= m
            got[src] = -give
        big = max(abs(v) for v in lin_col.values())
        for s, v in got.items():
            if abs(v) > SNAP * big:                       # what is left of a matched term at the fit's precision is no flow
                if v > 0:
                    add(None, s, col, v)
                else:
                    add(s, None, col, -v)
    flows = []
    for (a, b), terms in pair.items():
        if a is None and b in fixed and set(terms) <= inputs and len(terms) == 1:
            (n_, k_), = terms.items()
            if abs(k_ - 1.0) <= 1e-3:
                terms = {n_: 1.0}                         # a side declared "input" is 1 x the input (boundary.py)
        flows.append(_flow(a, b, _rate(dict(terms), names), inputs))
    for s, (sign, w) in hinges.items():
        key = (None, s) if sign > 0 else (s, None)
        if key in pair:
            return None                                   # a hinge and a linear outside flow on one side
        flows.append(_flow(*key, _rate(dict(w), names), inputs))
    return flows, left, tols


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None, log: list | None = None) -> dict:
    """The result with each unit's flows read again from its rows where the answer leaves a row of
    exact data unexplained (see the module docstring)."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    opts = opts or {}
    data = _boundary.Data(stocks, run, opts)
    if not data.usable:
        return result
    ids = data.ids
    try:
        resid = data.dy - data.change(result["flows"])
    except Exception:                                     # noqa: BLE001  (a flow the simulator cannot evaluate)
        return result
    t = [float(x) for x in run["t"]]
    at = {x: i for i, x in enumerate(t)}
    ins = []
    for name, v in (opts.get("inputs") or {}).items():
        if name in ids or str(name).startswith("capmin__"):
            continue
        v = np.asarray(v, dtype=float)
        if len(v) != len(t):
            continue
        ins.append((name, np.array([v[at[float(x)]] for x in data.tt])))
    names = ids + [n for n, _ in ins] + ["1"]
    Z = np.vstack([data.L] + [u[None, :] for _, u in ins] + [np.ones((1, data.T))])
    levels = np.array([np.asarray(run["levels"][i], dtype=float) for i in ids])
    rows = _Rows(data, Z, names, _quantum(levels))
    ok = {}
    for i, s in enumerate(ids):
        e = rows.exact(data.dy[i])
        ok[s] = float(np.sqrt(np.mean(resid[i] ** 2))) <= rows.tol(data.dy[i], None if e is None else e[1])
    bad = [s for s in ids if not ok[s]]
    if not bad:
        return result
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    final = {s["id"] for s in stocks if s.get("final")}
    inputs = {n for n, _ in ins}
    b = _boundary.Boundary(run)
    flows = copy.deepcopy(result["flows"])
    trace = []
    for u in sorted({unit[s] for s in bad}):
        block = [s for s in ids if unit[s] == u]
        inside = set(block)
        touches = lambda f: bool({f.get("from"), f.get("to")} & inside)  # noqa: E731
        kept = [f for f in flows if not touches(f)]
        y = {s: data.dy[ids.index(s)] for s in block}
        got = _block(block, y, rows, unit, final, inputs, set(b.fixed))
        if got is None:
            continue
        new, left, tols = got
        if any(ok[s] for s in left) or not any(s not in left for s in block if not ok[s]):
            continue
        own = [f for f in flows if touches(f) and ((f.get("from") in left and f.get("to") is None)
                                                  or (f.get("to") in left and f.get("from") is None))]
        cand = kept + new + own
        if _boundary.violations(new, ids, b, inputs | {n for n in (opts.get("inputs") or {})}):
            continue
        try:
            r2 = data.dy - data.change(cand)
        except Exception:                                 # noqa: BLE001
            continue
        if any(float(np.sqrt(np.mean(r2[ids.index(s)] ** 2))) > 2 * tols[s] for s in block if s not in left):
            continue                                      # the written flows (floored by the engine) must reproduce the rows
        flows = cand
        trace.append(f"{u}: {len(new)} flows re-read from {len(block) - len(left)} exact rows; kept {left}")
    if not trace:
        return result
    out = dict(result)
    out["flows"] = flows
    out["reread"] = trace
    if log is not None:
        log.extend(trace)
    return out
