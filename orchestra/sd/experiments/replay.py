"""The replay: the base model and the experiment run over a past window, driven by that window's
own measured inputs and flows (``observed()``), against what was measured. It is the backtest of
an equation (does it explain what happened, or was it only tuned to an outcome?) and the
counterfactual replay ("last month, with these equations").

**The runs.** Both start from each stock's level measured at the window's start (a hidden stock
from its initial level) and run free to its end: nothing is reset along the way, so an equation
that is wrong shows as a stock that drifts.

**The scores.**

- **each stock**: the run's error against the measured level, ``rms(run − measured) / scale``,
  with ``scale`` the level's own spread (its standard deviation, at least a tenth of its mean): 0
  is perfect, 1 is as far off as the level varies (``sd.trust.era_errors`` measures the same);
- **each flow with a counter**: its equation's **one-step** fit, the equation evaluated on the
  *measured* levels and inputs (not the run's) over each stretch its counter counted, against what
  it counted: the Poisson deviance (``deviance``, lower is better) and the share of the deviance
  of a constant rate it removes (``d2``, 1 is perfect, 0 is no better than the mean rate, below 0
  worse). One-step, each equation is judged on its own, apart from the errors of the others; the
  free run (``total``, what the run moved over the window against what was counted) shows how
  the errors add up;
- **experiment against base**: ``better`` or ``worse`` when the experiment's deviance is lower or
  higher by more than ``MARGIN`` (2, the deviance one parameter is worth, or 2% of it), a stock's
  error by more than ``STOCK_MARGIN``; else ``same``.

A flow written ``observed()`` replays what was counted, so it has nothing to score."""

from __future__ import annotations

import math

import numpy as np

from ..model import Model
from . import engine
from .compile import Frame
from .forward import keep_index
from .history import at, initial, levels_at, measured_rates, step_for, unit_s
from .history import hidden as is_hidden

MARGIN = 2.0
MARGIN_SHARE = 0.02
STOCK_MARGIN = 0.05
POINTS = 121


def window_of(history: dict, start: float | None, end: float | None) -> tuple[float, float]:
    s = float(history.get("start") if start is None else start)
    e = float(history.get("at") if end is None else end)
    if not e > s:
        raise ValueError("the window must end after it starts")
    return s, e


def central(model: Model, history: dict, start: float, end: float, *, step_s: float | None = None, flows=None, columns: int = 1,
            params=None, factors=None, levels=None) -> engine.Run:
    """One replay of ``model`` over [start, end] (columns: candidates, ``params`` and ``factors``
    per column)."""
    step_s = step_for(end - start, step_s)
    steps = max(1, math.ceil((end - start) / step_s))
    flows = flows if flows is not None else engine.compiled(model)
    lv = levels if levels is not None else levels_at(model, history, start)[0]
    return engine.run(model, t0=start, steps=steps, step_s=step_s, unit_s=unit_s(model), levels=lv,
                      inputs={k: list(v) for k, v in (history.get("inputs") or {}).items()},
                      observed=measured_rates(history, [f.id for f in flows if f.observed]), columns=columns,
                      factors=factors, params=params, flows=flows)


def stock_error(run_t, run_v, measured) -> float | None:
    """``rms(run − measured) / scale`` at the run's times within the measured points."""
    pairs = [(v, m) for t, v in zip(run_t, run_v) if (m := at(measured, t)) is not None]
    if len(pairs) < 2:
        return None
    ms = [m for _, m in pairs]
    mean = sum(ms) / len(ms)
    sd = math.sqrt(sum((m - mean) ** 2 for m in ms) / len(ms))
    rms = math.sqrt(sum((v - m) ** 2 for v, m in pairs) / len(pairs))
    scale = max(sd, 0.1 * abs(mean), 1e-9)
    return rms / scale


def _deviance(n: np.ndarray, mu: np.ndarray) -> float:
    mu = np.maximum(mu, 1e-9)
    with np.errstate(divide="ignore", invalid="ignore"):
        term = np.where(n > 0, n * np.log(n / mu), 0.0) - (n - mu)
    return float(2 * term.sum())


def one_step(model: Model, history: dict, start: float, end: float, flows=None) -> dict[str, dict]:
    """Each counted flow's equation evaluated on the measured levels and inputs over each stretch
    its counter counted, against the count (see above)."""
    flows = flows if flows is not None else engine.compiled(model)
    ids = [s.id for s in model.stocks]
    names = list(dict.fromkeys([*(history.get("inputs") or {})]))
    measured = history.get("stocks") or {}
    counted = history.get("flows") or {}
    fstep = float(history.get("flow_step") or 30.0)
    sstep = float(history.get("stock_step") or 15.0)
    unit = unit_s(model)
    grid = np.arange(start, end, min(sstep, fstep))
    index = {f"stock:{s}": i for i, s in enumerate(ids)} | {f"input:{n}": len(ids) + j for j, n in enumerate(names)}
    fr = Frame(index, (grid[1] - grid[0]) / unit if len(grid) > 1 else 1.0, 1)
    rates = measured_rates(history, [f.id for f in flows if f.observed])
    for f in flows:
        fr.params[f.id] = dict(f.params)
    hidden = {s.id: initial(s) for s in model.stocks if is_hidden(s)}
    want = [f for f in flows if counted.get(f.id) and not f.observed and not (set(f.reads) & set(hidden))]
    pred = {f.id: np.zeros(len(grid)) for f in want}
    with np.errstate(all="ignore"):
        for i, t in enumerate(grid):
            for k, s in enumerate(ids):
                v = at(measured.get(s), t) if s not in hidden else hidden[s]
                fr.R[k, 0] = 0.0 if v is None else v
            for n in names:
                v = at(history["inputs"][n], t)
                fr.R[index[f"input:{n}"], 0] = 0.0 if v is None else v
            for f in flows:
                if f.observed:
                    fr.observed[f.id] = rates[f.id].at(t)
            for f in want:
                v = float(np.asarray(f.fn(fr), dtype=float).reshape(-1)[0])
                pred[f.id][i] = max(0.0, v) if math.isfinite(v) else 0.0
            fr.advance()
    out = {}
    for f in want:
        pts = [(t, v) for t, v in counted[f.id] if start + fstep <= t <= end]
        if len(pts) < 2:
            continue
        mu, n = [], []
        for t, v in pts:
            sel = (grid >= t - fstep) & (grid < t)
            if not sel.any():
                continue
            mu.append(float(pred[f.id][sel].mean()) * fstep / unit)
            n.append(max(0.0, v) * fstep / unit)
        if len(n) < 2:
            continue
        n_, mu_ = np.array(n), np.array(mu)
        dev = _deviance(n_, mu_)
        null = _deviance(n_, np.full(len(n_), n_.mean()))
        out[f.id] = {"deviance": round(dev, 3), "d2": round(1 - dev / null, 4) if null > 1e-9 else None, "stretches": len(n),
                     "counted": round(float(n_.sum()), 3), "predicted": round(float(mu_.sum()), 3)}
    return out


def _versus(a: float | None, b: float | None, margin: float) -> str | None:
    if a is None or b is None:
        return None
    return "better" if b < a - margin else "worse" if b > a + margin else "same"


def replay(base: Model, draft: Model, history: dict, *, start: float | None = None, end: float | None = None,
           step_s: float | None = None, points: int = POINTS) -> dict:
    """Both runs over the window, observed against simulated, and the scores (see above)."""
    start, end = window_of(history, start, end)
    for m, who in ((base, "base"), (draft, "experiment")):
        names = set(history.get("inputs") or {})
        fl = engine.compiled(m, list(names))
        missing = sorted({x[6:] for f in fl for x in f.reads if x.startswith("input:")} - names)
        if missing:
            raise ValueError(f"the {who} reads input{'s' if len(missing) > 1 else ''} {', '.join(missing)}, not measured in the window: "
                             "a replay runs on what was measured")
    fb, fd = engine.compiled(base), engine.compiled(draft)
    A = central(base, history, start, end, step_s=step_s, flows=fb)
    B = central(draft, history, start, end, step_s=step_s, flows=fd)
    steps = A.levels.shape[2] - 1
    keep = keep_index(steps, points)
    measured = history.get("stocks") or {}
    stocks = {}
    for sid in dict.fromkeys([*A.stocks, *B.stocks]):
        row: dict = {"measured": [[float(A.t[i] - start), at(measured.get(sid), float(A.t[i]))] for i in keep] if measured.get(sid) else None}
        errs = {}
        for name, R in (("base", A), ("experiment", B)):
            if sid in R.stocks:
                v = R.levels[0, R.stocks.index(sid)]
                row[name] = [round(float(v[i]), 4) for i in keep]
                errs[name] = stock_error(R.t, v, measured.get(sid)) if measured.get(sid) else None
            else:
                row[name] = None
        row["error"] = {k: None if v is None else round(v, 4) for k, v in errs.items()}
        row["versus_base"] = _versus(errs.get("base"), errs.get("experiment"), STOCK_MARGIN)
        stocks[sid] = row
    os_b, os_d = one_step(base, history, start, end, fb), one_step(draft, history, start, end, fd)
    unit = unit_s(base)
    counted = history.get("flows") or {}
    fstep = float(history.get("flow_step") or 30.0)
    flows = {}
    rkeep = [min(i, steps - 1) for i in keep]
    for fid in dict.fromkeys([*A.flows, *B.flows]):
        pts = [v for t, v in counted.get(fid) or [] if start < t <= end]
        row = {"measured_total": round(sum(pts) * fstep / unit, 3) if pts else None}
        for name, R, os_ in (("base", A, os_b), ("experiment", B, os_d)):
            if fid in R.flows:
                r = R.rates[0, R.flows.index(fid)]
                row[name] = {"rate": [round(float(r[i]), 6) for i in rkeep], "total": round(float(r.sum()) * (R.t[1] - R.t[0]) / unit, 3),
                             "one_step": os_.get(fid)}
            else:
                row[name] = None
        a, b = ((row.get(k) or {}).get("one_step") or {} for k in ("base", "experiment"))
        if a.get("deviance") is not None and b.get("deviance") is not None:
            row["versus_base"] = _versus(a["deviance"], b["deviance"], max(MARGIN, MARGIN_SHARE * a["deviance"]))
        flows[fid] = row
    tally = lambda rows: {k: sum(1 for r in rows.values() if r.get("versus_base") == k) for k in ("better", "same", "worse")}
    return {"mode": "replay", "time_unit": base.time_unit, "start": start, "end": end, "step_s": float(A.t[1] - A.t[0]),
            "t": [round(float(A.t[i] - start), 3) for i in keep], "stocks": stocks, "flows": flows,
            "summary": {"stocks": tally(stocks), "flows": tally(flows)},
            "nonfinite": {"base": A.nonfinite, "experiment": B.nonfinite},
            "how": "free runs from the measured levels at the start, on the window's measured inputs; stock error is rms over the "
                   "level's spread; a flow's one-step fit is its equation on the measured levels against its counter (Poisson "
                   "deviance, lower is better; d2 the share of a constant rate's deviance removed)"}
