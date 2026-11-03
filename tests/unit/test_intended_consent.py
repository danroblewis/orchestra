"""The owner's consent in the declared layer (docs/proposals/intended-model.md §3, §4, §6.2): a
request is answered only by the op it asked for; a revision answering a ``switch_kind`` request
applies at once; what the owner declared is changed only by the owner; the owner's pending
change overrides another on the same fields; a page records only rule 9's closed list; a
declared stock is not removed while something declared names it."""

import pytest

from orchestra.sd.intended import IntentError, requests
from orchestra.sd.store import ModelStore

OWNER = {"author": "owner", "source": "supervisor", "quote": "yes, that one"}
SUPERVISOR = {"author": "supervisor", "source": "supervisor"}
FCI = "feature_count_improver"


class Bus:
    """Enough of ``Events`` for a request: the event keeps the id it is given."""

    def publish(self, type_, data, **kw):
        return {"id": kw["id"]}


def store(tmp_path):
    return ModelStore(tmp_path / "model").intended()


def machine(mid=FCI, **kw):
    return {"op": "propose_machine", "id": mid, "kind": "universal", "engagement": {"mode": "continuous"},
            "receives": ["session.settled"], **kw}


def asked(s, control, eid=FCI, part="machine", change=None) -> str:
    """The owner's request, published and noted as the web server does; its event id."""
    return requests.publish(s, Bus(), {"control": control, "part": part, "id": eid, "change": change})["id"]


def confirmed(s, mid=FCI):
    s.apply([machine(mid)], SUPERVISOR)
    s.apply([{"op": "confirm", "part": "machine", "id": mid}], {**SUPERVISOR, "request": asked(s, "confirm", mid)})


def test_a_request_is_answered_only_by_the_op_it_asked_for(tmp_path):
    s = store(tmp_path)
    s.apply([machine(), machine("other")], SUPERVISOR)
    confirm = {"op": "confirm", "part": "machine", "id": FCI}
    for rid in ("ev-made-up", asked(s, "discard"), asked(s, "confirm", "other")):
        with pytest.raises(IntentError, match="owner's unanswered request") as e:
            s.apply([confirm], {**SUPERVISOR, "request": rid})
        assert e.value.status == 422
    assert s.read()["layer"]["machines"][FCI]["state"] == "proposed"
    rid = asked(s, "confirm")
    assert ("machine", FCI) in requests.unanswered(s)
    s.apply([confirm], {**SUPERVISOR, "request": rid})
    assert s.read()["layer"]["machines"][FCI]["state"] == "declared"
    assert ("machine", FCI) not in requests.unanswered(s)
    with pytest.raises(IntentError, match="not one of the owner's unanswered requests"):  # answered: not open any more
        s.apply([{"op": "discard", "part": "machine", "id": "other"}], {**SUPERVISOR, "request": rid})


def test_a_request_naming_a_change_is_answered_only_with_that_change(tmp_path):
    s = store(tmp_path)
    confirmed(s)
    a = s.apply([{"op": "revise_machine", "id": FCI, "set": {"title": "A"}}], SUPERVISOR)["changes"][0]["change"]
    b = s.apply([{"op": "revise_machine", "id": FCI, "set": {"description": "B"}}], SUPERVISOR)["changes"][0]["change"]
    rid = asked(s, "confirm", change=a)
    with pytest.raises(IntentError, match="not the owner's unanswered request"):
        s.apply([{"op": "confirm", "part": "machine", "id": FCI, "change": b}], {**SUPERVISOR, "request": rid})
    s.apply([{"op": "confirm", "part": "machine", "id": FCI, "change": a}], {**SUPERVISOR, "request": rid})
    assert s.read()["layer"]["machines"][FCI]["title"] == "A"


def test_a_revision_answering_the_owners_switch_kind_request_applies_at_once(tmp_path):
    s = store(tmp_path)
    confirmed(s)
    rid = asked(s, "switch_kind")
    s.apply([{"op": "revise_machine", "id": FCI, "set": {"kind": "programmatic"}}], {**SUPERVISOR, "request": rid})
    m = s.read()["layer"]["machines"][FCI]
    assert m["kind"] == "programmatic" and m["pending"] == []
    assert m["latest"]["request"] == rid and m["latest"]["before"] == {"kind": "universal"}
    assert ("machine", FCI) not in requests.unanswered(s)


def test_a_switch_kind_request_does_not_carry_other_changes(tmp_path):
    s = store(tmp_path)
    confirmed(s)
    rid = asked(s, "switch_kind")
    s.apply([{"op": "revise_machine", "id": FCI, "set": {"kind": "programmatic", "title": "X"}}], {**SUPERVISOR, "request": rid})
    m = s.read()["layer"]["machines"][FCI]
    assert m["kind"] == "universal" and len(m["pending"]) == 1                # not the kind alone: it waits
    rid = asked(s, "confirm", change=m["pending"][0]["change"])
    s.apply([{"op": "revise_machine", "id": FCI, "set": {"kind": "programmatic"}}], {**SUPERVISOR, "request": rid})
    assert s.read()["layer"]["machines"][FCI]["kind"] == "universal"            # a confirm request is no switch
    assert rid in requests.open_requests(s)                                      # ... and it is not answered by one


@pytest.mark.parametrize("who", ["owner", "supervisor"])
def test_a_null_add_or_remove_is_an_empty_list(tmp_path, who):
    s = store(tmp_path)
    if who == "owner":
        s.apply([machine()], SUPERVISOR)
        s.apply([{"op": "revise_machine", "id": FCI, "add": {"tags": None}, "remove": {"receives": None}}], OWNER)
        assert s.read()["layer"]["machines"][FCI]["pending"] == []
        return
    confirmed(s)
    got = s.apply([{"op": "revise_machine", "id": FCI, "add": {"tags": None}, "remove": {"receives": None}}], SUPERVISOR)
    [p] = s.read()["layer"]["machines"][FCI]["pending"]
    assert p["add"] == {"tags": []} and p["remove"] == {"receives": []}
    s.apply([{"op": "confirm", "part": "machine", "id": FCI, "change": got["changes"][0]["change"]}], OWNER)
    assert s.read()["layer"]["machines"][FCI]["pending"] == []


def test_confirming_a_pending_change_declares_the_event_types_it_adds(tmp_path):
    s = store(tmp_path)
    confirmed(s)
    got = s.apply([{"op": "revise_machine", "id": FCI, "add": {"receives": ["new.type"]}}], SUPERVISOR)
    assert "new.type" not in s.read()["layer"]["events"]
    s.apply([{"op": "confirm", "part": "machine", "id": FCI, "change": got["changes"][0]["change"]}], OWNER)
    assert s.read()["layer"]["events"]["new.type"]["implicit"] is True


def test_a_declared_stock_named_by_a_flow_is_not_retracted_until_the_flow_is(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "id": "feat", "name": "Features"}, {"op": "declare_flow", "id": "in", "from": "a", "to": "feat"}],
            OWNER)
    with pytest.raises(IntentError, match="flow in") as e:
        s.apply([{"op": "retract", "part": "stock", "id": "feat"}], OWNER)
    assert e.value.status == 422
    s.apply([{"op": "retract", "part": "flow", "id": "in"}, {"op": "retract", "part": "stock", "id": "feat"}], OWNER)
    assert s.read()["layer"]["stocks"] == {} and s.read()["layer"]["flows"] == {}


def test_a_proposed_stock_named_by_an_expected_effect_or_a_target_is_not_discarded(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "id": "feat", "name": "Features"}, machine(),
             {"op": "set_expected_effect", "machine": FCI, "horizon_s": 60, "edits": [{"stock": "feat", "rises": True}]},
             {"op": "set_target", "part": "stock", "key": "feat", "target": "above", "value": 1, "over_s": 60}], SUPERVISOR)
    with pytest.raises(IntentError, match="the target on feat, machine feature_count_improver's expected effect"):
        s.apply([{"op": "discard", "part": "stock", "id": "feat"}], OWNER)


def test_the_owners_redeclaration_of_a_proposed_flow_declares_it(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_flow", "id": "ab", "from": "a", "to": "b"}], SUPERVISOR)
    assert s.read()["layer"]["flows"]["ab"]["state"] == "proposed"
    got = s.apply([{"op": "declare_flow", "id": "ab", "from": "a", "to": "b", "name": "a to b"}], OWNER)
    f = s.read()["layer"]["flows"]["ab"]
    assert f["state"] == "declared" and f["name"] == "a to b" and f["confirmed"] == {"by": "owner", "via": "plugin", "source": "supervisor", "change": got["changes"][0]["change"]}
    with pytest.raises(IntentError, match="already declared"):
        s.apply([{"op": "declare_flow", "id": "ab", "from": "a", "to": "b"}], SUPERVISOR)


@pytest.mark.parametrize("op", [
    {"op": "retract", "part": "stock", "id": "features"},
    {"op": "unexpect", "part": "stock", "key": "k"},
    {"op": "unignore", "part": "stock", "key": "j"},
    {"op": "set_target", "part": "stock", "id": "features", "target": "above", "value": 1, "over_s": 60},
    {"op": "set_target", "part": "stock", "key": "q", "target": "below", "value": 1, "over_s": 60}])
def test_what_the_owner_declared_is_changed_only_by_the_owner(tmp_path, op):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "name": "Features"}, {"op": "expect", "part": "stock", "key": "k"},
             {"op": "ignore", "part": "stock", "key": "j"},
             {"op": "set_target", "part": "stock", "key": "q", "target": "above", "value": 5, "over_s": 60}], OWNER)
    with pytest.raises(IntentError, match="the owner declared this: ask the owner") as e:
        s.apply([op], SUPERVISOR)
    assert e.value.status == 422
    s.apply([op], OWNER)


def test_what_the_plugin_proposed_itself_stays_its_own(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "name": "Bugs"}, {"op": "expect", "part": "stock", "key": "k"}], SUPERVISOR)
    s.apply([{"op": "unexpect", "part": "stock", "key": "k"}, {"op": "retract", "part": "stock", "id": "bugs"}], SUPERVISOR)
    assert s.read()["layer"]["stocks"] == {}


def test_retracting_an_owners_machine_answers_a_discard_request(tmp_path):
    s = store(tmp_path)
    s.apply([machine()], {**OWNER, "quote": "make me one"})
    with pytest.raises(IntentError, match="ask the owner"):
        s.apply([{"op": "retract", "part": "machine", "id": FCI}], SUPERVISOR)
    s.apply([{"op": "retract", "part": "machine", "id": FCI}], {**SUPERVISOR, "request": asked(s, "discard")})
    assert s.read()["layer"]["machines"] == {}


def test_an_expected_effect_on_a_confirmed_machine_waits_and_new_edits_drop_the_prediction(tmp_path):
    s = store(tmp_path)
    s.apply([machine(), {"op": "set_expected_effect", "machine": FCI, "horizon_s": 60, "edits": [{"stock": "a", "rises": True}]},
             {"op": "record_prediction", "machine": FCI, "prediction": "ev-p"}], SUPERVISOR)
    s.apply([{"op": "set_expected_effect", "machine": FCI, "horizon_s": 120, "edits": [{"stock": "a", "rises": True}]}], SUPERVISOR)
    assert s.read()["layer"]["machines"][FCI]["expected_effect"]["prediction"] == "ev-p"     # the same edits keep it
    s.apply([{"op": "set_expected_effect", "machine": FCI, "horizon_s": 60, "edits": [{"stock": "b", "falls": True}]}], SUPERVISOR)
    assert s.read()["layer"]["machines"][FCI]["expected_effect"]["prediction"] is None
    s.apply([{"op": "confirm", "part": "machine", "id": FCI}], OWNER)
    got = s.apply([{"op": "set_expected_effect", "machine": FCI, "horizon_s": 60, "edits": [{"stock": "c", "rises": True}]}],
                  SUPERVISOR)
    m = s.read()["layer"]["machines"][FCI]
    assert m["expected_effect"]["edits"] == [{"stock": "b", "falls": True}]
    [p] = m["pending"]
    assert p["set"]["expected_effect"]["edits"] == [{"stock": "c", "rises": True}] and p["set"]["expected_effect"]["prediction"] is None
    s.apply([{"op": "confirm", "part": "machine", "id": FCI, "change": got["changes"][0]["change"]}], OWNER)
    assert s.read()["layer"]["machines"][FCI]["expected_effect"]["edits"] == [{"stock": "c", "rises": True}]


def test_the_owners_pending_change_overrides_another_on_the_same_fields(tmp_path):
    from orchestra.sd.intended.machines_view import intent_of

    s = store(tmp_path)
    confirmed(s)
    mine = s.apply([{"op": "revise_machine", "id": FCI, "set": {"engagement": {"mode": "scheduled", "at": "00:00"}}}],
                   {**OWNER, "quote": "12am every day"})["changes"][0]["change"]
    theirs = s.apply([{"op": "revise_machine", "id": FCI, "set": {"engagement": {"mode": "ad hoc"}}}],
                     SUPERVISOR)["changes"][0]["change"]
    other = s.apply([{"op": "revise_machine", "id": FCI, "set": {"title": "FCI"}}], SUPERVISOR)["changes"][0]["change"]
    layer = s.read()["layer"]
    pend = {p["change"]: p for p in intent_of(layer["machines"][FCI], layer, False, None, None, {})["pending"]}
    assert pend[theirs]["overridden_by"] == mine and "overridden_by" not in pend[mine] and "overridden_by" not in pend[other]
    assert "overridden_by" not in layer["machines"][FCI]["pending"][1]        # derived on read, never stored
    with pytest.raises(IntentError, match="owner's unanswered request"):         # a request for another change
        s.apply([{"op": "confirm", "part": "machine", "id": FCI, "change": theirs}],
                {**SUPERVISOR, "request": asked(s, "confirm", change=mine)})
    s.apply([{"op": "confirm", "part": "machine", "id": FCI, "change": theirs}],
            {**SUPERVISOR, "request": asked(s, "confirm", change=theirs)})
    assert s.read()["layer"]["machines"][FCI]["engagement"] == {"mode": "ad hoc"}


@pytest.mark.parametrize("ops", [
    [{"op": "confirm", "part": "machine", "id": FCI}],
    [{"op": "discard", "part": "attachment", "id": "x"}],
    [{"op": "declare_stock", "name": "Bugs"}],
    [{"op": "expect", "part": "stock", "key": "a"}, {"op": "expect", "part": "stock", "key": "b"}]])
def test_a_page_call_is_one_control_of_the_closed_list(tmp_path, ops):
    s = store(tmp_path)
    s.apply([machine()], SUPERVISOR)
    with pytest.raises(IntentError, match="one observation") as e:
        s.apply(ops, {"author": "owner", "control": "confirm"}, via="page")
    assert e.value.status == 400 and s.current_version() == 1
