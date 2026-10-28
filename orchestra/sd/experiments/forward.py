"""The forward run: the base model and the experiment from the measured levels now, ``horizon_s``
ahead, with a band, the limits they hit, and where not to trust them (goal G5;
docs/proposals/control-theory.md §7). It took the place of the scale-and-add "what if" on
2026-10-27, and keeps its band and its trust flags.

**The runs.** Both start from each stock's measured level now (a hidden stock from its initial
level; the scenario's ``levels`` override the experiment's) and run the engine (``engine``) for
``horizon_s``. The base reads its measured inputs held at their last value; the experiment reads
its scenario (``scenario``). A flow written ``observed()`` (one with no equation) is held at its
measured mean over the last ten minutes, in both.

**The band.** ``members`` runs of each, with every flow's rate multiplied by ``exp(z · rel)``: z
standard normal per member and flow (by id, so the base and the experiment share it, and the band
of their difference is the difference's), ``rel`` the flow's relative error as its fit records it
in each model (``sd.trust.spread``; an equation an experiment wrote is declared, so ±50% until it
is fitted).
Each trajectory is the central run (the numbers as written) and the 10th and 90th percentiles of
the members. Measured levels are taken as exact. The members carry the parameters' uncertainty
only, which for a model whose structure is wrong is far too narrow (the metrics lab found the truth
inside it a quarter of the time where it claims 80%). So each stock's band (the base's and the
experiment's; not their difference, whose structural error mostly cancels) is widened, in
quadrature, by ``z × growth × h`` at horizon ``h``: how far the model's runs from part-way
through its own window missed the measured level (``sd.experiments.heldout``), as discovery saved
it in the stock's trust (``trust["behaviour"]``), or measured on the history for a model saved
without it. A level never below zero gets no band below zero. "Not trusted" is still reported
beside it: a missing flow is not in any replay.

**Limits.** Where a stock reaches 0 (its outflows are then cut to what it holds) or leaves the
``bounds`` given, in the central run and in what share of the members; ``new`` when the base does
not hit it.

**Not trusted** (``sd.trust``): a flow declared, carried from the prior, a net flow, replayed, or
fitted on too little (``weak_flow``), when it is changed or touches a stock asked about; a stock
that is hidden, has no measured level now, that the base's own replay since the era began misses
by more than its own spread (``era_errors``), whose run leaves the range observed by half its
width, or one of whose changed flows runs outside 1/1.5–1.5× the rates seen.

Nothing here changes the model, saves a version or writes a metric."""

from __future__ import annotations

import math

import numpy as np

from ..model import Model
from ..trust import era_errors, spread, weak_flow
from . import engine
from .heldout import measure, widen
from .history import hidden, holds, initial, levels_at, step_for, unit_s
from .scenario import inputs as scenario_inputs

MEMBERS = 24
POINTS = 61
QUANTILES = (0.1, 0.9)
OUTSIDE = 0.5              # a run leaves the observed range by this share of its width (at least one unit)
RATE_OUTSIDE = 1.5         # a rate beyond this many times the highest seen (or under the lowest over it)
MINOR = 0.1                # a flow weak only for its few events, carrying under this share of its stock's busiest flow


def keep_index(steps: int, points: int) -> list[int]:
    return sorted({round(i * steps / max(1, points - 1)) for i in range(points)}) if points and steps + 1 > points else list(range(steps + 1))


def band(X, keep: list[int]) -> dict:
    """Central (the first row), and the members' 10th and 90th percentiles, at ``keep``."""
    central = X[0]
    lo, hi = (np.quantile(X[1:], q, axis=0) if len(X) > 1 else central for q in QUANTILES)
    r = lambda xs: [round(float(xs[i]), 4) for i in keep]
    return {"central": r(central), "lo": r(lo), "hi": r(hi)}


def draws(flow_ids: list[str], members: int, seed: int) -> dict[str, np.ndarray]:
    """Each flow's z per member, by id, so the base and the experiment share them."""
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((max(0, members), len(flow_ids)))
    return {fid: z[:, j] for j, fid in enumerate(flow_ids)}


def factors(z: dict[str, np.ndarray], rel: dict[str, float]) -> dict[str, np.ndarray]:
    """Each flow's factor per column: 1 in the first (the central run), ``exp(z · rel)`` after."""
    return {fid: np.concatenate([[1.0], np.exp(z[fid] * r)]) for fid, r in rel.items()}


def era_error(model: Model, history: dict, now: float) -> dict[str, float]:
    """Each measured stock's error in the model's own replay since the era began (``sd.trust``)."""
    from .replay import central

    start = max(float(history.get("start") if history.get("start") is not None else now), float((model.discovery or {}).get("fit_start") or 0.0))
    if now <= start or not history.get("stocks"):
        return {}
    r = central(model, history, start, now, step_s=15.0)
    return era_errors(model, history, {sid: [[float(t), float(v)] for t, v in zip(r.t, r.levels[0, k])] for k, sid in enumerate(r.stocks)})


def behaviour_of(model: Model, history: dict, now: float) -> dict[str, dict]:
    """Each stock's held-out replay record: as discovery saved it in its trust, or, for a measured
    stock without one (a model saved before it was measured), measured on this history over the
    window the model was discovered on (never after it: what happened since is what a forward run
    is judged by, ``sd.diverge``, and must not widen its own band)."""
    out = {s.id: dict(b) for s in model.stocks if isinstance(b := ((s.evidence or {}).get("trust") or {}).get("behaviour"), dict)}
    measured = history.get("stocks") or {}
    disc = model.discovery or {}
    if disc.get("end") is not None and any(s.id not in out and measured.get(s.id) for s in model.stocks):
        start = max(float(history.get("start") if history.get("start") is not None else now), float(disc.get("fit_start") or 0.0))
        try:
            got = measure(model, history, start, min(now, float(disc["end"])), float(history.get("stock_step") or 60.0))
        except (ValueError, ArithmeticError):
            got = {}
        out.update({sid: {**r, "from": "history"} for sid, r in got.items() if sid not in out})
    return out


def forward(base: Model, draft: Model, history: dict, scenario: dict | None = None, *, horizon_s: float = 3600.0,
            step_s: float | None = None, members: int = MEMBERS, seed: int = 0, bounds: dict | None = None,
            now: float | None = None, points: int = POINTS, stocks: list[str] | None = None, changed: list[str] | None = None) -> dict:
    """Both runs over ``horizon_s`` from ``now`` (default: the history's ``at``), for ``stocks``
    (default: all), with their band, limits and what is not trusted; ``changed``: the flows the
    experiment changed or added (default: from ``views.diff``), whose rates are reported and judged."""
    if changed is None:
        from .views import diff
        d = diff(base, draft, scenario)
        changed = [r["id"] for r in d["flows"]["changed"] + d["flows"]["added"]]
    if not (horizon_s > 0) or horizon_s > 366 * 86400:
        raise ValueError("the horizon must be above 0 and at most a year")
    now = float(history.get("at") if now is None else now)
    step_s = step_for(horizon_s, step_s)
    steps = max(1, math.ceil(horizon_s / step_s))
    unit = unit_s(base)
    scen = scenario or {}
    ids_b, ids_d = [s.id for s in base.stocks], [s.id for s in draft.stocks]
    every = list(dict.fromkeys([*ids_b, *ids_d]))
    want = list(stocks or every)
    if unknown := [s for s in want if s not in every]:
        raise ValueError(f"no stock {', '.join(unknown)} in the base or the experiment; its stocks: {', '.join(every)}")
    flows_b = engine.compiled(base)
    flows_d = engine.compiled(draft, list(scen.get("inputs") or {}))
    fids = list(dict.fromkeys([f.id for f in flows_b] + [f.id for f in flows_d]))
    observed = holds(history, [f.id for f in flows_b + flows_d if f.observed], now)
    recent = {fid: [v for t, v in (history.get("flows") or {}).get(fid) or [] if now - 600 <= t <= now] for fid in fids}
    by_id = {f.id: f for f in draft.flows} | {f.id: f for f in base.flows}
    obs_ids = {f.id for f in flows_b + flows_d if f.observed}
    spreads_b = {f.id: spread(f, recent[f.id] if f.id in obs_ids else None) for f in base.flows}
    spreads = {f.id: spread(f, recent[f.id] if f.id in obs_ids else None) for f in draft.flows}
    z = draws(fids, members, seed)
    k_b = factors(z, {fid: s[0] for fid, s in spreads_b.items()})
    k_d = factors(z, {fid: s[0] for fid, s in spreads.items()})
    M = max(0, members) + 1
    lv_b, missing = levels_at(base, history, now)
    lv_d, _ = levels_at(draft, history, now, scen.get("levels"))
    in_b = scenario_inputs(history, now, None, horizon_s, step_s)
    in_d = scenario_inputs(history, now, scen, horizon_s, step_s)
    common = {"t0": now, "steps": steps, "step_s": step_s, "unit_s": unit, "columns": M}
    A = engine.run(base, levels=lv_b, inputs=in_b, observed=observed, factors=k_b, flows=flows_b, **common)
    B = engine.run(draft, levels=lv_d, inputs=in_d, observed=observed, factors=k_d, flows=flows_d, **common)
    offsets = [round(i * step_s, 3) for i in range(steps + 1)]
    keep = keep_index(steps, points)

    # what is not trusted
    replayed = sorted(obs_ids)
    weak = {}
    for fid in fids:
        f = next((x for x in draft.flows if x.id == fid), None) or by_id[fid]
        if why := weak_flow(f, fid in obs_ids):
            weak[fid] = why
    events = {fid: ((by_id[fid].current().quality.get("events") or 0.0) if by_id[fid].current() else 0.0) for fid in fids}
    all_flows = [*base.flows, *(f for f in draft.flows if f.id not in {x.id for x in base.flows})]

    def minor(fid, sid: str) -> bool:
        busiest = max(events[x.id] for x in all_flows if sid in (x.src, x.dst))
        return all(w.startswith("fitted on ") for w in weak[fid]) and events[fid] < MINOR * busiest

    era = era_error(base, history, now)
    measured = history.get("stocks") or {}
    stock_why: dict[str, list[str]] = {}
    for sid in every:
        st = next((s for s in draft.stocks if s.id == sid), None) or next(s for s in base.stocks if s.id == sid)
        why = []
        if hidden(st):
            why.append(f"hidden: no series measures it; it starts at {initial(st):g}")
        elif sid in missing or not measured.get(sid):
            why.append("no measured level now; it starts at 0")
        if era.get(sid, 0.0) > 1.0:
            why.append(f"the model's own run since the era began misses its measured level by {era[sid]:.1f}× the level's spread")
        why += [f"flow {f.id}: {'; '.join(weak[f.id])}" for f in all_flows if f.id in weak and sid in (f.src, f.dst) and not minor(f.id, sid)]
        seen = [v for _, v in measured.get(sid) or []]
        if seen and sid in ids_d:
            lo, hi = min(seen), max(seen)
            room = OUTSIDE * max(hi - lo, 1.0)
            run = B.levels[0, ids_d.index(sid)]
            t = next((o for o, x in zip(offsets, run) if x < lo - room or x > hi + room), None)
            if t is not None:
                why.append(f"extrapolation: leaves the observed range {lo:g}–{hi:g} at +{t:g} s")
        stock_why[sid] = why

    # limits: the floor at 0, and the caller's bounds
    limits = []
    for name, R, ids in (("base", A, ids_b), ("experiment", B, ids_d)):
        for kk, sid in enumerate(ids):
            lo, hi = (bounds or {}).get(sid, (None, None))
            X = R.levels[:, kk]
            tests = [("floor", lambda x: x <= 1e-9, X[0, 0] > 1e-9)]
            if lo is not None:
                tests.append(("below bound", lambda x, lo=lo: x < lo, True))
            if hi is not None:
                tests.append(("above bound", lambda x, hi=hi: x > hi, True))
            for kind, hit, applies in tests:
                if not applies:
                    continue
                hits = hit(X)
                t = offsets[int(np.argmax(hits[0]))] if hits[0].any() else None
                share = float(hits[1:].any(axis=1).mean()) if len(X) > 1 else float(t is not None)
                if t is not None or share > 0:
                    limits.append({"stock": sid, "run": name, "kind": kind, "at_s": t, "members": round(share, 3),
                                   **({"bound": lo if kind == "below bound" else hi} if kind != "floor" else {})})
    in_base = {(x["stock"], x["kind"]) for x in limits if x["run"] == "base" and x["at_s"] is not None}
    for x in limits:
        if x["run"] == "experiment":
            x["new"] = x["at_s"] is not None and (x["stock"], x["kind"]) not in in_base

    # the changed flows' rates now, against what was seen
    touched = [f for f in (changed or []) if f in fids]
    rates_now = {}
    for fid in touched:
        seen = [v for _, v in (history.get("flows") or {}).get(fid) or []]
        r0 = float(A.rates[0, A.flows.index(fid), 0]) if fid in A.flows else None
        r1 = float(B.rates[0, B.flows.index(fid), 0]) if fid in B.flows else None
        rates_now[fid] = {"base": None if r0 is None else round(r0, 6), "experiment": None if r1 is None else round(r1, 6),
                          "observed": [min(seen), max(seen)] if seen else None}
        if seen and r1 is not None and (r1 > RATE_OUTSIDE * max(seen) + 1e-9 or r1 < min(seen) / RATE_OUTSIDE - 1e-9):
            note = f"extrapolation: flow {fid} at {r1:.4g} per {base.time_unit}, outside the {min(seen):.4g}–{max(seen):.4g} seen"
            f = by_id[fid]
            for end in (f.src, f.dst):
                if end in stock_why:
                    stock_why[end].append(note)

    # the structure's uncertainty: each stock's held-out replay error (sd.experiments.heldout), saved
    # at discovery or measured on this history; the difference's band is left alone (base and
    # experiment share the structure, and its error mostly cancels)
    beh = behaviour_of(base, history, now)
    t_keep = [offsets[i] for i in keep]

    def widened(b: dict, sid: str, start: float | None) -> dict:
        floor = start is not None and start >= 0 and all(v >= 0 for _, v in measured.get(sid) or [])
        return widen(b, beh.get(sid), t_keep, unit, floor)

    def stock_row(sid: str) -> dict:
        st = next((s for s in draft.stocks if s.id == sid), None) or next(s for s in base.stocks if s.id == sid)
        row = {"name": st.name, "unit": st.unit, "start": {"base": lv_b.get(sid), "experiment": lv_d.get(sid)},
               "base": widened(band(A.levels[:, ids_b.index(sid)], keep), sid, lv_b.get(sid)) if sid in ids_b else None,
               "experiment": widened(band(B.levels[:, ids_d.index(sid)], keep), sid, lv_d.get(sid)) if sid in ids_d else None,
               "difference": band(B.levels[:, ids_d.index(sid)] - A.levels[:, ids_b.index(sid)], keep) if sid in ids_b and sid in ids_d else None,
               "trusted": not stock_why[sid], "why": stock_why[sid]}
        if rec := beh.get(sid):
            row["behaviour"] = {k: rec[k] for k in ("score", "level", "error", "hold_error", "beats_hold") if k in rec}
        return row

    rkeep = [min(i, steps - 1) for i in keep]
    flows_out = {fid: {"base": band(A.rates[:, A.flows.index(fid)], rkeep) if fid in A.flows else None,
                       "experiment": band(B.rates[:, B.flows.index(fid)], rkeep) if fid in B.flows else None}
                 for fid in fids}
    near = {fid for fid in fids if fid in touched or {by_id[fid].src, by_id[fid].dst} & set(want)}
    not_trusted = [{"kind": "flow", "id": fid, "why": why} for fid, why in weak.items() if fid in near]
    not_trusted += [{"kind": "stock", "id": sid, "why": stock_why[sid]} for sid in want if stock_why[sid]]
    return {"mode": "forward", "time_unit": base.time_unit, "now": now, "horizon_s": steps * step_s, "step_s": step_s,
            "t": [offsets[i] for i in keep], "stocks": {sid: stock_row(sid) for sid in want}, "flows": flows_out,
            "rates_now": rates_now, "changed": touched, "limits": [x for x in limits if x["stock"] in want or x.get("new")],
            "replayed": replayed, "not_trusted": not_trusted, "trusted": not any(stock_why[s] for s in want),
            "nonfinite": {"base": A.nonfinite, "experiment": B.nonfinite},
            "band": {"members": max(0, members), "quantiles": list(QUANTILES), "seed": seed,
                     "spread": {fid: {"rel": round(r, 4), "how": how, **({"base": {"rel": round(spreads_b[fid][0], 4), "how": spreads_b[fid][1]}}
                                                                          if fid in spreads_b and spreads_b[fid] != (r, how) else {})}
                                for fid, (r, how) in spreads.items()},
                     "structural": {sid: {"growth": round(r["growth"], 6), "z": r["z"], "from": r.get("from", "discovery")}
                                    for sid, r in beh.items() if sid in want},
                     "how": "each flow's rate times exp(z·rel), z standard normal per member and flow, shared by the base and the "
                            "experiment; rel is the relative error its fit records (sd.trust), the experiment's (and the base's where it "
                            "differs) given; levels now are taken as exact. Each stock's band is then widened, in quadrature, by "
                            "z × growth × the horizon: how far its held-out replays missed (sd.experiments.heldout, 'structural')"}}


def trajectories(result: dict) -> dict:
    """A prediction's ``trajectories`` (``sd.predictions``) from a forward run: the experiment's
    stocks from the time the change is made."""
    return {"t": list(result["t"]), "stocks": {sid: dict(s["experiment"]) for sid, s in result["stocks"].items() if s.get("experiment")}}
