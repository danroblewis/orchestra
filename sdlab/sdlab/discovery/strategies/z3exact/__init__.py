"""z3exact: exact structure search on noise-free data (docs/research/z3.md, experiment B).

The fewest terms that fit every one-step change within the data's own rounding, with the declared
boundary as a hard constraint (core.py: Z3 over exact rationals, a copy of the harness's z3_ident.py),
then the numbers refitted by least squares (all stocks' changes jointly). The class is linear: moves
between stocks of one unit reading one of their two stocks ("ends"), and outside terms where the
boundary allows them (constants per announced era, measured inputs, levels); if nothing of that class
fits, moves may read any column ("any"). Of several smallest structures, the one with the least squared
error is returned (and the rest counted in the note).

Noisy data: nothing fits within the rounding, so it returns no flows with a note saying so (no best
effort). The same when the data are outside the linear class (nonlinear rates, floors, unannounced
changes) or Z3 runs out of time.
"""

from __future__ import annotations

import time

import numpy as np

from . import core

BUDGET = 60.0                 # seconds of Z3 search per class
TOTAL = 90.0                  # seconds for everything (the ladder's item timeout is 120 s; Z3 and HiGHS are not interruptible)
CAP = 12                      # smallest structures compared at most


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    notes = []
    began = time.perf_counter()
    for moves in core.MOVE_CLASSES:
        budget = min(BUDGET, TOTAL - (time.perf_counter() - began))
        if budget < 5:
            notes.append(f"[{moves}] not tried (out of time)")
            break
        p = core.prepare(stocks, run, opts, moves=moves)
        if p.steps < 20:
            return {"flows": [], "note": "z3exact: too few steps."}
        r = core.enumerate_structures(p, slack=0, cap=CAP, budget=budget)
        notes.append(f"[{moves}] {r['status']} ({r['seconds']:.1f} s, {r.get('checks')} checks)")
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
        note = (f"z3exact: {len(sup)} terms, {r['status']} in the class '{moves}'"
                + (f" ({len(fits)} smallest structures fit; the least squared error kept)" if len(fits) > 1 else "")
                + f"; largest one-step residual {miss:.3g}; " + "; ".join(notes))
        return {"flows": flows_of(p, sup, k), "note": note, "z3": {"status": r["status"], "k_min": r.get("k_min"),
                "smallest": len(fits), "moves": moves, "seconds": r["seconds"]}}
    return {"flows": [], "note": "z3exact: no structure found, no flows returned (outside the class: noisy data or a "
            "nonlinear truth; unknown: a timeout or a class too large to search): " + "; ".join(notes)}


def _sse(p: core.Problem, sup: list[int], k: np.ndarray) -> float:
    X, Y = core._floats(p)
    pred = np.zeros_like(Y)
    for m, i in enumerate(sup):
        t = p.terms[i]
        for r, sid in enumerate(p.ids):
            sg = core._contrib(p, t, sid)
            if sg:
                pred[r] += sg * k[m] * X[:, t.col]
    return float(((Y - pred) ** 2).sum())


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
