"""Rows the answer leaves unexplained, repaired with the plain moves and outflows they lack (k8s 310, 2026-10-22,
docs/research/fixes/310-structures.md; the idea of combined2's counted._repair, c22e751, written here anew).

The answer's stages are judged on the whole model, and a row they cannot explain can be left with a flow the
floor never lets move (310 none-short: `retries -> outside = max(0, -0.41 - 0.0002 retries)`, nothing into
retries, no `retries -> queue`, the retries row's misfit taken by nothing). Here:

- the **bad rows** are the measured stocks (not counters) whose flows this module can read (constant,
  proportional and linear rates, table effects) and whose one-step residual is above GATE x the data's
  quantum;
- the **free flows** are the plain flows on a bad row (no effect, no profile): their numbers are refitted
  jointly on every row they touch by active-set least squares (a flow's columns count only on the steps
  where its rate is positive, as the engine floors it; started unfloored), every other flow held;
- **candidates** are added one at a time: a proportional move A -> B between measured stocks of one unit
  (both ends bad rows: a move repairs two rows; never out of a counter; 310 none-long took
  `pending -> oom_kills_total` while the counter's row was explained but for its counted inflow), or a bad row's proportional outflow on a side the declared
  boundary has (any side with none declared). The one that lowers the touched rows' BIC most is kept when
  it gains GAIN x log n, then the next.

The repair replaces the answer only when the touched rows' BIC falls by GAIN x log n in all.
"""

from __future__ import annotations

import copy
import math

import numpy as np

from ._vendored.combined import judge as J
from .hidden import _amount

GATE = 100.0
GAIN = 2.0
ACTIVE_ITERS = 8
MAX_ADDS = 6


def _linear(r: dict | None) -> tuple[float, dict] | None:
    if r is None:
        return None
    f = r.get("form")
    if f == "constant":
        return float(r.get("value") or 0.0), {}
    if f == "proportional":
        return 0.0, {r.get("stock"): float(r.get("k") or 0.0)}
    if f == "linear":
        return float(r.get("c") or 0.0), {t.get("stock"): float(t.get("k") or 0.0) for t in r.get("terms") or []}
    return None


def _fixed_side(f: dict, bound: dict, declared: bool) -> bool:
    """An outside flow on a side the declared boundary gives as measured or an input (1 x the series)."""
    if not declared or (f.get("from") and f.get("to")):
        return False
    s, side = (f.get("to"), "in") if f.get("from") is None else (f.get("from"), "out")
    kinds = (bound.get(s) or {}).get(side) or []
    kinds = [kinds] if isinstance(kinds, str) else list(kinds)
    return bool(kinds) and "estimate" not in kinds


def _free(f: dict, X: dict, bound: dict | None = None, declared: bool = False) -> bool:
    lin = _linear(f.get("rate"))
    return (lin is not None and not _fixed_side(f, bound or {}, declared) and not f.get("effects") and len(f.get("inflow") or []) <= 1 and not f.get("byTime")
            and not f.get("via") and not f.get("uses") and not f.get("two_way") and float(f.get("ratio") or 1) == 1
            and all(k in X for k in lin[1]))


def _sign(f: dict, s: str) -> float:
    return (1.0 if f.get("to") == s else 0.0) - (1.0 if f.get("from") == s else 0.0)


def _fit(flows: list[dict], free: list[int], rows: list[str], X: dict, dy: dict, n: int) -> tuple[list[dict], dict] | None:
    """The free flows' numbers fitted jointly on `rows` (active set, see the module): (flows, {row: SSE})."""
    held = np.zeros((len(rows), n))
    for f in [g for i, g in enumerate(flows) if i not in set(free)]:
        if not any(_sign(f, s) for s in rows):
            continue
        a = _amount(f, X, n)
        if a is None:
            return None
        for j, s in enumerate(rows):
            held[j] += _sign(f, s) * a
    y = np.concatenate([dy[s] - held[j] for j, s in enumerate(rows)])
    params = []
    for i in free:
        c, ks = _linear(flows[i]["rate"])
        params.append((i, ["1"] + list(ks) if (c or not ks) else list(ks)))
    masks = [np.ones(n, dtype=bool) for _ in params]
    b = None
    for _ in range(ACTIVE_ITERS):
        blocks = []
        for s in rows:
            cols = []
            for (i, names), on in zip(params, masks):
                sg = _sign(flows[i], s)
                cols += [sg * on * (np.ones(n) if nm == "1" else X[nm]) for nm in names]
            blocks.append(np.column_stack(cols))
        A = np.vstack(blocks)
        sc = np.maximum(np.abs(A).max(axis=0), 1e-300)
        b = np.linalg.lstsq(A / sc, y, rcond=None)[0] / sc
        new, j = [], 0
        for _, names in params:
            v = sum(b[j + q] * (np.ones(n) if nm == "1" else X[nm]) for q, nm in enumerate(names))
            new.append(np.asarray(v) > 0)
            j += len(names)
        if all(np.array_equal(m1, m2) for m1, m2 in zip(new, masks)):
            break
        masks = new
    out = copy.deepcopy(flows)
    j = 0
    for i, names in params:
        c, terms = 0.0, []
        for nm in names:
            if nm == "1":
                c = float(b[j])
            else:
                terms.append({"stock": nm, "k": float(b[j])})
            j += 1
        out[i].pop("inflow", None)
        if not terms:
            out[i]["rate"] = {"form": "constant", "value": c}
        elif len(terms) == 1 and c == 0.0:
            out[i]["rate"] = {"form": "proportional", "stock": terms[0]["stock"], "k": terms[0]["k"]}
        else:
            out[i]["rate"] = {"form": "linear", "c": c, "terms": terms}
        if out[i].get("rates"):
            out[i]["rates"] = [out[i]["rate"]]
    sse = {}
    for s in rows:
        net = np.zeros(n)
        for f in out:
            sg = _sign(f, s)
            if sg:
                a = _amount(f, X, n)
                if a is None:
                    return None
                net += sg * a
        r = dy[s] - net
        sse[s] = float(r @ r)
    return out, sse


def _numbers(flows: list[dict], idx: list[int]) -> int:
    k = 0
    for i in idx:
        c, ks = _linear(flows[i]["rate"])
        k += len(ks) + (1 if (c or not ks) else 0)
    return k


def _bic(sse: dict, k: int, n: int, floor: float) -> float:
    return sum(n * math.log(max(v, floor) / n) for v in sse.values()) + k * math.log(n)


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    if not isinstance(result, dict) or not result.get("flows") or (opts or {}).get("eras") or (opts or {}).get("injections"):
        return result
    try:
        return _apply(result, stocks, run, opts or {})
    except Exception as e:                            # noqa: BLE001  (the answer stands as it was)
        return {**result, "repair": {"error": f"{type(e).__name__}: {e}"[:300]}}


def _apply(result: dict, stocks: list[dict], run: dict, opts: dict) -> dict:
    ids = [s["id"] for s in stocks if s["id"] in (run.get("levels") or {})]
    L = {k: np.asarray(run["levels"][k], dtype=float) for k in ids}
    T = min(len(v) for v in L.values())
    if T < 30:
        return result
    n = T - 1
    X = {k: v[:n] for k, v in L.items()}
    for k, v in (opts.get("inputs") or {}).items():
        if k not in X and len(v) >= T:
            X[k] = np.asarray(v, dtype=float)[1:T]
    dy = {k: np.diff(v[:T]) for k, v in L.items()}
    q = J.quantum(np.vstack([v[:T] for v in L.values()]))
    floor = n * q * q / 12.0
    unit = {s["id"]: s.get("unit") for s in stocks}
    finals = {s["id"] for s in stocks if s.get("final")}
    declared = bool(run.get("boundary_declared"))
    bound = run.get("boundary") or {}
    flows = list(result["flows"])
    measured = set(ids)

    def readable(s):
        return all(_amount(f, X, n) is not None for f in flows if _sign(f, s) or (f.get("from") == s or f.get("to") == s))

    bad = []
    for s in ids:
        if s in finals or not readable(s):
            continue
        net = np.zeros(n)
        for f in flows:
            if f.get("from") == s or f.get("to") == s:
                net += _sign(f, s) * _amount(f, X, n)
        r = dy[s] - net
        if float(np.sqrt(np.mean(r * r))) > GATE * q:
            bad.append(s)
    if not bad:
        return result

    def touched(fl):
        rows = set(bad)
        for f in fl:
            if (f.get("from") in bad or f.get("to") in bad) and _free(f, X, bound, declared):
                rows |= {x for x in (f.get("from"), f.get("to")) if x in measured}
        return sorted(rows)

    def readable_in(fl, s):
        return all(_amount(f, X, n) is not None for f in fl if f.get("from") == s or f.get("to") == s)

    def all_sse(fl):
        out = {}
        for s in ids:
            on = [f for f in fl if f.get("from") == s or f.get("to") == s]
            amts = [_amount(f, X, n) for f in on]
            if any(a is None for a in amts):
                continue                                  # a row this cannot read: the same in every candidate
            net = sum((_sign(f, s) * a for f, a in zip(on, amts)), np.zeros(n))
            out[s] = float(((dy[s] - net) ** 2).sum())
        return out

    def evaluate(fl):
        rows = touched(fl)
        if not all(readable_in(fl, s) for s in rows):
            return None
        free = [i for i, f in enumerate(fl) if (f.get("from") in bad or f.get("to") in bad) and _free(f, X, bound, declared)]
        if not free:
            return None
        got = _fit(fl, free, rows, X, dy, n)
        if got is None:
            return None
        return _bic(all_sse(got[0]), _numbers(got[0], free), n, floor), got[0], rows

    base = evaluate(flows)
    if base is None:
        return result
    free0 = [i for i, f in enumerate(flows) if (f.get("from") in bad or f.get("to") in bad) and _free(f, X, bound, declared)]
    bic0 = _bic(all_sse(flows), _numbers(flows, free0), n, floor)
    cur = base
    added = []
    for _ in range(MAX_ADDS):
        have = {(f.get("from"), f.get("to")) for f in cur[1]}
        cands = []
        for a in ids:
            for b in ids:
                if a == b or a in finals or (a, b) in have or unit.get(a) != unit.get(b):
                    continue
                if a not in bad or b not in bad:
                    continue                              # a move repairs two rows: both must be unexplained
                cands.append({"id": f"repair_{a}_{b}", "from": a, "to": b, "ratio": 1, "rate": {"form": "proportional", "stock": a, "k": 0.0}})
        for s in bad:
            sides = bound.get(s) or {}
            if (s, None) in have or (declared and "estimate" not in (sides.get("out") or [])):
                continue
            cands.append({"id": f"repair_{s}_out", "from": s, "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": s, "k": 0.0}})
        top = None
        for c in cands:
            got = evaluate(cur[1] + [c])
            if got is not None and (top is None or got[0] < top[0][0]):
                top = (got, c)
        if top is None or not top[0][0] < cur[0] - GAIN * math.log(n):
            break
        cur = top[0]
        added.append(f"{top[1]['from']} -> {top[1]['to'] or 'outside'}")
    if not added or not cur[0] < bic0 - GAIN * math.log(n):
        return {**result, "repair": {"bad": bad, "added": [], "kept": False}}
    # a free flow the refit leaves moving nothing (its rate at or below 0 on every step) is dropped
    out = [f for f in cur[1] if not (_free(f, X, bound, declared) and (f.get("from") in bad or f.get("to") in bad)
                                     and float(np.max(_amount(f, X, n))) <= 0.0)]
    return {**result, "flows": out, "repair": {"bad": bad, "added": added, "bic": [round(bic0, 2), round(cur[0], 2)], "kept": True}}
