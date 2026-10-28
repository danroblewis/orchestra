"""Data a model would have made: a stochastic run of its equations, as the metrics store would
have held it. The inverse solver's uniqueness check makes the counterfactual window's data this
way and discovers a model from it (the owner's fabricate-and-rediscover idea, used as a check);
tests make synthetic systems with known equations the same way.

Each step every flow moves a Poisson count with its rate's mean (``rate × step``), its stock's
outflows cut together, item by item, to what the stock holds, so levels and counters stay whole
numbers and every stock balances exactly, as a real system's would. Measured inputs and
``observed()`` flows are read from the history as the replay reads them."""

from __future__ import annotations

import math

import numpy as np

from ..model import Model
from . import engine
from .compile import Frame
from .history import levels_at, measured_rates, unit_s


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


def counter_name(f) -> str:
    """The name a flow's counter is written under: its own, ending ``_total`` as a counter's
    name does (discovery tells a counter by it)."""
    name = f.counter.name if f.counter else (f.measured_by[0].name if f.measured_by else f.id)
    return name if name.endswith("_total") else f"{name}_total"


def dump(model: Model, run: dict, labels: dict | None = None) -> list[tuple[str, dict, list]]:
    """The run as the metrics store's dump: each measured stock's level (under its series' name)
    and each measured flow's counter (its counter's name; two flows of one counter, the second
    under its own id). Hidden stocks and flows no counter measures are not in it."""
    lab = dict(labels or {"machine": "fabricated"})
    out, taken = [], set()
    for s in model.stocks:
        if s.series is not None:
            out.append((s.series.name, lab, list(zip(run["t"], run["levels"][s.id]))))
    for f in model.flows:
        if not (f.counter or f.measured_by):
            continue                                    # no counter measures it: not in the data
        name = counter_name(f)
        if name in taken:
            name = f"{f.id}_total".replace("@", "_").replace(">", "_").replace(":", "_")
        taken.add(name)
        out.append((name, lab, list(zip(run["t"], run["counts"][f.id]))))
    return out


def as_history(model: Model, run: dict, *, flow_step: float = 30.0, inputs: dict | None = None) -> dict:
    """The run as the web server's history (``web.background.history``): levels at every step,
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


def history_of_dump(model: Model, data: list, step_s: float, flow_step: float = 30.0) -> dict:
    """A dump (``dump``) as the history of ``model``, a model discovered from such data: its
    stocks' levels and its flows' rates, by their series' names."""
    by = {name: pts for name, _, pts in data}
    unit = unit_s(model)
    t0 = min((p[0][0] for p in by.values() if p), default=0.0)
    out = {"stocks": {}, "flows": {}, "inputs": {}, "stock_step": step_s, "flow_step": flow_step, "time_unit": model.time_unit}
    for s in model.stocks:
        if s.series is not None and s.series.name in by:
            out["stocks"][s.id] = [[t, v] for t, v in by[s.series.name]]
    every = max(1, round(flow_step / step_s))
    for f in model.flows:
        refs = [r.name for r in ([f.counter] if f.counter else []) + list(f.measured_by)]
        pts = [by[n] for n in refs if n in by]
        if not pts:
            continue
        total = [sum(p[i][1] for p in pts) for i in range(len(pts[0]))]
        ts = [t for t, _ in pts[0]]
        out["flows"][f.id] = [[ts[i], (total[i] - total[i - every]) * unit / (ts[i] - ts[i - every])] for i in range(every, len(ts), every)]
    out["start"], out["at"] = t0, max((p[-1][0] for p in by.values() if p), default=t0)
    return out
