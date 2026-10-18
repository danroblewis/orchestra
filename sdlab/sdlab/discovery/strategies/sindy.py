"""PySINDy with system-dynamics libraries and constraints (experiment exp/pysindy).

Each stock's change in a step is a sparse combination of library terms - the levels, and products of
two levels (a flow out of A sped up by C) - chosen by STLSQ over a threshold path, BIC-best
(sparse.py); the outside inflow is found in pieces by our own change scan and taken out; announced
eras add a level's number per configuration for the levels a row uses. Conservation is imposed as
equality constraints across rows, solved jointly with ConstrainedSR3 (conserve_joint.py). The
terms are read back as flows, products as effects and losses in a third stock as co-flows
(term_flows.py). Several candidates are fitted and the one whose model behaves best on the data is
kept (identify.judge), as in the main line.

`opts["sindy"]` (or $SDLAB_SINDY, for the bench) picks an ablation:
  plain        PySINDy as it comes: levels and a constant, one STLSQ threshold (summed BIC)
  levels       levels only, per-row threshold path, inflow pieces
  products     + products of levels (read as effects)
  constrained  + conservation constraints (ConstrainedSR3)
  uses         + co-flows read off losses in third stocks
  full         + candidates judged by behaviour (default)
  combo        the matrix method's chosen model and the product candidates, judged together

Needs pysindy and cvxpy (the optional group research: uv sync --extra research); without them,
MissingExtra.
"""

from __future__ import annotations

import os

import numpy as np

from ..flows import merge_by_label
from ..identify import identify as matrix_identify
from ..identify import judge
from ..matrix import configurations
from ..optional import require
from ..regression import piece_values

try:                                     # optional: uv sync --extra research (pysindy, cvxpy)
    from ..conserve_joint import conserve
    from ..library import build, era_of, factors
    from ..sparse import fit_row, inflow_series, plain_sindy
    from ..term_flows import read
except ImportError:                      # identify() says what is missing
    pass

LEVELS = ("plain", "levels", "products", "constrained", "uses", "full", "combo")


def identify_one(stocks: list[dict], run: dict, o: dict) -> dict:
    ids = [s["id"] for s in stocks]
    S = len(ids)
    t = run["t"]
    T = len(t) - 1
    if T < 20:
        return {"flows": [], "note": "Too few steps."}
    lv = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, [0] * len(t)), dtype=float) for i in ids]))
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    at = lambda k: t[k + 1]  # noqa: E731
    unit = [s.get("unit") or "" for s in stocks]
    final = {k for k, s in enumerate(stocks) if s.get("final")}
    group = [s.get("group") for s in stocks]
    conf = configurations(o.get("eras"), t) if o.get("eras_split") else None
    labels, cfg = (conf[0], conf[1]) if conf else ([None], np.zeros(T, dtype=int))
    L = len(labels)

    if o["mode"] == "plain":
        terms = [(j,) for j in range(S)]
        X = prev
        rows = plain_sindy(prev, dy)
    else:
        terms, X = build(prev, o["products"], cfg, L)

        def ok(term, s):
            fs = factors(term)
            return all(j == s or not group[j] or not group[s] or group[j] == group[s] for j in fs) and not (s in final and s in fs)

        level_of = {term[0]: f for f, term in enumerate(terms) if len(term) == 1}
        simpler = {f: [level_of[j] for j in dict.fromkeys(term)] for f, term in enumerate(terms) if len(term) == 2}
        rows = []
        for s in range(S):
            base = [f for f, term in enumerate(terms) if era_of(term) is None and ok(term, s)]
            simple = [f for f in base if len(terms[f]) == 1]
            r = fit_row(dy[s], X, base, o["inflow"], simple=simple, gamma=o.get("gamma", 1.0), pelt_mult=o.get("pelt_mult", 1.0), simpler=simpler)
            if L > 1:
                js = {factors(terms[f])[0] for f in r["terms"] if len(factors(terms[f])) == 1} | ({s} if s not in final else set())
                extra = [f for f, term in enumerate(terms) if era_of(term) is not None and term[0] in js and ok(term, s)]
                if extra:
                    r = fit_row(dy[s], X, base + extra, o["inflow"], simple=simple, gamma=o.get("gamma", 1.0), pelt_mult=o.get("pelt_mult", 1.0), simpler=simpler)
            rows.append(r)

    note = None
    if o.get("constrain"):
        u = np.array([inflow_series(r, T) for r in rows])
        note = conserve(rows, terms, X, dy, u, unit, final)
        for s, r in enumerate(rows):                     # the pieces measured again with the numbers kept
            if r["cuts"]:
                res = dy[s] - (np.array(r["beta"]) @ X[r["terms"]] if r["terms"] else 0)
                r["pieces"] = piece_values(res, X, [], np.zeros(0), r["cuts"])

    inflow = [[{"from": at(p["a"]), "to": at(p["b"] - 1), "value": p["v"]} for p in r["pieces"]] for r in rows]
    per_label = []
    for c in range(L):
        coef = []
        for r in rows:
            d: dict[int, float] = {}
            for f, b in zip(r["terms"], r["beta"]):
                e = era_of(terms[f])
                if e is None:
                    d[f] = d.get(f, 0.0) + b
                elif e == c:
                    base_f = terms.index(factors(terms[f]))
                    d[base_f] = d.get(base_f, 0.0) + b
            coef.append(d)
        base_terms = terms
        per_label.append(read(stocks, base_terms, coef, prev, inflow if c == 0 else [[] for _ in rows], uses=o.get("uses", False)))
    flows = merge_by_label(per_label, labels, conf[2]) if L > 1 else per_label[0]
    matrix = [{"id": ids[s], "terms": [_name(terms[f], ids) for f in r["terms"]], "beta": r["beta"], "inflow": inflow[s]} for s, r in enumerate(rows)]
    out = {"flows": flows, "matrix": matrix, "method": "sindy", "windows": T, "window": 1}
    if note:
        out["conservation"] = {"kept": [_name(terms[f], ids) for f in note["kept"]], "tried": note["tried"]}
    if L > 1:
        out["eras"] = labels
    return out


def _name(term: tuple, ids: list[str]) -> str:
    fs = "*".join(ids[j] for j in factors(term))
    return fs + (f"@{era_of(term)}" if era_of(term) is not None else "")


def variants(level: str, has_eras: bool) -> list[dict]:
    k = LEVELS.index(level)
    one = {"mode": "plain" if level == "plain" else "sparse", "products": k >= 2, "constrain": k >= 3, "uses": k >= 4, "inflow": "changing"}
    if level not in ("full", "combo"):
        return [{**one, "name": level}]
    out = []
    for products in (True,) if level == "combo" else (True, False):
        for inflow, mult, label in (("changing", 1.0, "changing inflows"), ("changing", 2.0, "changing inflows (fewer changes)"), ("constant", 1.0, "constant inflows")):
            for split in ((False, True) if has_eras else (False,)):
                out.append({**one, "products": products, "inflow": inflow, "pelt_mult": mult, "eras_split": split,
                            "name": f"{'products' if products else 'levels'}, {label}{', numbers per era' if split else ''}"})
    return out


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    require("pysindy")
    require("cvxpy")
    opts = dict(opts or {})
    level = opts.pop("sindy", None) or os.environ.get("SDLAB_SINDY") or "full"
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    best, tried = None, []
    if level == "combo":
        r = matrix_identify(stocks, run, opts)
        best = (r, judge(r["flows"], stocks, run), "matrix: " + r["chosen"])
        tried = [{"name": best[2], "error": best[1]}]
    for v in variants(level, has_eras):
        r = identify_one(stocks, run, {**opts, **v})
        e = judge(r["flows"], stocks, run) if level in ("full", "combo") else 0.0
        tried.append({"name": v["name"], "error": e})
        if best is None or e < best[1]:
            best = (r, e, v["name"])
    r = best[0]
    r["chosen"], r["tried"] = best[2], tried
    return r
