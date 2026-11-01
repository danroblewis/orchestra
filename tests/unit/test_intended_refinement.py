"""A refinement's marks (E2, ``refinement.py``): ``latest`` is the machine as it stands against its
baseline (as first declared while proposed, as last confirmed after), across every op since, by
key, never only the last op's change; each op still cuts its own ``dN``."""

from test_intended_store import OWNER, SUPERVISOR, answer, machine, store

from orchestra.sd.intended.machines_view import merge

FCI = "feature_count_improver"


def said(quote: str) -> dict:
    return {**OWNER, "quote": quote}


def revise(s, quote: str, **parts) -> None:
    s.apply([{"op": "revise_machine", "id": FCI, **parts}], said(quote))


def refined_three_times(tmp_path):
    s = store(tmp_path)
    s.apply([machine(receives=["session.settled", "task.requested"])], SUPERVISOR)
    first = s.current_version()
    revise(s, "watch the gate too", add={"receives": ["gate.rejected", "gate.landed"]})
    revise(s, "it doesn't need task.requested", remove={"receives": ["task.requested"]})
    revise(s, "make it nightly", set={"engagement": {"mode": "scheduled", "at": "00:00"}})
    return s, first


def test_every_op_of_the_refinement_is_marked_against_the_first_declaration(tmp_path):
    s, first = refined_three_times(tmp_path)
    assert s.current_version() == first + 3                        # one dN per op
    m = s.read()["layer"]["machines"][FCI]
    assert m["receives"] == ["session.settled", "gate.rejected", "gate.landed"]
    latest = m["latest"]
    assert latest["added"] == {"receives": ["gate.rejected", "gate.landed"]}
    assert latest["removed"] == {"receives": ["task.requested"]}  # removed by the second op, still marked after the third
    assert latest["before"] == {"engagement": {"mode": "continuous"}}
    assert latest["quotes"] == ["watch the gate too", "it doesn't need task.requested", "make it nightly"]
    assert len(latest["changes"]) == 3 and latest["change"] == latest["changes"][-1]


def test_the_page_draws_every_removed_receive_as_a_ghost(tmp_path):
    s, _ = refined_three_times(tmp_path)
    out = {"machines": [], "edges": []}
    merge(out, s)
    gone = {e["from"] for e in out["intended_edges"] if e["gone"]}
    drawn = {e["from"] for e in out["intended_edges"] if not e["gone"] and e["kind"] == "subscribes"}
    assert gone == {"task.requested"} and drawn == {"session.settled", "gate.rejected", "gate.landed"}
    assert out["machines"][0]["intent"]["latest"]["added"] == {"receives": ["gate.rejected", "gate.landed"]}


def test_a_change_undone_later_in_the_refinement_is_no_change(tmp_path):
    s = store(tmp_path)
    s.apply([machine()], SUPERVISOR)
    revise(s, "add the gate", add={"receives": ["gate.rejected"]}, remove={"receives": ["session.settled"]})
    revise(s, "no, as it was", add={"receives": ["session.settled"]}, remove={"receives": ["gate.rejected"]})
    revise(s, "rewrite the steps", set={"spec": {"steps": ["c"], "invariants": ["x"]}})
    revise(s, "rewrite them again", set={"spec": {"steps": ["d"], "invariants": ["x"]}})
    latest = s.read()["layer"]["machines"][FCI]["latest"]
    assert latest["added"] == {} and latest["removed"] == {}
    assert latest["before"] == {"steps": ["b", "a"], "present": "spec is opaque"}   # the first declaration's, by key


def test_a_confirmation_starts_a_new_baseline(tmp_path):
    s, _ = refined_three_times(tmp_path)
    s.apply([{"op": "confirm", "part": "machine", "id": FCI}], answer(s, "confirm"))
    got = s.apply([{"op": "revise_machine", "id": FCI, "add": {"receives": ["changes.requested"]}}], said("and reviews"))
    change = got["changes"][0]["change"]
    s.apply([{"op": "confirm", "part": "machine", "id": FCI, "change": change}], OWNER)
    latest = s.read()["layer"]["machines"][FCI]["latest"]
    assert latest["added"] == {"receives": ["changes.requested"]} and latest["removed"] == {} and latest["before"] == {}
    assert latest["changes"] == [change]
