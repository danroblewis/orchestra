"""What if: the model's prediction of a change, against no change, with a band, and where not to
trust it (goal G5: docs/roadmap/goals.md; docs/proposals/control-theory.md §7).

Given the model and its recent history (the web server's ``history``: measured levels, flow rates
and inputs), ``what_if`` runs the model forward from the measured levels now, ``horizon_s`` ahead,
twice: as it is (the **baseline**) and with the **interventions** applied from now. Each run is
stepped by SD Lab's simulator exactly as ``sd.simulate``'s projection is (the same flows, replays
and inputs held at their last value), so with no intervention the central baseline is that
projection.

Interventions (``kind`` and its fields):

- ``scale_flow`` (``flow``, ``factor``): the flow's rate times ``factor``;
- ``add_flow`` (``flow``, ``amount``): ``amount`` per time unit added to the flow's rate (a
  negative amount only on a constant, proportional or linear rate, which stays at least 0);
- ``set_stock`` (``stock``, ``level``): the stock's level now;
- ``set_input`` / ``scale_input`` (``input``, ``value`` / ``factor``): a measured input held at
  ``value`` (or its last value times ``factor``) from now;
- ``set_param`` (``flow``, ``param``, ``value``): one number of the flow's rate (per time unit, by
  its name in SD Lab's rate: ``value`` of a constant, ``k``, ``c``, ``k1``…, ``goal``, ``time``).

**The band.** ``members`` runs of each, with every flow's rate multiplied by ``exp(z · rel)``, z
standard normal and ``rel`` the flow's relative error as its fit records it (``sd.trust.spread``),
drawn once per member and shared by the baseline and the intervention, so the band of their
difference is the difference's. Each trajectory reports the central run (the fitted numbers) and
the 10th and 90th percentiles of the members. Measured levels are taken as exact; hidden stocks
start at 0. The band is the parameters' uncertainty only, not the structure's: a missing flow
widens no band, which is why "not trusted" (``sd.trust``) is reported beside it.

**Limits.** Where a stock reaches 0 (the floor: its outflows are then cut to what it holds) or
leaves ``bounds`` the caller gives, in the central run and in what share of the members; and where
a run leaves what was observed (``extrapolation``).

Nothing here changes the model, saves a version or writes a metric: it is a reading of the model,
like the Dynamics page's projection."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .discover import UNITS
from .model import Model
from .rates import numbers, scale, times
from .simulate import HOLD_S, _at, _rate, simulate
from .trust import era_errors, spread, weak_flow

MEMBERS = 24
STEPS_MAX = 480
POINTS = 61
QUANTILES = (0.1, 0.9)
OUTSIDE = 0.5              # a run leaves the observed range by this share of its width (at least one unit)
RATE_OUTSIDE = 1.5
MINOR = 0.1                # a flow weak only for its few events, carrying under this share of its stock's busiest flow         # a rate beyond this many times the highest seen (or under the lowest over it)

FIELDS = {"scale_flow": ("flow", "factor"), "add_flow": ("flow", "amount"), "set_stock": ("stock", "level"),
          "set_input": ("input", "value"), "scale_input": ("input", "factor"), "set_param": ("flow", "param", "value")}


@dataclass
class _Flow:
    id: str
    src: str | None
    dst: str | None
    rate: dict | None          # per time unit; None: replayed
    hold: float = 0.0          # replayed: its rate (per time unit) from now
    extra: float = 0.0         # added by add_flow (per time unit)


def check(model: Model, history: dict, interventions: list[dict]) -> list[dict]:
    """The interventions, checked against the model: each has a known kind and names something the
    model has. Raises ValueError saying what is wrong."""
    stocks, flows = {s.id for s in model.stocks}, {f.id for f in model.flows}
    inputs = set(history.get("inputs") or {}) | set((model.discovery or {}).get("inputs") or {})
    out = []
    for iv in interventions:
        kind = iv.get("kind")
        if kind not in FIELDS:
            raise ValueError(f"unknown intervention {kind!r}: one of {', '.join(FIELDS)}")
        missing = [k for k in FIELDS[kind] if iv.get(k) is None]
        if missing:
            raise ValueError(f"{kind} needs {', '.join(missing)}")
        target, known = FIELDS[kind][0], {"flow": flows, "stock": stocks, "input": inputs}[FIELDS[kind][0]]
        if iv[target] not in known:
            raise ValueError(f"no {target} {iv[target]!r} in the model; its {target}s: {', '.join(sorted(known)) or 'none'}")
        num = FIELDS[kind][-1]
        try:
            v = float(iv[num])
        except (TypeError, ValueError):
            raise ValueError(f"{kind}: {num} must be a number") from None
        if not math.isfinite(v) or (num == "factor" and v < 0):
            raise ValueError(f"{kind}: {num} must be finite{' and at least 0' if num == 'factor' else ''}")
        out.append({**{k: iv[k] for k in FIELDS[kind]}, "kind": kind, num: v})
    return out


def _set_param(rate: dict, param: str, value: float, fid: str) -> dict:
    r = dict(rate)
    have = numbers(r)
    if param == "c" and r.get("form") == "constant":
        param = "value"
    if param not in have or param.startswith("p"):
        raise ValueError(f"flow {fid}: no parameter {param!r}; its parameters: {', '.join(sorted(have)) or 'none'}")
    if param in r:
        r[param] = value
    else:                                               # k1, k2…: a linear rate's terms
        i = int(param[1:]) - 1
        r["terms"] = [dict(t) for t in r["terms"]]
        r["terms"][i]["k"] = value
    return r


def _plus(rate: dict, amount: float, fid: str) -> dict:
    """A rate with ``amount`` (negative) added, as a linear rate."""
    form = rate.get("form")
    if rate.get("effects") or form not in ("constant", "proportional", "linear"):
        raise ValueError(f"flow {fid}: a negative amount can be added only to a constant, proportional or linear rate, not {form}")
    if form == "constant":
        return {"form": "linear", "c": float(rate.get("value") or 0.0) + amount, "terms": []}
    if form == "proportional":
        return {"form": "linear", "c": amount, "terms": [{"stock": rate.get("stock"), "k": float(rate.get("k") or 0.0)}]}
    return {**rate, "c": float(rate.get("c") or 0.0) + amount}


def _flows(model: Model, history: dict, now: float) -> tuple[list[_Flow], dict[str, list[float]]]:
    """The model's flows as the simulator steps them (``sd.simulate``), and the recent rates of the
    replayed ones."""
    out, recent = [], {}
    for f in model.flows:
        rate = _rate(f.current(), f.src)
        if rate is not None:
            out.append(_Flow(f.id, f.src, f.dst, rate))
            continue
        recent[f.id] = [v for t, v in (history.get("flows") or {}).get(f.id) or [] if t >= now - HOLD_S]
        hold = sum(recent[f.id]) / len(recent[f.id]) if recent[f.id] else 0.0
        out.append(_Flow(f.id, f.src, f.dst, None, hold))
    return out, recent


def _intervene(flows: list[_Flow], ivs: list[dict]) -> list[_Flow]:
    out = []
    for fl in flows:
        fl = _Flow(fl.id, fl.src, fl.dst, dict(fl.rate) if fl.rate else None, fl.hold)
        for iv in ivs:
            if iv.get("flow") != fl.id:
                continue
            if iv["kind"] == "scale_flow":
                if fl.rate is None:
                    fl.hold *= iv["factor"]
                elif iv["factor"] == 0:
                    fl.rate = {"form": "constant", "value": 0.0}
                elif (r := times(fl.rate, iv["factor"])) is None:
                    raise ValueError(f"flow {fl.id}: its {fl.rate.get('form')} rate cannot be scaled")
                else:
                    fl.rate = r
            elif iv["kind"] == "add_flow":
                fl.extra += iv["amount"]
            elif iv["kind"] == "set_param":
                if fl.rate is None:
                    raise ValueError(f"flow {fl.id} is replayed: it has no parameters to set")
                fl.rate = _set_param(fl.rate, str(iv["param"]), iv["value"], fl.id)
        if fl.extra < 0:
            if fl.rate is None:
                fl.hold, fl.extra = max(0.0, fl.hold + fl.extra), 0.0
            else:
                fl.rate, fl.extra = _plus(fl.rate, fl.extra, fl.id), 0.0
        out.append(fl)
    return out


def _stepped(flows: list[_Flow], g: float) -> tuple[list[dict], list[int | None]]:
    """The simulator's flows, per step of ``g`` time units (a replayed flow held at its rate, as
    ``sd.simulate`` holds it from now), and which of ``flows`` each is (None: what add_flow adds,
    which moves along its flow and is not uncertain)."""
    out, of = [], []
    for j, fl in enumerate(flows):
        r = scale(fl.rate, g) if fl.rate is not None else {"form": "constant", "value": fl.hold * g}
        out.append({"id": fl.id, "from": fl.src, "to": fl.dst, "rate": r, **({"effects": r["effects"]} if r.get("effects") else {})})
        of.append(j)
        if fl.extra > 0:
            out.append({"id": f"{fl.id}+", "from": fl.src, "to": fl.dst, "rate": {"form": "constant", "value": fl.extra * g}})
            of.append(None)
    return out, of


class _Times:
    """A compiled rate times one factor per state: every member of the band is one state of one
    run. The same as the rate with its numbers scaled (``rates.times``), since each form is floored
    at 0 and the factors are above 0."""

    def __init__(self, rate, k):
        self.rate, self.k = rate, k

    def __call__(self, L, seg):
        return self.rate(L, seg) * self.k


def _inputs(history: dict, now: float, ivs: list[dict]) -> dict | None:
    """The measured inputs up to now, as the simulator reads them, each held from now at its last
    value or at what an intervention sets."""
    series = {k: [p for p in pts if p[0] <= now] for k, pts in (history.get("inputs") or {}).items()}
    for iv in ivs:
        if iv["kind"] in ("set_input", "scale_input"):
            last = _at(series.get(iv["input"]) or [], now) or 0.0
            v = iv["value"] if iv["kind"] == "set_input" else last * iv["factor"]
            series[iv["input"]] = [*series.get(iv["input"], []), [now, v]]
    if not series:
        return None
    ts = sorted({t for pts in series.values() for t, _ in pts}) or [now]
    return {"t": ts, "values": {k: [_at(pts, t) or 0.0 for t in ts] for k, pts in series.items()}}


def _run(flows: list[_Flow], factors, g: float, ids: list[str], inputs: dict | None, levels: list[float], now: float,
         steps: int, step_s: float):
    """Levels (members x stocks x steps + 1), every member at once: ``factors`` is members x flows."""
    import numpy as np

    from ..sdlab.discovery.simulate import Model as Stepper

    stepped, of = _stepped(flows, g)
    stepper = Stepper(stepped, ids, inputs=inputs)
    M = factors.shape[0]
    # the vendored simulator's compiled flows: (src, dst, ratio, segments, rate, values); none here has values
    stepper.parts = [(src, dst, ratio, segs, rate if j is None else _Times(rate, factors[:, j]), vals)
                     for (src, dst, ratio, segs, rate, vals), j in zip(stepper.parts, of)]
    L = np.repeat(np.array([[v] for v in levels], dtype=float), M, axis=1)
    out = np.empty((M, len(ids), steps + 1))
    out[:, :, 0] = L.T
    for i in range(steps):
        L = stepper.step(L, np.full(M, now + i * step_s))
        out[:, :, i + 1] = L.T
    return out


def _rate_now(fl: _Flow, ids: list[str], inputs: dict | None, levels: list[float], now: float) -> float:
    """A flow's rate (per time unit) at the levels now, before any stock limits it."""
    if fl.rate is None:
        return fl.hold + fl.extra
    import numpy as np

    from ..sdlab.discovery.simulate import Model as Stepper

    probe = "\0rate"
    r = {**fl.rate}
    flows = [{"id": fl.id, "from": None, "to": probe, "rate": r, **({"effects": r["effects"]} if r.get("effects") else {})}]
    d = Stepper(flows, [*ids, probe], inputs=inputs).change(np.array([[v] for v in [*levels, 0.0]], dtype=float), np.array([now]))
    return float(d[-1, 0]) + fl.extra


def _first(ts: list[float], xs, hit) -> float | None:
    return next((t for t, x in zip(ts, xs) if hit(x)), None)


def what_if(model: Model, history: dict, interventions: list[dict], *, stocks: list[str] | None = None,
            horizon_s: float = 3600.0, step_s: float | None = None, members: int = MEMBERS, seed: int = 0,
            bounds: dict[str, tuple[float | None, float | None]] | None = None, now: float | None = None,
            points: int = POINTS, label: dict | None = None) -> dict:
    """The baseline and the intervention over ``horizon_s`` from ``now`` (default: the history's
    ``at``), for ``stocks`` (default: all), with their band, their limits and what is not trusted.
    ``step_s`` defaults to 15 s, longer when the horizon would need more than STEPS_MAX steps."""
    import numpy as np

    ivs = check(model, history, interventions)
    ids = [s.id for s in model.stocks]
    want = list(stocks or ids)
    if unknown := [s for s in want if s not in ids]:
        raise ValueError(f"no stock {', '.join(unknown)} in the model; its stocks: {', '.join(ids)}")
    if horizon_s <= 0:
        raise ValueError("the horizon must be above 0")
    now = float(history.get("at") if now is None else now)
    step_s = float(step_s or max(15.0, horizon_s / STEPS_MAX))
    steps = max(1, math.ceil(horizon_s / step_s))
    g = step_s / UNITS[model.time_unit]
    measured = history.get("stocks") or {}
    base_levels = [_at(measured.get(i) or [], now) or 0.0 for i in ids]
    set_to = {iv["stock"]: iv["level"] for iv in ivs if iv["kind"] == "set_stock"}
    iv_levels = [set_to.get(i, v) for i, v in zip(ids, base_levels)]
    base_flows, recent = _flows(model, history, now)
    iv_flows = _intervene(base_flows, ivs)
    base_in, iv_in = _inputs(history, now, []), _inputs(history, now, ivs)

    spreads = {f.id: spread(f, recent.get(f.id)) for f in model.flows}
    rel = np.array([spreads[f.id][0] for f in model.flows])
    rng = np.random.default_rng(seed)
    factors = np.vstack([np.ones(len(rel)), np.exp(rng.standard_normal((max(0, members), len(rel))) * rel)])   # the first: the fitted numbers
    A = {"baseline": _run(base_flows, factors, g, ids, base_in, base_levels, now, steps, step_s),
         "intervention": _run(iv_flows, factors, g, ids, iv_in, iv_levels, now, steps, step_s)}
    D = A["intervention"] - A["baseline"]
    offsets = [round(i * step_s, 3) for i in range(steps + 1)]
    keep = sorted({round(i * steps / max(1, points - 1)) for i in range(points)}) if points and steps + 1 > points else list(range(steps + 1))

    def band(X, s: int) -> dict:
        central = X[0, s]
        lo, hi = (np.quantile(X[1:, s], q, axis=0) if len(X) > 1 else central for q in QUANTILES)
        r = lambda xs: [round(float(xs[i]), 4) for i in keep]
        return {"central": r(central), "lo": r(lo), "hi": r(hi)}

    # what is not trusted
    replayed = [fl.id for fl in base_flows if fl.rate is None]
    weak = {f.id: why for f in model.flows if (why := weak_flow(f, f.id in replayed))}
    events = {f.id: (f.current().quality.get("events") or 0.0) if f.current() else 0.0 for f in model.flows}

    def minor(f, sid: str) -> bool:
        """A flow weak only for its few events, which carries under MINOR of what the stock's
        busiest flow carries: it hardly moves the stock, and does not make it untrusted."""
        busiest = max(events[x.id] for x in model.flows if sid in (x.src, x.dst))
        return all(w.startswith("fitted on ") for w in weak[f.id]) and events[f.id] < MINOR * busiest

    era = {}
    if history.get("stocks"):
        start = max(float(now if history.get("start") is None else history["start"]), float((model.discovery or {}).get("fit_start") or 0.0))
        if now > start:
            era = era_errors(model, history, simulate(model, history, now=now, start=start, horizon_s=15.0)["era"])
    observed = {i: [v for _, v in measured.get(i) or []] for i in ids}
    stock_why: dict[str, list[str]] = {}
    for k, s in enumerate(model.stocks):
        why = []
        if s.evidence.get("hidden"):
            why.append("hidden: no series measures it; it starts at 0")
        elif not measured.get(s.id):
            why.append("no measured level now; it starts at 0")
        if era.get(s.id, 0.0) > 1.0:
            why.append(f"the model's own run since the era began misses its measured level by {era[s.id]:.1f}× the level's spread")
        why += [f"flow {f.id}: {'; '.join(weak[f.id])}" for f in model.flows if f.id in weak and s.id in (f.src, f.dst) and not minor(f, s.id)]
        if observed[s.id]:
            lo, hi = min(observed[s.id]), max(observed[s.id])
            room = OUTSIDE * max(hi - lo, 1.0)
            run = A["intervention"][0, k]
            t = _first(offsets, run, lambda x, lo=lo, hi=hi, room=room: x < lo - room or x > hi + room)
            if t is not None:
                why.append(f"extrapolation: leaves the observed range {lo:g}–{hi:g} at +{t:g} s")
        stock_why[s.id] = why

    # limits: the floor at 0, and the caller's bounds
    limits = []
    for name, X in A.items():
        for k, sid in enumerate(ids):
            lo, hi = (bounds or {}).get(sid, (None, None))
            tests = [("floor", lambda x: x <= 1e-9, X[0, k, 0] > 1e-9)]
            if lo is not None:
                tests.append(("below bound", lambda x, lo=lo: x < lo, True))
            if hi is not None:
                tests.append(("above bound", lambda x, hi=hi: x > hi, True))
            for kind, hit, applies in tests:
                if not applies:
                    continue
                hits = hit(X[:, k])                                   # members x steps
                t = offsets[int(np.argmax(hits[0]))] if hits[0].any() else None
                share = float(hits[1:].any(axis=1).mean()) if len(X) > 1 else float(t is not None)
                if t is not None or share > 0:
                    limits.append({"stock": sid, "run": name, "kind": kind, "at_s": t, "members": round(share, 3),
                                   **({"bound": lo if kind == "below bound" else hi} if kind != "floor" else {})})
    in_base = {(x["stock"], x["kind"]) for x in limits if x["run"] == "baseline" and x["at_s"] is not None}
    for x in limits:
        if x["run"] == "intervention":
            x["new"] = x["at_s"] is not None and (x["stock"], x["kind"]) not in in_base

    # the rates now of the flows the interventions touch, against what was seen
    touched = list(dict.fromkeys(iv["flow"] for iv in ivs if "flow" in iv))
    rates = {}
    for fid in touched:
        b = next(fl for fl in base_flows if fl.id == fid)
        i = next(fl for fl in iv_flows if fl.id == fid)
        seen = [v for _, v in (history.get("flows") or {}).get(fid) or []]
        r0, r1 = _rate_now(b, ids, base_in, base_levels, now), _rate_now(i, ids, iv_in, iv_levels, now)
        rates[fid] = {"baseline": round(r0, 6), "intervention": round(r1, 6), "observed": [min(seen), max(seen)] if seen else None}
        if seen and (r1 > RATE_OUTSIDE * max(seen) + 1e-9 or r1 < min(seen) / RATE_OUTSIDE - 1e-9):
            note = f"extrapolation: flow {fid} at {r1:.4g} per {model.time_unit}, outside the {min(seen):.4g}–{max(seen):.4g} seen"
            for f in model.flows:
                if f.id == fid:
                    for end in (f.src, f.dst):
                        if end:
                            stock_why[end].append(note)

    near = {f.id for f in model.flows if f.id in touched or {f.src, f.dst} & set(want)}
    not_trusted = [{"kind": "flow", "id": fid, "why": why} for fid, why in weak.items() if fid in near]
    not_trusted += [{"kind": "stock", "id": sid, "why": stock_why[sid]} for sid in want if stock_why[sid]]
    return {
        "model": label or {"id": model.id}, "time_unit": model.time_unit, "now": now, "horizon_s": steps * step_s, "step_s": step_s,
        "interventions": ivs, "t": [offsets[i] for i in keep],
        "stocks": {sid: {"name": model.stock(sid).name, "unit": model.stock(sid).unit, "start": {"baseline": base_levels[k], "intervention": iv_levels[k]},
                         "baseline": band(A["baseline"], k), "intervention": band(A["intervention"], k), "difference": band(D, k),
                         "trusted": not stock_why[sid], "why": stock_why[sid]}
                   for sid in want for k in [ids.index(sid)]},
        "flows": rates, "limits": [x for x in limits if x["stock"] in want or x.get("new")],
        "replayed": replayed, "not_trusted": not_trusted, "trusted": not any(stock_why[s] for s in want),
        "band": {"members": max(0, members), "quantiles": list(QUANTILES), "seed": seed,
                 "spread": {fid: {"rel": round(r, 4), "how": how} for fid, (r, how) in spreads.items()},
                 "how": "each flow's rate times exp(z·rel), z standard normal per member and flow, shared by baseline and "
                        "intervention; rel is the relative error its fit records (sd.trust); levels now are taken as exact"},
    }


def load(models, version: int | None = None) -> tuple[Model | None, dict]:
    """The model to ask: a saved version when named, otherwise the host's latest discovery (what
    the Dynamics page shows), else the current version; and a label saying which."""
    if version is not None:
        return models.load(version), {"version": version}
    cached = models.latest_discovery()
    if cached and cached[1].stocks:
        return cached[1], {"version": None, "latest_discovery_at": cached[0], "current_version": models.current_version()}
    return models.load(), {"version": models.current_version()}
