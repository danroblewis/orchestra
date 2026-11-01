"""What is the owner's in the declared layer (docs/proposals/intended-model.md §3, §4): the owner's
marks, event types and confirmed elements are changed only with the owner's consent; a key is
expected or ignored, never both; what a pending change names is not retracted; the owner's own
quoted words are never refused."""

import pytest

from orchestra.sd.intended import IntentError, requests
from orchestra.sd.intended.consent import ASK_THE_OWNER
from orchestra.sd.intended.machines_view import intent_of
from orchestra.sd.store import ModelStore

OWNER = {"author": "owner", "source": "supervisor", "quote": "yes, that one"}
SUPERVISOR = {"author": "supervisor", "source": "supervisor"}
PAGE = {"author": "owner", "control": "expect", "page": "dynamics"}
FCI = "feature_count_improver"


class Bus:
    def publish(self, type_, data, **kw):
        return {"id": kw["id"]}


def store(tmp_path):
    return ModelStore(tmp_path / "model").intended()


def machine(mid=FCI, **kw):
    return {"op": "propose_machine", "id": mid, "kind": "universal", "engagement": {"mode": "continuous"},
            "receives": ["session.settled"], **kw}


def asked(s, control, eid=FCI, part="machine", change=None) -> str:
    return requests.publish(s, Bus(), {"control": control, "part": part, "id": eid, "change": change})["id"]


def marks(s):
    return s.read()["layer"]["marks"]


def test_another_authors_re_mark_leaves_the_owners_mark_and_provenance(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "expect", "part": "stock", "key": "k"}], PAGE, via="page")
    mine = marks(s)["expected"]["k"]
    with pytest.raises(IntentError, match=ASK_THE_OWNER):
        s.apply([{"op": "expect", "part": "stock", "key": "k"}, {"op": "unexpect", "part": "stock", "key": "k"}], SUPERVISOR)
    s.apply([{"op": "expect", "part": "stock", "key": "k"}], SUPERVISOR)
    with pytest.raises(IntentError, match=ASK_THE_OWNER):
        s.apply([{"op": "unexpect", "part": "stock", "key": "k"}], SUPERVISOR)
    assert marks(s)["expected"]["k"] == mine and mine["provenance"]["via"] == "page"


def test_a_key_is_expected_or_ignored_never_both(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "expect", "part": "stock", "key": "k"}], OWNER)
    s.apply([{"op": "ignore", "part": "stock", "key": "k"}], OWNER)
    assert "k" not in marks(s)["expected"] and "k" in marks(s)["ignored"]
    s.apply([{"op": "expect", "part": "stock", "key": "k"}], OWNER)
    assert "k" in marks(s)["expected"] and "k" not in marks(s)["ignored"]


def test_another_authors_ignore_of_the_owners_expected_key_is_refused(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "expect", "part": "flow", "key": "a -> b"}], OWNER)
    with pytest.raises(IntentError, match=ASK_THE_OWNER):
        s.apply([{"op": "ignore", "part": "flow", "key": "a -> b"}], SUPERVISOR)
    assert "a -> b" in marks(s)["expected"] and marks(s)["ignored"] == {}


def test_the_owners_event_type_is_neither_redescribed_nor_retracted_by_another(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_event", "type": "a.b", "description": "the owner's words"}], OWNER)
    for op in ({"op": "declare_event", "type": "a.b", "description": "mine now"}, {"op": "retract", "part": "event", "id": "a.b"}):
        with pytest.raises(IntentError, match=ASK_THE_OWNER):
            s.apply([op], SUPERVISOR)
    assert s.read()["layer"]["events"]["a.b"]["description"] == "the owner's words"


def test_an_undescribed_event_type_is_described_by_anyone(tmp_path):
    s = store(tmp_path)
    s.apply([machine()], {**OWNER, "quote": "watch the sessions"})
    assert s.read()["layer"]["events"]["session.settled"]["implicit"] is True
    s.apply([{"op": "declare_event", "type": "session.settled", "description": "a session ended"}], SUPERVISOR)
    assert s.read()["layer"]["events"]["session.settled"]["description"] == "a session ended"


def test_an_event_type_a_machine_names_is_not_retracted(tmp_path):
    s = store(tmp_path)
    s.apply([machine(emits=["work.requested"])], SUPERVISOR)
    with pytest.raises(IntentError, match=f"event work.requested is named by machine {FCI}: change the machine first"):
        s.apply([{"op": "retract", "part": "event", "id": "work.requested"}], OWNER)
    s.apply([{"op": "declare_event", "type": "other.type", "description": "unused"}], OWNER)
    s.apply([{"op": "retract", "part": "event", "id": "other.type"}], OWNER)
    assert "other.type" not in s.read()["layer"]["events"]


def test_the_owners_confirmation_makes_a_proposal_the_owners(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "id": "bugs", "name": "Bugs"}], SUPERVISOR)
    got = s.apply([{"op": "confirm", "part": "stock", "id": "bugs"}], {"author": "owner", "control": "confirm"}, via="page")
    assert s.read()["layer"]["stocks"]["bugs"]["confirmed"] == {"by": "owner", "change": got["changes"][0]["change"]}
    for op in ({"op": "retract", "part": "stock", "id": "bugs"},
               {"op": "set_target", "part": "stock", "id": "bugs", "target": "below", "value": 3, "over_s": 60}):
        with pytest.raises(IntentError, match=ASK_THE_OWNER):
            s.apply([op], SUPERVISOR)
    s.apply([{"op": "retract", "part": "stock", "id": "bugs"}], OWNER)          # the owner's quoted retract
    assert s.read()["layer"]["stocks"] == {}


def test_a_confirmed_machine_is_the_owners_and_its_intent_says_who_confirmed(tmp_path):
    s = store(tmp_path)
    s.apply([machine()], SUPERVISOR)
    rid = asked(s, "confirm")
    got = s.apply([{"op": "confirm", "part": "machine", "id": FCI}], {**SUPERVISOR, "request": rid})
    layer = s.read()["layer"]
    m = layer["machines"][FCI]
    assert m["confirmed"] == {"by": "owner", "via": "request", "request": rid, "change": got["changes"][0]["change"]}
    assert intent_of(m, layer, False, None, None, {})["confirmed"] == m["confirmed"]
    with pytest.raises(IntentError, match=ASK_THE_OWNER):
        s.apply([{"op": "retract", "part": "machine", "id": FCI}], SUPERVISOR)


def test_a_target_set_on_the_owners_element_is_the_setters(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "id": "bugs", "name": "Bugs"}], SUPERVISOR)
    s.apply([{"op": "set_target", "part": "stock", "id": "bugs", "target": "below", "value": 3, "over_s": 60}], SUPERVISOR)
    s.apply([{"op": "confirm", "part": "stock", "id": "bugs"}], OWNER)
    s.apply([{"op": "set_target", "part": "stock", "id": "bugs", "target": "below", "value": 2, "over_s": 60}], SUPERVISOR)
    s.apply([{"op": "set_target", "part": "stock", "id": "bugs", "target": "below", "value": 1, "over_s": 60}], OWNER)
    el = s.read()["layer"]["stocks"]["bugs"]
    assert el["target"] == {"op": "below", "value": 1.0, "over_s": 60.0} and el["target_by"]["provenance"]["author"] == "owner"
    with pytest.raises(IntentError, match=ASK_THE_OWNER):
        s.apply([{"op": "set_target", "part": "stock", "id": "bugs", "target": "below", "value": 9, "over_s": 60}], SUPERVISOR)


def test_the_owners_quoted_confirm_of_an_overridden_change_applies(tmp_path):
    s = store(tmp_path)
    s.apply([machine()], SUPERVISOR)
    s.apply([{"op": "confirm", "part": "machine", "id": FCI}], OWNER)
    s.apply([{"op": "revise_machine", "id": FCI, "set": {"title": "Owner's"}}], {**OWNER, "quote": "call it that"})
    theirs = s.apply([{"op": "revise_machine", "id": FCI, "set": {"title": "Theirs"}}], SUPERVISOR)["changes"][0]["change"]
    with pytest.raises(IntentError, match="confirmed by the owner"):
        s.apply([{"op": "confirm", "part": "machine", "id": FCI, "change": theirs}], SUPERVISOR)
    s.apply([{"op": "confirm", "part": "machine", "id": FCI, "change": theirs}], {**OWNER, "quote": "take the Supervisor's title"})
    assert s.read()["layer"]["machines"][FCI]["title"] == "Theirs"


def test_the_owners_quoted_rename_of_a_declared_flow_applies(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_flow", "id": "ab", "from": "a", "to": "b"}], OWNER)
    s.apply([{"op": "set_target", "part": "flow", "id": "ab", "target": "above", "value": 5, "over_s": 86400}], OWNER)
    s.apply([{"op": "declare_flow", "id": "ab", "from": "a", "to": "b", "name": "landed"}], {**OWNER, "quote": "call that flow landed"})
    f = s.read()["layer"]["flows"]["ab"]
    assert f["name"] == "landed" and f["state"] == "declared" and f["target"]["value"] == 5.0
    assert f["provenance"]["quote"] == "yes, that one" and f["latest"]["before"] == {"name": "a → b"}
    with pytest.raises(IntentError, match="flow ab is already declared"):
        s.apply([{"op": "declare_flow", "id": "ab", "from": "a", "to": "b", "name": "x"}], SUPERVISOR)


def test_a_stock_a_pending_change_names_is_not_retracted(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "id": "features", "name": "Features"}, machine()], OWNER)
    s.apply([{"op": "confirm", "part": "machine", "id": FCI}], OWNER)
    got = s.apply([{"op": "set_expected_effect", "machine": FCI, "horizon_s": 60, "edits": [{"stock": "features", "rises": True}]}],
                  SUPERVISOR)
    cid = got["changes"][0]["change"]
    assert s.read()["layer"]["machines"][FCI]["expected_effect"] is None
    with pytest.raises(IntentError, match=f"machine {FCI}'s pending change {cid}"):
        s.apply([{"op": "retract", "part": "stock", "id": "features"}], OWNER)


@pytest.mark.parametrize("author", ["owner", "supervisor"])
def test_nothing_writes_as_the_host_until_inference_does(tmp_path, author):
    with pytest.raises(IntentError, match="via is one of plugin, endpoint, page") as e:
        store(tmp_path).apply([{"op": "declare_stock", "name": "Bugs"}], {"author": author}, via="host")
    assert e.value.status == 400
