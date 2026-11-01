"""The system dynamics core: model JSON, structure checks, Orchestra's factory, and the store's
versions."""

from __future__ import annotations

import threading

from orchestra.sd.model import Equation, Flow, Machine, Model, SeriesRef, Stock
from orchestra.sd.store import ModelStore

LEVEL, IN, OUT = "sim_level", "sim_in_total", "sim_out_total"


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




def test_two_writers_saving_at_once_get_distinct_versions(tmp_path):
    store = ModelStore.for_state(tmp_path)
    models = []
    for i in range(8):
        m = small_model()
        m.name = f"system{i}"
        models.append(m)
    got, go = [], threading.Barrier(len(models))

    def save(m):
        go.wait()
        got.append(ModelStore.for_state(tmp_path).save(m, note=m.name))
    threads = [threading.Thread(target=save, args=(m,)) for m in models]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(got) == list(range(1, len(models) + 1))
    assert {store.load(v).name for v in got} == {m.name for m in models}
