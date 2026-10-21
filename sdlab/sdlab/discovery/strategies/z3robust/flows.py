"""SD Lab flows from a structure's terms (z3robust): copied from z3exact's __init__.py at commit 45bfaac
(sdlab branch; `_sign`, `flows_of` and `fixed_inputs` as they were there). Strategies are isolated
(CLAUDE.md rule 11): changing z3exact never changes this copy."""

from __future__ import annotations

import numpy as np

from . import core


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
    linear; a constant per era makes the flow follow the eras (byTime). (z3robust) A column over the whole
    run (era None, core.prepare(pooled=True)) holds in every era."""
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
            c0 = sum(v for c, v in parts if p.cols[c].kind == "const" and p.cols[c].era in (None, e))
            merged: dict = {}         # (z3robust) a whole-run column and its era's column read one series
            for c, v in parts:
                if p.cols[c].kind != "const" and p.cols[c].era in (None, e):
                    merged[p.cols[c].name] = merged.get(p.cols[c].name, 0.0) + v
            reads = list(merged.items())
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
                         "terms": [{"stock": n, "k": sum(v for c, v in parts if p.cols[c].name == n and p.cols[c].era in (None, e)
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
