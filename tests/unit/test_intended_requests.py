"""The owner's requests (docs/proposals/intended-model.md §6.2; §10 test 16): a call may cite only
an open request; only an op that answers one clears it; a request that can no longer be acted on
drops out; a request is noted before it is published; a torn journal line never swallows the
next call."""

import json

import pytest

from orchestra.sd.intended import IntentError, lines, requests
from orchestra.sd.store import ModelStore

OWNER = {"author": "owner", "source": "supervisor", "quote": "yes"}
SUPERVISOR = {"author": "supervisor", "source": "supervisor"}
FCI = "feature_count_improver"


class Bus:
    def __init__(self, during=None):
        self.during = during

    def publish(self, type_, data, **kw):
        ev = {"id": kw["id"], "type": type_, "data": data}
        if self.during:
            self.during(ev)
        return ev


def store(tmp_path):
    s = ModelStore(tmp_path / "model").intended()
    s.apply([{"op": "propose_machine", "id": FCI}, {"op": "propose_machine", "id": "other"}], SUPERVISOR)
    return s


def asked(s, control, eid=FCI, change=None, bus=None) -> str:
    return requests.publish(s, bus or Bus(), {"control": control, "part": "machine", "id": eid, "change": change})["id"]


def test_a_made_up_request_is_refused_even_on_an_op_that_needs_no_consent(tmp_path):
    s = store(tmp_path)
    with pytest.raises(IntentError, match="provenance.request ev-made-up is not one of the owner's unanswered requests") as e:
        s.apply([{"op": "declare_event", "type": "a.b", "description": "x"}], {**SUPERVISOR, "request": "ev-made-up"})
    assert e.value.status == 422 and s.current_version() == 1


def test_only_an_op_that_answers_a_request_clears_it(tmp_path):
    s = store(tmp_path)
    rid = asked(s, "confirm")
    s.apply([{"op": "declare_event", "type": "a.b", "description": "x"}], {**SUPERVISOR, "request": rid})
    assert rid in requests.open_requests(s) and "answered" not in s.journal()[-1]
    s.apply([{"op": "confirm", "part": "machine", "id": FCI}], {**SUPERVISOR, "request": rid})
    assert rid not in requests.open_requests(s) and s.journal()[-1]["answered"] == [rid]


def test_a_request_settled_another_way_drops_out(tmp_path):
    s = store(tmp_path)
    rid, gone = asked(s, "confirm"), asked(s, "discard", "other")
    s.apply([{"op": "confirm", "part": "machine", "id": FCI}], {**OWNER, "quote": "yes, confirm it"})   # the owner's quote
    s.apply([{"op": "retract", "part": "machine", "id": "other"}], SUPERVISOR)
    assert requests.open_requests(s) == {} and requests.unanswered(s) == {}
    assert not [o for o in s.design(hold=3)["open"] if o["what"] == "unanswered request"]
    with pytest.raises(IntentError, match="not one of the owner's unanswered requests"):
        s.apply([{"op": "discard", "part": "machine", "id": FCI}], {**SUPERVISOR, "request": rid})
    assert gone not in requests.open_requests(s)


def test_a_request_for_a_change_drops_out_once_the_change_is_settled(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "confirm", "part": "machine", "id": FCI}], OWNER)
    cid = s.apply([{"op": "revise_machine", "id": FCI, "set": {"title": "A"}}], SUPERVISOR)["changes"][0]["change"]
    rid = asked(s, "confirm", change=cid)
    s.apply([{"op": "discard", "part": "machine", "id": FCI, "change": cid}], OWNER)
    assert rid not in requests.open_requests(s)


def test_a_confirm_request_on_a_declared_element_is_a_409(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "confirm", "part": "machine", "id": FCI}], OWNER)
    for control in ("confirm", "discard"):
        with pytest.raises(IntentError, match="is declared, not proposed") as e:
            asked(s, control)
        assert e.value.status == 409
    asked(s, "switch_kind")                                 # a switch is asked of a confirmed machine too


def test_design_lists_every_open_request(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "confirm", "part": "machine", "id": FCI}], OWNER)
    a = s.apply([{"op": "revise_machine", "id": FCI, "set": {"title": "A"}}], SUPERVISOR)["changes"][0]["change"]
    b = s.apply([{"op": "revise_machine", "id": FCI, "set": {"description": "B"}}], SUPERVISOR)["changes"][0]["change"]
    ra, rb = asked(s, "confirm", change=a), asked(s, "confirm", change=b)
    listed = [(o["event"], o["change"]) for o in s.design(hold=3)["open"] if o["what"] == "unanswered request"]
    assert listed == [(ra, a), (rb, b)]
    assert requests.unanswered(s)[("machine", FCI)]["event"] == rb


def test_a_plugin_answering_inside_the_publish_finds_the_request_open(tmp_path):
    s = store(tmp_path)

    def answer(ev):
        s.apply([{"op": "confirm", "part": "machine", "id": FCI}], {**SUPERVISOR, "request": ev["id"]})
    rid = asked(s, "confirm", bus=Bus(answer))
    assert s.read()["layer"]["machines"][FCI]["state"] == "declared" and s.journal()[-1]["answered"] == [rid]


def test_a_request_whose_publish_fails_is_not_left_noted(tmp_path):
    s = store(tmp_path)
    keep = asked(s, "confirm", "other")

    class Down:
        def publish(self, *a, **kw):
            raise OSError("the bus is down")
    with pytest.raises(OSError):
        requests.publish(s, Down(), {"control": "confirm", "part": "machine", "id": FCI})
    assert [r["event"] for r in requests.noted(s)] == [keep]


def test_a_torn_journal_line_never_swallows_the_next_call(tmp_path):
    s = store(tmp_path)
    j = s.dir / "journal.jsonl"
    j.write_text(j.read_text() + '{"seq": 2, "at": 1, "provenance"', encoding="utf-8")
    got = s.apply([{"op": "declare_event", "type": "a.b", "description": "x"}], OWNER)
    assert [e["seq"] for e in s.journal()] == [1, got["version"]]
    p = tmp_path / "x.jsonl"
    lines.append(p, {"a": 1})
    lines.append(p, {"b": 2})
    assert [json.loads(x) for x in p.read_text().splitlines()] == [{"a": 1}, {"b": 2}]
