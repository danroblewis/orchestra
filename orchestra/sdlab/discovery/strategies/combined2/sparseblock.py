"""A unit's block of rows re-read sparsely from the levels where the pick does not explain it exactly
(docs/research/fixes/315-combined2.md, 2026-10-22).

The judge picks one specialist's whole model, and every later pass refits the flows that model has. When stocks
move together (kubernetes 315: catalog and cart share one caller, so their queues and inflights are nearly
collinear on the record, relative size 1e-6), a specialist can explain the block with crossed moves between the
two chains (`cart_queue -> catalog_inflight`, `catalog_queue -> cart_inflight`) and outside flows reading
whichever of the collinear levels its search met first. That model is close but not exact on noise-free levels,
and nothing downstream searches for the sparser model that is.

Here, for each unit (a move carries one thing, so a unit's measured stocks form a block whose one-step rows
depend only on the flows that touch them), when the levels are reported to a resolution q > 0 (noise-free
decimals; on whole-number counts this pass is idle) and the pick's flows leave the block's rows above EXACT times
the rounding's variance, the block is re-read from the levels alone:

  atoms   every proportional move A -> B (A not final, both in the block: each appears in two rows with opposite
          signs, so mass balance identifies it), and on every outside side the boundary allows (declared, not
          `input`; with none declared, the sides the pick has) a term k x X for each measured, non-final column X;
  fit     forward selection of atoms by non-negative least squares on the stacked rows (sides fixed at 1 x an
          input are held), each step kept while the block's BIC falls by more than GAIN log n, then backward:
          each atom dropped where that does not raise the BIC by more than GAIN log n.

The re-read replaces the pick's flows on the block only when it is exact (SSE within EXACT times the rounding's
variance) and the pick's is over FAR times its SSE, and only when every flow the pick has on the block is a
plain linear or proportional rate between measured stocks (a switch, table, MIN or hidden stock is left to the
passes that wrote it). A side's terms are written as one linear flow (one flow per declared side).

(2026-10-22, k8s-316, docs/research/fixes/316-combined2.md) A block is one unit, or the units a move the declared
boundary forces across units joins (capmin.forced_pairs: a waiting query takes a connection). And a capacity limit
the block already has (a move whose rate is a MIN expression capmin.restore wrote, which hinge.amount evaluates)
is held: the rows are re-read with its amounts taken off, and it is kept as it is. 316 none-short: the limit
db_waiting -> db_active was exact, but the pick had fitted the two rows' outside flows without it (-63.8 +
0.18 pricing_queue into db_waiting); re-read, they are 0.06 pricing_inflight + 0.1 cart_inflight and 0.8 db_active.

Adopting it: copy this file (it needs hinge.py's columns / delta / row_error / allowed_sides / _linear / amount,
counted.py's _row_sse and rowrepair.resolution) and call `apply(result, stocks, run, opts)` on the pick before
the passes that refit rows.
"""

from __future__ import annotations

import copy
import itertools

import numpy as np
from scipy.optimize import nnls

from . import counted, hinge, rowrepair

EXACT = 100.0         # as blocks.EXACT: a block is exact when its SSE is within this many times the rounding's variance
FAR = 1e3             # the pick's block is replaced only when its SSE is over this many times the re-read's
MAX_TERMS = 4         # columns one row may read
RARE = 0.01          # (k8s-317) at most this share of the steps a rarely binding limit may leave unexplained (_rare)
COND = 1e6            # a column set more collinear than this (scaled columns' condition number) reads nothing (engine_forms reread.COND)


def _plain(f: dict, levels) -> bool:
    if any(x and x not in levels for x in (f.get("from"), f.get("to"))):
        return False
    r = f.get("rate") or {}
    if f.get("effects") or (r.get("form") not in ("proportional", "linear", "constant", "const")):   # (k8s-317) a constant too
        return False
    return hinge._linear(r) is not None


def _limit(f: dict, rows, levels, cols: dict, n: int) -> bool:
    """(2026-10-22, k8s-316) A move inside the block whose rate is an expression hinge.amount evaluates (a capacity
    limit capmin.restore wrote): held while the block is re-read."""
    r = f.get("rate") or {}
    return r.get("form") == "expr" and f.get("from") in rows and f.get("to") in rows and not f.get("effects") \
        and hinge.amount(f, cols, n) is not None


def _blocks(unit: dict, flows: list[dict], pairs: set) -> list[list[str]]:
    """(2026-10-22, k8s-316) The rows of each unit, with the units a forced cross-unit move of the flows joins merged."""
    groups = {u: {x for x, v in unit.items() if v == u} for u in set(unit.values())}
    for f in flows:
        a, b = f.get("from"), f.get("to")
        if (a, b) in pairs and a in unit and b in unit and unit[a] != unit[b]:
            ga, gb = next(g for g in groups.values() if a in g), next(g for g in groups.values() if b in g)
            if ga is not gb:
                ga |= gb
                groups = {k: g for k, g in groups.items() if g is not gb}
    return sorted((sorted(g) for g in groups.values()), key=lambda r: "+".join(sorted({unit[x] for x in r})))


def _input_side(x: str, run: dict) -> bool:
    kinds = ((run.get("boundary") or {}).get(x) or {}).get("in") or []
    return bool(run.get("boundary_declared")) and "input" in kinds


def _subset(y: np.ndarray, pool: dict, names: list[str], tol: float) -> dict | None:
    """The smallest set of columns (at most MAX_TERMS; the fewest, then the lowest SSE) whose least-squares fit
    reproduces y to tol, columns more collinear than COND excluded: {column: number}; None when no set does."""
    if float(y @ y) <= tol:
        return {}
    for size in range(1, MAX_TERMS + 1):
        best = None
        for idx in itertools.combinations(names, size):
            A = np.column_stack([pool[c] for c in idx])
            nrm = np.sqrt(np.sum(A ** 2, axis=0))
            if size > 1 and np.linalg.cond(A / nrm) > COND:
                continue
            c, *_ = np.linalg.lstsq(A, y, rcond=None)
            e = y - A @ c
            sse = float(e @ e)
            if sse <= tol and (best is None or sse < best[0]):
                best = (sse, dict(zip(idx, (float(v) for v in c))))
        if best is not None:
            return best[1]
    return None


def _masked_sse(x: str, flows: list[dict], levels, cols: dict, n: int, keep) -> float | None:
    """(k8s-317) X's row's SSE on the kept steps (all of them when keep is None)."""
    if keep is None:
        return counted._row_sse(x, flows, levels, cols, n)
    got = hinge.row_error(x, flows, levels, cols, n)
    if got is None:
        return None
    r, sides = got
    e = (r - sides["in"] + sides["out"])[keep]
    return float(e @ e)


def _rare(rows: list[str], flows: list[dict], run: dict, levels, cols: dict, n: int, finals: set, q: float):
    """(2026-10-22, k8s-317, docs/research/fixes/317-combined2.md) The steps a block's rows leave unexplained when a
    rarely binding limit is all that keeps a row from being linear: for each row no linear set reproduces, the best
    set (at most MAX_TERMS columns) that reproduces it on all but RARE of the steps; their union, as a mask of the
    steps kept (None when a row has no such set, or every row is linear already). 317 none-short: frontend's
    dispatch MIN binds on 1 of 300 steps, so its queue and inflight rows are linear but for one step, and the whole
    requests block (15 rows: three services' queues, retries, inflights and counters) was refused."""
    held = [f for f in flows if (f.get("from") is None and f.get("to") in rows and _input_side(f["to"], run))
            or _limit(f, rows, levels, cols, n)]
    tol = EXACT * n * q * q / 6
    names = sorted(c for c in cols if c not in finals and np.std(cols[c][:n]) > 0)
    pool = {c: np.asarray(cols[c][:n], dtype=float) for c in names}
    out = np.zeros(n, dtype=bool)
    cut = max(1, int(RARE * n))
    for x in rows:
        got = hinge.row_error(x, held, levels, cols, n)
        if got is None:
            return None
        r, sides = got
        y = r - sides["in"] + sides["out"]
        if _subset(y, pool, names, tol) is not None:
            continue
        best = None
        for size in range(1, MAX_TERMS + 1):
            for idx in itertools.combinations(names, size):
                A = np.column_stack([pool[c] for c in idx])
                nrm = np.sqrt(np.sum(A ** 2, axis=0))
                if size > 1 and np.linalg.cond(A / nrm) > COND:
                    continue
                c, *_ = np.linalg.lstsq(A, y, rcond=None)
                e = (y - A @ c) ** 2
                worst = np.argsort(e)[-cut:]
                ok = np.ones(n, dtype=bool)
                ok[worst] = False
                c, *_ = np.linalg.lstsq(A[ok], y[ok], rcond=None)       # refitted without them (they pull the fit)
                e = (y - A @ c) ** 2
                worst = np.argsort(e)[-cut:]
                rest = float(e.sum() - e[worst].sum())
                if rest <= tol * (n - cut) / n:
                    big = np.zeros(n, dtype=bool)
                    big[worst] = True
                    big &= e > tol / n                     # only the steps it really misses
                    if best is None or rest < best[0]:
                        best = (rest, big)
            if best is not None:
                break
        if best is None:
            return None
        out |= best[1]
    if not out.any():
        return None
    return ~out


def _reread(rows: list[str], flows: list[dict], run: dict, levels, cols: dict, n: int, finals: set, q: float,
            unit: dict | None = None, pairs: set = frozenset(), keep=None):
    """The block read again from the levels: each row's exact best subset, its terms joined into moves and outside
    flows (atoms), whose numbers are fitted together by non-negative least squares on the stacked rows, then each
    atom dropped (outside terms first: a move conserves) where the block stays exact. (flows, SSE, atoms) or None."""
    held = [f for f in flows if (f.get("from") is None and f.get("to") in rows and _input_side(f["to"], run))
            or _limit(f, rows, levels, cols, n)]
    unit = unit or {}
    m = n if keep is None else int(keep.sum())            # (k8s-317) the steps read: all, or those _rare keeps
    tol = EXACT * m * q * q / 6
    names = sorted(c for c in cols if c not in finals and np.std(cols[c][:n]) > 0)
    pool = {c: np.asarray(cols[c][:n], dtype=float)[keep if keep is not None else slice(None)] for c in names}
    ys, W = {}, {}
    for x in rows:
        got = hinge.row_error(x, held, levels, cols, n)
        if got is None:
            return None
        r, sides = got
        ys[x] = (r - sides["in"] + sides["out"])[keep if keep is not None else slice(None)]
        w = _subset(ys[x], pool, names, tol)
        if w is None:
            return None                                  # a row no linear set reproduces: not this pass's
        W[x] = w
    atoms = []
    for a in rows:
        if a in finals or W[a].get(a, 0.0) >= 0:
            continue
        for b in rows:
            if b != a and W[b].get(a, 0.0) > 0 and (unit.get(a) == unit.get(b) or (a, b) in pairs):
                atoms.append(("move", a, b, a))
    for x in rows:
        sides = hinge.allowed_sides(x, run, flows)
        for c, k in W[x].items():
            s = "in" if k > 0 else "out"
            if s in sides and not (s == "in" and _input_side(x, run)):
                atoms.append((s, x, None, c))
    if not atoms:
        return None
    pos = {x: i for i, x in enumerate(rows)}
    y = np.concatenate([ys[x] for x in rows])
    vecs = []
    for kind, a, b, c in atoms:
        v = np.zeros(len(y))
        if kind == "move":
            v[pos[a] * m:(pos[a] + 1) * m] -= pool[a]
            v[pos[b] * m:(pos[b] + 1) * m] += pool[a]
        else:
            v[pos[a] * m:(pos[a] + 1) * m] = pool[c] if kind == "in" else -pool[c]
        vecs.append(v)
    M = np.column_stack(vecs)
    chosen = list(range(len(atoms)))
    coef, res = nnls(M, y, maxiter=50 * len(atoms) + 50)
    total = len(rows) * tol
    if float(res * res) > total:
        return None
    order = sorted(chosen, key=lambda j: (atoms[j][0] == "move", j))   # outside terms tried first
    for j in order:
        idx = [i for i in chosen if i != j]
        if not idx:
            continue
        c2, r2 = nnls(M[:, idx], y, maxiter=50 * len(idx) + 50)
        if float(r2 * r2) <= total:
            chosen, coef, res = idx, c2, r2
    if len(coef) != len(chosen):
        coef = nnls(M[:, chosen], y, maxiter=50 * len(chosen) + 50)[0]
    new = [dict(f) for f in held]
    side_terms: dict = {}
    k_used = 0
    for j, k in zip(chosen, coef):
        if k <= 0:
            continue
        k_used += 1
        kind, a, b, c = atoms[j]
        if kind == "move":
            new.append({"id": f"sparse_{a}_{b}", "from": a, "to": b, "ratio": 1, "rate": {"form": "proportional", "stock": a, "k": float(k)}})
        else:
            side_terms.setdefault((kind, a), []).append({"stock": c, "k": float(k)})
    for (kind, x), terms in sorted(side_terms.items()):
        rate = {"form": "linear", "c": 0.0, "terms": terms}
        if kind == "in":
            new.append({"id": f"sparse_in_{x}", "from": None, "to": x, "ratio": 1, "rate": rate})
        else:
            new.append({"id": f"sparse_out_{x}", "from": x, "to": None, "ratio": 1, "rate": rate})
    sse = sum(_masked_sse(x, new, levels, cols, n, keep) or 0.0 for x in rows)
    return new, sse, k_used


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer with each unit's block re-read sparsely where the pick does not explain it exactly (module docstring)."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    levels, cols, n = hinge.columns(run, opts)
    if n < 10:
        return result
    unit = {s["id"]: s.get("unit") for s in stocks if s["id"] in levels and s.get("unit")}
    finals = {s["id"] for s in stocks if s.get("final")}
    flows = list(result["flows"])
    notes = []
    from .capmin import forced_pairs
    pairs = forced_pairs(stocks, run)
    for rows in _blocks(unit, flows, pairs):
        u = "+".join(sorted({unit[x] for x in rows}))
        if len(rows) < 2:
            continue
        q = rowrepair.resolution(levels, rows)
        if q <= 0:
            continue
        mine = [f for f in flows if f.get("from") in rows or f.get("to") in rows]
        if not mine or not all(_plain(f, levels) or _limit(f, rows, levels, cols, n) for f in mine):
            continue
        if any(f.get("from") in rows and f.get("to") and f.get("to") not in rows for f in mine) or \
                any(f.get("to") in rows and f.get("from") and f.get("from") not in rows for f in mine):
            continue                                     # a move out of the block (another unit's): left alone
        exact = EXACT * len(rows) * n * q * q / 6
        sse_pick = 0.0
        for x in rows:
            v = counted._row_sse(x, flows, levels, cols, n)
            if v is None:
                sse_pick = None
                break
            sse_pick += v
        if sse_pick is None or sse_pick <= exact:
            continue
        keep = None
        got = _reread(rows, flows, run, levels, cols, n, finals, q, unit, pairs)
        if got is None:
            # (k8s-317) a row linear but for a rarely binding limit: the block read on the other steps, and compared
            # with the pick's on the same steps; a limit the block holds is first held, then left out (a limit the
            # rows do not need on the steps read is not kept: 317's offered room limit on frontend's queue)
            bases = [flows]
            free = [f for f in flows if not _limit(f, rows, levels, cols, n)]
            if len(free) < len(flows):
                bases.append(free)
            for base in bases:
                keep = _rare(rows, base, run, levels, cols, n, finals, q)
                got = None if keep is None else _reread(rows, base, run, levels, cols, n, finals, q, unit, pairs, keep)
                if got is not None:
                    break
            if got is None:
                continue
            exact = EXACT * len(rows) * int(keep.sum()) * q * q / 6
            sse_pick = 0.0
            for x in rows:
                v = _masked_sse(x, flows, levels, cols, n, keep)
                if v is None:
                    sse_pick = None
                    break
                sse_pick += v
            if sse_pick is None:
                continue
        new, sse, k = got
        if sse > exact or sse_pick <= FAR * max(sse, 1e-300):
            continue
        flows = [f for f in flows if not (f.get("from") in rows or f.get("to") in rows)] + new
        notes.append({"unit": u, "rows": rows, "sse_pick": sse_pick, "sse": sse, "atoms": k,
                      **({"steps_set_aside": int(n - keep.sum())} if keep is not None else {})})
    if not notes:
        return result
    out = copy.deepcopy(result)
    out["flows"] = flows
    out["sparse_blocks"] = notes
    return out
