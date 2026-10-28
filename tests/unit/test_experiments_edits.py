"""The operations on an experiment's draft (sd/experiments/edits.py): each checked, a batch applied
whole or not at all, every equation's origin recorded, and the difference from the base."""

import pytest
from experiment_systems import chain

from orchestra.sd.experiments.edits import EditError, apply
from orchestra.sd.experiments.views import diff, model_view

EID = "x-0123456789ab"


def edit(*edits, model=None, scenario=None):
    m = model or chain()
    return apply(m, scenario or {}, chain(), list(edits), EID, "curator")


def test_add_replace_and_remove_a_flow_record_their_origin_and_show_in_the_diff():
    d = edit({"op": "add_flow", "id": "back", "from": "ready", "to": "queue", "equation": "k * min(queue, ready)", "params": {"k": 0.1}},
             {"op": "replace_flow", "id": "drain", "equation": "k * ready ** 1.5", "params": {"k": 0.05}},
             {"op": "remove_flow", "id": "side"})
    back, drain = d.model.flow("back"), d.model.flow("drain")
    for f in (back, drain):
        e = f.current()
        assert e.origin == "declared" and e.method == f"experiment {EID} by curator", "an equation an edit writes is an assumption"
    assert back.current().inputs == ["queue", "ready"] and back.current().spec == {"language": "orchestra", "text": "k * min(queue, ready)"}
    assert drain.counter.name == "drain_total" and len(drain.equations) == 2, "the flow keeps its counter; its fitted equation stays behind"
    x = diff(chain(), d.model, d.scenario)
    assert [r["id"] for r in x["flows"]["added"]] == ["back"] and [r["id"] for r in x["flows"]["removed"]] == ["side"]
    [ch] = x["flows"]["changed"]
    assert ch["id"] == "drain" and ch["what"] == ["equation"] and ch["before"]["equation"] == "k * ready"
    assert ch["after"] == {"from": "ready", "to": None, "equation": "k * ready ** 1.5", "params": {"k": 0.05}, "origin": "declared",
                           "method": f"experiment {EID} by curator"}
    assert x["edits"] == 3


def test_set_params_changes_numbers_by_name_and_the_diff_says_only_params():
    d = edit({"op": "set_params", "flow": "arrive", "params": {"c": 6.0}})
    e = d.model.flow("arrive").current()
    assert e.form == "constant" and e.params == {"c": 6.0} and e.origin == "declared"
    [ch] = diff(chain(), d.model)["flows"]["changed"]
    assert ch["what"] == ["params"] and ch["before"]["params"] == {"c": 3.0} and ch["after"]["params"] == {"c": 6.0}
    with pytest.raises(EditError, match="flow arrive has no parameter k; its equation is 'c' with c"):
        edit({"op": "set_params", "flow": "arrive", "params": {"k": 1}})


def test_a_hidden_stock_is_added_with_its_initial_level_and_removed_only_when_nothing_uses_it():
    d = edit({"op": "add_stock", "id": "buffer", "initial": 4.0}, {"op": "add_flow", "id": "spill", "from": "ready", "to": "buffer",
                                                                     "equation": "k * ready", "params": {"k": 0.01}})
    st = d.model.stock("buffer")
    assert st.series is None and st.evidence == {"hidden": True, "initial": 4.0, "experiment": EID, "by": "curator"}
    view = model_view(d.model)
    assert next(s for s in view["stocks"] if s["id"] == "buffer") == {"id": "buffer", "name": "buffer", "unit": "items", "hidden": True,
                                                                          "initial": 4.0}
    with pytest.raises(EditError, match="stock buffer is an end of flow spill"):
        apply(d.model, d.scenario, chain(), [{"op": "remove_stock", "id": "buffer"}], EID, "curator")
    gone = apply(d.model, d.scenario, chain(), [{"op": "remove_flow", "id": "spill"}, {"op": "remove_stock", "id": "buffer"}], EID, "curator")
    assert "buffer" not in {s.id for s in gone.model.stocks}


@pytest.mark.parametrize(("edits", "says"), [
    ([{"op": "add_flow", "id": "x", "from": "nowhere", "to": None, "equation": "1"}], "from: no stock nowhere"),
    ([{"op": "add_flow", "id": "x", "from": None, "to": None, "equation": "1"}], "at least one end in a stock"),
    ([{"op": "add_flow", "id": "arrive", "from": None, "to": "queue", "equation": "1"}], "already in the draft"),
    ([{"op": "replace_flow", "id": "nope", "equation": "1"}], "no flow nope"),
    ([{"op": "replace_flow", "id": "drain", "equation": "k * readyy", "params": {"k": 1}}], "unknown name readyy"),
    ([{"op": "replace_flow", "id": "drain", "equation": "k * ready", "params": {"k": 1, "j": 2}}], "parameter j not read"),
    ([{"op": "remove_flow", "id": "move"}, {"op": "remove_stock", "id": "queue"}], "stock queue is an end of flow arrive"),
    ([{"op": "add_stock", "id": "h"}, {"op": "add_flow", "id": "f", "from": "h", "to": None, "equation": "k * h", "params": {"k": 1}},
      {"op": "remove_flow", "id": "f"}, {"op": "add_flow", "id": "g", "from": None, "to": "queue", "equation": "h"},
      {"op": "remove_stock", "id": "h"}], "flow g: unknown name h"),
    ([{"op": "explode"}], "op, one of"),
    ([{"op": "remove_flow", "id": "side", "colour": "red"}], "unknown field colour"),
    ([{"op": "set_input", "input": "demand", "scenario": {"kind": "hold"}}], "not measured, so it has no last value"),
    ([{"op": "set_level", "stock": "queue", "level": -1}], "at least 0"),
    ([], "a list of 1 to"),
])
def test_a_refused_batch_says_which_edit_and_why_and_changes_nothing(edits, says):
    m = chain()
    before = m.to_json()
    with pytest.raises(EditError, match=says) as e:
        apply(m, {}, chain(), edits, EID, "curator")
    assert m.to_json() == before
    if edits and "after the batch" not in str(e.value):
        assert e.value.index is not None and str(e.value).startswith(f"edit {e.value.index} (")


def test_a_batch_is_atomic_the_first_failure_refuses_the_edits_before_it():
    with pytest.raises(EditError, match="edit 2") as e:
        edit({"op": "remove_flow", "id": "side"}, {"op": "set_params", "flow": "arrive", "params": {"c": 9.0}},
             {"op": "replace_flow", "id": "drain", "equation": "k * nothing", "params": {"k": 1}})
    assert e.value.index == 2


def test_a_scenario_says_what_a_forward_run_assumes_of_inputs_and_levels():
    m = chain()
    m.discovery["inputs"] = {"demand": {"name": "demand", "labels": {}}}
    d = apply(m, {}, m, [{"op": "set_input", "input": "demand", "scenario": {"kind": "ramp", "to_s": 600, "value": 5}},
                         {"op": "set_input", "input": "price", "scenario": {"kind": "series", "points": [[600, 2], [0, 1]]}},
                         {"op": "replace_flow", "id": "arrive", "equation": "k * demand / price", "params": {"k": 1.0}},
                         {"op": "set_level", "stock": "queue", "level": 12}], EID, "curator")
    assert d.scenario == {"inputs": {"demand": {"kind": "ramp", "to_s": 600.0, "value": 5.0},
                                     "price": {"kind": "series", "points": [[0.0, 1.0], [600.0, 2.0]]}}, "levels": {"queue": 12.0}}
    assert d.model.flow("arrive").current().inputs == ["input:demand", "input:price"]


def test_load_model_replaces_the_draft_keeping_what_the_base_has_as_it_was():
    simple = {"stocks": [{"id": "queue"}, {"id": "ready"}, {"id": "parked", "initial": 2}],
              "flows": [{"id": "arrive", "from": None, "to": "queue", "equation": "c", "params": {"c": 3.0}},
                        {"id": "move", "from": "queue", "to": "ready", "equation": "k * queue", "params": {"k": 0.25}},
                        {"id": "drain", "from": "ready", "to": "parked", "equation": "k * ready", "params": {"k": 0.3}}]}
    d = edit({"op": "load_model", "model": simple})
    assert d.model.flow("arrive").current().origin == "fitted", "written as the base has it: the base's own fit"
    assert d.model.flow("move").current().origin == "declared" and d.model.flow("move").counter.name == "move_total"
    assert d.model.flow("drain").dst == "parked" and d.model.stock("parked").evidence["hidden"]
    x = diff(chain(), d.model)
    assert [r["id"] for r in x["flows"]["removed"]] == ["side"] and x["stocks"]["added"] == [{"id": "parked", "initial": 2.0}]
    again = edit({"op": "load_model", "model": chain().to_json()})
    assert diff(chain(), again.model)["edits"] == 0, "a model as Orchestra writes it loads too"


def test_an_equation_the_language_cannot_render_refuses_the_edit_and_does_not_fail():
    from orchestra.sd.model import Equation

    m = chain()
    m.flow("side").equations = [Equation("mystery", {"q": 1.0}, "fitted")]
    with pytest.raises(EditError, match="edit 0 \\(set_params\\): an equation of form 'mystery' has no rendering") as e:
        apply(m, {}, m, [{"op": "set_params", "flow": "side", "params": {"q": 2.0}}], EID, "curator")
    assert e.value.index == 0
