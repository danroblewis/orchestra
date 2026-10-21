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

import math
import os

import numpy as np

from ...flows import merge_by_label
from ...identify import identify as matrix_identify
from ...identify import judge
from ...matrix import configurations
from ...optional import require
from ...regression import piece_values, row_sums

try:                                     # optional: uv sync --extra research (pysindy, cvxpy)
    from ...conserve_joint import conserve
    from ...library import build, era_of, factors
    from ...sparse import inflow_series, plain_sindy, select
    from ...term_flows import read
except ImportError:                      # identify() says what is missing
    pass
from ...changes import pelt
from ...regression import fit_subset
from . import boundary
from scipy.stats import chi2 as _chi2

LEVELS = ("plain", "levels", "products", "constrained", "uses", "full", "combo")


def _ebic(T: int, rss: float, p: float, k: int, P: int, gamma: float) -> float:
    """BIC plus the price of having picked k of P candidate terms (sparse._ebic)."""
    return T * math.log(max(rss, 1e-12) / T) + p * math.log(T) + 2 * gamma * (math.lgamma(P + 1) - math.lgamma(k + 1) - math.lgamma(P - k + 1))


def _changes_price(cuts: list[int] | None) -> int:
    """An outside inflow's numbers when every change is priced as a value and a place (as earned_pieces
    prices them): a constant is one, every change adds two."""
    return 0 if not cuts else 1 + 2 * (len(cuts) - 2)


def _white(e: np.ndarray, alpha: float = 0.01) -> bool:
    """Ljung-Box: no autocorrelation in e up to lag ceil(sqrt(T)) at level alpha (a copy of
    earned_pieces' rows.white at 66086e7, via matrix/earned_rows.py)."""
    e = np.asarray(e, dtype=float) - float(np.mean(e))
    n = e.shape[0]
    v = float(e @ e)
    if n < 10 or v <= 0:
        return True
    m = min(n - 2, int(math.ceil(math.sqrt(n))))
    r = np.array([float(e[k:] @ e[:-k]) / v for k in range(1, m + 1)])
    q = n * (n + 2) * float(np.sum(r * r / (n - np.arange(1, m + 1))))
    return bool(_chi2.sf(q, m) > alpha)


def _earned(y: np.ndarray, Xa: np.ndarray, pick: dict, T: int, P: int, gamma: float) -> dict:
    """The pieces kept only if they earn their places: dropped (for no inflow or a constant one, the
    levels chosen beside the pieces kept) when that leaves white residuals and a lower BIC with every
    change priced as a value and a place (earned_pieces' rule, rows.reselect "beside"). fit_row prices
    a change as its value alone while PELT chooses the places, so chance pieces paid on counting noise
    (kubernetes 303 counts-short: five pieces of an outflow from the final counter, 21 below the
    no-piece BIC, 1.8 above it once the four places are priced); docs/research/k8s-303-sindy.md."""
    chosen = pick["chosen"]
    best, best_sc = pick, _ebic(T, pick["f"].rss, len(chosen) + _changes_price(pick["cuts"]), len(chosen), P, gamma)
    for cuts in (None, [0, T]):
        f = fit_subset(row_sums(y, Xa, cuts), chosen)
        sc = _ebic(T, f.rss, len(chosen) + _changes_price(cuts), len(chosen), P, gamma)
        if sc >= best_sc - 1e-9:
            continue
        e = y - (f.beta @ Xa[chosen] if chosen else 0.0)
        if _white(e):
            best, best_sc = {"cuts": cuts, "chosen": chosen, "f": f, "sc": sc}, sc
    return best


def _select(y: np.ndarray, X: np.ndarray, cuts: list[int] | None, **kw) -> list[int]:
    """sparse.select, or no columns when the row may read none (sparse.select fails on an empty
    library: a lone stock with only an outside inflow, 001-inflow-only)."""
    return select(y, X, cuts, **kw) if X.shape[0] else []


def fit_row(y: np.ndarray, X: np.ndarray, allowed: list[int], inflow: str = "changing", min_piece: int = 5, simple: list[int] | None = None,
            gamma: float = 0.0, pelt_mult: float = 1.0, simpler: dict[int, list[int]] | None = None) -> dict:
    """A copy of sparse.fit_row (the pinned shared library, at b9fe1d6) with one addition: chosen
    pieces must earn their places (_earned). y: one stock's change per step; X: library values (terms
    x steps); allowed: the terms this row may use; simple: those used in the first pass, before the
    inflow's pieces are known (so that products do not stand in for changes in the inflow). Returns
    the chosen terms, their numbers, and the outside inflow's pieces."""
    T = y.shape[0]
    Xa = X[allowed] if allowed else np.zeros((0, T))
    first = [q for q, f in enumerate(allowed) if f in set(simple)] if simple is not None else None
    at = {f: q for q, f in enumerate(allowed)}
    simp = {at[f]: [at[j] for j in js if j in at] for f, js in (simpler or {}).items() if f in at}
    P = len(allowed)

    def form(c, extra, chosen=None):
        chosen = _select(y, Xa, c, gamma=gamma, simpler=simp) if chosen is None else chosen
        f = fit_subset(row_sums(y, Xa, c), chosen)
        return {"cuts": c, "chosen": chosen, "f": f, "sc": _ebic(T, f.rss, len(chosen) + extra, len(chosen), P, gamma)}

    # the outside inflow: none, constant, or changing - each with the terms chosen beside it (a
    # changing inflow only for a stock whose inflow is on average clearly one way, as in matrix.py)
    pick = form(None, 0)
    if inflow != "none":
        const = form([0, T], 1)
        pick = const if const["sc"] < pick["sc"] else pick
    if inflow == "changing":
        cuts = [0, T]
        for p in range(5):
            if p == 0 and first is not None:
                chosen = [first[q] for q in _select(y, Xa[first], cuts, gamma=gamma)]
            else:
                chosen = _select(y, Xa, cuts, gamma=gamma, simpler=simp)
            f = fit_subset(row_sums(y, Xa, cuts), chosen)
            nxt = pelt(y - (f.beta @ Xa[chosen] if chosen else 0), min_piece, 0.5 if p == 0 else pelt_mult)
            if nxt == cuts and p >= 2:
                break
            cuts = nxt
        if len(cuts) > 2:
            pcs = form(cuts, len(cuts) - 1)
            vals = piece_values(y, Xa, pcs["chosen"], pcs["f"].beta, cuts)
            W = sum(v["w"] for v in vals)
            mean = sum(v["v"] * v["w"] for v in vals) / W
            sd = math.sqrt(sum(v["w"] * (v["v"] - mean) ** 2 for v in vals) / W)
            if (pick is const or abs(mean) > 0.5 * sd) and pcs["sc"] < pick["sc"]:
                pick = _earned(y, Xa, pcs, T, P, gamma)
    chosen, beta = pick["chosen"], pick["f"].beta
    pieces = piece_values(y, Xa, chosen, beta, pick["cuts"]) if pick["cuts"] else []
    return {"terms": [allowed[q] for q in chosen], "beta": [float(b) for b in beta], "pieces": pieces, "cuts": pick["cuts"],
            "rss": pick["f"].rss, "p": len(chosen) + (len(pick["cuts"]) - 1 if pick["cuts"] else 0)}


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

    # measured inputs (opts "inputs", {name: value per step aligned with t}): a column each after the
    # library terms, its value during the step (t[k] to t[k + 1]: the value at t[k + 1], as the matrix
    # reads it); any row may take one (k > 0 an inflow k x input, k < 0 an outflow)
    inputs = [(k, np.nan_to_num(np.asarray(v, dtype=float))[1: len(t)]) for k, v in (o.get("inputs") or {}).items() if k not in ids] \
        if o["mode"] != "plain" else []
    if o["mode"] == "plain":
        terms = [(j,) for j in range(S)]
        X = prev
        rows = plain_sindy(prev, dy)
    else:
        terms, X = build(prev, o["products"], cfg, L)
        nT = len(terms)
        ins = list(range(nT, nT + len(inputs)))
        if inputs:
            X = np.vstack([X] + [v[None, :] for _, v in inputs])

        def ok(term, s):
            fs = factors(term)
            return all(j == s or not group[j] or not group[s] or group[j] == group[s] for j in fs) and not (s in final and s in fs)

        # the declared boundary (boundary.py): a row reads a measured input only on a measured side, a
        # level of another unit (or a product with one) only on an estimate side, and has an outside
        # inflow (constant or changing) only on an estimate side
        bnd = boundary.Boundary(run)

        def inside(term, s):
            return bnd.links_ok(ids[s]) or all(unit[j] == unit[s] for j in factors(term))

        level_of = {term[0]: f for f, term in enumerate(terms) if len(term) == 1}
        simpler = {f: [level_of[j] for j in dict.fromkeys(term)] for f, term in enumerate(terms) if len(term) == 2}
        rows = []
        for s in range(S):
            base = [f for f, term in enumerate(terms) if era_of(term) is None and ok(term, s) and inside(term, s)] \
                + [f for f in ins if f not in set(_capmin.excluded(ids[s], {f: inputs[f - nT][0] for f in ins}, ins, bnd.inputs_ok(ids[s]), o))]   # (capmin.py)
            simple = [f for f in base if f in ins or len(terms[f]) == 1]
            inflow = o["inflow"] if bnd.pieces_ok(ids[s]) else "none"
            r = fit_row(dy[s], X, base, inflow, simple=simple, gamma=o.get("gamma", 1.0), pelt_mult=o.get("pelt_mult", 1.0), simpler=simpler)
            if L > 1:
                js = {factors(terms[f])[0] for f in r["terms"] if f < nT and len(factors(terms[f])) == 1} | ({s} if s not in final else set())
                extra = [f for f, term in enumerate(terms) if era_of(term) is not None and term[0] in js and ok(term, s) and inside(term, s)]
                if extra:
                    r = fit_row(dy[s], X, base + extra, inflow, simple=simple, gamma=o.get("gamma", 1.0), pelt_mult=o.get("pelt_mult", 1.0), simpler=simpler)
            rows.append(r)

    note = None
    if o.get("constrain"):
        u = np.array([inflow_series(r, T) for r in rows])
        note = conserve(rows, terms + [("input", k) for k, _ in inputs], X, dy, u, unit, final)   # an input is no one's source
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
                if f >= len(terms):                      # a measured input: read below
                    continue
                e = era_of(terms[f])
                if e is None:
                    d[f] = d.get(f, 0.0) + b
                elif e == c:
                    base_f = terms.index(factors(terms[f]))
                    d[base_f] = d.get(base_f, 0.0) + b
            coef.append(d)
        base_terms = terms
        per_label.append(read(stocks, base_terms, coef, prev, inflow if c == 0 else [[] for _ in rows], uses=o.get("uses", False))
                         + _input_flows(rows, ids, len(terms), inputs))
    flows = merge_by_label(per_label, labels, conf[2]) if L > 1 else per_label[0]
    names = terms + [("input", k) for k, _ in inputs]
    matrix = [{"id": ids[s], "terms": [_name(names[f], ids) for f in r["terms"]], "beta": r["beta"], "inflow": inflow[s]} for s, r in enumerate(rows)]
    out = {"flows": flows, "matrix": matrix, "method": "sindy", "windows": T, "window": 1}
    if note:
        out["conservation"] = {"kept": [_name(names[f], ids) for f in note["kept"]], "tried": note["tried"]}
    if L > 1:
        out["eras"] = labels
    return out


def _input_flows(rows: list[dict], ids: list[str], nT: int, inputs: list) -> list[dict]:
    """Flows reading measured inputs, from the rows' numbers on their columns (after the nT library
    terms): k > 0 an inflow from outside at k x input, k < 0 an outflow to outside at -k x input (as
    matrix.input_flows reads the matrix's rows)."""
    out = []
    for s, r in enumerate(rows):
        for f, k in zip(r["terms"], r["beta"]):
            if f < nT or not k:
                continue
            name, v = inputs[f - nT]
            rate = {"form": "linear", "c": 0, "terms": [{"stock": name, "k": round(abs(k), 6)}]}
            ends = {"from": None, "to": ids[s]} if k > 0 else {"from": ids[s], "to": None}
            out.append({**ends, "ratio": 1, "rate": rate, "rates": [rate], "perStep": abs(k) * float(v.mean()),
                        "nearly": [], "bothWays": False, "input": name})
    return out


def _name(term: tuple, ids: list[str]) -> str:
    if term and term[0] == "input":
        return term[1]
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


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    require("pysindy")
    require("cvxpy")
    opts = dict(opts or {})
    level = opts.pop("sindy", None) or os.environ.get("SDLAB_SINDY") or "full"
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    best, tried = None, []
    if level == "combo":
        r = matrix_identify(stocks, run, opts)
        best = (r, judge(r["flows"], stocks, run, inputs=opts.get("inputs")), "matrix: " + r["chosen"])
        tried = [{"name": best[2], "error": best[1]}]
    declared = boundary.Boundary(run).declared
    for v in variants(level, has_eras):
        r = identify_one(stocks, run, {**opts, **v})
        # the declared boundary: the judge sees the candidate guarded (boundary.py); its own model is
        # kept, so the measurement-error refit decides its numbers and the final guard its structure
        g = boundary.apply(r, stocks, run, opts, final=False) if declared and r.get("flows") else r
        e = judge(g["flows"], stocks, run, inputs=opts.get("inputs")) if level in ("full", "combo") else 0.0
        tried.append({"name": v["name"], "error": e})
        if best is None or e < best[1]:
            best = (r, e, v["name"])
    r = best[0]
    r["chosen"], r["tried"] = best[2], tried
    return r


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (the _eiv_ code below), then kept inside the announced boundary (boundary.py:
    the guard and the moves where one is declared, each outside flow priced as a boundary claim where
    none is; the rows are fitted inside it, identify_one)."""
    return boundary.apply(_eiv_apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts), stocks, run, opts)


# Errors in variables (docs/research/eiv-refit.md): a copy (as in held_out.py at e8edf28) of the strategies' eiv.py, its names prefixed
# _eiv_. When the levels carry measurement error (one-step residuals negatively correlated from step to
# step), the found numbers are refitted with the levels two steps back as instruments, and kept only if
# the model then runs at least as close to the data over 5, 20 and 100 steps. Parts the instrumented fit
# cannot tell from nothing are pruned first (docs/research/k8s-303.md).
import copy as _eiv_copy  # noqa: E402

import numpy as _eiv_np  # noqa: E402
from scipy.stats import norm as _eiv_norm  # noqa: E402

from ...simulate import Model as _EivModel, behaviour_error as _eiv_behaviour_error, levels_array as _eiv_levels_array, starts_for as _eiv_starts_for  # noqa: E402

_EIV_ALPHA = 1e-3          # the white-noise test's level (one-sided, over the stocks)
_EIV_ITERATIONS = 3        # Gauss-Newton steps of each fit (the rates are linear in their numbers, so one is
                      # exact unless a floor, a shared stock or an effect bends them)
_EIV_HORIZONS = (5, 20, 100)
_EIV_PRICE = 2.0           # a part's price per number on the instrumented fit's Wald statistic (Akaike's)
_EIV_TRIM = 5.0            # a one-step residual beyond this many robust sds marks a level outlier
_EIV_GUARD = 2.0           # paired standard errors the pruned model may lose by at the longest horizon


def _eiv_slots(flows: list[dict]) -> list[tuple[dict, str]]:
    """The numbers to refit, as (dict, key): a proportional rate's k, a linear rate's constant (when
    not 0) and its terms' k, a constant rate's value, a found outside inflow's piece values; per era
    where a rate follows the eras (eras that share a rate dict share the number)."""
    out, seen = [], set()
    for f in flows:
        if f.get("inflow"):
            out += [(g, "value") for g in f["inflow"] if g.get("value") is not None]
            continue
        for r in ([g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]):
            if id(r) in seen:
                continue
            seen.add(id(r))
            form = r.get("form")
            if form == "proportional" and r.get("k") is not None:
                out.append((r, "k"))
            elif form == "constant" and r.get("value") is not None:
                out.append((r, "value"))
            elif form == "linear":
                if r.get("c"):
                    out.append((r, "c"))
                out += [(x, "k") for x in r.get("terms") or [] if x.get("k") is not None]
    return out


def _eiv_known(flows: list[dict], names: set) -> bool:
    """Every stock the flows name is measured or a measured input (no hidden stocks)."""
    for f in flows:
        named = [f.get("from"), f.get("to")]
        for r in [g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]:
            named += [r.get("stock")] + [x.get("stock") for x in r.get("terms") or []]
        named += [e.get("stock") for e in f.get("effects") or []] + [u.get("stock") for u in f.get("uses") or []]
        if any(s is not None and s not in names for s in named):
            return False
    return True


def _eiv_judge(flows: list[dict], ids: list[str], run: dict, opts: dict) -> float:
    """The main line's judge (identify.judge) with the measured inputs: the mean multi-step error."""
    hs = [h for h in _EIV_HORIZONS if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    kw = {"inputs": opts["inputs"]} if opts.get("inputs") else {}
    return sum(_eiv_behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, injections=opts.get("injections"), **kw)
               for h in hs) / len(hs)


class _EivFit:
    """The flows' numbers as a vector, and each stock's change over the rows' steps for any of them."""

    def __init__(self, flows: list[dict], ids: list[str], t: _eiv_np.ndarray, A: _eiv_np.ndarray, inputs: dict | None, rows: _eiv_np.ndarray):
        self.flows, self.ids, self.t, self.A, self.inputs, self.rows = flows, ids, t, A, inputs, rows
        self.places = _eiv_slots(flows)
        self.dy = A[:, rows] - A[:, rows - 1]

    def theta(self) -> _eiv_np.ndarray:
        return _eiv_np.array([float(d[k]) for d, k in self.places])

    def set(self, theta: _eiv_np.ndarray) -> None:
        for (d, k), v in zip(self.places, theta):
            d[k] = float(v)

    def change(self, theta: _eiv_np.ndarray, lag: int) -> _eiv_np.ndarray:
        """Each stock's change over the rows' steps (stocks x rows), from the levels `lag` steps before
        each row (1: the step's own start; 2: one step earlier), at the row's time and inputs."""
        self.set(theta)
        return _EivModel(self.flows, self.ids, inputs=self.inputs).change(self.A[:, self.rows - lag], self.t[self.rows])

    def resid(self, theta: _eiv_np.ndarray) -> _eiv_np.ndarray:
        return self.dy - self.change(theta, 1)

    def jac(self, theta: _eiv_np.ndarray, lag: int) -> _eiv_np.ndarray:
        """d change / d numbers (stocks x rows x numbers), by differences."""
        base = self.change(theta, lag)
        J = _eiv_np.empty(base.shape + (len(theta),))
        for j in range(len(theta)):
            h = 1e-4 * max(1e-3, abs(theta[j]))
            th = theta.copy()
            th[j] += h
            J[:, :, j] = (self.change(th, lag) - base) / h
        self.set(theta)
        return J


def _eiv_white_z(e: _eiv_np.ndarray, dy: _eiv_np.ndarray) -> list[float]:
    """Each stock's lag-1 correlation of its residuals, as a z-score under white noise (0 where the
    residuals are nothing but rounding)."""
    out = []
    for s in range(e.shape[0]):
        es = e[s] - e[s].mean()
        v = float(es @ es)
        out.append(float(es[1:] @ es[:-1]) / v * _eiv_np.sqrt(len(es)) if v > 1e-12 * max(1.0, float(dy[s] @ dy[s])) else 0.0)
    return out


def _eiv_units(flows: list[dict]) -> list[tuple[int, int | None]]:
    """The parts pruning may drop, as (flow, term): a whole flow (None), or one term of a linear rate
    with more than one number. Flows that follow the eras are left alone."""
    out = []
    for fi, f in enumerate(flows):
        if f.get("byTime"):
            continue
        r = f.get("rate") or {}
        terms = [ti for ti, x in enumerate(r.get("terms") or []) if x.get("k") is not None]
        if r.get("form") == "linear" and len(terms) + bool(r.get("c")) > 1:
            out += [(fi, ti) for ti in terms]
        else:
            out.append((fi, None))
    return out


def _eiv_unit_places(fit: _EivFit, unit: tuple[int, int | None]) -> list[int]:
    """The positions of a part's numbers in fit.places."""
    fi, ti = unit
    f = fit.flows[fi]
    if ti is not None:
        mine = {id(f["rate"]["terms"][ti])}
    else:
        r = f.get("rate") or {}
        mine = {id(g) for g in f.get("inflow") or []} | {id(r)} | {id(x) for x in r.get("terms") or []}
    return [j for j, (d, k) in enumerate(fit.places) if id(d) in mine and (ti is None or k == "k")]


def _eiv_without(flows: list[dict], unit: tuple[int, int | None]) -> list[dict]:
    fi, ti = unit
    out = _eiv_copy.deepcopy(flows)
    if ti is None:
        del out[fi]
    else:
        r = out[fi]["rate"]
        del r["terms"][ti]
        if out[fi].get("rates"):
            out[fi]["rates"] = [r]
    return out


def _eiv_name(flows: list[dict], unit: tuple[int, int | None]) -> str:
    f = flows[unit[0]]
    return (f"{f.get('from') or 'outside'} -> {f.get('to') or 'outside'}"
            + (f" [{f['rate']['terms'][unit[1]].get('stock')}]" if unit[1] is not None else ""))


class _EivInstrumented:
    """A structure's instrumented fit: its numbers (least squares, then instrumental-variables steps;
    a step that fails keeps the last finite one), their covariance, and which numbers some row reads."""

    def __init__(self, flows: list[dict], ids: list[str], t: _eiv_np.ndarray, A: _eiv_np.ndarray, inputs: dict | None,
                 rows: _eiv_np.ndarray, w: _eiv_np.ndarray):
        self.work, self.w = _eiv_copy.deepcopy(flows), w
        self.fit = _EivFit(self.work, ids, t, A, inputs, rows)
        th = self.fit.theta()
        self.ok = len(th) > 0
        if not self.ok:
            return
        for _ in range(_EIV_ITERATIONS):
            th = th + _eiv_np.linalg.lstsq(self.stack(self.fit.jac(th, 1)), self.stack(self.fit.resid(th)), rcond=None)[0]
        e = self.fit.resid(th)
        dev = _eiv_np.abs(e - _eiv_np.median(e, axis=1, keepdims=True))
        bad = set(rows[_eiv_np.any(dev > _EIV_TRIM * 1.4826 * _eiv_np.maximum(_eiv_np.median(dev, axis=1), 1e-12)[:, None], axis=0)].tolist())
        keep = _eiv_np.array([r for r in rows if not {r - 1, r, r + 1, r + 2} & bad])
        if bad and len(keep) >= 10 * len(th):            # the rows a level outlier touches, as a change or an instrument
            self.fit = _EivFit(self.work, ids, t, A, inputs, keep)
        good = None
        for _ in range(_EIV_ITERATIONS):
            J, Zi = self.stack(self.fit.jac(th, 1)), self.stack(self.fit.jac(th, 2))
            c = _eiv_np.sqrt((J ** 2).sum(axis=0))
            act = c > 0                                  # a number no row reads (a piece outside the rows) stays
            ZJ = (Zi[:, act] / c[act]).T @ (J[:, act] / c[act])
            if not act.any() or not _eiv_np.all(_eiv_np.isfinite(ZJ)) or _eiv_np.linalg.cond(ZJ) > 1e12:
                break
            step = _eiv_np.zeros_like(th)
            step[act] = _eiv_np.linalg.solve(ZJ, (Zi[:, act] / c[act]).T @ self.stack(self.fit.resid(th))) / c[act]
            if not _eiv_np.all(_eiv_np.isfinite(th + step)):
                break
            th = good = th + step
        self.ok = good is not None
        if not self.ok:
            return
        self.th = good
        J, Zi, e = self.fit.jac(good, 1), self.fit.jac(good, 2), self.fit.resid(good)
        self.live = _eiv_np.abs(J).sum(axis=(0, 1)) > 0
        g = _eiv_np.einsum("srp,sr->rp", Zi * w[:, None, None], e * w[:, None])     # each step's moments
        S = g.T @ g
        for lag, weight in ((1, 2 / 3), (2, 1 / 3)):
            C = g[lag:].T @ g[:-lag]
            S += weight * (C + C.T)
        B = _eiv_np.linalg.pinv(_eiv_np.einsum("srp,srq->pq", Zi * w[:, None, None], J * w[:, None, None]))
        self.V = B @ S @ B.T
        self.fit.set(good)

    def stack(self, M: _eiv_np.ndarray) -> _eiv_np.ndarray:
        w = self.w
        return (M * (w[:, None] if M.ndim == 2 else w[:, None, None])).reshape(-1, *M.shape[2:])

    def weakest(self) -> tuple[int, int | None] | None:
        """The part with the largest shortfall of its Wald statistic below PRICE per number, or None."""
        best = None
        for u in _eiv_units(self.work):
            js = _eiv_unit_places(self.fit, u)
            if not js:
                continue
            if not self.live[js].any():                 # it never flows
                return u
            wald = float(self.th[js] @ _eiv_np.linalg.pinv(self.V[_eiv_np.ix_(js, js)]) @ self.th[js])
            short = wald - _EIV_PRICE * len(js)
            if short < 0 and (best is None or short < best[0]):
                best = (short, u)
        return best and best[1]


def _eiv_runs(flows: list[dict], ids: list[str], run: dict, opts: dict) -> _eiv_np.ndarray:
    """Each run's share of the judge (behaviour_error) at its longest horizon."""
    hs = [h for h in _EIV_HORIZONS if h < len(run["t"]) / 4]
    A = _eiv_levels_array(run["levels"], ids)
    n, h = A.shape[1], hs[-1]
    s0 = _eiv_starts_for(n, h, 80)
    sd = A.std(axis=1)
    sd[sd == 0] = 1
    tt = _eiv_np.asarray(run["t"], dtype=float)
    inputs = opts.get("inputs")
    end = _EivModel(flows, ids, inputs={"t": run["t"], "values": inputs} if inputs else None).run(
        A[:, s0 - 1], tt[s0[None, :] + _eiv_np.arange(h)[:, None]], opts.get("injections"))
    obs = A[:, s0 + h - 1]
    e = ((end - obs) / sd[:, None]) ** 2
    e[~_eiv_np.isfinite(e)] = 1e6
    return e.sum(axis=0) / max(1e-9, float((((obs - A[:, s0 - 1]) / sd[:, None]) ** 2).sum()))


def _eiv_prune(flows: list[dict], ids: list[str], t: _eiv_np.ndarray, A: _eiv_np.ndarray, inputs: dict | None, rows: _eiv_np.ndarray,
           w: _eiv_np.ndarray, run: dict, opts: dict) -> tuple[list[dict], dict] | None:
    """The flows with the parts the instrumented fit cannot tell from nothing dropped and the rest
    refitted, and what was done; None when nothing is dropped or no stage passes the guard."""
    cur, names, stages = _EivInstrumented(flows, ids, t, A, inputs, rows, w), [], []
    while cur.ok and len(cur.work) > 1:
        u = cur.weakest()
        if u is None:
            break
        nxt = _EivInstrumented(_eiv_without(cur.work, u), ids, t, A, inputs, rows, w)
        if not nxt.ok:
            break
        names.append(_eiv_name(cur.work, u))
        cur = nxt
        stages.append((cur.work, list(names)))
    if not stages or not [h for h in _EIV_HORIZONS if h < len(run["t"]) / 4]:
        return None
    before = _eiv_runs(flows, ids, run, opts)
    for work, dropped in reversed(stages):
        d = _eiv_runs(work, ids, run, opts) - before
        z = float(d.sum() / max(1e-12, _eiv_np.sqrt(len(d) * d.var(ddof=1)))) if len(d) > 1 else float("inf")
        if z <= _EIV_GUARD:
            return work, {"dropped": dropped, "z": round(z, 2)}
    return None


def _eiv_carried(flows: list[dict], ids: list[str], t: _eiv_np.ndarray, L: _eiv_np.ndarray, inputs: dict | None) -> _eiv_np.ndarray:
    """What each flow carries in each step from levels L at times t (flows x steps; what its receiver
    gets), each flow on its own."""
    out = _eiv_np.zeros((len(flows), L.shape[1]))
    for i, f in enumerate(flows):
        if f.get("from") in ids:
            out[i] = -_EivModel([{**f, "to": None}], ids, inputs=inputs).change(L, t)[ids.index(f["from"])] / float(f.get("ratio") or 1)
        elif f.get("to") in ids:
            out[i] = _EivModel([f], ids, inputs=inputs).change(L, t)[ids.index(f["to"])]
    return out


def _eiv_level_ll(y: _eiv_np.ndarray, level: _eiv_np.ndarray) -> float:
    """-2 log-likelihood of a level-space residual y = R0 + e with var(e) = a + b x level^2 (feasible GLS:
    R0 and a, b fitted from the residuals in turn; each squared residual counted at most TRIM^2 variances)."""
    V = _eiv_np.column_stack([_eiv_np.ones_like(level), level ** 2])
    v = _eiv_np.ones_like(y)
    for it in range(4):
        w = 1 / v
        r = y - float((w * y).sum() / w.sum())
        z = r ** 2 if it == 0 else _eiv_np.minimum(r ** 2, _EIV_TRIM ** 2 * v)
        ab = _eiv_np.linalg.lstsq(V * w[:, None], z * w, rcond=None)[0]
        v = _eiv_np.maximum(max(ab[0], 0.0) + max(ab[1], 0.0) * level ** 2, 1e-9 * max(float(_eiv_np.mean(z)), 1e-12))
    w = 1 / v
    r = y - float((w * y).sum() / w.sum())
    return float(_eiv_np.sum(_eiv_np.log(v) + _eiv_np.minimum(r ** 2 / v, _EIV_TRIM ** 2)))


def _eiv_set_rate(f: dict, rate: dict) -> None:
    f["rate"] = rate
    if f.get("rates"):
        f["rates"] = [rate]


def _eiv_moves(flows: list[dict], fi: int, R: str) -> list[tuple[list[dict], int, int | None, dict | None]]:
    """The drain flows[fi] made a move into R, and, for each inflow from outside into R that reads the
    drain's stock, the move replacing that reading; each as (flows, how many numbers it removes, the
    replaced inflow's index in flows, what is left of that inflow or None). The moved flow is marked
    "_moved"."""
    X = flows[fi]["from"]
    a = _eiv_copy.deepcopy(flows)
    a[fi]["to"], a[fi]["_moved"] = R, True
    out: list = [(a, 0, None, None)]
    for gi, g in enumerate(flows):
        r = g.get("rate") or {}
        if g.get("from") is not None or g.get("to") != R or g.get("byTime") or g.get("inflow"):
            continue
        if r.get("form") == "proportional" and r.get("stock") == X:
            rest = None
        elif r.get("form") == "linear" and any(x.get("stock") == X and x.get("k") is not None for x in r.get("terms") or []):
            terms = [x for x in r["terms"] if x.get("stock") != X]
            rest = None
            if terms or r.get("c"):
                rest = _eiv_copy.deepcopy(g)
                _eiv_set_rate(rest, {**r, "terms": terms} if terms else {"form": "constant", "value": r["c"]})
        else:
            continue
        b = [h for hi, h in enumerate(a) if hi != gi] if rest is None else [rest if hi == gi else h for hi, h in enumerate(a)]
        out.append((b, len(_eiv_slots([g])) - (len(_eiv_slots([rest])) if rest else 0), gi, rest))
    return out


def _eiv_joined(flows: list[dict]) -> list[dict]:
    """The moved flow (marked "_moved", the mark removed) joined to a proportional flow on the same stock
    between the same stocks, if there is one."""
    fi = next(i for i, g in enumerate(flows) if g.get("_moved"))
    f = flows[fi]
    del f["_moved"]
    r = f.get("rate") or {}
    if f.get("byTime") or r.get("form") != "proportional":
        return flows
    for gi, g in enumerate(flows):
        q = g.get("rate") or {}
        if (gi != fi and g.get("from") == f["from"] and g.get("to") == f["to"] and not g.get("byTime")
                and q.get("form") == "proportional" and q.get("stock") == r.get("stock")
                and float(g.get("ratio") or 1) == float(f.get("ratio") or 1)):
            _eiv_set_rate(g, {**q, "k": float(q["k"]) + float(r["k"])})
            return [h for hi, h in enumerate(flows) if hi != fi]
    return flows


def _eiv_merge(flows: list[dict], ids: list[str], run: dict, opts: dict) -> tuple[list[dict], list[str]]:
    """The flows with drains to outside made moves where a measured stock's level shows it receives
    them (the module's Moves), and the moves made."""
    t = _eiv_np.asarray(run["t"], dtype=float)
    A = _eiv_levels_array(run["levels"], ids)
    n = A.shape[1]
    inputs = {"t": list(run["t"]), "values": opts["inputs"]} if opts.get("inputs") else None
    J = _eiv_np.zeros((len(ids), n - 1))                     # announced injections, added before their step's flows
    for j in opts.get("injections") or []:
        if j.get("stock") in ids:
            J[ids.index(j["stock"]), _eiv_np.nonzero(t[1:] == float(j["t"]))[0]] += float(j["amount"])
    L, tt, price = A[:, :-1] + J, t[1:], float(_eiv_np.log(n))
    done: list[str] = []
    for _ in range(len(flows)):
        c = _eiv_carried(flows, ids, tt, L, inputs)
        net = _eiv_np.zeros((len(ids), n - 1))               # what the flows add to each stock in each step
        for i, f in enumerate(flows):
            if f.get("to") in ids:
                net[ids.index(f["to"])] += c[i]
            if f.get("from") in ids:
                net[ids.index(f["from"])] -= c[i] * float(f.get("ratio") or 1)
        y = A[:, 1:] - _eiv_np.cumsum(J + net, axis=1)       # each stock's level less what its flows added
        now: dict[int, float] = {}
        best = None
        for fi, f in enumerate(flows):
            if f.get("to") is not None or f.get("from") not in ids or f.get("inflow"):
                continue
            for r, R in enumerate(ids):
                if R == f["from"]:
                    continue
                if r not in now:
                    now[r] = _eiv_level_ll(y[r], A[r, 1:])
                for cand, fewer, gi, rest in _eiv_moves(flows, fi, R):
                    extra = c[fi].copy()
                    if gi is not None:
                        extra -= c[gi]
                        if rest is not None:
                            extra += _eiv_carried([rest], ids, tt, L, inputs)[0]
                    gain = now[r] - _eiv_level_ll(y[r] - _eiv_np.cumsum(extra), A[r, 1:]) - price * (1 - fewer)
                    if gain > price and (best is None or gain > best[0]):
                        best = (gain, cand, f"{f['from']} -> {R}" + (" (replacing an inflow)" if gi is not None else ""))
        if best is None:
            break
        flows = _eiv_joined(best[1])
        done.append(best[2])
    return flows, done


def _eiv_refit(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None = None) -> tuple[list[dict], dict]:
    """The flows with their numbers refitted by instrumental variables where the module says, drains
    made moves where a level shows its receiver (Moves), and what was found ({} where nothing could be
    tested)."""
    out, info = _eiv_refit_numbers(flows, stocks, run, opts)
    if not info.pop("error", False):
        return out, info
    moved, done = _eiv_merge(out, [s["id"] for s in stocks], run, opts or {})
    if not done:
        return out, info
    return moved, {**info, "moved": done, "used": True}


def _eiv_refit_numbers(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None = None) -> tuple[list[dict], dict]:
    """refit's numbers and pruning; info["error"] where the data show measurement error."""
    opts = opts or {}
    ids = [s["id"] for s in stocks]
    inputs = opts.get("inputs") or {}
    t = _eiv_np.asarray(run["t"], dtype=float)
    n = len(t)
    if not flows or n < 20 or not _eiv_known(flows, set(ids) | set(inputs)) or _eiv_np.any(_eiv_np.diff(t) != 1):
        return flows, {}
    A = _eiv_levels_array(run["levels"], ids)
    if not _eiv_np.all(_eiv_np.isfinite(_eiv_np.asarray([run["levels"].get(i, []) for i in ids], dtype=float))):
        return flows, {}
    work = _eiv_copy.deepcopy(flows)
    pulses = {float(j["t"]) for j in opts.get("injections") or []}
    rows = _eiv_np.array([i for i in range(2, n) if t[i] not in pulses and t[i - 1] not in pulses])
    fit = _EivFit(work, ids, t, A, {"t": list(run["t"]), "values": inputs} if inputs else None, rows)
    theta0 = fit.theta()
    p = len(theta0)
    if p == 0 or len(rows) < 10 * p:
        return flows, {}
    # each stock's rows weighted by the spread of its one-step residuals
    sd = fit.resid(theta0).std(axis=1)
    w = 1.0 / _eiv_np.maximum(sd, 1e-9 * max(1.0, float(_eiv_np.abs(A).max())))

    def stack(M: _eiv_np.ndarray) -> _eiv_np.ndarray:        # stocks x rows (x numbers) -> weighted rows
        return (M * (w[:, None] if M.ndim == 2 else w[:, None, None])).reshape(-1, *M.shape[2:])

    th_o = theta0.copy()
    for _ in range(_EIV_ITERATIONS):
        th_o = th_o + _eiv_np.linalg.lstsq(stack(fit.jac(th_o, 1)), stack(fit.resid(th_o)), rcond=None)[0]
    z = _eiv_white_z(fit.resid(th_o), fit.dy)
    info = {"white_z": [round(x, 2) for x in z], "used": False}
    if min(z) > -_eiv_norm.isf(_EIV_ALPHA / len(z)):
        fit.set(theta0)
        return flows, info
    fit.set(theta0)
    info["error"] = True
    pruned = _eiv_prune(flows, ids, t, A, {"t": list(run["t"]), "values": inputs} if inputs else None, rows, w, run, opts)
    if pruned:
        return pruned[0], {**info, **pruned[1], "used": True}
    th_i = th_o.copy()
    for _ in range(_EIV_ITERATIONS):
        J, Z = stack(fit.jac(th_i, 1)), stack(fit.jac(th_i, 2))
        ZJ = Z.T @ J
        if not _eiv_np.all(_eiv_np.isfinite(ZJ)) or _eiv_np.linalg.cond(ZJ) > 1e12:
            fit.set(theta0)
            return flows, {**info, "skipped": "weak instruments"}
        th_i = th_i + _eiv_np.linalg.solve(ZJ, Z.T @ stack(fit.resid(th_i)))
    if not _eiv_np.all(_eiv_np.isfinite(th_i)):
        fit.set(theta0)
        return flows, {**info, "skipped": "no finite fit"}
    fit.set(_eiv_np.round(th_i, 6))
    before, after = _eiv_judge(flows, ids, run, opts), _eiv_judge(work, ids, run, opts)
    info.update(found=theta0.round(6).tolist(), instrumented=th_i.round(6).tolist(), judged=[before, after])
    if not after <= before:
        # (as eiv.py, the declared boundary) a structure that arrives with nothing to prune (outside flows
        # kept to the boundary already) is held to the pruned model's test: no further from the data at
        # the judge's longest horizon by more than GUARD paired standard errors, since at shorter horizons
        # the measurement error at each run's start still favours the biased numbers (303 meas-long)
        if not [h for h in _EIV_HORIZONS if h < len(run["t"]) / 4]:
            return flows, info
        d = _eiv_runs(work, ids, run, opts) - _eiv_runs(flows, ids, run, opts)
        z = float(d.sum() / max(1e-12, _eiv_np.sqrt(len(d) * d.var(ddof=1)))) if len(d) > 1 else float("inf")
        info["z"] = round(z, 2)
        if not z <= _EIV_GUARD:
            return flows, info
    return work, {**info, "used": True}


def _eiv_apply(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    """A strategy's result with its flows refitted (refit), and what the refit found under "eiv"."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    try:
        flows, info = _eiv_refit(result["flows"], stocks, run, opts)
    except (ValueError, _eiv_np.linalg.LinAlgError, FloatingPointError) as e:
        return {**result, "eiv": {"error": f"{type(e).__name__}: {e}"[:200]}}
    return {**result, "flows": flows, "eiv": info}


# A capacity limit offered to the fit (capmin.py, docs/research/k8s-306-s1.md, 2026-10-21): identify above
# runs with the regime-clipped series MIN(X, theta x Y) as one more measured input where the data show a
# limit, and every term that reads it is written back as MIN(a x X, a theta x Y).
from . import capmin as _capmin  # noqa: E402

_identify_linear = identify


def identify(stocks: list[dict], run: dict, opts: dict | None = None, *args, **kw) -> dict:  # noqa: F811
    return _capmin.wrap(_identify_linear, stocks, run, opts, *args, **kw)
