"""A declared name (the owner, 2026-11-02: "We could allow the user to give their own custom name,
and use the effective ID name we have to associate it"): a declared stock linked to a discovered
one, or a declared flow found as one, lends its name to that part on the pages, the generated
name kept as its identifier; not otherwise. And every stock and flow carries its ``tags``."""

from fastapi.testclient import TestClient
from intended_seed import project_at, seed, v2_model

from orchestra.sd.intended.display import declared_names
from orchestra.sd.intended.keys import Keys

OWNER = {"author": "owner", "source": "supervisor", "quote": "call the acceptance tests the feature gate"}


def _key(model, sid: str) -> str:
    return Keys(model).stock_of_id[sid]


def _layer(project, ops, prov=OWNER):
    store = project.intended
    store.apply(ops, prov)
    return store.read()["layer"]


def test_a_linked_declared_stock_lends_its_name_and_an_unlinked_one_does_not(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    m = v2_model()
    layer = _layer(project, [{"op": "declare_stock", "id": "feature_gate", "name": "feature gate"}])
    assert declared_names(layer, Keys(m)) == {"stocks": {}, "flows": {}}       # declared, never linked: no name lent
    layer = _layer(project, [{"op": "link", "part": "stock", "id": "feature_gate", "found_as": _key(m, "acceptance_tests_passing")}])
    got = declared_names(layer, Keys(m))["stocks"]
    assert list(got) == ["acceptance_tests_passing"]
    assert got["acceptance_tests_passing"]["name"] == "feature gate"
    assert got["acceptance_tests_passing"]["id"] == "feature_gate"
    assert got["acceptance_tests_passing"]["provenance"]["author"] == "owner"
    # linked to a key the shown model does not have: nothing lent
    layer = _layer(project, [{"op": "link", "part": "stock", "id": "feature_gate", "found_as": "gone{}"}])
    assert declared_names(layer, Keys(m))["stocks"] == {}


def test_a_proposed_declaration_lends_no_name_until_it_is_declared(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    m = v2_model()
    layer = _layer(project, [{"op": "declare_stock", "id": "gate", "name": "gate"},
                             {"op": "link", "part": "stock", "id": "gate", "found_as": _key(m, "acceptance_tests_passing")}],
                   {"author": "integrator", "source": "integrator", "reason": "a guess"})
    assert layer["stocks"]["gate"]["state"] == "proposed"
    assert declared_names(layer, Keys(m))["stocks"] == {}


def test_a_declared_flow_found_by_its_ends_lends_a_name_it_was_given_never_the_generated_one(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    m = v2_model()
    f = next(x for x in m.flows if x.src and x.dst)
    a, b = _key(m, f.src), _key(m, f.dst)
    assert sum(1 for x in m.flows if (x.src, x.dst) == (f.src, f.dst)) == 1      # one flow between those ends: one match
    layer = _layer(project, [{"op": "declare_flow", "id": "plain", "from": a, "to": b}])
    assert declared_names(layer, Keys(m))["flows"] == {}
    layer = _layer(project, [{"op": "retract", "part": "flow", "id": "plain"},
                             {"op": "declare_flow", "id": "handoff", "from": a, "to": b, "name": "the hand-off"}])
    assert declared_names(layer, Keys(m))["flows"] == {f.id: {"name": "the hand-off", "part": "flow", "id": "handoff",
                                                              "provenance": layer["flows"]["handoff"]["provenance"]}}


def test_the_dynamics_and_machines_answers_carry_the_lent_name_and_every_parts_tags(tmp_path, monkeypatch):
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer

    project = project_at(tmp_path, monkeypatch)
    seed(project)
    m = v2_model()
    _layer(project, [{"op": "declare_stock", "id": "feature_gate", "name": "feature gate"},
                     {"op": "link", "part": "stock", "id": "feature_gate", "found_as": _key(m, "acceptance_tests_passing")}])
    c = TestClient(create_app(project), headers=bearer(project))
    got = c.get("/api/dynamics/model").json()["model"]
    assert all(isinstance(x["tags"], list) for x in got["stocks"] + got["flows"])
    named = {s["id"]: s.get("declared_name") for s in got["stocks"]}
    assert named["acceptance_tests_passing"]["name"] == "feature gate"
    assert all(v is None for k, v in named.items() if k != "acceptance_tests_passing")
    # the generated name stays the model's own, the key its identifier
    s = next(s for s in got["stocks"] if s["id"] == "acceptance_tests_passing")
    assert s["name"] == "acceptance tests passing"
    assert got["intended"]["keys"]["stocks"]["acceptance_tests_passing"] == _key(m, "acceptance_tests_passing")
    from orchestra.sd.store import ModelStore
    from orchestra.web.machines import model_parts
    lent = declared_names(project.intended.read()["layer"], Keys(ModelStore.for_state(project.state_dir).load()))
    parts = model_parts(m, lent)
    assert next(s for s in parts["stocks"] if s["id"] == "acceptance_tests_passing")["declared_name"]["name"] == "feature gate"
    assert all("declared_name" not in s for s in model_parts(m)["stocks"])
