"""The declared layer's store (docs/proposals/intended-model.md §2–§5, §10 tests 1–4, 20, 25, 26):
one call is one journal line and one ``dN``, all or nothing; past versions stay as they were;
provenance and change ids on everything; the machine envelope checked and its ``spec`` stored
as sent; revisions applied at once or kept pending."""

import json

import pytest

from orchestra.sd.intended import IntendedStore, IntentError
from orchestra.sd.store import ModelStore

OWNER = {"author": "owner", "source": "supervisor", "turn": "sessions/supervisor/41", "message": "msg_0193",
         "quote": "I'm going to create a Features stock."}
SUPERVISOR = {"author": "supervisor", "source": "supervisor", "reason": "a guess"}


def store(tmp_path) -> IntendedStore:
    return ModelStore(tmp_path / "model").intended()


def machine(**kw):
    return {"op": "propose_machine", "id": "feature_count_improver", "title": "Feature Count Improver", "kind": "universal",
            "managed": "orchestra", "engagement": {"mode": "continuous"}, "receives": ["session.settled"], "emits": ["work.requested"],
            "spec": {"steps": ["b", "a"], "invariants": ["x"], "present": "spec is opaque"}, **kw}


def test_one_call_is_one_journal_line_and_one_version_and_a_refused_op_writes_nothing(tmp_path):
    s = store(tmp_path)
    got = s.apply([{"op": "declare_stock", "name": "Features"}, {"op": "declare_effect", "name": "Latency"}], OWNER)
    assert got["version"] == 1 and [c["change"] for c in got["changes"]] == ["c1.0", "c1.1"]
    assert len(s.journal()) == 1 and (s.dir / "d0001.json").exists()
    with pytest.raises(IntentError) as e:
        s.apply([{"op": "declare_stock", "name": "Bugs"}, {"op": "expect", "part": "stock", "key": "x"},
                 {"op": "declare_flow", "from": None, "to": None}], OWNER)
    assert e.value.index == 2 and e.value.status == 422
    assert len(s.journal()) == 1 and s.current_version() == 1 and "bugs" not in s.read()["layer"]["stocks"]


def test_past_versions_read_back_unchanged_and_numbered_without_gaps(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "name": "Features"}], OWNER)
    first = json.dumps(s.read(1))
    s.apply([{"op": "declare_stock", "id": "features", "name": "Features", "unit": "features"}], OWNER)
    s.apply([{"op": "retract", "part": "stock", "id": "features"}], OWNER)
    assert json.dumps(s.read(1)) == first
    assert [v["version"] for v in s.versions()] == [1, 2, 3] and s.read()["layer"]["stocks"] == {}
    assert s.read(0)["version"] == 0


def test_every_element_and_change_carries_provenance(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "name": "Features"}], OWNER)
    s.apply([{"op": "expect", "part": "stock", "key": "k"}], {"author": "owner", "via": "page", "control": "expect",
                                                             "page": "dynamics", "from": "changes since v14"}, via="page")
    layer = s.read()["layer"]
    p = layer["stocks"]["features"]["provenance"]
    assert {"author", "via", "at", "source", "turn", "message", "quote"} <= set(p) and p["via"] == "plugin"
    m = layer["marks"]["expected"]["k"]["provenance"]
    assert m["via"] == "page" and m["control"] == "expect" and m["page"] == "dynamics" and m["from"] == "changes since v14"
    assert all(c["change"] for e in s.journal() for c in e["changes"])


def test_a_plugins_owner_needs_the_quote(tmp_path):
    with pytest.raises(IntentError):
        store(tmp_path).apply([{"op": "declare_stock", "name": "Features"}], {"author": "owner", "source": "supervisor"})


@pytest.mark.parametrize("bad", [
    {"colour": "red"}, {"id": "Feature-Count"}, {"kind": "agent"}, {"managed": "cloud"},
    {"engagement": {"mode": "nightly"}}, {"engagement": {"mode": "scheduled", "missed": "later"}},
    {"engagement": {"mode": "continuous", "at": "00:00"}}])
def test_the_store_refuses_what_the_envelope_does_not_know(tmp_path, bad):
    with pytest.raises(IntentError):
        store(tmp_path).apply([machine(**bad)], SUPERVISOR)


@pytest.mark.parametrize("mode", ["ad hoc", "continuous", "scheduled"])
def test_external_takes_every_mode_and_spec_is_stored_as_sent(tmp_path, mode):
    s = store(tmp_path)
    eng = {"mode": mode, **({"at": "00:00", "tz": "America/Los_Angeles", "missed": "skip"} if mode == "scheduled" else {})}
    s.apply([machine(managed="external", engagement=eng)], SUPERVISOR)
    m = s.read()["layer"]["machines"]["feature_count_improver"]
    assert m["managed"] == "external" and m["engagement"] == eng and m["state"] == "proposed"
    assert m["spec"] == {"steps": ["b", "a"], "invariants": ["x"], "present": "spec is opaque"}
    assert list(m["spec"]) == ["steps", "invariants", "present"]
    assert s.read()["layer"]["events"]["work.requested"]["implicit"]


@pytest.mark.parametrize("derived", ["present", "heard", "measured", "candidates", "verdict"])
def test_an_op_carrying_a_derived_field_is_refused(tmp_path, derived):
    with pytest.raises(IntentError, match="derived"):
        store(tmp_path).apply([{"op": "declare_stock", "name": "Features", derived: True}], OWNER)


def test_an_owners_revision_applies_at_once_and_anothers_waits(tmp_path):
    s = store(tmp_path)
    s.apply([machine()], SUPERVISOR)
    s.apply([{"op": "revise_machine", "id": "feature_count_improver",
              "set": {"engagement": {"mode": "scheduled", "at": "00:00"}},
              "add": {"receives": ["gate.rejected"]}, "remove": {"receives": ["session.settled"]}}],
            {**OWNER, "quote": "…12am every day"})
    m = s.read()["layer"]["machines"]["feature_count_improver"]
    assert m["engagement"]["mode"] == "scheduled" and m["receives"] == ["gate.rejected"]
    assert m["latest"]["added"] == {"receives": ["gate.rejected"]} and m["latest"]["removed"] == {"receives": ["session.settled"]}
    assert m["latest"]["before"] == {"engagement": {"mode": "continuous"}} and m["latest"]["quotes"] == ["…12am every day"]
    got = s.apply([{"op": "revise_machine", "id": "feature_count_improver", "set": {"spec": {"steps": ["c"], "invariants": ["x"]}}}],
                  SUPERVISOR)
    m = s.read()["layer"]["machines"]["feature_count_improver"]
    change = got["changes"][0]["change"]
    assert m["spec"]["steps"] == ["b", "a"] and [p["change"] for p in m["pending"]] == [change]
    s.apply([{"op": "confirm", "part": "machine", "id": "feature_count_improver", "change": change}], SUPERVISOR)
    m = s.read()["layer"]["machines"]["feature_count_improver"]
    assert m["spec"] == {"steps": ["c"], "invariants": ["x"]} and m["pending"] == [] and m["latest"]["before"]["steps"] == ["b", "a"]


def test_confirm_and_discard_and_guesses(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "name": "Bugs"}, machine(guessed=["receives[0]"])], SUPERVISOR)
    layer = s.read()["layer"]
    assert layer["stocks"]["bugs"]["state"] == "proposed"
    s.apply([{"op": "confirm", "part": "machine", "id": "feature_count_improver"},
             {"op": "discard", "part": "stock", "id": "bugs"}], SUPERVISOR)
    layer = s.read()["layer"]
    assert layer["machines"]["feature_count_improver"]["state"] == "declared"
    assert layer["machines"]["feature_count_improver"]["guessed"] == [] and "bugs" not in layer["stocks"]
    with pytest.raises(IntentError):
        s.apply([{"op": "discard", "part": "machine", "id": "feature_count_improver"}], SUPERVISOR)


def test_an_expected_effect_adds_no_flow_and_links_its_prediction(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "name": "Features"}], OWNER)
    s.apply([machine(), {"op": "set_expected_effect", "machine": "feature_count_improver", "horizon_s": 604800,
                         "edits": [{"stock": "features", "rises": True}, {"from": "features", "to": None, "appears": True}]}],
            SUPERVISOR)
    layer = s.read()["layer"]
    assert layer["flows"] == {} and layer["machines"]["feature_count_improver"]["expected_effect"]["prediction"] is None
    s.apply([{"op": "record_prediction", "machine": "feature_count_improver", "prediction": "ev123"}], SUPERVISOR)
    assert s.read()["layer"]["machines"]["feature_count_improver"]["expected_effect"]["prediction"] == "ev123"
    with pytest.raises(IntentError):
        s.apply([{"op": "set_expected_effect", "machine": "feature_count_improver", "horizon_s": 1,
                  "edits": [{"stock": "features", "rises": True, "falls": True}]}], SUPERVISOR)


def test_attachments_are_proposed_versioned_and_retracted_with_their_machine(tmp_path):
    s = store(tmp_path)
    s.apply([machine(), {"op": "propose_attachment", "machine": "feature_count_improver", "instrument": "pg",
                         "match": {"labels": {"job": "=~deploy-.*"}}, "instance_label": "server"}], SUPERVISOR)
    a = s.read()["layer"]["attachments"]
    assert list(a) == ["feature_count_improver_pg"] and a["feature_count_improver_pg"]["state"] == "proposed"
    s.apply([{"op": "retract", "part": "machine", "id": "feature_count_improver"}], SUPERVISOR)
    assert s.read()["layer"]["attachments"] == {}
    assert s.read(1)["layer"]["attachments"]


def test_set_target_names_its_comparison_target(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_flow", "from": "a", "to": None},
             {"op": "set_target", "part": "flow", "id": "a_to_outside", "target": "above", "value": 5, "over_s": 86400},
             {"op": "set_target", "part": "stock", "key": "q", "target": "within", "value": 1, "hi": 3, "over_s": 60}], OWNER)
    layer = s.read()["layer"]
    assert layer["flows"]["a_to_outside"]["target"] == {"op": "above", "value": 5.0, "over_s": 86400.0}
    assert layer["targets"]["q"]["target"]["hi"] == 3.0
