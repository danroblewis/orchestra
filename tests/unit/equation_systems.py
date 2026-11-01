"""Synthetic systems with known equations, for the forward run's tests (not collected itself).

``chain``: work arrives at a queue (``arrive``: c a minute), moves on to a ready stock
(``move``: k per queued item a minute), is joined there by a side supply (``side``: c a minute)
and drained (``drain``: k per ready item a minute). At c = 3, 0.5, 3 and 0.3 the queue settles at
6 and the ready stock at 20; doubling the arrivals settles them at 12 and 30, the ready stock
×1.5.

``fabricate`` makes the data a model would have made: each step every flow moves a Poisson count
with its rate's mean, its stock's outflows cut together, item by item, to what the stock holds, so
levels and counters stay whole numbers and every stock balances exactly."""

import math

import numpy as np

from orchestra.sd.equations import engine
from orchestra.sd.equations.compile import Frame
from orchestra.sd.equations.history import levels_at, measured_rates, unit_s
from orchestra.sd.model import Equation, Flow, Model, SeriesRef, Stock

T0 = 1_800_000_000.0


def eq(form, inputs=(), **params):
    return Equation(form, dict(params), "fitted", "poisson-mle", None, None, {"events": 500.0, "dispersion": 1.0, "live_minutes": 120.0},
                    list(inputs))


def chain(arrive=3.0, move=0.5, side=3.0, drain=0.3) -> Model:
    m = Model("system", "chain", time_unit="minute",
              stocks=[Stock("queue", "queue", series=SeriesRef("queue")), Stock("ready", "ready", series=SeriesRef("ready"))],
              flows=[Flow("arrive", "arrive", None, "queue", SeriesRef("arrive_total"), [eq("constant", c=arrive)]),
                     Flow("move", "move", "queue", "ready", SeriesRef("move_total"), [eq("proportional", ["queue"], k=move)]),
                     Flow("side", "side", None, "ready", SeriesRef("side_total"), [eq("constant", c=side)]),
                     Flow("drain", "drain", "ready", None, SeriesRef("drain_total"), [eq("proportional", ["ready"], k=drain)])])
    m.discovery = {"fit_start": T0, "inputs": {}}
    return m


def history_of(model: Model, *, minutes: int = 120, start_levels=None, seed: int = 1, step_s: float = 5.0) -> dict:
    """The window's data, made by ``model`` itself, from ``start_levels`` (default: its steady state)."""
    lv = start_levels or {"queue": 6.0, "ready": 20.0}
    run = fabricate(model, {"inputs": {}}, start=T0, end=T0 + minutes * 60, step_s=step_s, seed=seed, levels=lv)
    return as_history(model, run)


def fabricate(model: Model, history: dict, *, start: float, end: float, step_s: float, seed: int = 0,
              levels: dict | None = None) -> dict:
    """The run: ``t`` (every step's end, and the start), each stock's ``levels`` and each flow's
    cumulative ``counts`` at those times."""
    flows = engine.compiled(model)
    ids = [s.id for s in model.stocks]
    names = list(history.get("inputs") or {})
    index = {f"stock:{s}": i for i, s in enumerate(ids)} | {f"input:{n}": len(ids) + j for j, n in enumerate(names)}
    unit = unit_s(model)
    g = step_s / unit
    fr = Frame(index, g, 1)
    for f in flows:
        fr.params[f.id] = dict(f.params)
    inputs = {n: engine.Series(history["inputs"][n]) for n in names}
    seen = measured_rates(history, [f.id for f in flows if f.observed])
    lv = levels if levels is not None else levels_at(model, history, start)[0]
    L = np.array([float(round(lv.get(s) or 0.0)) for s in ids])
    src = [ids.index(f.src) if f.src in ids else None for f in flows]
    dst = [ids.index(f.dst) if f.dst in ids else None for f in flows]
    rng = np.random.default_rng(seed)
    steps = max(1, int((end - start) // step_s))
    times = [start + i * step_s for i in range(steps + 1)]
    out_l = {s: [float(L[k])] for k, s in enumerate(ids)}
    counts = {f.id: [0.0] for f in flows}
    total = {f.id: 0.0 for f in flows}
    with np.errstate(all="ignore"):
        for i in range(steps):
            t = times[i]
            fr.R[: len(ids), 0] = L
            for n in names:
                fr.R[index[f"input:{n}"], 0] = inputs[n].at(t)
            for fid, r in seen.items():
                fr.observed[fid] = r.at(t)
            mean = []
            for f in flows:
                v = float(np.asarray(f.fn(fr), dtype=float).reshape(-1)[0])
                mean.append(max(0.0, v) * g if math.isfinite(v) else 0.0)
            amount = [int(rng.poisson(m)) if m > 0 else 0 for m in mean]
            for c in range(len(ids)):
                takers = [j for j, s in enumerate(src) if s == c]
                want = sum(amount[j] for j in takers)
                while want > L[c] and want > 0:                  # cut item by item, from the largest
                    j = max(takers, key=lambda j: amount[j])
                    amount[j] -= 1
                    want -= 1
            for j, a in enumerate(amount):
                if src[j] is not None:
                    L[src[j]] -= a
                if dst[j] is not None:
                    L[dst[j]] += a
                total[flows[j].id] += a
            for k, s in enumerate(ids):
                out_l[s].append(float(L[k]))
            for f in flows:
                counts[f.id].append(total[f.id])
            fr.advance()
    return {"t": times, "levels": out_l, "counts": counts, "step_s": step_s}


def as_history(model: Model, run: dict, *, flow_step: float = 30.0, inputs: dict | None = None) -> dict:
    """The run as the web server's history (``sd.history.history``): levels at every step,
    each flow's rate per time unit over each ``flow_step``, and the inputs given."""
    unit = unit_s(model)
    t = run["t"]
    every = max(1, round(flow_step / run["step_s"]))
    flows = {}
    for f in model.flows:
        c = run["counts"][f.id]
        flows[f.id] = [[t[i], (c[i] - c[i - every]) * unit / (t[i] - t[i - every])] for i in range(every, len(t), every)]
    return {"at": t[-1], "start": t[0], "stock_step": run["step_s"], "flow_step": every * run["step_s"], "time_unit": model.time_unit,
            "stocks": {s.id: [[tt, v] for tt, v in zip(t, run["levels"][s.id])] for s in model.stocks if s.series is not None},
            "flows": flows, "inputs": dict(inputs or {})}
