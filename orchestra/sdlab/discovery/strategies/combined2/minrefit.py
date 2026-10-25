"""A capacity limit's numbers refitted on the rows it touches (docs/research/fixes/311-combined2.md, 2026-10-22).

capmin.offer fits a limit MIN(X, theta Y) or MIN(X, theta x max(0, beta Y - Z)) before the model exists: on rows
that still carry every flow the fit has not found yet (kubernetes 311: the pods' start, min(0.5 pending,
4 nodes - ready), was offered as min(0.61 pending, max(0, 3.83 nodes - 0.96 ready)) while the OOM kills and the
created / deleted gaps were still in the pending and ready rows). Once the later passes have placed those
flows, the limit's numbers are refitted here.

For each move A -> B whose rate is a limit as capmin.restore writes it, `min(k * X, c * Y)` or
`min(k * X, max(0, a * Y + b * Z))`, on the rows of A and B with every other flow held: the steps are split into
regimes (the demand arm, the capacity arm, the capacity at its floor), each arm's numbers are fitted by least
squares on its steps (both rows at once: the move leaves one and enters the other), and the regimes are
recomputed from the fit until they settle (active-set least squares, as hinge.hfit). Then the block of A's unit
is repaired with the limit held (counted._repair_once: the moves and outside rates refitted jointly, the floored
sides refitted), and the two alternate ROUNDS times. The result is kept only where the block's BIC falls.

Adopting it: copy this file with counted.py and hinge.py (hinge.amount evaluates the limit's expression) and call
`apply(result, stocks, run, opts)` after the passes that place the block's other flows.
"""

from __future__ import annotations

import copy
import math
import re

import numpy as np

from . import counted, hinge

ROUNDS = 4
GAIN = 2.0           # a limit kept must lower its block's BIC by more than GAIN log n (_earn)
ITERS = 30
FLOOR_REL = 1e-9

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_PLAIN = re.compile(rf"min\(\s*({_NUM})\s*\*\s*(\w+)\s*,\s*({_NUM})\s*\*\s*(\w+)\s*\)")
_ROOM = re.compile(rf"min\(\s*({_NUM})\s*\*\s*(\w+)\s*,\s*max\(\s*0\s*,\s*({_NUM})\s*\*\s*(\w+)\s*\+\s*({_NUM})\s*\*\s*(\w+)\s*\)\s*\)")


def parse(expr: str) -> dict | None:
    """{"k", "x", "cap": [(c, Y), ...], "room": bool} for a limit as capmin writes it, else None."""
    if not isinstance(expr, str):
        return None
    m = _ROOM.fullmatch(expr.strip())
    if m:
        return {"k": float(m.group(1)), "x": m.group(2), "cap": [(float(m.group(3)), m.group(4)), (float(m.group(5)), m.group(6))], "room": True}
    m = _PLAIN.fullmatch(expr.strip())
    if m:
        return {"k": float(m.group(1)), "x": m.group(2), "cap": [(float(m.group(3)), m.group(4))], "room": False}
    return None


def write(p: dict) -> str:
    k, x = p["k"], p["x"]
    if p["room"]:
        (a, y), (b, z) = p["cap"]
        return f"min({k!r} * {x}, max(0, {a!r} * {y} + {b!r} * {z}))"
    (c, y), = p["cap"]
    return f"min({k!r} * {x}, {c!r} * {y})"


def _free(f: dict, rows: set, cols: dict, n: int) -> bool:
    """A linear flow on the rows that is refitted with the limit (counted._refit_moves' rule)."""
    a, b = f.get("from"), f.get("to")
    inner = a in rows and b in rows
    side = (a is None and b in rows) or (b is None and a in rows)
    return (inner or side) and not f.get("effects") and not f.get("inflow") and not f.get("counted") and not f.get("input") \
        and hinge._linear(f.get("rate") or {}) is not None and hinge.amount(f, cols, n) is not None


def _names(f: dict) -> list[str]:
    c, ks = hinge._linear(f["rate"])
    return (["1"] if c else []) + list(ks)


def _known(nm: str, cols: dict) -> bool:
    """(2026-10-22, k8s-316) a measured column, or the constant 1 (a fixed pool's size, capmin.ONE)."""
    return nm == "1" or nm in cols


def _block(unit: dict, src: str, dst: str):
    """(2026-10-22, k8s-316) The units whose rows a limit's move touches: its source's, and its receiver's where the
    declared boundary forces a move across units (capmin.forced_pairs); one unit otherwise, as before."""
    return {unit.get(src), unit.get(dst)}


def _col(nm: str, cols: dict, n: int) -> np.ndarray:
    return np.ones(n) if nm == "1" else np.asarray(cols[nm][:n], dtype=float)


def _fit(p: dict, src: str, dst: str, flows: list[dict], fid, levels, cols, n, rows: set | None = None):
    """The limit's numbers and the rows' free linear flows together, by active-set least squares on the rows:
    the limit's steps split into its regimes (the demand arm, the capacity arm, the capacity at its floor) and
    each free flow's into those where it is positive (the engine floors every flow), refitted until they
    settle. (limit, flows) or None."""
    rows = sorted(rows or {src, dst})
    free = [i for i, f in enumerate(flows) if f.get("id") != fid and _free(f, set(rows), cols, n) and _names(f)]
    held = [f for i, f in enumerate(flows) if f.get("id") != fid and i not in free]
    ys = []
    for x in rows:
        got = hinge.row_error(x, held, levels, cols, n)
        if got is None:
            return None
        r, sides = got
        ys.append(r - sides["in"] + sides["out"])
    y = np.concatenate(ys)

    def sign(f, x):
        return (-float(f.get("ratio") or 1)) if f.get("from") == x else (1.0 if f.get("to") == x else 0.0)

    lim = {"from": src, "to": dst}
    X = _col(p["x"], cols, n)
    C = np.column_stack([_col(v, cols, n) for _, v in p["cap"]])
    params = [(i, _names(flows[i])) for i in free]
    cur = dict(p)
    masks = [np.ones(n, dtype=bool) for _ in params]
    b = None
    for _ in range(ITERS):
        cap = C @ np.array([c for c, _ in cur["cap"]])
        arm_x = cur["k"] * X <= np.maximum(0.0, cap)
        arm_c = (~arm_x) & (cap > 0)
        blocks = []
        for x in rows:
            s = sign(lim, x)
            cx = [s * X * arm_x] + [s * C[:, j] * arm_c for j in range(C.shape[1])]
            for (i, names), on in zip(params, masks):
                g = sign(flows[i], x)
                cx += [g * on * _col(nm, cols, n) for nm in names]
            blocks.append(np.column_stack(cx))
        b, *_ = np.linalg.lstsq(np.vstack(blocks), y, rcond=None)
        new = dict(cur, k=float(b[0]) if arm_x.any() else cur["k"])
        if arm_c.sum() > C.shape[1]:
            new["cap"] = [(float(v), nm) for v, (_, nm) in zip(b[1:1 + C.shape[1]], cur["cap"])]
        j = 1 + C.shape[1]
        nm2 = []
        for _, names in params:
            v = np.zeros(n)
            for nm, k in zip(names, b[j:j + len(names)]):
                v = v + k * _col(nm, cols, n)
            nm2.append(v > 0)
            j += len(names)
        if new == cur and all(np.array_equal(m1, m2) for m1, m2 in zip(nm2, masks)):
            break
        cur, masks = new, nm2
    out = copy.deepcopy(flows)
    j = 1 + C.shape[1]
    for i, names in params:
        c, terms = 0.0, []
        for nm in names:
            if nm == "1":
                c = float(b[j])
            else:
                terms.append({"stock": nm, "k": float(b[j])})
            j += 1
        f = out[i]
        if not terms:
            f["rate"] = {"form": "constant", "value": c}
        elif len(terms) == 1 and not c and f["rate"].get("form") == "proportional":
            f["rate"] = {"form": "proportional", "stock": terms[0]["stock"], "k": terms[0]["k"]}
        else:
            f["rate"] = {"form": "linear", "c": c, "terms": terms}
    for f in out:
        if f.get("id") == fid:
            f["rate"] = {"form": "expr", "expr": write(cur)}
    return cur, out


def _block_bic(flows, rows, levels, cols, n, floor) -> float | None:
    sse = 0.0
    for x in rows:
        v = counted._row_sse(x, flows, levels, cols, n)
        if v is None:
            return None
        sse += v
    return counted._bic_rows(sse, counted._nums(flows, rows), n, len(rows), floor)


def _without(f: dict, nm: str) -> dict | None:
    """f with the term nm (or its constant, "1") removed; None where nothing would be left (the flow goes)."""
    c, ks = hinge._linear(f["rate"])
    if nm == "1":
        c = 0.0
    else:
        ks = {k: v for k, v in ks.items() if k != nm}
    if not ks and not c:
        return None
    g = copy.deepcopy(f)
    g["rate"] = {"form": "linear", "c": c, "terms": [{"stock": k, "k": v} for k, v in ks.items()]} if ks else {"form": "constant", "value": c}
    return g


def _prune(q, src, dst, flows, fid, rows, levels, cols, n, floor):
    """Backward elimination: each term of the rows' free linear flows (a flow's last term: the flow) dropped in
    turn, the limit and the flows refitted together (_fit), the drop kept where the block's BIC falls; repeated
    while one does. A limit offered slightly off leaves the other flows a term to make up for it (311 none-long:
    the pods' deletion took 12 - 4 nodes), which the alternation keeps; dropped, the limit fits exactly."""
    cur, bic = flows, _block_bic(flows, rows, levels, cols, n, floor)
    dropped = []
    while bic is not None:
        best = None
        for i, f in enumerate(cur):
            if f.get("id") == fid or not _free(f, set(rows), cols, n) or not _names(f):
                continue
            for nm in _names(f):
                g = _without(f, nm)
                trial = cur[:i] + ([g] if g else []) + cur[i + 1:]
                got = _fit(q, src, dst, trial, fid, levels, cols, n, rows)
                if got is None:
                    continue
                b = _block_bic(got[1], rows, levels, cols, n, floor)
                if b is not None and b < bic and (best is None or b < best[0]):
                    best = (b, got, f"{f.get('from') or 'outside'} -> {f.get('to') or 'outside'}: {nm}")
        if best is None:
            break
        bic, (q, cur) = best[0], best[1]
        dropped.append(best[2])
    return q, cur, bic, dropped


def _amount(p: dict, cols, n) -> np.ndarray:
    cap = sum(c * _col(v, cols, n) for c, v in p["cap"])
    return np.maximum(0.0, np.minimum(p["k"] * cols[p["x"]][:n], np.maximum(0.0, cap) if p["room"] else cap))


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    levels, cols, n = hinge.columns(run, opts)
    if n < 10:
        return result
    unit = {s["id"]: s.get("unit") for s in stocks if s["id"] in levels}
    finals = {s["id"] for s in stocks if s.get("final")}
    out, notes = _refit_all(result, run, levels, cols, n, unit, finals)
    out, gone = _earn(out, run, levels, cols, n, unit, finals)
    if notes:
        out["limits_refitted"] = notes
    if gone:
        out["limits_unearned"] = gone
    return out


def _limits(flows: list[dict], levels, cols) -> list[dict]:
    out = []
    for f in flows:
        p = parse((f.get("rate") or {}).get("expr")) if (f.get("rate") or {}).get("form") == "expr" else None
        if p is not None and f.get("from") in levels and f.get("to") in levels and float(f.get("ratio") or 1) == 1 \
                and not f.get("effects") and all(_known(v, cols) for v in [p["x"]] + [v for _, v in p["cap"]]):
            out.append(f)
    return out


def _earn(out: dict, run, levels, cols, n, unit, finals) -> tuple[dict, list]:
    """(2026-10-22, k8s-312 round 2, docs/research/fixes/312-combined2-r2.md) Each limit must earn its numbers once
    the block's other flows are placed: the answer without it, every other limit refitted (_refit_all), replaces
    the answer where the block's BIC (its SSE floored at the levels' rounding, rowrepair.resolution) does not rise
    by more than GAIN log n. capmin offers a limit on rows that still carry every flow the fit has not found
    (312 none-long: ready -> pending = min(0.0017 ready, max(0, 0.0117 pending)) beside the counted OOM move
    ready x table(mem)); held, it pins the real limit (the pods' start) at min(0.508 pending, 4.02 nodes - 1.005
    ready), 2400 x the truth's misfit; dropped, the start refits to min(0.5 pending, 4 nodes - ready)."""
    from . import rowrepair

    gone = []
    for key in [(g["from"], g["to"], g["rate"]["expr"]) for g in _limits(out["flows"], levels, cols)]:
        f = next((g for g in _limits(out["flows"], levels, cols) if (g["from"], g["to"], g["rate"]["expr"]) == key), None)
        if f is None:                                     # refitted when another limit went: judged as it now is
            f = next((g for g in _limits(out["flows"], levels, cols) if (g["from"], g["to"]) == key[:2]), None)
        if f is None:
            continue
        rows = {x for x in levels if unit.get(x) in _block(unit, f["from"], f["to"]) and x not in finals
                and hinge.row_error(x, out["flows"], levels, cols, n) is not None}
        if not {f["from"], f["to"]} <= rows:
            continue
        scale = max(1e-12, max(float(np.abs(hinge.delta(levels, x, n)).max()) for x in rows))
        floor = len(rows) * n * max((FLOOR_REL * scale) ** 2, rowrepair.resolution(levels, rows) ** 2 / 6)
        bic0 = _block_bic(out["flows"], rows, levels, cols, n, floor)
        if bic0 is None:
            continue
        trial = dict(out, flows=[g for g in out["flows"] if g is not f])
        trial, _ = _refit_all(trial, run, levels, cols, n, unit, finals)
        bic1 = _block_bic(trial["flows"], rows, levels, cols, n, floor)
        if bic1 is not None and bic1 < bic0 + GAIN * math.log(n):
            gone.append({"flow": f"{f['from']} -> {f['to']}", "expr": f["rate"]["expr"], "bic_with": bic0, "bic_without": bic1})
            out = trial
    return out, gone


def _refit_all(result: dict, run, levels, cols, n, unit, finals) -> tuple[dict, list]:
    out = copy.deepcopy(result)
    notes = []
    for i, f in enumerate(list(out["flows"])):
        src, dst = f.get("from"), f.get("to")
        p = parse((f.get("rate") or {}).get("expr")) if (f.get("rate") or {}).get("form") == "expr" else None
        if p is None or src not in levels or dst not in levels or float(f.get("ratio") or 1) != 1 or f.get("effects") \
                or any(not _known(v, cols) for v in [p["x"]] + [v for _, v in p["cap"]]):
            continue
        fid = f.setdefault("id", f"limit_{src}_{dst}")
        flows = out["flows"]
        rows = {x for x in levels if unit.get(x) in _block(unit, src, dst) and x not in finals
                and hinge.row_error(x, flows, levels, cols, n) is not None}
        if not {src, dst} <= rows:
            continue
        scale = max(1e-12, max(float(np.abs(hinge.delta(levels, x, n)).max()) for x in rows))
        floor = len(rows) * n * (FLOOR_REL * scale) ** 2
        sse0 = [counted._row_sse(x, flows, levels, cols, n) for x in rows]
        if any(v is None for v in sse0):
            continue
        bic0 = counted._bic_rows(sum(sse0), counted._nums(flows, rows), n, len(rows), floor)   # the answer as it came
        cur, q = flows, p
        for _ in range(ROUNDS):
            got = _fit(q, src, dst, cur, fid, levels, cols, n, rows)
            if got is None:
                q = None
                break
            q, cur = got
            for x in sorted(rows):                         # each row's floored sides refitted with the limit held
                have = {s for g in cur for s in [hinge._side(g, x)] if s}
                got = hinge.refit_row(x, cur, levels, cols, n, hinge.allowed_sides(x, run, cur) & have, force=True)
                if got is not None:
                    cur = got[0]
        if q is not None:                                  # the limit and the moves fitted last
            got = _fit(q, src, dst, cur, fid, levels, cols, n, rows)
            q, cur = got if got else (None, cur)
        if q is None:
            continue
        q, cur, bic1, dropped = _prune(q, src, dst, cur, fid, rows, levels, cols, n, floor)
        if bic1 < bic0:
            out["flows"] = cur
            notes.append({"flow": f"{src} -> {dst}", "before": write(p), "after": write(q), "bic_before": bic0, "bic_after": bic1,
                          **({"dropped": dropped} if dropped else {})})
    return out, notes
