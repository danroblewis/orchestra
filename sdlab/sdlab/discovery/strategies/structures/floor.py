"""Outside flows fitted under the engine's floor (k8s 309, 2026-10-21, docs/research/fixes/309-structures.md).

The engine floors every rate at 0: a linear rate `ready - desired` moves nothing while ready is below
desired and deletes the surplus at once when it is above. The fits upstream regress each stock's change
on its levels as if the rate were linear everywhere, so a rate whose floor binds on most steps (a
surplus removed, a missing amount created: a one-step goal gap closed only one way) comes out as a small
drift, and the misfit is routed through spurious moves (309: `desired -> ready = 0.118 desired` beside
`ready -> outside = 0.12 ready` in place of `ready -> outside = ready - desired`).

Here each measured stock's outside side (one the declared boundary has; with no declared boundary only
a side that already has an outside flow) is refitted as one floored linear rate, max(0, c + w . X), with
X chosen among the measured levels and inputs (a link: it may cross units) by forward selection on BIC
(then backward), on the stock's change, the numbers of its other plain flows refitted with it. The fit
is Gauss-Newton on the hinge (a floored rate counts only on the steps where it is above 0), started
from the steps where what the other flows leave moves. Each candidate is also offered with one of the
stock's moves dropped (the move the misfit was routed through). Every candidate's numbers are then
refitted on all stocks together under the floors (_refit: the same Gauss-Newton, every plain flow's
rate active only where it is above 0, each stock's rows weighted by its residual variance), and a
candidate replaces the model only when combined's judge (judge.score: the one-step likelihood with the
engine's floors, and a BIC price) prefers the whole model, the controller forms (controller.py) applied
to both. The best change is taken and the search repeats (ROUNDS).
"""

from __future__ import annotations

import copy
import json
import math
import os

import numpy as np

from sdlab.discovery.simulate import Model

from . import controller
from ._vendored.combined import judge as J

ROUNDS = 4
MAX_TERMS = 4
GN_ITERS = 12
MIN_BINDS = 3       # a floored rate must be at or below 0 on at least this many steps
PLAIN = ("constant", "proportional", "linear")
_DEBUG = bool(os.environ.get("SDLAB_FLOOR_DEBUG"))


def _plain(f: dict) -> bool:
    r = f.get("rate") or {}
    return (r.get("form") in PLAIN and not f.get("byTime") and not f.get("inflow") and not f.get("effects")
            and not f.get("uses") and not f.get("via") and float(f.get("ratio") or 1) == 1)


def _reads(f: dict) -> set:
    r = f.get("rate") or {}
    out = {r.get("stock")} if r.get("stock") else set()
    return out | {t.get("stock") for t in r.get("terms") or []}


def _cols(rate: dict, mat: dict) -> list[tuple] | None:
    """The rate's free numbers as (key, column); None when it reads a column that is not there."""
    form = rate.get("form")
    n = len(next(iter(mat.values())))
    if form == "constant":
        return [(("value",), np.ones(n))]
    if form == "proportional":
        x = mat.get(rate.get("stock"))
        return None if x is None else [(("k",), x)]
    out = [(("c",), np.ones(n))] if rate.get("c") else []
    for j, t in enumerate(rate.get("terms") or []):
        x = mat.get(t.get("stock"))
        if x is None:
            return None
        out.append((("terms", j), x))
    return out


def _get(rate: dict, key: tuple) -> float:
    return float(rate["terms"][key[1]]["k"]) if key[0] == "terms" else float(rate.get(key[0]) or 0.0)


def _set(rate: dict, key: tuple, v: float) -> None:
    if key[0] == "terms":
        rate["terms"][key[1]]["k"] = float(v)
    else:
        rate[key[0]] = float(v)


def _gn(y: np.ndarray, blocks: list[tuple], theta: np.ndarray, w: np.ndarray | None = None) -> tuple[np.ndarray, float]:
    """Gauss-Newton for y ~ sum over blocks (sign, columns C (n x k), slice into theta) of sign x max(0, C theta)
    (row weights w); every block is floored. Returns (theta, weighted SSE)."""
    w = np.ones(len(y)) if w is None else w

    def pred(th):
        p = np.zeros(len(y))
        for sg, C, sl in blocks:
            p += sg * np.maximum(0.0, C @ th[sl])
        return p
    best = (theta.copy(), float(np.sum(w * (y - pred(theta)) ** 2)))
    th = theta.copy()
    prev_act = None
    for _ in range(GN_ITERS):
        D = np.zeros((len(y), len(th)))
        acts = []
        for sg, C, sl in blocks:
            a = (C @ th[sl]) > 0
            acts.append(a)
            D[:, sl] += sg * C * a[:, None]
        act = np.concatenate(acts) if acts else None
        if prev_act is not None and np.array_equal(act, prev_act):
            break
        prev_act = act
        sw = np.sqrt(w)
        try:
            th = np.linalg.lstsq(D * sw[:, None], y * sw, rcond=None)[0]
        except np.linalg.LinAlgError:
            break
        sse = float(np.sum(w * (y - pred(th)) ** 2))
        if sse < best[1]:
            best = (th.copy(), sse)
    return best


def _row_fit(y: np.ndarray, free: list[tuple], A: np.ndarray, sign: float, thr: float) -> tuple[np.ndarray, float] | None:
    """The stock's row: its other plain flows (free: (sign, columns, start numbers)) and the new floored
    side (sign x max(0, A w)), w started on the steps where what the free flows leave moves."""
    blocks, theta, k = [], [], 0
    for sg, C, th0 in free:
        blocks.append((sg, C, slice(k, k + C.shape[1])))
        theta.extend(th0)
        k += C.shape[1]
    theta = np.array(theta, dtype=float)
    base = np.zeros(len(y))
    for sg, C, sl in blocks:
        base += sg * np.maximum(0.0, C @ theta[sl])
    r = sign * (y - base)
    act = r > thr
    if act.sum() < A.shape[1] + 1:
        return None
    try:
        w0 = np.linalg.lstsq(A[act], r[act], rcond=None)[0]
    except np.linalg.LinAlgError:
        return None
    blocks.append((sign, A, slice(k, k + A.shape[1])))
    return _gn(y, blocks, np.concatenate([theta, w0]))


def _select(y: np.ndarray, free: list[tuple], cols: dict[str, np.ndarray], sign: float, q: float) -> tuple[dict, list] | None:
    """The floored linear rate for the stock's side (a linear rate dict) and its free flows' refitted
    numbers, the side's columns chosen forward then backward on BIC."""
    n = len(y)
    floor = max(q * q / 6.0, 1e-300)
    thr = max(0.5 * q, 1e-9 * float(np.max(np.abs(y)) or 1.0))
    mat = {"1": np.ones(n), **cols}
    names = list(mat)
    nfree = sum(C.shape[1] for _, C, _ in free)

    def fit(use):
        got = _row_fit(y, free, np.column_stack([mat[k] for k in use]), sign, thr)
        if got is None:
            return None
        return n * math.log(max(got[1] / n, floor)) + (len(use) + nfree) * math.log(n), got[0]
    chosen: list[str] = []
    best = None
    while len(chosen) < MAX_TERMS:
        step = None
        for c in names:
            if c in chosen:
                continue
            got = fit(chosen + [c])
            if got is not None and (step is None or got[0] < step[0]):
                step = (got[0], chosen + [c], got[1])
        if step is None or (best is not None and not step[0] < best[0]):
            break
        best, chosen = (step[0], step[2]), step[1]
    if best is None:
        return None
    pruned = True
    while pruned and len(chosen) > 1:
        pruned = False
        for c in list(chosen):
            use = [k for k in chosen if k != c]
            got = fit(use)
            if got is not None and got[0] <= best[0]:
                best, chosen, pruned = got, use, True
                break
    th = best[1]
    c, terms = 0.0, []
    for k, v in zip(chosen, th[nfree:]):
        if k == "1":
            c = float(v)
        else:
            terms.append({"stock": k, "k": float(v)})
    if not terms:
        return None                                   # a floored constant is a constant: the fits upstream have it
    out, k = [], 0
    for _, C, _ in free:
        out.append(th[k:k + C.shape[1]])
        k += C.shape[1]
    return {"form": "linear", "c": c, "terms": terms}, out


def _refit(flows: list[dict], data: J.Data, mat: dict, offered: set) -> list[dict]:
    """Every plain flow's numbers refitted on all measured stocks together, each rate floored at 0 (see
    the module); the other flows held as they are."""
    ids = data.ids
    index = {s: i for i, s in enumerate(ids)}
    free, fixed = [], []
    for f in flows:
        c = _cols(f.get("rate") or {}, mat) if _plain(f) and not (_reads(f) & offered) else None
        (free if c else fixed).append((f, c))
    if not free:
        return flows
    S, T = data.dy.shape
    fx = J.one_step([f for f, _ in fixed], data)[0] if fixed else np.zeros_like(data.dy)
    y = (data.dy - fx).reshape(-1)
    blocks, theta, k = [], [], 0
    for f, c in free:
        C = np.column_stack([col for _, col in c])
        th0 = [_get(f["rate"], key) for key, _ in c]
        for s, sg in ((f.get("from"), -1.0), (f.get("to"), 1.0)):
            if s in index:
                big = np.zeros((S * T, C.shape[1]))
                big[index[s] * T:(index[s] + 1) * T] = C
                blocks.append((sg, big, slice(k, k + C.shape[1])))
        theta.extend(th0)
        k += C.shape[1]
    theta = np.array(theta, dtype=float)
    floor = max(data.q ** 2 / 6.0, 1e-300)
    th = theta
    for _ in range(3):                                # feasible weighted LS: each stock's rows by its residual variance
        p = np.zeros(S * T)
        for sg, C, sl in blocks:
            p += sg * np.maximum(0.0, C @ th[sl])
        v = np.maximum(((y - p).reshape(S, T) ** 2).mean(axis=1), floor)
        th = _gn(y, blocks, th, np.repeat(1.0 / v, T))[0]
    out = []
    k = 0
    new = {}
    for f, c in free:
        g = copy.deepcopy(f)
        for key, _ in c:
            _set(g["rate"], key, th[k])
            k += 1
        if g.get("rates"):
            g["rates"] = [g["rate"]]
        new[id(f)] = g
    for f in flows:
        out.append(new.get(id(f), f))
    return out


def _post(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None) -> list[dict]:
    return controller.apply({"flows": flows}, stocks, run, opts).get("flows") or flows


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None, judge_opts: dict | None = None) -> dict:
    """The answer with outside rates refitted under the floor where the judge prefers it (see the module).
    opts: what the caller was given (the controller's drivers); judge_opts: the opts the flows were fitted
    with (a capacity series offered as an input, capmin.py), for the judge's inputs."""
    if not isinstance(result, dict) or not result.get("flows") or (opts or {}).get("eras"):
        return result
    jo = judge_opts if judge_opts is not None else (opts or {})
    try:
        return _apply(result, stocks, run, opts or {}, jo)
    except Exception as e:                            # noqa: BLE001  (the answer stands as it was)
        return {**result, "floor": {"error": f"{type(e).__name__}: {e}"[:300]}}


def _apply(result: dict, stocks: list[dict], run: dict, opts: dict, jo: dict) -> dict:
    data = J.Data(stocks, run, jo.get("injections"), jo.get("inputs"))
    ids = data.ids
    measured = set(ids)
    final = {s["id"] for s in stocks if s.get("final")}
    declared = bool(run.get("boundary_declared"))
    bound = run.get("boundary") or {}
    offered = set((jo.get("capmin") or {}).keys()) | {k for k in (jo.get("inputs") or {}) if k not in (opts.get("inputs") or {})}
    R = Model([], ids, inputs=data.model_inputs)._read(data.prev, data.tt)
    names = list(ids) + ([k for k in data.inputs if k not in measured] if data.inputs else [])
    allcols = {k: R[i] for i, k in enumerate(names)}
    cols = {k: v for k, v in allcols.items() if k not in offered and np.ptp(v) > 0}
    cur = list(result["flows"])

    def judge(fl):
        return J.score(_post(fl, stocks, run, opts), data)["bic"]
    best = judge(cur)
    first = best
    again = _refit(cur, data, allcols, offered)            # the baseline refitted the same way, so a change earns its
    b = judge(again)                                       # place by its structure, not by the refit of its numbers
    if b < best:
        best, cur = b, again
    margin = math.log(max(2, data.T))                      # a change must beat the baseline by more than this
    made = []
    for _ in range(ROUNDS):
        top = None
        for i, s in enumerate(ids):
            if s in final:
                continue
            for side in ("in", "out"):
                if side == "in":
                    here = [f for f in cur if f.get("from") is None and f.get("to") == s]
                else:
                    here = [f for f in cur if f.get("from") == s and f.get("to") is None]
                if declared and not (bound.get(s) or {}).get(side):
                    continue
                if not declared and not here:
                    continue
                if any(not _plain(f) or (_reads(f) & offered) for f in here):
                    continue
                moves = [f for f in cur if f.get("from") in measured and f.get("to") in measured and s in (f["from"], f["to"])
                         and _plain(f) and not (_reads(f) & offered)]
                for drop, own in [(d_, o_) for d_ in [[]] + [[mv] for mv in moves] for o_ in (False, True)]:
                    gone = here + drop
                    kept = [f for f in cur if not any(f is g for g in gone)]
                    touch = [f for f in kept if s in (f.get("from"), f.get("to"))]
                    free, fixed_f, free_f = [], [], []
                    for f in touch:
                        # own: only the stock's own outside flows are refitted with the side (its moves held: their
                        # other stock's row has them too); else its moves are refitted with it as well
                        mine = not (f.get("from") in measured and f.get("to") in measured)
                        c = _cols(f.get("rate") or {}, allcols) if _plain(f) and not (_reads(f) & offered) and (mine or not own) else None
                        if c:
                            free.append((-1.0 if f.get("from") == s else 1.0, np.column_stack([col for _, col in c]),
                                         [_get(f["rate"], key) for key, _ in c]))
                            free_f.append((f, c))
                        else:
                            fixed_f.append(f)
                    mu = J.one_step(fixed_f, data)[0] if fixed_f else np.zeros_like(data.dy)
                    y = data.dy[i] - mu[i]
                    got = _select(y, free, cols, 1.0 if side == "in" else -1.0, data.q)
                    if got is None:
                        continue
                    rate, nums = got
                    amount = rate["c"] + sum(t["k"] * cols[t["stock"]] for t in rate["terms"])
                    if int(np.sum(amount <= 0)) < MIN_BINDS:
                        continue                              # the floor never binds: a linear rate, which the fits upstream have
                    upd = {}
                    for (f, c), th in zip(free_f, nums):
                        g = copy.deepcopy(f)
                        for (key, _), v in zip(c, th):
                            _set(g["rate"], key, v)
                        if g.get("rates"):
                            g["rates"] = [g["rate"]]
                        upd[id(f)] = g
                    new = [upd.get(id(f), f) for f in kept]
                    new.append({"id": f"floor_{s}_{side}", "from": None if side == "in" else s, "to": s if side == "in" else None,
                                "ratio": 1, "rate": rate, "rates": [rate]})
                    note = {"stock": s, "side": side, "dropped": [(f.get("from"), f.get("to")) for f in drop]}
                    for cand in (new, _refit(new, data, allcols, offered)):
                        b = judge(cand)
                        if _DEBUG:
                            print("floor cand", s, side, own, note["dropped"], round(b, 1), round(best, 1), json.dumps(rate))
                        if top is None or b < top[0]:
                            top = (b, cand, note)
        if top is None or not top[0] < best - margin:
            break
        best, cur = top[0], top[1]
        side_rate = next((f["rate"] for f in cur if f.get("id") == f"floor_{top[2]['stock']}_{top[2]['side']}"), None)
        made.append({**top[2], "rate": side_rate})
    if not made:
        return result
    return {**result, "flows": cur, "floor": {"changes": made, "bic": {"before": round(first, 3), "after": round(best, 3)}}}
