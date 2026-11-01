"""Synthetic systems with known equations, for the experiments' tests (not collected itself).

``chain``: work arrives at a queue (``arrive``: c a minute), moves on to a ready stock
(``move``: k per queued item a minute), is joined there by a side supply (``side``: c a minute)
and drained (``drain``: k per ready item a minute). At c = 3, 0.5, 3 and 0.3 the queue settles at
6 and the ready stock at 20; doubling the arrivals settles them at 12 and 30, the ready stock
×1.5."""

from orchestra.sd.experiments.fabricate import fabricate
from orchestra.sd.experiments.history import unit_s
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
