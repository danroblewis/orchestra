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

        level_of = {term[0]: f for f, term in enumerate(terms) if len(term) == 1}
        simpler = {f: [level_of[j] for j in dict.fromkeys(term)] for f, term in enumerate(terms) if len(term) == 2}
        rows = []
        for s in range(S):
            base = [f for f, term in enumerate(terms) if era_of(term) is None and ok(term, s)] + ins
            simple = [f for f in base if f in ins or len(terms[f]) == 1]
            r = fit_row(dy[s], X, base, o["inflow"], simple=simple, gamma=o.get("gamma", 1.0), pelt_mult=o.get("pelt_mult", 1.0), simpler=simpler)
            if L > 1:
                js = {factors(terms[f])[0] for f in r["terms"] if f < nT and len(factors(terms[f])) == 1} | ({s} if s not in final else set())
                extra = [f for f, term in enumerate(terms) if era_of(term) is not None and term[0] in js and ok(term, s)]
                if extra:
                    r = fit_row(dy[s], X, base + extra, o["inflow"], simple=simple, gamma=o.get("gamma", 1.0), pelt_mult=o.get("pelt_mult", 1.0), simpler=simpler)
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
    for v in variants(level, has_eras):
        r = identify_one(stocks, run, {**opts, **v})
        e = judge(r["flows"], stocks, run, inputs=opts.get("inputs")) if level in ("full", "combo") else 0.0
        tried.append({"name": v["name"], "error": e})
        if best is None or e < best[1]:
            best = (r, e, v["name"])
    r = best[0]
    r["chosen"], r["tried"] = best[2], tried
    return r


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """The answer above with its numbers refitted by instrumental variables where the levels carry
    measurement error (the _eiv_ code below)."""
    return _eiv_apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)


# Errors in variables (docs/research/eiv-refit.md): a copy (as in held_out.py at e8edf28) of the strategies' eiv.py, its names prefixed
# _eiv_. When the levels carry measurement error (one-step residuals negatively correlated from step to
# step), the found numbers are refitted with the levels two steps back as instruments, and kept only if
# the model then runs at least as close to the data over 5, 20 and 100 steps.
import copy as _eiv_copy  # noqa: E402

import numpy as _eiv_np  # noqa: E402
from scipy.stats import norm as _eiv_norm  # noqa: E402

from ..simulate import Model as _EivModel, behaviour_error as _eiv_behaviour_error, levels_array as _eiv_levels_array  # noqa: E402

_EIV_ALPHA = 1e-3          # the white-noise test's level (one-sided, over the stocks)
_EIV_ITERATIONS = 3        # Gauss-Newton steps of each fit (the rates are linear in their numbers, so one is
                      # exact unless a floor, a shared stock or an effect bends them)
_EIV_HORIZONS = (5, 20, 100)


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


def _eiv_refit(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None = None) -> tuple[list[dict], dict]:
    """The flows with their numbers refitted by instrumental variables where the module says, and
    what was found ({} where nothing could be tested)."""
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
