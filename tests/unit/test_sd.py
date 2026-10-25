"""The system dynamics core: model JSON, structure checks, Orchestra's factory, and the fitter
recovering known rates from a simulated history."""

from __future__ import annotations

import math
import random

from orchestra.collectors import EVENTS, FLOW, STOCK
from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.factory import MACHINES, ticket_factory
from orchestra.sd.fit import fit_model
from orchestra.sd.model import Flow, Machine, Model, SeriesRef, Stock
from orchestra.sd.store import ModelStore


def test_factory_is_valid_and_round_trips(tmp_path):
    m = ticket_factory("p")
    assert m.check() == []
    assert sum(mc.bootstrap for mc in m.machines) == 1, "exactly one bootstrap machine: Orchestra's host"
    attributed = {f for mc in m.machines for f in mc.attributed}
    assert attributed == {f.id for f in m.flows}, "every flow has a machine hypothesis, and only real flows do"
    store = ModelStore(tmp_path)
    store.save(m)
    back = store.load("tickets")
    assert back.to_json() == m.to_json()
    assert set(MACHINES) == {mc.id for mc in back.machines}


def test_check_catches_bad_structure():
    m = Model("x", "x", stocks=[Stock("A", "A")],
              flows=[Flow("A>B", "a to b", "A", "B")],
              machines=[Machine("m", "m", "program", attributed=["nope"]), Machine("h1", "h", "program", bootstrap=True),
                        Machine("h2", "h", "program", bootstrap=True)])
    errs = m.check()
    assert any("unknown stock B" in e for e in errs)
    assert any("unknown flow nope" in e for e in errs)
    assert any("bootstrap" in e for e in errs)


def _simulate(store, *, inflow_per_h: float, k_per_h: float, hours: int, stopped: tuple[int, int], seed: int = 7):
    """A stock S fed at a constant rate and drained in proportion to its level, minute by minute,
    with the loop stopped for a while (nothing moves then). Writes what the collector would."""
    rnd = random.Random(seed)
    lab = {"project": "p"}
    t0, level, n_in, n_out = 1_800_000_000.0, 0, 0, 0
    pts = [Point(EVENTS, 1, t0, {**lab, "type": "loop_started"}),
           Point(EVENTS, 1, t0 + stopped[0] * 3600, {**lab, "type": "loop_stopped"}),
           Point(EVENTS, 2, t0 + stopped[1] * 3600, {**lab, "type": "loop_started"})]
    for minute in range(hours * 60):
        t = t0 + minute * 60 + 30
        if stopped[0] * 60 <= minute < stopped[1] * 60:
            continue
        if rnd.random() < inflow_per_h / 60:
            level += 1
            n_in += 1
            pts += [Point(STOCK, level, t, {**lab, "stock": "S"}), Point(FLOW, n_in, t, {**lab, "flow": "outside>S"})]
        for _ in range(level):
            if rnd.random() < k_per_h / 60:
                level -= 1
                n_out += 1
                pts += [Point(STOCK, level, t + 1, {**lab, "stock": "S"}), Point(FLOW, n_out, t + 1, {**lab, "flow": "S>outside"})]
    store.write(pts)


def test_fit_recovers_known_rates_and_forms(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    _simulate(store, inflow_per_h=3.0, k_per_h=0.5, hours=400, stopped=(150, 230))
    lab = {"project": "p"}
    m = Model("sim", "sim", stocks=[Stock("S", "S", series=SeriesRef(STOCK, {**lab, "stock": "S"}))],
              flows=[Flow("outside>S", "in", None, "S", SeriesRef(FLOW, {**lab, "flow": "outside>S"})),
                     Flow("S>outside", "out", "S", None, SeriesRef(FLOW, {**lab, "flow": "S>outside"}))])
    fit_model(m, store, "p")
    inflow, outflow = m.flow("outside>S").current(), m.flow("S>outside").current()
    assert inflow.form == "constant" and outflow.form == "proportional"
    assert inflow.origin == "fitted" and inflow.method == "poisson-mle"
    assert abs(inflow.params["c"] - 3.0) < 3 * inflow.quality["se"] + 0.1, inflow.params
    assert abs(outflow.params["k"] - 0.5) < 3 * outflow.quality["se"] + 0.02, outflow.params
    assert math.isclose(inflow.quality["running_hours"], 400 - 80, abs_tol=1.5), "stopped hours are left out"
    assert inflow.quality["events_while_stopped"] == 0
