"""z3exact: exact structure search on noise-free data (docs/research/z3.md, experiment B).

The fewest terms that fit every one-step change within the data's own rounding, with the declared
boundary as a hard constraint (core.py: Z3 over exact rationals, a copy of the harness's z3_ident.py),
then the numbers refitted by least squares (all stocks' changes jointly). The class is linear: moves
between stocks of one unit reading one of their two stocks ("ends"), and outside terms where the
boundary allows them (constants, measured inputs, levels; per announced era); the boundary first as
written (an outside term only on a declared side of its column's kind), then, if nothing fits, as the
scorer reads it (any declared side), then with moves reading any column ("any"). Of several smallest structures, the one with the least squared
error is returned (and the rest counted in the note).

When nothing fits within the rounding (noisy data, or a truth outside the linear class: nonlinear rates,
floors, unannounced changes) it returns a BEST EFFORT, labelled so in its note and in result["z3"]
["best_effort"]: backward elimination on the same linear class, each stock's squared error kept within
1.05 x the all-term model's (`_best_effort`; no Z3, no proof).
"""

from __future__ import annotations

import time

import numpy as np

from . import core

BUDGET = 25.0                 # seconds of Z3 search per exact class
BEST_EFFORT_RSS = 1.05        # best effort: a term is dropped while every stock's RSS stays within this x the all-term model's
TOTAL = 95.0                  # seconds for everything (the ladder's item timeout is 120 s; Z3 and HiGHS are not interruptible)
CLASSES = (("ends", "kinds"), ("ends", "sides"), ("any", "sides"))   # tried in turn until one fits
CAP = 12                      # smallest structures compared at most


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    notes = []
    began = time.perf_counter()
    for moves, rule in CLASSES:
        budget = min(BUDGET, TOTAL - (time.perf_counter() - began))
        if budget < 5:
            notes.append(f"[{moves}, {rule}] not tried (out of time)")
            break
        p = core.prepare(stocks, run, opts, moves=moves, boundary=rule)
        if p.steps < 20:
            return {"flows": [], "note": "z3exact: too few steps."}
        r = core.enumerate_structures(p, slack=0, cap=CAP, budget=budget)
        notes.append(f"[{moves}, {rule}] {r['status']} ({r['seconds']:.1f} s, {r.get('checks')} checks)")
        if not r["structures"]:
            if r["status"].startswith("unknown"):
                break
            continue
        fits = []
        for sup in r["structures"]:
            k, miss = core.refit(p, sup)
            fits.append((_sse(p, sup, k), sup, k, miss))
        fits.sort(key=lambda x: x[0])
        _, sup, k, miss = fits[0]
        note = (f"z3exact: {len(sup)} terms, {r['status']} in the class '{moves}, {rule}'"
                + (f" ({len(fits)} smallest structures fit; the least squared error kept)" if len(fits) > 1 else "")
                + f"; largest one-step residual {miss:.3g}; " + "; ".join(notes))
        return {"flows": fixed_inputs(flows_of(p, sup, k), run, (opts.get("inputs") or {}).keys()), "note": note, "z3": {"status": r["status"], "k_min": r.get("k_min"),
                "smallest": len(fits), "moves": moves, "boundary": rule, "seconds": r["seconds"]}}
    left = TOTAL - (time.perf_counter() - began)
    if left >= 5:
        got = _best_effort(stocks, run, opts, left, notes)
        if got is not None:
            return {**got, "flows": fixed_inputs(got.get("flows") or [], run, (opts.get("inputs") or {}).keys())}
    return {"flows": [], "note": "z3exact: no structure found, no flows returned (outside the class: noisy data or a "
            "nonlinear truth; unknown: a timeout or a class too large to search): " + "; ".join(notes)}


def _best_effort(stocks: list[dict], run: dict, opts: dict, budget: float, notes: list[str]) -> dict | None:
    """BEST EFFORT, labelled so (result["z3"]["best_effort"] = True and the note), when no structure fits
    within the data's rounding (noisy data, or a truth outside the linear class): not Z3, but backward
    elimination on the same class (ends moves, the boundary by sides): start from every term fitted by
    least squares on the one-step changes, drop the term with the smallest |t| while every stock's
    residual sum of squares stays within BEST_EFFORT_RSS (1.05) times the all-term model's (plus the
    rounding's own n h^2), numbers by least squares. (BIC keeps junk terms on noise-free misfit data:
    its log RSS rewards every tiny gain.)"""
    began = time.perf_counter()
    p = core.prepare(stocks, run, opts, moves="ends", boundary="sides")
    X, Y = core._floats(p)
    S, n = Y.shape
    cols = []
    for i, t in enumerate(p.terms):
        col = np.zeros(S * n)
        for r, sid in enumerate(p.ids):
            sg = core._contrib(p, t, sid)
            if sg:
                col[r * n:(r + 1) * n] = sg * X[:, t.col]
        cols.append(col)
    D, y = np.array(cols).T, Y.reshape(-1)
    keep = [i for i in range(len(cols)) if np.any(D[:, i])]

    def fit(sup):
        if not sup:
            return np.zeros(0), (Y ** 2).sum(axis=1), Y
        k, *_ = np.linalg.lstsq(D[:, sup], y, rcond=None)
        res = (y - D[:, sup] @ k).reshape(S, n)
        return k, (res ** 2).sum(axis=1), res

    k, rss, res = fit(keep)
    allowed = BEST_EFFORT_RSS * rss + n * float(p.h) ** 2 * 4
    while keep and time.perf_counter() - began < budget:
        sigma2 = float((res ** 2).sum()) / max(1, S * n - len(keep))
        try:
            cov = np.linalg.pinv(D[:, keep].T @ D[:, keep]) * sigma2
            tval = np.abs(k) / np.sqrt(np.maximum(np.diag(cov), 1e-300))
        except np.linalg.LinAlgError:
            break
        dropped = False
        # tried first: outside terms and terms that read neither end of their flow (SD prefers moves that
        # read their source), each group by |t|; at most ten tries a round
        order = sorted(range(len(keep)), key=lambda j: (_plain(p, keep[j]), tval[j]))
        for j in order[:10]:
            trial = keep[:j] + keep[j + 1:]
            k2, rss2, res2 = fit(trial)
            if np.all(rss2 <= allowed):
                keep, k, res, dropped = trial, k2, res2, True
                break
        if not dropped:
            break
    notes.append(f"[best effort] backward elimination: {len(keep)} of {len(cols)} terms kept ({time.perf_counter() - began:.1f} s)")
    if not keep:
        return None
    miss = float(np.abs(res).max())
    note = (f"z3exact BEST EFFORT (no structure fits within the data's rounding; not proved by Z3): {len(keep)} terms by "
            f"backward elimination (each stock's squared error within {BEST_EFFORT_RSS:g} x the all-term model's) on the linear class; largest one-step residual {miss:.3g}; " + "; ".join(notes))
    return {"flows": flows_of(p, keep, k), "note": note, "z3": {"status": "best effort", "moves": "ends", "boundary": "sides",
            "best_effort": True, "seconds": round(time.perf_counter() - began, 3)}}


def _plain(p: core.Problem, i: int) -> int:
    """0 for a term best dropped first (an outside term, or one reading another stock), 1 for a move or
    drain reading its own stock."""
    t, c = p.terms[i], p.cols[p.terms[i].col]
    own = c.kind == "stock" and c.name in (t.a, t.b)
    return 1 if own else 0


def _pred(p: core.Problem, sup: list[int], k: np.ndarray, X: np.ndarray, Y: np.ndarray) -> np.ndarray:
    pred = np.zeros_like(Y)
    for m, i in enumerate(sup):
        t = p.terms[i]
        for r, sid in enumerate(p.ids):
            sg = core._contrib(p, t, sid)
            if sg:
                pred[r] += sg * k[m] * X[:, t.col]
    return pred


def _sse(p: core.Problem, sup: list[int], k: np.ndarray) -> float:
    X, Y = core._floats(p)
    return float(((Y - _pred(p, sup, k, X, Y)) ** 2).sum())


def _sign(p: core.Problem, col: int) -> float:
    """The usual sign of a column over the run (levels and constants: +1; an input: its mean's)."""
    c = p.cols[col]
    if c.kind != "input":
        return 1.0
    m = float(np.mean([float(v) for v in p.X[col]])) if p.X[col] else 1.0
    return -1.0 if m < 0 else 1.0


def flows_of(p: core.Problem, sup: list[int], k: np.ndarray, t: list | None = None) -> list[dict]:
    """SD Lab flows from a structure's terms and numbers: a move's term goes a -> b when it moves level
    that way (its number times the column's usual sign is positive), else b -> a; an outside term goes
    into its stock or out of it by the same rule where both sides are allowed, else to its one side.
    Terms of one (from, to) share a flow: proportional (one term on the source's level), constant, or
    linear; a constant per era makes the flow follow the eras (byTime)."""
    groups: dict[tuple, list[tuple[int, float]]] = {}
    for m, i in enumerate(sup):
        term, v = p.terms[i], float(k[m])
        if v == 0.0:
            continue
        pos = v * _sign(p, term.col) > 0
        if term.kind == "move":
            key, val = ((term.a, term.b), v) if pos else ((term.b, term.a), -v)
        else:
            side = ("in" if pos else "out") if len(term.sides) == 2 else term.sides[0]
            key, val = ((None, term.a), v) if side == "in" else ((term.a, None), -v)
        groups.setdefault(key, []).append((term.col, val))
    out = []
    era_t = [float(x) for x in p.era_starts]
    for (a, b), parts in groups.items():
        def rate(e, linear: bool = False, parts=parts, a=a) -> dict:
            c0 = sum(v for c, v in parts if p.cols[c].kind == "const" and p.cols[c].era == e)
            reads = [(p.cols[c].name, v) for c, v in parts if p.cols[c].kind != "const" and p.cols[c].era == e]
            if not reads and not linear:
                return {"form": "constant", "value": c0}
            if len(reads) == 1 and c0 == 0 and reads[0][0] == a and not linear:
                return {"form": "proportional", "stock": a, "k": reads[0][1]}
            return {"form": "linear", "c": c0, "terms": [{"stock": n, "k": v} for n, v in reads]}

        f: dict = {"from": a, "to": b, "ratio": 1}
        if any(p.cols[c].era is not None for c, _ in parts):
            eras = range(len(era_t))
            segs = [rate(e) for e in eras]
            if len({(r["form"], tuple(x["stock"] for x in r.get("terms") or []) or r.get("stock")) for r in segs}) > 1:
                names = sorted({p.cols[c].name for c, _ in parts if p.cols[c].kind != "const"})
                segs = [{"form": "linear", "c": r.get("c", r.get("value", 0.0)),
                         "terms": [{"stock": n, "k": sum(v for c, v in parts if p.cols[c].name == n and p.cols[c].era == e
                                                         and p.cols[c].kind != "const")} for n in names]}
                        for e, r in zip(eras, segs)]
            f["byTime"] = [{"from": era_t[e], "to": (era_t[e + 1] - 1) if e + 1 < len(era_t) else 1e12, "rate": segs[e]} for e in eras]
            f["rate"] = segs[0]
            f["rates"] = segs
        else:
            f["rate"] = rate(None)
            f["rates"] = [f["rate"]]
        ins = [n for c, _ in parts if p.cols[c].kind == "input" for n in [p.cols[c].name]]
        if ins:
            f["input"] = ins[0]
        out.append(f)
    return out


# A capacity limit offered to the fit (capmin.py, docs/research/k8s-306-s1.md, 2026-10-21): identify above
# runs with the regime-clipped series MIN(X, theta x Y) as one more measured input where the data show a
# limit, and every term that reads it is written back as MIN(a x X, a theta x Y).
from . import capmin as _capmin  # noqa: E402

_identify_linear = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    """(2026-10-21, k8s-307, docs/research/k8s-307-c1.md) Between the fit and the MIN written back, where the
    levels carry measurement error, the numbers are refitted and the structure revised on the output error
    and judged on a Kalman likelihood (oefit.py, a copy of combined2's: the model run through the whole
    record against the measured levels)."""
    from . import oefit

    o, cap = _capmin.offer(stocks, run, opts)
    r = oefit.refit(_identify_linear(stocks, run, o, *args, **kw), stocks, run, o, cap)
    return _capmin.restore(r, cap)


def fixed_inputs(flows: list[dict], run: dict, inputs) -> list[dict]:
    """(2026-10-21, the user) A declared "input" inflow IS the measured series: the inflow into such a stock
    that reads a measured input is set at exactly 1 x it (no constant, never rescaled); on a side that
    declares only inputs, the stock's other outside inflows are dropped. The other numbers are not refitted
    (this strategy's search reads the side as "measured")."""
    if not run.get("boundary_declared"):
        return flows
    inputs = set(inputs or ())
    flows = [dict(f) for f in flows]

    def reads(f: dict) -> list:
        r = f.get("rate") or {}
        t = [r.get("stock")] if r.get("form") == "proportional" else [x.get("stock") for x in r.get("terms") or []]
        return [x for x in t if x in inputs]

    for s, e in sorted((run.get("boundary") or {}).items()):
        kinds = list(e.get("in") or [])
        into = [i for i, f in enumerate(flows) if f.get("from") is None and f.get("to") == s and not f.get("byTime")]
        fed = [i for i in into if reads(flows[i])]
        if "input" not in kinds or not fed:
            continue
        name = reads(flows[fed[0]])[0]
        rate = {"form": "proportional", "stock": name, "k": 1.0}
        flows[fed[0]] = {**{k: v for k, v in flows[fed[0]].items() if k in ("from", "to", "name", "id")},
                         "ratio": 1, "rate": rate, "rates": [rate], "input": name}
        drop = [i for i in into if i != fed[0]] if all(k == "input" for k in kinds) else []
        flows = [f for i, f in enumerate(flows) if i not in drop]
    return flows
