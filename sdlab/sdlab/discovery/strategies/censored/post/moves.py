"""Rows rebuilt together by best subset, their terms paired into moves (k8s 312, docs/research/fixes/312-structures.md).

rebuild.py (k8s 311) refits one row's outside sides by best subset when the base's forward stepwise left it far
from exact. A row whose missing terms are moves cannot be rebuilt that way: its partner rows lack them too. On
312 none-short the queue's change (traffic in, 0.6 x MIN(queue, 66.7 ready) to inflight, 0.08 queue to retries,
0.6 retries back) is a small difference of large terms; no single column explains it, the stepwise took the
node count first (`queue -> responses_total = 101 nodes`) and the dispatch move, the timeouts and the retries
were lost. Best subset finds the queue's row exactly (four columns).

Here the rows the answer leaves far from exact (residual rms above GATE x the data's quantum; counters
included, as receivers) are rebuilt together:

1. each row's change, less the flows it shares with a row outside the set (and its fixed declared sides), is
   fitted by best subset of at most MAX_TERMS columns (a constant, the non-counter levels, the inputs, the
   capacity series the row may read) on BIC; a row the best subset leaves far from exact (above GATE x the
   quantum: a nonlinear row, left to the later stages) leaves the set, and the set is refitted;
2. the terms are paired, column by column, into flows: a negative term on one row and a positive term of the
   same column on a row of the same unit are a move between them, reading that column (the largest receiver
   first, from the source whose remaining amount is closest); what is left on a row goes to its outside side
   where the declared boundary gives it one to estimate (with none declared, a side it already has); a term
   with no place takes its row out of the set;
3. the new flows replace the plain flows within the set, their numbers refitted jointly under the engine's
   floor (repair.py's active set), and the rebuild is kept when every row of the set is then near exact and
   the set's BIC falls by GAIN x log n.
"""

from __future__ import annotations

import copy
import math
import os

import numpy as np

from . import capmin, steps
from . import judge as J
from .hidden import _amount
from .rebuild import _best_subset
from .repair import _fit, _fixed_side, _linear, _numbers, _sign

GATE = 100.0
GAIN = 6.0
TRIM = 2               # (k8s 317, every=True) steps a row may miss by more than the tolerance
SNAP = 1e-3            # a leftover below this share of the column's largest term is rounding
_DEBUG = bool(os.environ.get("SDLAB_MOVES_DEBUG"))


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None, every: bool = False) -> dict:
    """opts: those the answer was fitted with (the capacity series offered as inputs, capmin.py). every: (k8s 317)
    every measured row is a candidate for the set, not only those the answer leaves far from exact."""
    if not isinstance(result, dict) or not result.get("flows") or (opts or {}).get("eras"):
        return result
    try:
        return _apply(result, stocks, run, opts or {}, every)
    except Exception as e:                            # noqa: BLE001  (the answer stands as it was)
        return {**result, "moves": {"error": f"{type(e).__name__}: {e}"[:300]}}


def _plain(f: dict) -> bool:
    return (_linear(f.get("rate")) is not None and not f.get("effects") and not f.get("byTime") and not f.get("via")
            and not f.get("uses") and not f.get("two_way") and float(f.get("ratio") or 1) == 1
            and (not f.get("input") or (f.get("from") and f.get("to")))      # (k8s 317) a move reading an input is plain
            and len(f.get("inflow") or []) <= 1)


def _apply(result: dict, stocks: list[dict], run: dict, opts: dict, every: bool = False) -> dict:
    ids = [s["id"] for s in stocks if s["id"] in (run.get("levels") or {})]
    L = {k: np.asarray(run["levels"][k], dtype=float) for k in ids}
    T = min(len(v) for v in L.values())
    if T < 30:
        return result
    n = T - 1
    X = {k: v[:n] for k, v in L.items()}
    inputs = []
    for k, v in (opts.get("inputs") or {}).items():
        if k not in X and len(v) >= T:
            X[k] = np.asarray(v, dtype=float)[1:T]
            inputs.append(k)
    dy = {k: np.diff(v[:T]) for k, v in L.items()}
    steps.adjust(X, dy, run, opts, n)
    q = J.quantum(np.vstack([v[:T] for v in L.values()]))
    floor = n * q * q / 12.0
    tol = GATE * q
    unit = {s["id"]: s.get("unit") for s in stocks}
    finals = {s["id"] for s in stocks if s.get("final")}
    declared = bool(run.get("boundary_declared"))
    bound = run.get("boundary") or {}
    flows = copy.deepcopy(result["flows"])
    amt = [_amount(f, X, n) for f in flows]
    tt = np.asarray(run["t"], dtype=float)[:n]
    if every:
        # (k8s 317) an outside flow written as a profile (a schedule of pieces, the base's stand-in for terms it
        # did not find) is one the rows may replace: its amount is its pieces' values, as the engine reads them
        amt = [_profile(f, tt) if _scheduled(f) else a for f, a in zip(flows, amt)]

    def rms(r):
        return float(np.sqrt(np.mean(r * r)))

    def rms_t(r):
        # (k8s 317) the row's misfit with its TRIM worst steps set aside: a limit that binds on one step (317's
        # dispatch, after a node failure) leaves one step off, and the row's terms are still the row's
        if len(r) <= 10 * TRIM:
            return rms(r)
        a = np.sort(np.abs(r))[:-TRIM] if TRIM else np.abs(r)
        return float(np.sqrt(np.mean(a * a)))

    def row_of(s, fl, am):
        net = np.zeros(n)
        for f, a in zip(fl, am):
            sg = _sign(f, s)
            if sg:
                if a is None:
                    return None
                net += sg * a
        return dy[s] - net

    def side_ok(s, side):
        if declared:
            k = (bound.get(s) or {}).get(side) or []
            k = [k] if isinstance(k, str) else list(k)
            return "estimate" in k
        return any((f.get("to") == s and f.get("from") is None) if side == "in" else (f.get("from") == s and f.get("to") is None)
                   for f in flows)

    forced = _forced(ids, finals, unit, bound) if declared else set()
    res0 = {s: row_of(s, flows, amt) for s in ids}
    bad = {s for s in ids if res0[s] is not None and (every or rms(res0[s]) > tol)}
    if len(bad) < 2:
        return result

    def replaceable(i, S):
        f = flows[i]
        a, b = f.get("from"), f.get("to")
        if not (_plain(f) or (every and _scheduled(f))) or amt[i] is None or _fixed_side(f, bound, declared):
            return False
        return (a is None or a in S) and (b is None or b in S) and (a in S or b in S)

    def cols_for(s):
        cols = {"1": np.ones(n)}
        for k in ids:
            if k not in finals and np.ptp(X[k]) > 0:
                cols[k] = X[k]
        for k in inputs:
            rd = capmin.readers(k, opts)
            if (rd is None or s in rd) and np.ptp(X[k]) > 0:
                cols[k] = X[k]
        return cols

    S = set(bad)
    fits = {}
    memo: dict = {}                  # (k8s 317) a row's best subset depends only on what is held on it
    wrow: dict = {}                  # (k8s 317) each row's steps kept by the robust fit
    for _ in range(len(ids)):
        mine = [i for i in range(len(flows)) if replaceable(i, S)]
        fits = {}
        drop = set()
        for s in S:
            hold = tuple(i for i in range(len(flows)) if i not in mine and _sign(flows[i], s))
            held = sum((_sign(flows[i], s) * amt[i] for i in hold), np.zeros(n))
            y = dy[s] - held
            if (s, hold) not in memo:
                memo[(s, hold)] = _robust_subset(y, cols_for(s), n, floor) if every else _best_subset(y, cols_for(s), n, floor)
            bic, names, beta = memo[(s, hold)]
            r = y - (np.column_stack([cols_for(s)[k] for k in names]) @ beta if names else 0.0)
            if (rms_t(r) if every else rms(r)) > tol:
                drop.add(s)
            # a term that moves less than the row's tolerance on every step is no flow (best subset fills its
            # columns: 312 none-short wrote 1e-12 x traffic beside the queue's fixed input)
            cs = cols_for(s)
            use = list(names)
            w = np.ones(n, dtype=bool)
            if every and TRIM and n > 10 * TRIM:
                w[np.argsort(np.abs(r))[-TRIM:]] = False      # (k8s 317) the steps the robust subset set aside
            for k in sorted(names, key=lambda k: float(np.max(np.abs(dict(zip(names, beta))[k] * cs[k])))):
                rest = [c for c in use if c != k]
                if not rest:
                    break
                A = np.column_stack([cs[c] for c in rest])
                bb = np.linalg.lstsq(A[w], y[w], rcond=None)[0]
                if (rms_t(y - A @ bb) if every else rms(y - A @ bb)) <= tol:
                    use = rest
            if use != list(names):
                A = np.column_stack([cs[c] for c in use])
                beta = np.linalg.lstsq(A[w], y[w], rcond=None)[0]
                names = tuple(use)
            fits[s] = {k: float(b) for k, b in zip(names, beta)}
            wrow[s] = w
        if _DEBUG:
            print("moves set", sorted(S), "drop", sorted(drop), {k: {c: round(x, 4) for c, x in v.items()} for k, v in fits.items()})
        if not drop:
            # pair the terms
            new, placed_ok, leftover_rows = _pair(fits, S, _joined(unit, forced), side_ok)
            if leftover_rows:
                if _DEBUG:
                    print("moves unplaced", sorted(leftover_rows))
                S -= leftover_rows
                continue
            break
        S -= drop
        if len(S) < 2:
            return {**result, "moves": {"bad": sorted(bad), "kept": False}}
    else:
        return {**result, "moves": {"bad": sorted(bad), "kept": False}}
    if len(S) < 2 or not new:
        return {**result, "moves": {"bad": sorted(bad), "kept": False}}
    mine = [i for i in range(len(flows)) if replaceable(i, S)]
    rows = sorted(S)
    k0 = _numbers(flows, mine)
    wm = None
    if every:
        # (k8s 317) both models judged, and the new one fitted, on the steps every row of the set kept
        wm = np.ones(n, dtype=bool)
        for s in rows:
            if s in wrow:
                wm &= wrow[s]
    sse0 = {s: float(res0[s][wm] @ res0[s][wm]) if wm is not None else float(res0[s] @ res0[s]) for s in rows}
    keep = [f for i, f in enumerate(flows) if i not in mine]
    cand = keep + new
    free = list(range(len(keep), len(cand)))
    got = _fit(cand, free, rows, X, dy, n, wm)
    if got is None:
        return {**result, "moves": {"bad": sorted(bad), "set": rows, "kept": False, "why": "the refit failed"}}
    cand, sse1 = got
    cand = [f for j, f in enumerate(cand) if j not in free or float(np.max(_amount(f, X, n))) > 0.0]
    k1 = _numbers(cand, [j for j, f in enumerate(cand) if str(f.get("id", "")).startswith("moves_")])
    bic0 = sum(n * math.log(max(v, floor) / n) for v in sse0.values()) + k0 * math.log(n)
    bic1 = sum(n * math.log(max(v, floor) / n) for v in sse1.values()) + k1 * math.log(n)
    worst = max(math.sqrt(v / n) for v in sse1.values())
    if every:
        am1 = [_profile(f, tt) if _scheduled(f) else _amount(f, X, n) for f in cand]
        worst = max((rms_t(r) for r in (row_of(s, cand, am1) for s in rows) if r is not None), default=worst)
    info = {"bad": sorted(bad), "set": rows, "bic": [round(bic0, 1), round(bic1, 1)], "worst_rms": worst,
            "flows": [f"{f.get('from') or 'outside'} -> {f.get('to') or 'outside'}" for f in new]}
    if worst > tol or not bic1 < bic0 - GAIN * math.log(n):
        return {**result, "moves": {**info, "kept": False}}
    return {**result, "flows": cand, "moves": {**info, "kept": True}}


def _robust_subset(y: np.ndarray, cols: dict, n: int, floor: float):
    """(k8s 317) The best subset chosen again with the TRIM steps its first choice misses most left out: one step
    a rare limit binds on (a node failure's) otherwise picks columns that only spike there (pending pods in the
    queue's row). The numbers are those of the trimmed fit."""
    got = _best_subset(y, cols, n, floor)
    if not TRIM or n <= 10 * TRIM:
        return got
    _, names, beta = got
    r = y - (np.column_stack([cols[k] for k in names]) @ beta if names else 0.0)
    keep = np.ones(n, dtype=bool)
    keep[np.argsort(np.abs(r))[-TRIM:]] = False
    m = int(keep.sum())
    return _best_subset(y[keep], {k: v[keep] for k, v in cols.items()}, m, floor * m / n)


def _scheduled(f: dict) -> bool:
    """(k8s 317) An outside flow whose amount is a profile of pieces in time (`inflow`), nothing else on it."""
    return (len(f.get("inflow") or []) > 1 and (f.get("from") is None) != (f.get("to") is None) and not f.get("effects")
            and not f.get("byTime") and not f.get("via") and not f.get("uses") and float(f.get("ratio") or 1) == 1)


def _profile(f: dict, t: np.ndarray) -> np.ndarray:
    """A profile's amount at each step's time: the first piece that covers it, else the last (simulate._Segments)."""
    segs = f["inflow"]
    order = sorted(range(len(segs)), key=lambda i: segs[i]["from"])
    froms = np.array([segs[i]["from"] for i in order], dtype=float)
    tos = np.array([segs[i]["to"] for i in order], dtype=float)
    vals = np.maximum(0.0, np.array([float(segs[i]["value"]) for i in order]))
    pos = np.searchsorted(froms, t, side="right") - 1
    ok = (pos >= 0) & (t <= tos[np.clip(pos, 0, None)])
    last = vals[int(np.argmax(np.array(order) == len(segs) - 1))]
    return np.where(ok, vals[np.clip(pos, 0, None)], last)


def _forced(ids: list[str], finals: set, unit: dict, bound: dict) -> set:
    """(k8s 317; the rule of 316's limited move, docs/research/fixes/316-structures.md) The moves the declared boundary
    forces across units: a source alone in its unit with no outside outflow, into a receiver alone in its unit with
    no outside inflow (316/317: a waiting query takes a pool connection). Nothing else may cross units."""
    count: dict = {}
    for s in ids:
        if s not in finals:
            count[unit.get(s)] = count.get(unit.get(s), 0) + 1
    alone = [s for s in ids if s not in finals and unit.get(s) is not None and count.get(unit.get(s)) == 1]
    side = {s: (bound.get(s) or {}) for s in alone}
    return {(a, b) for a in alone for b in alone if a != b and not side[a].get("out") and not side[b].get("in")}


def _joined(unit: dict, forced: set) -> dict:
    """The units with the two ends of each forced move made one (the pairing joins terms within a unit)."""
    out = dict(unit)
    for a, b in sorted(forced):
        ua, ub = out.get(a), out.get(b)
        if ua != ub:
            for k, v in list(out.items()):
                if v == ub:
                    out[k] = ua
    return out


def _pair(fits: dict, S: set, unit: dict, side_ok) -> tuple[list[dict], bool, set]:
    """The flows the rows' terms make (see the module): (flows, True, rows whose terms have no place)."""
    terms: dict[tuple, float] = {}            # (from, to, column) -> number
    bad_rows: set = set()
    columns = sorted({c for f in fits.values() for c in f})
    for col in columns:
        on = {s: fits[s][col] for s in fits if col in fits[s]}
        big = max(abs(v) for v in on.values())
        if col != "1":
            for u in sorted({unit.get(s) for s in on}, key=str):
                grp = {s: v for s, v in on.items() if unit.get(s) == u and u is not None}
                src = {s: -v for s, v in grp.items() if v < 0}
                # (k8s 317) receivers with no outside inflow first: their term can only be a move, while one
                # with a side may take the rest as a link (317: cart_inflight feeds responses 0.5 and errors 0.03 by
                # moves and catalog_queue 0.2 by a link; largest first gave catalog_queue the errors' share)
                snk = sorted(((v, s) for s, v in grp.items() if v > 0), key=lambda vs: (side_ok(vs[1], "in"), -vs[0]))
                for v, b in snk:
                    while v > SNAP * big and src:
                        a = min(src, key=lambda s: (src[s] < v * (1 - 1e-6), abs(src[s] - v)))
                        take = min(v, src[a])
                        terms[(a, b, col)] = terms.get((a, b, col), 0.0) + take
                        src[a] -= take
                        v -= take
                        on[a] += take
                        on[b] -= take
                        if src[a] <= SNAP * big:
                            src.pop(a)
        for s, v in on.items():
            if abs(v) <= SNAP * big:
                continue
            side = "in" if v > 0 else "out"
            if not side_ok(s, side):
                bad_rows.add(s)
                continue
            key = (None, s, col) if side == "in" else (s, None, col)
            terms[key] = terms.get(key, 0.0) + abs(v)
    if bad_rows:
        return [], False, bad_rows
    by_pair: dict[tuple, dict] = {}
    for (a, b, col), v in terms.items():
        by_pair.setdefault((a, b), {})[col] = v
    out = []
    for (a, b), cs in sorted(by_pair.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
        c = float(cs.pop("1", 0.0))
        ks = [{"stock": k, "k": float(v)} for k, v in cs.items()]
        if not ks:
            rate = {"form": "constant", "value": c}
        elif len(ks) == 1 and c == 0.0:
            rate = {"form": "proportional", "stock": ks[0]["stock"], "k": ks[0]["k"]}
        else:
            rate = {"form": "linear", "c": c, "terms": ks}
        out.append({"id": f"moves_{a or 'outside'}_{b or 'outside'}", "from": a, "to": b, "ratio": 1, "rate": rate, "rates": [rate]})
    return out, True, set()


def coflows(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """(k8s 312, the coflow-earn rule proposed in 307-structures.md) a co-flow (a flow's `uses`: what it draws
    from another stock per unit moved) must pay its number: it is dropped when the drawn stock's row is no
    worse without the draw, by BIC (log n per number). On 312 none-short the base's `pending -> ready` drew
    0.535 queue requests per pod started (its queue row was junk); once the queue's row is rebuilt it is exact
    without the draw, and the draw left every pod row unreadable to the later stages."""
    if not isinstance(result, dict) or not result.get("flows") or (opts or {}).get("eras"):
        return result
    try:
        return _coflows(result, stocks, run, opts or {})
    except Exception as e:                            # noqa: BLE001  (the answer stands as it was)
        return {**result, "coflows": {"error": f"{type(e).__name__}: {e}"[:300]}}


def _coflows(result: dict, stocks: list[dict], run: dict, opts: dict) -> dict:
    if not any(f.get("uses") for f in result["flows"]):
        return result
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
    steps.adjust(X, dy, run, opts, n)
    q = J.quantum(np.vstack([v[:T] for v in L.values()]))
    floor = n * q * q / 12.0
    flows = copy.deepcopy(result["flows"])
    dropped, added = [], []
    for f in flows:
        for u in list(f.get("uses") or []):
            s = u.get("stock")
            if s not in dy:
                continue
            bare = {k: v for k, v in f.items() if k != "uses"}
            a = _amount(bare, X, n)
            if a is None:
                continue
            net = np.zeros(n)
            ok = True
            for g in flows:
                if g is f or not _sign(g, s):
                    continue
                b = _amount(g, X, n)
                if b is None:
                    ok = False
                    break
                net += _sign(g, s) * b
            if not ok:
                continue
            draw = float(u.get("per") or 0.0) * a
            r_with = dy[s] - net + draw - _sign(f, s) * a
            r_without = dy[s] - net - _sign(f, s) * a
            b_with = n * math.log(max(float(r_with @ r_with), floor) / n) + math.log(n)
            b_without = n * math.log(max(float(r_without @ r_without), floor) / n)
            if b_without <= b_with:
                f["uses"] = [x for x in f["uses"] if x is not u]
                dropped.append(f"{f.get('from')} -> {f.get('to')} uses {s}")
                continue
            # a draw that pays is written out as what it is, an outflow of the drawn stock at per x the flow's
            # rate, where the drawn stock may have one (312 none-long: `pending -> oom_kills_total` drew 1.79 ready
            # per unit; as a co-flow it left the pod rows unreadable to every later stage)
            lin = _linear(bare.get("rate"))
            if lin is None or bare.get("effects") or bare.get("byTime") or not _side_ok(s, "out", flows, run):
                continue
            per = float(u.get("per") or 0.0)
            c, ks = lin
            rate = {"form": "linear", "c": per * c, "terms": [{"stock": k, "k": per * v} for k, v in ks.items()]}
            added.append({"id": f"coflow_{s}_out", "from": s, "to": None, "ratio": 1, "rate": rate, "rates": [rate]})
            f["uses"] = [x for x in f["uses"] if x is not u]
            dropped.append(f"{f.get('from')} -> {f.get('to')} uses {s}: written as {s} -> outside")
        if "uses" in f and not f["uses"]:
            f.pop("uses")
            f.pop("note", None)
    if not dropped:
        return result
    return {**result, "flows": flows + added, "coflows": {"dropped": dropped}}


def _side_ok(s: str, side: str, flows: list[dict], run: dict) -> bool:
    if run.get("boundary_declared"):
        k = ((run.get("boundary") or {}).get(s) or {}).get(side) or []
        k = [k] if isinstance(k, str) else list(k)
        return "estimate" in k
    return True
