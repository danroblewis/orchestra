"""The system dynamics core: model JSON, structure checks, Orchestra's factory, and the fitter
recovering known rates from a simulated history."""

from __future__ import annotations

import json
import math
import random

from orchestra.collectors import EVENTS

LEVEL, IN, OUT = "sim_level", "sim_in_total", "sim_out_total"
from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.fit import fit_model
from orchestra.sd.model import Equation, Flow, Machine, Model, SeriesRef, Stock
from orchestra.sd.store import ModelStore


def small_model() -> Model:
    lab = {"project": "p"}
    return Model("system", "The system",
                 stocks=[Stock("S", "S", series=SeriesRef(LEVEL, lab))],
                 flows=[Flow("outside>S", "in", None, "S", SeriesRef(IN, lab)), Flow("S>outside", "out", "S", None, SeriesRef(OUT, lab))],
                 machines=[Machine("m", "m", "program", "", ["outside>S"])])


def test_model_round_trips(tmp_path):
    m = small_model()
    assert m.check() == []
    store = ModelStore(tmp_path)
    assert store.save(m, note="declared") == 1
    assert store.load().to_json() == m.to_json()
    # a past version's machines carry "engagement": [], a field nothing ever filled: read, ignored
    past = {**m.to_json(), "machines": [{**mc, "engagement": []} for mc in m.to_json()["machines"]]}
    assert Model.from_json(past).to_json() == m.to_json()


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
            pts += [Point(LEVEL, level, t, lab), Point(IN, n_in, t, lab)]
        for _ in range(level):
            if rnd.random() < k_per_h / 60:
                level -= 1
                n_out += 1
                pts += [Point(LEVEL, level, t + 1, lab), Point(OUT, n_out, t + 1, lab)]
    store.write(pts)


def test_fit_recovers_known_rates_and_forms(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    _simulate(store, inflow_per_h=3.0, k_per_h=0.5, hours=400, stopped=(150, 230))
    lab = {"project": "p"}
    m = Model("sim", "sim", stocks=[Stock("S", "S", series=SeriesRef(LEVEL, lab))],
              flows=[Flow("outside>S", "in", None, "S", SeriesRef(IN, lab)),
                     Flow("S>outside", "out", "S", None, SeriesRef(OUT, lab))])
    fit_model(m, store, "p")
    inflow, outflow = m.flow("outside>S").current(), m.flow("S>outside").current()
    assert inflow.form == "constant" and outflow.form == "proportional"
    assert inflow.origin == "fitted" and inflow.method == "poisson-mle"
    assert abs(inflow.params["c"] - 3.0) < 3 * inflow.quality["se"] + 0.1, inflow.params
    assert abs(outflow.params["k"] - 0.5) < 3 * outflow.quality["se"] + 0.02, outflow.params
    assert math.isclose(inflow.quality["running_hours"], 400 - 80, abs_tol=1.5), "stopped hours are left out"
    assert inflow.quality["events_while_stopped"] == 0


def test_one_model_with_versions(tmp_path):
    store = ModelStore.for_state(tmp_path)
    m = small_model()
    assert store.load() is None
    assert store.save(m, "declared") == 1
    assert store.save(m, "same again") == 1, "an unchanged model adds no version"
    m.flows[0].equations.append(Equation("constant", {"c": 1.0}, "fitted"))
    assert store.save(m, "fitted") == 2
    assert [v["note"] for v in store.versions()] == ["declared", "fitted"]
    assert store.load(1).flows[0].equations == [] and store.load().flows[0].equations
    assert store.current_version() == 2


def test_a_legacy_model_becomes_version_1(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "tickets.json").write_text(json.dumps(small_model().to_json()))
    store = ModelStore.for_state(tmp_path)
    assert store.versions()[0]["note"] == "imported from models/tickets.json"
    assert store.load().name == "The system"
