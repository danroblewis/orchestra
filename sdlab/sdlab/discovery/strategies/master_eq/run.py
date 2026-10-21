"""identify(): a master-equation model of counted levels (docs/research/master_eq.md).

Counted levels (whole numbers) are read as units moving between stocks with per-step probabilities
that depend only on where they are: the mean-field (master-equation) model. Its numbers come from
generalised least squares on each step's change with the covariance those numbers imply (fit.py),
its terms from non-negative least squares over every move, drain, input share and constant, pruned
by BIC; then links, binds and era-split numbers are offered one at a time. The model is kept when
it forecasts the run better than the main line's (the main line's behaviour judge); other data go to
the main line.
"""

from __future__ import annotations

import math
import time

import numpy as np

from .earned import main_line as mainline
from . import boundary
from ...simulate import behaviour_error
from . import fit as F
from . import ml as ML
from . import terms as T
from .write import to_flows

OWN_OPTS = ("budget", "products_upto", "judge_slack")
PRODUCTS_UPTO = 6          # binds and catalysed moves are offered to models of at most this many stocks
EXTRA_ROUNDS = 12          # forward steps over the extras
ML_UPTO = 90               # more active terms than this after GLS: GLS's own elimination first
JUDGE_SLACK = 1.0          # kept when its judge error is at most this times the main line's
MAX_STOCKS = 16             # more stocks: the main line (the pool of moves grows as the square)
TRAIN = 0.7                # the held-out check: refitted on this first share of the run, judged on the rest


def counted(run: dict) -> bool:
    for v in run["levels"].values():
        a = np.asarray(v, dtype=float)
        a = a[np.isfinite(a)]
        if a.size and (not np.all(a == np.round(a)) or np.any(a < 0)):
            return False
    return True


def era_labels(t: np.ndarray, eras: list[dict] | None) -> tuple[np.ndarray, list[str], list[tuple[float, float, str]]]:
    """Each time's era label, the labels, and the eras as (from, to, label) over the run."""
    es = sorted([e for e in eras or [] if e and e.get("start") is not None], key=lambda e: float(e["start"]))
    if len(es) < 2:
        return np.array(["" for _ in t], dtype=object), [], []
    lab = np.array([str(es[0].get("label") or es[0]["start"]) for _ in t], dtype=object)
    spans = []
    for k, e in enumerate(es):
        a = float(e["start"])
        b = float(es[k + 1]["start"]) - 1 if k + 1 < len(es) else float(t[-1])
        name = str(e.get("label") or e["start"])
        lab[(t >= a) & (t <= b)] = name
        spans.append((a, b, name))
    return lab, sorted(set(lab)), spans


def prepare(stocks: list[dict], run: dict, opts: dict):
    ids = [s["id"] for s in stocks]
    t = np.asarray(run["t"], dtype=float)
    Y = np.nan_to_num(np.array([np.asarray(run["levels"][i], dtype=float) for i in ids]).T)
    inputs = sorted((opts.get("inputs") or {}).keys())
    U = np.array([np.nan_to_num(np.asarray(opts["inputs"][k], dtype=float)) for k in inputs]).T if inputs else np.zeros((len(t), 0))
    J = np.zeros_like(Y)
    pos = {float(x): k for k, x in enumerate(t)}
    for j in opts.get("injections") or []:
        k = pos.get(float(j["t"]))
        if k is not None and j.get("stock") in ids:
            J[k, ids.index(j["stock"])] += float(j["amount"])
    x = Y[:-1] + J[1:]
    lab, labels, spans = era_labels(t, opts.get("eras"))
    D = T.Data(x=x, d=Y[1:] - x, u=U[1:], era=lab[1:], labels=labels)
    return D, ids, inputs, spans


def judge(flows: list[dict], stocks: list[dict], run: dict, opts: dict, horizons=(5, 20, 100)) -> float:
    hs = [h for h in horizons if h < len(run["t"]) / 4]
    if not flows or not hs:
        return float("inf")
    ids = [s["id"] for s in stocks]
    return sum(behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, injections=opts.get("injections"),
                               inputs=opts.get("inputs")) for h in hs) / len(hs)


def alternatives(P: F.Problem) -> dict[int, list[int]]:
    """For each term taking units from a source: the pool's other terms of that kind from the same
    source (another destination, or outside)."""
    by: dict[tuple, list[int]] = {}
    for k, t in enumerate(P.pool):
        if t.kind in ("move", "drain"):
            by.setdefault(("out", t.src, t.era), []).append(k)
        elif t.kind == "link":
            by.setdefault(("link", t.src, t.era), []).append(k)
        elif t.kind in ("bind", "catal"):
            by.setdefault((t.kind, t.src, t.other, t.era), []).append(k)
    out = {}
    for ks in by.values():
        for k in ks:
            out[k] = [x for x in ks if x != k]
    return out


def merges(P: F.Problem, f: F.Fit, pen: float) -> list[tuple[float, list[int], np.ndarray]]:
    """Every way of letting two of a term's era numbers share one (or all of them, one unsplit term):
    (price, columns, GLS numbers at f's covariance), cheapest first."""
    cols = ML.active(f)
    groups: dict[tuple, list[int]] = {}
    for c in cols:
        t = P.pool[c]
        if t.era is not None:
            groups.setdefault((t.kind, t.src, t.dst, t.other), []).append(c)
    labels = P.D.labels
    offers = []
    for (kind, src, dst, other), cs in groups.items():
        eras = {P.pool[c].era: c for c in cs}
        # the group's labels as they stand (a label with no active term has number 0)
        parts = list(eras)
        cand = []
        if len(parts) >= 2:
            for i in range(len(parts)):
                for j in range(i + 1, len(parts)):
                    cand.append(([eras[parts[i]], eras[parts[j]]], tuple(sorted(parts[i] + parts[j]))))
        cand.append((cs, None if len(sum(parts, ())) == len(labels) or len(parts) == 1 and False else tuple(sorted(sum(parts, ())))))
        if len(parts) == 1 and len(parts[0]) < len(labels):
            cand[-1] = (cs, None)                          # one era's number for all eras
        for drop, era in cand:
            new = P.add([T.Term(kind, src, dst, other, era if era is None or len(era) < len(labels) else None)])[0]
            if new in cols:
                continue
            offers.append(([c for c in cols if c not in drop] + [new], new, drop))
    if not offers:
        return []
    pool = sorted(set(cols) | {o[1] for o in offers})
    G, b, _, _ = F.whiten(P, f.Sig, np.asarray(pool, int))
    ix = {c: k for k, c in enumerate(pool)}
    out = []
    for cs, new, drop in offers:
        idx = [ix[c] for c in cs]
        th = np.zeros(len(P.pool))
        th[cs] = F.nnls_gram(G[np.ix_(idx, idx)], b[idx])
        out.append((F.nll_at(P, th, f.mode) + pen * (len(cs) - len(cols)), cs, th))
    out.sort(key=lambda x: x[0])
    return out


def master(stocks: list[dict], run: dict, opts: dict) -> dict:
    began = time.perf_counter()
    budget = float(opts.get("budget", 200))
    at = lambda share: began + share * budget          # noqa: E731
    D, ids, inputs, spans = prepare(stocks, run, opts)
    S, m = D.S, D.u.shape[1]
    units = [s.get("unit") or "" for s in stocks]
    # the declared boundary (boundary.py): only the outside terms it allows are in the pool; with
    # none declared, each outside flow is a boundary claim priced in the BIC (ml.bic)
    b = boundary.Boundary(run)
    P = F.Problem(D, T.inside(T.conservative(S, m, units, D.labels), b, ids))
    P.claim_price = 0.0 if b.declared else boundary.CLAIM_PRICE
    pen = math.log(P.N)
    trace = []
    base_cols = list(range(len(P.pool)))
    P.add(T.inside(T.extras(S, units, S <= int(opts.get("products_upto", PRODUCTS_UPTO))), b, ids))
    alts = alternatives(P)
    keys = {t.key(): k for k, t in enumerate(P.pool)}
    rev = {k: keys[("move", t.dst, t.src, None, t.era)] for k, t in enumerate(P.pool) if t.kind == "move" and ("move", t.dst, t.src, None, t.era) in keys}

    def select(cols, until):
        """GLS over the pool's terms `cols`, ML, elimination, swaps, elimination."""
        g = F.fit(P, np.asarray(cols, int), "poisson")
        if len(ML.active(g)) > ML_UPTO:                # GLS's elimination first (cheap), at half BIC's price: candidates for ML
            g = F.prune(g, 0.5 * pen, deadline=at(until * 0.4))
        # each move's reverse too: an exchange both ways barely moves the mean (GLS drops one side) but
        # doubles the noise, which only the likelihood sees
        back = [rev[c] for c in ML.active(g) if c in rev]
        g = ML.refine(P, ML.active(g) + back, g.theta, "poisson")
        g = ML.prune(g, pen, deadline=at(until * 0.7))
        g2 = ML.swap(g, alts, pen, deadline=at(until * 0.9))
        return g2 if g2 is g else ML.prune(g2, pen, deadline=at(until))

    f = select(base_cols, 0.4)
    trace.append({"step": "moves, drains, inputs, constants", "terms": len(f.terms()), "nll2": round(f.nll2(), 1), "s": round(time.perf_counter() - began, 1)})
    # extras one at a time (links; binds and catalysed moves for few stocks; and terms dropped before): a
    # term that earns its place by BIC on the model as it stands is added to the pool and the model
    # selected again (a bind found late leaves the other terms bent around its absence)
    chosen: list[int] = []
    for _ in range(EXTRA_ROUNDS):
        if time.perf_counter() > at(0.6):
            break
        g = ML.rank_additions(f, [c for c in range(len(P.pool)) if f.theta[c] <= 0 and c not in chosen])
        best = None
        for _, c in g[:4]:
            f2 = ML.prune(ML.refine(P, ML.active(f) + [c], f.theta, f.mode), pen, deadline=at(0.65))
            if f2.theta[c] > 0 and ML.bic(f2, pen) < ML.bic(f, pen) - 1e-6 and (best is None or ML.bic(f2, pen) < ML.bic(best[0], pen)):
                best = (f2, c)
        if best is None:
            break
        chosen.append(best[1])
        f = best[0]
        if best[1] not in base_cols:
            f3 = select(base_cols + chosen, 0.7)
            if ML.bic(f3, pen) < ML.bic(f, pen):
                f = f3
        trace.append({"step": "extra", "term": P.pool[best[1]].key(), "nll2": round(f.nll2(), 1), "s": round(time.perf_counter() - began, 1)})
    # era-split numbers merged: a term with one number per announced era label is offered with some
    # labels sharing one number (all of them: an unsplit term), priced by the likelihood at the GLS
    # numbers, the best two refitted by ML; kept while BIC falls
    if len(D.labels) >= 2:
        for _ in range(4 * S * len(D.labels)):
            if time.perf_counter() > at(0.8):
                break
            ranked = merges(P, f, pen)
            best = None
            for _, cs, th in ranked[:4]:
                f2 = ML.refine(P, cs, th, f.mode, maxiter=100)
                if ML.bic(f2, pen) < ML.bic(f, pen) - 1e-6 and (best is None or ML.bic(f2, pen) < ML.bic(best, pen)):
                    best = f2
            if best is None:
                break
            f = best
            trace.append({"step": "eras merged", "terms": len(f.terms()), "s": round(time.perf_counter() - began, 1)})
    # the noise reading: binomial (particles) or poisson (counting noise), by likelihood
    fb = ML.refine(P, ML.active(f), f.theta, "binomial")
    modes = {"poisson": round(f.nll2(), 1), "binomial": round(fb.nll2(), 1)}
    if fb.nll2() < f.nll2():
        f = ML.prune(ML.swap(ML.prune(fb, pen, deadline=at(0.9)), alternatives(P), pen, deadline=at(0.95)), pen, deadline=at(0.97))
    # the dispersion: fitted, or held at 1 (the noise is exactly the counts': its size measures the flows)
    free = f
    P.phi1 = True
    f1 = ML.refine(P, ML.active(f), f.theta, f.mode)
    held = f1.nll2() + 1e-9 < free.nll2() + pen
    disp = {"fitted": round(free.nll2(), 1), "held at 1": round(f1.nll2(), 1)}
    if held:
        f = ML.prune(ML.swap(ML.prune(f1, pen, deadline=at(0.97)), alternatives(P), pen, deadline=at(0.98)), pen, deadline=at(0.99))
    else:
        P.phi1 = False
    normal = {i: max(1.0, float(np.mean(D.x[:, i]))) for i in range(S)}
    flows = to_flows(f.terms(), ids, inputs, normal, spans)
    return {"flows": flows, "_fit": (f.terms(), f.mode, P.phi1, normal), "master_eq": {"mode": f.mode, "phi": free.phi, "dispersion": disp, "held": held, "modes": modes, "terms": len(f.terms()), "trace": trace,
                                          "seconds": round(time.perf_counter() - began, 2)}}


def _slice(run: dict, opts: dict, a: int, b: int) -> tuple[dict, dict]:
    t = list(run["t"])[a:b]
    r = {"t": t, "levels": {k: list(v)[a:b] for k, v in run["levels"].items()}}
    o = {k: v for k, v in opts.items() if k not in ("inputs", "injections")}
    if opts.get("inputs"):
        o["inputs"] = {k: list(v)[a:b] for k, v in opts["inputs"].items()}
    if opts.get("injections"):
        o["injections"] = [j for j in opts["injections"] if t and t[0] <= float(j["t"]) <= t[-1]]
    return r, o


def refit(stocks: list[dict], run: dict, opts: dict, fitted, spans) -> list[dict]:
    """The chosen terms' numbers refitted by ML on another stretch of the run (the held-out check)."""
    terms, mode, phi1, normal = fitted
    D, ids, inputs, _ = prepare(stocks, run, opts)
    P = F.Problem(D, [t for t, _ in terms])
    P.phi1 = phi1
    th = np.array([k for _, k in terms])
    g = ML.refine(P, list(range(len(terms))), th, mode)
    return to_flows(g.terms(), ids, inputs, normal, spans)


def choose(stocks, run, opts, main_opts, own, base) -> dict:
    """Which model forecasts better where neither was fitted: both refitted on the first TRAIN of the
    run (the main line selected again; the master equation's terms refitted), judged by the main line's
    behaviour judge (runs from the measured levels) on the rest. On the whole run the main line's
    changing-inflow pieces follow the counts' noise, which the judge rewards."""
    n = len(run["t"])
    k = int(TRAIN * n)
    if n - k < 40:
        jb, jo = judge(base.get("flows") or [], stocks, run, opts), judge(own["flows"], stocks, run, opts)
        return {"how": "judge on the whole run", "main line": jb, "master equation": jo}
    run_tr, opts_tr = _slice(run, opts, 0, k)
    run_te, opts_te = _slice(run, opts, k, n)
    _, _, _, spans = prepare(stocks, run, opts)
    try:
        b_tr = mainline(stocks, run_tr, {kk: v for kk, v in opts_tr.items() if kk not in OWN_OPTS}).get("flows") or []
    except Exception:                                      # noqa: BLE001
        b_tr = []
    o_tr = refit(stocks, run_tr, opts_tr, own["_fit"], spans)
    return {"how": "held out", "main line": judge(b_tr, stocks, run_te, opts_te), "master equation": judge(o_tr, stocks, run_te, opts_te)}


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    main_opts = {k: v for k, v in opts.items() if k not in OWN_OPTS}
    if not counted(run) or len(run["t"]) < 12:
        return {**mainline(stocks, run, main_opts), "chosen_by": "levels not counted: the main line"}
    if len(stocks) > MAX_STOCKS:
        return {**mainline(stocks, run, main_opts), "chosen_by": f"more than {MAX_STOCKS} stocks: the main line"}
    t = np.asarray(run["t"], dtype=float)
    if not np.allclose(np.diff(t), 1.0):
        return {**mainline(stocks, run, main_opts), "chosen_by": "uneven times: the main line"}
    try:
        own = master(stocks, run, opts)
    except Exception as e:                                   # noqa: BLE001  (the main line's model stands)
        return {**mainline(stocks, run, main_opts), "chosen_by": f"master equation failed: {type(e).__name__}: {e}"}
    base = mainline(stocks, run, main_opts)
    if not own["flows"]:
        return {**base, "chosen_by": "master equation found nothing"}
    try:
        judged = choose(stocks, run, opts, main_opts, own, base)
    except Exception as e:                                  # noqa: BLE001
        judged = {"how": f"held-out check failed ({type(e).__name__}: {e}); judge on the whole run",
                  "main line": judge(base.get("flows") or [], stocks, run, opts), "master equation": judge(own["flows"], stocks, run, opts)}
    own.pop("_fit", None)
    jb, jo = judged["main line"], judged["master equation"]
    slack = float(opts.get("judge_slack", JUDGE_SLACK))
    if not np.isfinite(jb) or jo <= slack * jb:
        return {**own, "judged": judged, "chosen_by": f"master equation forecasts at least as well as the main line ({judged['how']})"}
    return {**base, "judged": judged, "master_eq": own["master_eq"], "chosen_by": f"the main line forecasts better ({judged['how']})"}
