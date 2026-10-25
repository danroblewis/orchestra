"""Experiment: hidden stocks as delayed copies of a level (docs/DISCOVERY-EXPERIMENTS.md).

The main line's candidates (identify.VARIANTS) are built and judged as usual. Then, for the best of
them, delayed copies of every stock's level are offered as columns (sdlab/discovery/hidden.py); the
copies the rows choose (with a positive number) name pairs A -> B that may have an unmeasured stock
between them. Each such stock is then added one at a time, greedily, while it makes the model
behave better on the data (its unmeasured stocks started from their own estimated levels), and its
delay is tuned between the grid's values. A chosen copy is an unmeasured stock A -> H -> B in the
found model, carrying its estimated level (result["inferred_levels"]).
"""

from __future__ import annotations

import numpy as np

from ..hidden import DELAYS, copies, delayed, inferred_levels
from ..identify import VARIANTS
from ..matrix import identify_one
from ..simulate import Model, behaviour_error, levels_array, starts_for


def judge_each(flows: list[dict], stocks: list[dict], run: dict, inferred: dict, horizons=(5, 20, 100)) -> list[float]:
    hs = [h for h in horizons if h < len(run["t"]) / 4]
    if not flows or not hs:
        return [float("inf")]
    ids = [s["id"] for s in stocks]
    return [behaviour_error(flows, ids, run["t"], run["levels"], horizon=h, inferred=inferred) for h in hs]


def chosen_copies(r: dict, extra: list[dict]) -> dict[tuple[str, str], dict]:
    """(source, receiving stock) -> the copy that row gives the largest positive number, offered to
    that row alone, in place of its source's level."""
    by_id = {e["id"]: e for e in extra}
    best: dict[tuple[str, str], tuple[float, dict]] = {}
    for row in r.get("matrix") or []:
        for c in row.get("coefL") or [row.get("coef") or {}]:
            for key, k in c.items():
                e = by_id.get(key)
                if e and k > 0 and k > best.get((e["source"], row["id"]), (0, None))[0]:
                    best[(e["source"], row["id"])] = (k, e)
    return {p: {**e, "id": f"{e['id']}@{p[1]}", "rows": {p[1]}, "replaces": True} for p, (k, e) in best.items()}


def screened_copies(stocks: list[dict], run: dict, base: dict, extra: list[dict], top: int = 6) -> dict[tuple[str, str], dict]:
    """(source, receiving stock) -> the copy that best explains the receiving stock's changes in
    place of its source's level, beside the levels its row already uses and a constant (no pieces:
    pieces fitted to the data would explain the hidden stock's arrivals before any copy is tried).
    Only copies with a positive number that pay for themselves (by more than log T), the `top` best."""
    ids = [s["id"] for s in stocks]
    lv = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, [0] * len(run["t"])), dtype=float) for i in ids]))
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    T = dy.shape[1]
    rows = {r["id"]: r for r in base.get("matrix") or []}

    def rss(X, y):
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        return float(((y - X @ beta) ** 2).sum()), beta

    found = []
    for b, s in ((b, ids.index(b)) for b in ids if b in rows):
        used = [ids.index(j) for j, k in (rows[b].get("coefL") or [rows[b].get("coef") or {}])[0].items() if j in ids and k]
        base_rss = rss(np.column_stack([prev[used].T, np.ones(T)]) if used else np.ones((T, 1)), dy[s])[0]
        best: dict[str, tuple[float, dict]] = {}
        for e in extra:
            if b not in e["rows"]:
                continue
            keep = [j for j in used if ids[j] != e["source"]]
            X = np.column_stack([prev[keep].T, np.ones(T), e["series"][:-1]]) if keep else np.column_stack([np.ones(T), e["series"][:-1]])
            r1, beta = rss(X, dy[s])
            gain = T * np.log(max(base_rss, 1e-12) / max(r1, 1e-12))
            if beta[-1] > 0 and gain > np.log(T) and gain > best.get(e["source"], (-np.inf, None))[0]:
                best[e["source"]] = (gain, e)
        found += [(g, (a, b), e) for a, (g, e) in best.items()]
    found.sort(key=lambda x: -x[0])
    return {p: {**e, "id": f"{e['id']}@{p[1]}", "rows": {p[1]}, "replaces": True} for g, p, e in found[:top]}


def retimed(c: dict, run: dict, d: float) -> dict:
    x = np.nan_to_num(np.asarray(run["levels"][c["source"]], dtype=float))
    return {**c, "id": f"{c['source']}~{d:.4g}@{next(iter(c['rows']))}", "delay": d, "series": delayed(x, d)}


def moved_in(flows: list[dict], inferred: dict, share: float) -> bool:
    """Every unmeasured stock is fed mostly by a move out of its source (things leave A and arrive in
    H), not by a link (arrivals that nothing loses): at least `share` of what feeds it."""
    for h in inferred:
        move = sum(f["rate"]["k"] for f in flows if f.get("to") == h and f.get("from"))
        link = sum(f["rate"]["terms"][0]["k"] for f in flows if f.get("to") == h and not f.get("from"))
        if move < share * (move + link):
            return False
    return True


def moved_error(flows: list[dict], stocks: list[dict], run: dict, inferred: dict, horizons=(5, 20, 100), starts: int = 80) -> float:
    """Like the judge, but each stock's error relative to how far that stock moved over the horizon
    (the judge's scale, each stock's spread, all but ignores a stock that only accumulates)."""
    ids = [s["id"] for s in stocks]
    S = len(ids)
    A = levels_array({**run["levels"], **inferred}, ids + list(inferred))
    tt = np.asarray(run["t"], dtype=float)
    out = []
    for h in [h for h in horizons if h < len(run["t"]) / 4]:
        s0 = starts_for(A.shape[1], h, starts)
        end = Model(flows, ids + list(inferred)).run(A[:, s0 - 1], tt[s0[None, :] + np.arange(h)[:, None]])[:S]
        obs = A[:S, s0 + h - 1]
        err = ((end - obs) ** 2).sum(axis=1)
        moved = ((obs - A[:S, s0 - 1]) ** 2).sum(axis=1)
        ok = moved > 0
        e = err[ok] / moved[ok]
        out.append(float(np.where(np.isfinite(e), e, 1e6).mean()) if ok.any() else 0.0)
    return sum(out) / len(out) if out else float("inf")


def flattened(flows: list[dict], into: set) -> list[dict]:
    """The flows with the outside inflow into the stocks `into` held at its mean (no pieces)."""
    return [{k: v for k, v in f.items() if k != "inflow"} if f.get("inflow") and f.get("to") in into else f for f in flows]


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    has_eras = len({e.get("label") or e.get("start") for e in opts.get("eras") or [] if e}) >= 2
    delays = opts.pop("delays", DELAYS)
    min_move = opts.pop("hidden_min_move", 0.5)
    margin = opts.pop("hidden_margin", 0.02)
    slack = opts.pop("hidden_slack", 0.15)
    steady_slack = opts.pop("hidden_steady_slack", 0.0)
    steady_rows = opts.pop("hidden_steady_rows", True)
    refine = opts.pop("hidden_refine", (1.4, 1 / 1.4))
    rule = opts.pop("hidden_rule", "structural")
    propose = opts.pop("hidden_propose", "both")
    steady = opts.pop("hidden_steady", "both")
    scale = opts.pop("hidden_scale", "moved")
    tried, cands = [], []

    def attempt(v, extra, name):
        # a "steady" receiving stock keeps its outside inflow (if any) constant, rather than taking
        # the hidden stock's noise as changes, and its row starts from the copy and its own level
        # (arrivals and drain explain the row together, neither alone)
        into = {next(iter(x["rows"])) for x in extra if x.get("steady")}
        start = {}
        for x in extra:
            if x.get("steady"):
                b = next(iter(x["rows"]))
                start.setdefault(b, [b]).append(x["id"])
        r = identify_one(stocks, run, {**opts, **v, "extra": extra, "steady": into, "start_with": start})
        inf = inferred_levels(r["flows"], extra)
        es = judge_each(r["flows"], stocks, run, inf) if moved_in(r["flows"], inf, min_move) else [float("inf")]
        e = sum(es) / len(es)
        tried.append({"name": name, "error": e})
        return {"e": e, "es": es, "r": r, "name": name, "inf": inf}

    def structural(res, into):
        # how well the model explains the receiving stocks without their outside inflow's pieces
        # (pieces fitted to the data explain any arrivals in the data, so they would always win)
        if res["e"] == float("inf"):
            return float("inf")
        return error(flattened(res["r"]["flows"], into), res["inf"])

    def error(flows, inf):
        if scale == "moved":
            return moved_error(flows, stocks, run, inf)
        es = judge_each(flows, stocks, run, inf)
        return sum(es) / len(es)

    def ratio(res, cur, extra):
        """How much better res is than cur (below 1 = better), or None when it is not acceptable."""
        if rule == "data":
            return res["e"] / cur["e"] if res["e"] < cur["e"] * (1 - margin) else None
        into = {next(iter(x["rows"])) for x in extra}
        q = structural(res, into) / max(1e-12, structural(cur, into))
        worse = error(res["r"]["flows"], res["inf"]) / max(1e-12, error(cur["r"]["flows"], cur["inf"])) if scale == "moved" else res["e"] / cur["e"]
        allowed = steady_slack if any(x.get("steady") for x in extra) else slack
        if steady_rows and not all(row_pays(res, cur, next(iter(x["rows"]))) for x in extra if x.get("steady")):
            return None
        return q if q < 1 - margin and worse < 1 + allowed else None

    def row_pays(res, cur, b):
        # a steady receiving row (the copy, no pieces) must fit its stock's changes better than the
        # row it replaces, each change in that row's outside inflow priced as two numbers (its
        # value and its place), by BIC
        T = len(run["t"]) - 1
        rb = next(x for x in res["r"]["matrix"] if x["id"] == b)
        ra = next(x for x in cur["r"]["matrix"] if x["id"] == b)
        pieces = len(ra["cuts"]) - 1 if ra.get("cuts") else 0
        bic = lambda rss, p: T * np.log(max(rss, 1e-12) / T) + p * np.log(T)  # noqa: E731
        return bic(rb["rss"], rb["p"]) < bic(ra["rss"], ra["p"] + max(0, pieces - 1))

    def label(name, extra):
        return f"{name}, hidden " + ", ".join(f"{x['source']}->{x['delay']:.3g}->{next(iter(x['rows']))}{' (steady)' if x.get('steady') else ''}" for x in extra)

    for v in opts.pop("variants", None) or VARIANTS:
        if v.get("split_eras") and not has_eras:
            continue
        cands.append((attempt(v, [], v["name"]), v))
    cands.sort(key=lambda c: c[0]["e"])
    cur, v = cands[0]
    every = copies(stocks, run, delays)
    pairs = {}
    if every and propose in ("stepwise", "both"):
        pairs.update(chosen_copies(identify_one(stocks, run, {**opts, **v, "extra": every}), every))
    if every and propose in ("screen", "both"):
        pairs.update({p: c for p, c in screened_copies(stocks, run, cur["r"], every).items() if p not in pairs})
    kept = []
    while pairs:
        trials = []
        for p, c0 in pairs.items():
            for st in (False, True) if steady == "both" else (bool(steady),):
                c = {**c0, "steady": st}
                res = attempt(v, kept + [c], label(cands[0][0]["name"], kept + [c]))
                q = ratio(res, cur, kept + [c])
                if q is not None:
                    trials.append((q, res, p, c))
        if not trials:
            break
        q, res, p, c = min(trials, key=lambda x: x[0])
        # the delay between the grid's values: a little faster or slower, while that helps
        for f in refine:
            while 0.005 < c["delay"] * f < 0.95:
                c2 = retimed(c, run, c["delay"] * f)
                res2 = attempt(v, kept + [c2], label(cands[0][0]["name"], kept + [c2]))
                q2 = ratio(res2, cur, kept + [c2])
                if q2 is None or not q2 < q:
                    break
                q, res, c = q2, res2, c2
        kept.append(c)
        pairs.pop(p)
        cur = res
    r = cur["r"]
    r["chosen"], r["tried"] = cur["name"], tried
    if cur["inf"]:
        r["inferred_levels"] = cur["inf"]
    return r

