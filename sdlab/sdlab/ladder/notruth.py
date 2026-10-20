"""NO-TRUTH evidence that a found model is right: checks that read only the discovery view and found
flows (never the truth, the case, its id or seed, hidden stocks, or the store), so they could run on a
real system where no truth exists. They sit beside the ladder's pass; they change no status or score.

Each check returns {"verdict", "findings", ...}. A verdict is one of
- "supports": the check looked and found nothing wrong (with the power stated in its numbers);
- "weak": something is detectable but small (a statistically clear but immaterial misfit, a fit that
  generalises less well than it fits, or agreement with only one other model);
- "contradicts": a material sign that the model is wrong; its findings say what kind of wrong;
- "uninformative": the data cannot tell (too short, too flat, nothing to compare with).
A finding that does not support carries a `diagnosis`: what kind of wrong it points to, for the
strategy agents.

1. residuals(view, flows): the model's one-step Kalman innovations (notruth_core.innovations) should be
   white (Ljung-Box) and not predictable from the inputs, the injections, any measured level or time
   (a partial F test over an AR(5) base, so serial correlation does not make a spurious hit), per stock.
2. invariance(view, flows): the found structure's numbers refitted separately on each announced era,
   each half, and each quarter of the run should agree (invariant causal prediction, Peters, Buehlmann
   and Meinshausen 2016): a chi-square test per number over the blocks, Holm-corrected.
3. heldout(view, flows): the numbers refitted on the first 70% predict the last 30% (h = 1, 5, 20 steps
   from re-anchored starts, and one free run from the cut) better than persistence (the naive forecast).
   Starts are anchored on the Kalman-filtered levels (data up to the start only; the model's own hidden
   stocks too). Pieces that lie mostly after the cut (an outside inflow's steps or pulses; less than half
   of them, or under 10 steps, before it) keep the found model's values, fitted on the whole run: the check tests the mechanism's numbers out of sample, given
   the model's own account of the unannounced inflow (which no forecast could know in advance).
4. agreement(view, flows, others): other models for the same data (e.g. other strategies' results) should
   predict the same multi-step paths and the same responses to pushes (impulse responses: one stock
   pushed by 10% of its level at 30 moments, every stock followed for 50 steps, the mean change per
   unit pushed). The model's own push-response table is reported too. Models with identical behaviour
   count once (strategies that share code agree by construction).

The one-step refits (invariance, held-out) minimise the one-step errors of the measured stocks, each
divided by its error scale, from their reported levels; a model's own unmeasured stocks are re-observed
with each trial's numbers. With report noise these refits are attenuated (errors in variables) the same
way in every block, so invariance stays fair, but the numbers themselves are not estimates of the truth.

evidence(view, flows, others) runs all four and adds a summary and an evidence score (the share of
informative checks that support, weak counting half): a summary of evidence, not a probability.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

from .notruth_core import (BURN, Compiled, active, build_grid, check_flows, check_view, finite, innovations, leaves,
                           refit, robust_sd, set_leaves)

ALPHA = 0.01                 # family-wise level of every check (Holm)
SMALL = 0.005                # a misfit below this fraction of the stock's level is immaterial
EFFECT = 0.02                # ... or one that explains less than this share of the innovations' variance
INV_MATERIAL = 0.05          # numbers that differ between blocks by less than this (relative) agree in practice
INV_UNINFORMATIVE = 0.5      # blocks whose numbers' SE are above this (relative) cannot tell
HELD_FRAC = 0.7
HELD_MARGIN = 0.1            # held-out skill below -0.1 at the main horizon contradicts (0 to -0.1: weak)
FREE_BAD = -0.5              # a free run from the cut contradicts only when this much worse than persistence
HORIZONS = (1, 5, 20)
AGREE_PRED = 0.05            # multi-step paths within 5% of the level: the same behaviour
AGREE_PUSH = 0.10            # push responses within 10% of the push
PUSH = 0.10                  # a push: 10% of the stock's level
PUSH_H = 50
MAX_FIT = 40                 # numbers refitted at once at most (more: pieces held at their found values)
RANK = {"contradicts": 3, "weak": 2, "supports": 1, "uninformative": 0, "n/a": 0}


def _worst(verdicts: list[str]) -> str:
    vs = [v for v in verdicts if v in RANK and RANK[v] > 0]
    return max(vs, key=RANK.get) if vs else "uninformative"


def _holm(ps: list[float]) -> list[float]:
    m = len(ps)
    order = np.argsort(ps)
    out = np.empty(m)
    run = 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (m - r) * ps[i]))
        out[i] = run
    return out.tolist()


# ---- 1. residuals ----

def _acf(x: np.ndarray, L: int) -> np.ndarray:
    x = x - x.mean()
    v = float(x @ x)
    return np.array([float(x[h:] @ x[:-h]) / v if v > 0 else 0.0 for h in range(1, L + 1)])


def _reads(f: dict) -> set:
    rs = [f.get("rate")] + [g.get("rate") for g in f.get("byTime") or []]
    out = set()
    for r in rs:
        r = r or {}
        out |= {r.get("stock")} | {t.get("stock") for t in r.get("terms") or []}
    out |= {e.get("stock") for e in f.get("effects") or []}
    return out - {None}


def _group_diag(kind: str, name: str, stock: str, coef: float, flows: list[dict]) -> str:
    touches = [f for f in flows if stock in (f.get("from"), f.get("to"))]
    read = any(name in _reads(f) for f in touches)
    if kind == "mean":
        return (f"{stock}: the model's one-step change is {'too low' if coef > 0 else 'too high'} on average: "
                + ("an inflow into it is understated or missing, or an outflow overstated" if coef > 0 else
                   "an outflow from it is understated or missing, or an inflow overstated"))
    if kind == "trend":
        return f"{stock}: the misfit drifts with time: a slow change over the run (an unannounced era, a drift) is not modelled"
    if kind == "input":
        return (f"{stock}: the misfit follows input {name}: its push into {stock} is "
                f"{'missing' if not read else ('understated' if coef > 0 else 'overstated')} (or its lag is wrong)")
    if kind == "injection":
        return f"{stock}: the misfit follows the announced injections into {name}: the response to a push of {name} is wrong in {stock}"
    if name == stock:
        return (f"{stock}: the misfit follows its own level: the rate on its own level (drain, goal) is off; the model "
                f"{'drains too much' if coef > 0 else 'drains too little'} when it is high")
    if read:
        return f"{stock}: the misfit follows {name}: the number of the flow that reads {name} is off"
    return f"{stock}: the misfit follows {name}: a link or move between {name} and {stock} is missing"


def _ac_diag(stock: str, ac: np.ndarray) -> str:
    peak = int(np.argmax(np.abs(ac))) + 1
    if peak > 1 and abs(ac[peak - 1]) > 2 * abs(ac[0]):
        return f"{stock}: the misfit repeats every {peak} steps: a periodic driver or a delay the model lacks"
    if ac[0] > 0:
        return (f"{stock}: the misfit persists from step to step: a missing or mis-timed slow flow, a hidden stock, "
                "or numbers off (a wrong time constant)")
    return f"{stock}: the misfit alternates: an over-strong correction (drain or link) or report noise the model passes on"


def _ols_rss(y: np.ndarray, A: np.ndarray) -> tuple[float, np.ndarray]:
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    r = y - A @ b
    return float(r @ r), b


def residuals(view: dict, flows: list[dict], alpha: float = ALPHA) -> dict:
    check_view(view)
    check_flows(flows)
    g = build_grid(view)
    c = Compiled(flows, g)
    inn = innovations(c)
    rows, findings = [], []
    for i, s in enumerate(g.ids):
        idx = np.flatnonzero(np.isfinite(inn.z[i]))
        idx = idx[idx >= max(BURN + 1, 2)]
        n = idx.size
        if n < 40:
            rows.append({"stock": s, "n": int(n), "verdict": "uninformative"})
            continue
        z = inn.z[i, idx]
        sdv = inn.sd[i, idx]
        lev = float(g.level[i])
        L = min(20, n // 5)
        ac = _acf(z, L)
        Q = n * (n + 2) * float(np.sum(ac ** 2 / (n - np.arange(1, L + 1))))
        p_lb = float(stats.chi2.sf(Q, L))
        p_ar = min(5, L)
        lagged = np.column_stack([np.concatenate([np.zeros(h), z[:-h]]) for h in range(1, p_ar + 1)])
        base = np.column_stack([np.ones(n), lagged])[p_ar:]
        zz = z[p_ar:]
        rss0, b0 = _ols_rss(zz, base)
        rss_c, _ = _ols_rss(zz, np.ones((zz.size, 1)))
        ar_part = base @ b0 - zz.mean()
        tests = [{"test": "white (Ljung-Box)", "kind": "white", "name": "", "p": p_lb, "effect": max(0.0, 1 - rss0 / rss_c) if rss_c > 0 else 0.0,
                  "size": float(np.sqrt(np.mean((ar_part * sdv[p_ar:]) ** 2))) / lev, "lag1": float(ac[0]),
                  "diagnosis": _ac_diag(s, ac)}]
        mean_t = float(z.mean() / (z.std(ddof=1) / math.sqrt(n))) if z.std() > 0 else 0.0
        tests.append({"test": "mean zero", "kind": "mean", "name": "", "p": float(2 * stats.t.sf(abs(mean_t), n - 1)),
                      "effect": float(z.mean() ** 2 / max(np.mean(z ** 2), 1e-300)), "size": abs(float(np.mean(inn.e[i, idx]))) / lev,
                      "coef": float(z.mean())})
        groups = []
        for k, u in g.input_grid.items():
            groups.append(("input", k, np.column_stack([u[idx], u[idx - 1], u[np.maximum(idx - 2, 0)]])))
        for j, sj in enumerate(g.ids):
            groups.append(("level", sj, g.Yi[j, idx - 1][:, None]))
        for sj in sorted({j["stock"] for j in g.injections}):
            amt = np.zeros(len(g.times))
            for j in g.injections:
                if j["stock"] == sj and g.times[0] <= int(j["t"]) <= g.times[-1]:
                    amt[int(j["t"]) - g.times[0]] += float(j["amount"])
            if amt.any():
                groups.append(("injection", sj, np.column_stack([amt[idx], amt[idx - 1], amt[np.maximum(idx - 2, 0)]])))
        groups.append(("trend", "time", ((idx - idx.mean()) / max(1.0, idx.std()))[:, None]))
        for kind, name, Xg in groups:
            Xg = Xg[p_ar:]
            sd_cols = Xg.std(axis=0)
            keep = sd_cols > 1e-12 * np.maximum(1.0, np.abs(Xg).max(axis=0))
            if not keep.any():
                continue
            Xg = (Xg[:, keep] - Xg[:, keep].mean(axis=0)) / sd_cols[keep]
            rss1, b1 = _ols_rss(zz, np.column_stack([base, Xg]))
            q = Xg.shape[1]
            df2 = zz.size - base.shape[1] - q
            if df2 <= 5 or rss1 <= 0:
                continue
            F = ((rss0 - rss1) / q) / (rss1 / df2)
            contrib = Xg @ b1[base.shape[1]:]
            tests.append({"test": f"{kind} {name}".strip(), "kind": kind, "name": name, "p": float(stats.f.sf(max(F, 0.0), q, df2)),
                          "effect": max(0.0, (rss0 - rss1) / rss0) if rss0 > 0 else 0.0,
                          "size": float(np.sqrt(np.mean((contrib * sdv[p_ar:]) ** 2))) / lev, "coef": float(b1[base.shape[1]])})
        rows.append({"stock": s, "n": int(n), "R": finite(np.mean(inn.R[i])), "Q": finite(np.mean(inn.Q[i])), "lag1": float(ac[0]), "tests": tests})
    allt = [t for r in rows for t in r.get("tests", [])]
    for t, ph in zip(allt, _holm([t["p"] for t in allt]) if allt else []):
        t["p_holm"] = ph
        if ph >= alpha:
            t["verdict"] = "supports"
        elif t["size"] < SMALL or t["effect"] < EFFECT:
            t["verdict"] = "weak"
        else:
            t["verdict"] = "contradicts"
    for r in rows:
        if "tests" not in r:
            continue
        r["verdict"] = _worst([t["verdict"] for t in r["tests"]])
        for t in r["tests"]:
            if t["verdict"] != "supports":
                if "diagnosis" not in t:
                    t["diagnosis"] = _group_diag(t["kind"], t["name"], r["stock"], t.get("coef", 0.0), flows)
                findings.append({"stock": r["stock"], "test": t["test"], "verdict": t["verdict"], "p_holm": t["p_holm"],
                                 "size": t["size"], "effect": t["effect"], "diagnosis": t["diagnosis"]})
    findings.sort(key=lambda f: (-RANK[f["verdict"]], -f["size"]))
    return {"check": "residuals", "verdict": _worst([r["verdict"] for r in rows]), "how": inn.how, "stocks": rows, "findings": findings}


# ---- 2. invariance ----

def _anchored(c: Compiled) -> tuple[np.ndarray, np.ndarray]:
    """The path the one-step refits start from (measured stocks at their reports, the model's own
    unmeasured ones at their Kalman-filtered levels) and each measured stock's one-step error scale."""
    inn = innovations(c)
    X = c.nominal()
    X[c.S:] = inn.M[c.S:]
    err = c.g.y[:, 1:] - c.one_step(X)[: c.S]
    w = np.array([robust_sd(err[i]) for i in range(c.S)])
    return X, np.where(np.isfinite(w) & (w > 0), w, c.g.q)


def _blocks(g, eras: list[dict]) -> dict[str, list[tuple[int, int]]]:
    """Partitions of the grid into blocks (index ranges, inclusive) of at least 30 steps."""
    N = len(g.times)
    out = {}
    starts = sorted(int(e["start"]) for e in eras or [] if e.get("start") is not None)
    if len(starts) > 1:
        cuts = [max(1, min(N, s - int(g.times[0]))) for s in starts] + [N]
        blk = [(a, b - 1) for a, b in zip(cuts[:-1], cuts[1:]) if b - a >= 30]
        if len(blk) > 1:
            out["eras"] = blk
    for name, m in (("halves", 2), ("quarters", 4)):
        edges = np.linspace(1, N, m + 1).astype(int)
        blk = [(int(a), int(b) - 1) for a, b in zip(edges[:-1], edges[1:])]
        if all(b - a + 1 >= 30 for a, b in blk):
            out[name] = blk
    return out


def _pattern(vals: np.ndarray, means: np.ndarray, ids: list[str], partition: str, blk, g) -> str:
    d = np.diff(vals)
    if partition == "eras":
        return ("differs between the announced eras (starting " + ", ".join(str(int(g.times[a])) for a, _ in blk)
                + "): the era changes this flow but the model holds the number fixed, or it absorbs a change elsewhere")
    if len(vals) >= 3 and (np.all(d > 0) or np.all(d < 0)):
        msg = "drifts steadily over the run: a slow change, or a number that depends on a level (a missing effect or nonlinearity)"
        if means.shape[1] >= 3:
            cs = [abs(np.corrcoef(vals, means[i])[0, 1]) if np.std(means[i]) > 0 else 0.0 for i in range(len(ids))]
            j = int(np.nanargmax(cs)) if cs else -1
            if j >= 0 and cs[j] > 0.9:
                msg += f"; it tracks the level of {ids[j]} (|r| = {cs[j]:.2f})"
        return msg
    return "is not the same from block to block: the structure does not hold the same way through the run (a missing flow or driver whose share varies)"


def invariance(view: dict, flows: list[dict], alpha: float = ALPHA) -> dict:
    check_view(view)
    check_flows(flows)
    g = build_grid(view)
    c = Compiled(flows, g)
    X, w = _anchored(c)
    lv = leaves(flows)
    if not lv:
        return {"check": "invariance", "verdict": "uninformative", "partitions": {}, "findings": [], "note": "no numbers to refit"}
    parts, findings = {}, []
    for pname, blk in _blocks(g, g.eras).items():
        spans = [(g.times[a], g.times[b]) for a, b in blk]
        compar = [i for i, leaf in enumerate(lv) if sum(active(leaf, lo, hi) for lo, hi in spans) >= 2]
        if not compar:
            continue
        compar = compar[:MAX_FIT]
        fits = []
        for a, b in blk:
            rows = np.arange(max(1, a), b + 1)
            lo, hi = g.times[rows[0]], g.times[rows[-1]]
            # the compared numbers first (so their places match across blocks), then this block's own pieces
            # (nuisance numbers, refitted too: held at the whole run's values, their errors would land on the others)
            own = [leaf for i, leaf in enumerate(lv) if i not in compar and active(leaf, lo, hi)]
            fits.append(refit(flows, g, X, rows, w, lv=([lv[i] for i in compar] + own)[:max(MAX_FIT, len(compar))]))
        means = np.array([[np.nanmean(g.Yi[i, a:b + 1]) for a, b in blk] for i in range(c.S)])
        res = []
        for n, li in enumerate(compar):
            vals, ses, used = [], [], []
            for bi, f in enumerate(fits):
                if f.fitted[n] and np.isfinite(f.se[n]) and f.se[n] > 0:
                    vals.append(f.values[n]), ses.append(f.se[n]), used.append(bi)
            if len(vals) < 2:
                continue
            vals, ses = np.array(vals), np.array(ses)
            wt = 1 / ses ** 2
            mean = float(np.sum(wt * vals) / np.sum(wt))
            Qs = float(np.sum(wt * (vals - mean) ** 2))
            ref = max(abs(mean), 1e-12)
            tr = []                                         # numbers it trades off against (|corr| > 0.8 in most blocks)
            for m2, lj in enumerate(compar):
                if m2 == n:
                    continue
                cs = [abs(f.corr[n, m2]) for f in fits if f.corr is not None and np.isfinite(f.corr[n, m2])]
                if cs and np.median(cs) > 0.8:
                    tr.append(lv[lj].name)
            res.append({"number": lv[li].name, "trades_off": tr, "found": lv[li].value, "blocks": [int(g.times[blk[b][0]]) for b in used],
                        "values": vals.tolist(), "se": ses.tolist(), "p": float(stats.chi2.sf(Qs, len(vals) - 1)),
                        "spread": float(np.max(np.abs(vals - mean)) / ref), "rel_se": float(np.median(ses) / ref),
                        "_m": means[:, used], "_blk": [blk[b] for b in used]})
        for r, ph in zip(res, _holm([r["p"] for r in res]) if res else []):
            r["p_holm"] = ph
            if r["rel_se"] > INV_UNINFORMATIVE:
                r["verdict"] = "uninformative"
            elif ph >= alpha:
                r["verdict"] = "supports"
            elif r["spread"] < INV_MATERIAL:
                r["verdict"] = "weak"
            else:
                r["verdict"] = "contradicts"
            m, b = r.pop("_m"), r.pop("_blk")
            if r["verdict"] in ("contradicts", "weak"):
                r["diagnosis"] = f"{r['number']} {_pattern(np.array(r['values']), m, g.ids, pname, b, g)}"
                if r["trades_off"]:
                    r["diagnosis"] += ("; it trades off against " + ", ".join(r["trades_off"]) + ": the data cannot tell these "
                                       "numbers apart, so one of the flows is likely extra (e.g. a move written as a drain plus a link)")
                findings.append({"partition": pname, **{k: r[k] for k in ("number", "verdict", "p_holm", "spread", "values", "diagnosis")}})
        parts[pname] = {"blocks": [[int(g.times[a]), int(g.times[b])] for a, b in blk], "numbers": res,
                        "verdict": _worst([r["verdict"] for r in res])}
    findings.sort(key=lambda f: (-RANK[f["verdict"]], -f["spread"]))
    return {"check": "invariance", "verdict": _worst([p["verdict"] for p in parts.values()]), "partitions": parts, "findings": findings}


# ---- 3. held-out ----

HOLD_MIN = 10                # a piece is refitted on the first part only when at least this many steps and half of it lie there


def _skill(c: Compiled, X: np.ndarray, g, lo: int, hi: int, h: int, n_starts: int = 40) -> list[dict]:
    """Per stock: rms error of the model h steps after starts in [lo, hi - h] (re-anchored on X) and of
    persistence, over reported targets."""
    if hi - h < lo:
        return []
    starts = np.unique(np.linspace(lo, hi - h, min(n_starts, hi - h - lo + 1)).astype(int))
    pred = c.run(X[:, starts], g.times[starts], h)[: c.S, :, h - 1]
    out = []
    for i, s in enumerate(g.ids):
        y = g.y[i, starts + h]
        ok = np.isfinite(y) & np.isfinite(pred[i])
        if ok.sum() < 5:
            out.append({"stock": s, "n": int(ok.sum())})
            continue
        em = float(np.sqrt(np.mean((pred[i][ok] - y[ok]) ** 2)))
        en = float(np.sqrt(np.mean((g.Yi[i, starts][ok] - y[ok]) ** 2)))
        out.append({"stock": s, "n": int(ok.sum()), "rms": em, "naive": en,
                    "skill": 1 - em / en if en > g.q[i] else None, "rel": (em - en) / g.level[i]})
    return out


def heldout(view: dict, flows: list[dict], frac: float = HELD_FRAC, horizons=HORIZONS) -> dict:
    check_view(view)
    check_flows(flows)
    g = build_grid(view)
    N = len(g.times)
    cut = int(frac * N)
    if cut < 40 or N - cut < 20:
        return {"check": "heldout", "verdict": "uninformative", "findings": [], "note": f"run too short ({N} steps)"}
    c0 = Compiled(flows, g)
    X0, w = _anchored(c0)
    t_cut = int(g.times[cut - 1])
    lv = leaves(flows)
    inside = lambda leaf: min(leaf.span[1], t_cut) - leaf.span[0] + 1 >= max(HOLD_MIN, 0.5 * (leaf.span[1] - leaf.span[0] + 1))  # noqa: E731
    fit_lv = [leaf for leaf in lv if leaf.span is None] + [leaf for leaf in reversed(lv) if leaf.span is not None and inside(leaf)]
    fit_lv = fit_lv[:MAX_FIT]
    fit = refit(flows, g, X0, np.arange(1, cut), w, lv=fit_lv)
    trained = set_leaves(flows, fit_lv, fit.values) if fit_lv else flows
    later = [leaf.name for leaf in lv if leaf.span is not None and not inside(leaf)]
    c = Compiled(trained, g)
    X = innovations(c).M
    out = {"check": "heldout", "cut": t_cut, "refit": {"n": len(fit_lv), "ok": fit.ok,
                                                         "changed": {leaf.name: [leaf.value, float(v)] for leaf, v in zip(fit_lv, fit.values)
                                                                     if abs(v - leaf.value) > 1e-9 * max(1, abs(leaf.value))}},
           "pieces_after_cut_from_found": len(later), "horizons": {}}
    for h in horizons:
        out["horizons"][str(h)] = {"held_out": _skill(c, X, g, cut - 1, N - 1, h), "in_sample": _skill(c, X, g, 1, cut - 1, h)}
    # one free run from the cut over the whole held-out part, against persistence from the cut
    run = c.run(X[:, [cut - 1]], g.times[[cut - 1]], N - cut)[: c.S, 0, :]
    free = []
    for i, s in enumerate(g.ids):
        y = g.y[i, cut:]
        ok = np.isfinite(y) & np.isfinite(run[i])
        if ok.sum() < 5:
            continue
        em = float(np.sqrt(np.mean((run[i][ok] - y[ok]) ** 2)))
        en = float(np.sqrt(np.mean((g.Yi[i, cut - 1] - y[ok]) ** 2)))
        free.append({"stock": s, "rms": em, "naive": en, "skill": 1 - em / en if en > g.q[i] else None, "rel": (em - en) / g.level[i]})
    out["free"] = free
    main = str(max(h for h in horizons if h <= (N - cut) // 2) if any(h <= (N - cut) // 2 for h in horizons) else horizons[0])
    out["main_horizon"] = int(main)
    findings, verdicts = [], []
    ins = {r["stock"]: r for r in out["horizons"][main]["in_sample"]}
    for r in out["horizons"][main]["held_out"] + [{**f, "free": True} for f in free]:
        if r.get("skill") is None:
            verdicts.append("uninformative")
            continue
        tag = "free run" if r.get("free") else f"@{main}"
        # near an equilibrium persistence is already a good forecast and both are noise: a free run counts
        # only when far worse, a horizon forecast only beyond the noise of a 40-start estimate
        if r["skill"] < (FREE_BAD if r.get("free") else -HELD_MARGIN) and r["rel"] >= SMALL:
            verdicts.append("contradicts")
            findings.append({"stock": r["stock"], "test": f"held-out {tag}", "verdict": "contradicts", "skill": r["skill"],
                             "diagnosis": (f"{r['stock']}: forecasts the held-out part worse than persistence ({tag}, skill {r['skill']:.2f}): "
                                           "wrong dynamics (time constant, equilibrium or a missing driver), or numbers that fit "
                                           "the first part only" + (f"; {len(later)} pieces after the cut are the found model's" if later else ""))})
        elif r["skill"] < 0:
            verdicts.append("weak")
            findings.append({"stock": r["stock"], "test": f"held-out {tag}", "verdict": "weak", "skill": r["skill"],
                             "diagnosis": f"{r['stock']}: no better than persistence ({tag}, skill {r['skill']:.2f}): its dynamics add "
                                          "little to a flat forecast here (a stock near equilibrium), or are slightly off"})
        else:
            gap = (ins.get(r["stock"], {}).get("skill") or 0) - r["skill"] if not r.get("free") else 0
            if gap > 0.3:
                verdicts.append("weak")
                findings.append({"stock": r["stock"], "test": f"held-out {tag}", "verdict": "weak", "skill": r["skill"],
                                 "diagnosis": f"{r['stock']}: skill drops from {r['skill'] + gap:.2f} in-sample to {r['skill']:.2f} held out: overfitted pieces or numbers"})
            else:
                verdicts.append("supports")
    out["verdict"] = _worst(verdicts)
    out["findings"] = findings
    return out


# ---- 4. agreement ----

def _behaviour(flows: list[dict], g, starts: np.ndarray, horizon: int, push_h: int) -> dict:
    c = Compiled(flows, g)
    X = innovations(c, fit_noise=False).M
    paths = c.run(X[:, starts], g.times[starts], horizon)[: c.S]
    resp = np.zeros((c.S, c.S, push_h))                       # [pushed, responding, step]
    L = X[:, starts]
    base = c.run(L, g.times[starts], push_h)[: c.S]
    for j in range(c.S):
        d = PUSH * float(g.level[j])
        Lp = L.copy()
        Lp[j] += d
        resp[j] = np.nanmean((c.run(Lp, g.times[starts], push_h)[: c.S] - base) / d, axis=1)
    return {"paths": paths, "resp": resp}


def push_table(resp: np.ndarray, ids: list[str], at=(1, 5, 20, 50)) -> dict:
    """The push responses: per pushed stock, each stock's change per unit pushed, h steps later."""
    return {ids[j]: {ids[i]: {str(h): finite(resp[j, i, h - 1]) for h in at if h <= resp.shape[2]} for i in range(len(ids))}
            for j in range(len(ids))}


def agreement(view: dict, flows: list[dict], others: dict[str, list[dict]], horizon: int = 20, push_h: int = PUSH_H) -> dict:
    check_view(view)
    check_flows(flows)
    for o in others.values():
        check_flows(o)
    g = build_grid(view)
    N = len(g.times)
    hi = max(1, N - 1 - max(horizon, push_h))
    starts = np.unique(np.linspace(1, hi, min(30, hi)).astype(int))
    me = _behaviour(flows, g, starts, horizon, push_h)
    lev = g.level[:, None, None]
    out = {"check": "agreement", "push_response": push_table(me["resp"], g.ids), "others": {}}
    if not others:
        return {**out, "verdict": "uninformative", "findings": [], "note": "no other model for this data"}
    seen, agree, distinct = [(np.round(me["paths"], 6).tobytes(), np.round(me["resp"], 6).tobytes())], [], 0
    for name, of in others.items():
        try:
            b = _behaviour(of, g, starts, horizon, push_h)
        except Exception as e:                               # noqa: BLE001
            out["others"][name] = {"error": str(e)[:200]}
            continue
        dp = np.sqrt(np.nanmean(((me["paths"] - b["paths"]) / lev) ** 2, axis=(1, 2)))
        dr = np.sqrt(np.nanmean((me["resp"] - b["resp"]) ** 2, axis=2))         # [pushed, responding]
        jw, iw = np.unravel_index(int(np.nanargmax(dr)), dr.shape) if np.isfinite(dr).any() else (0, 0)
        pred, push = float(np.nanmax(dp)), float(np.nanmax(dr))
        same = pred < AGREE_PRED and push < AGREE_PUSH
        key = (np.round(b["paths"], 6).tobytes(), np.round(b["resp"], 6).tobytes())
        dup = key in seen
        if not dup:
            seen.append(key)
            distinct += 1
        out["others"][name] = {"pred_diff": pred, "push_diff": push, "agree": same, "duplicate": dup,
                               "worst_push": f"{g.ids[jw]} -> {g.ids[iw]}"}
        if same and not dup:
            agree.append(name)
    n = sum(1 for v in out["others"].values() if "error" not in v and not v["duplicate"])
    out.update(n_distinct_others=n, n_agree=len(agree), agree_with=agree)
    findings = []
    if n == 0:
        verdict = "uninformative"
    elif len(agree) >= 2:
        verdict = "supports"
    else:
        verdict = "weak"
        far = sorted(((v["push_diff"], k, v) for k, v in out["others"].items() if "error" not in v and not v["agree"]), reverse=True)[:3]
        for _, k, v in far:
            findings.append({"other": k, "verdict": "weak", "diagnosis": f"disagrees with {k} most on the response {v['worst_push']} to a push "
                                                                         f"(paths {v['pred_diff']:.3f}, pushes {v['push_diff']:.3f}); disagreement says "
                                                                         "one of the two is wrong, not which"})
    out["verdict"] = verdict
    out["findings"] = findings
    return out


# ---- all four ----

def evidence(view: dict, flows: list[dict], others: dict[str, list[dict]] | None = None, checks=("residuals", "invariance", "heldout", "agreement")) -> dict:
    """Every check (each guarded on its own: an error is reported as that check's, never as a verdict),
    a count of verdicts, and the evidence score."""
    check_view(view)
    fns = {"residuals": lambda: residuals(view, flows), "invariance": lambda: invariance(view, flows),
           "heldout": lambda: heldout(view, flows), "agreement": lambda: agreement(view, flows, others or {})}
    out = {}
    for name in checks:
        try:
            out[name] = fns[name]()
        except AssertionError:
            raise
        except Exception as e:                                # noqa: BLE001
            out[name] = {"check": name, "verdict": "error", "error": f"{type(e).__name__}: {e}"[:300], "findings": []}
    counts = {v: sum(1 for r in out.values() if r["verdict"] == v) for v in ("supports", "weak", "contradicts", "uninformative", "error")}
    informative = counts["supports"] + counts["weak"] + counts["contradicts"]
    score = (counts["supports"] + 0.5 * counts["weak"]) / informative if informative else None
    return {"checks": out, "counts": counts, "score": score,
            "diagnoses": [f["diagnosis"] for r in out.values() for f in r.get("findings", []) if f.get("verdict") == "contradicts" and f.get("diagnosis")]}
