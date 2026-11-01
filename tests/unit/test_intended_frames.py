"""The Machines page's frames E1–E4 seeded through the intended model's ops, read back through the
real ``/api/machines``: the observed machines replayed from the capture, the declared machine with
the fields each frame draws (docs/proposals/intended-model.md §6.1, §7)."""

import time

import pytest
from intended_frames import ADDED, EMIT, FCI, NM, REMOVED, SAIL, replay_observed, seed_frame
from intended_seed import project_at
from test_intended_api_shapes import client, machines


def answer(tmp_path, monkeypatch, frame):
    project = project_at(tmp_path, monkeypatch)
    replay_observed(project)
    project = seed_frame(project, frame)
    got = machines(client(project))
    for _ in range(50):                         # the background reader folds the replay in
        if {"worker", "reviewer", "coordinator"} <= {m["id"] for m in got["machines"]}:
            break
        got = machines(client(project))
    return got, {m["id"]: m for m in got["machines"]}


def test_e1_a_proposed_universal_machine_with_its_declared_links(tmp_path, monkeypatch):
    got, ms = answer(tmp_path, monkeypatch, "E1")
    assert {"worker", "reviewer", "coordinator", "merge_gate", "planner", "supervisor"} <= set(ms)
    assert ms["worker"]["intent"] is None and ms["worker"]["publishes"]
    it = ms[FCI]["intent"]
    assert ms[FCI]["unseen"] and it["state"] == "proposed" and it["author"] == "supervisor" and not it["heard"]
    assert list(it["spec"]) == ["invariants", "steps", "uses"]          # the order it was declared in
    assert it["guessed"] == ["receives[0]", "receives[1]"]
    labels = [e["label"] for e in it["expected_effect"]["edits"]]
    assert labels[0] == "Features ↑" and labels[1] == "tasks gate runs (landed) ×1.2"
    assert [e["publishable"] for e in it["expected_effect"]["edits"]][:2] == [False, True]
    emits = [e for e in got["intended_edges"] if e["kind"] == "publishes"]
    assert emits == [{"from": FCI, "to": EMIT, "kind": "publishes", "state": "proposed", "observed": False, "gone": False}]
    assert {"type": EMIT, "description": "one idea to remove a cause of rejected work, with its evidence", "implicit": False} in got["intended_types"]


def test_e2_the_owner_revision_is_the_latest_change(tmp_path, monkeypatch):
    got, ms = answer(tmp_path, monkeypatch, "E2")
    it = ms[FCI]["intent"]
    assert it["latest"]["added"] == {"receives": ADDED} and it["latest"]["removed"] == {"receives": REMOVED}
    assert it["latest"]["before"]["engagement"] == {"mode": "continuous"} and "steps" in it["latest"]["before"]
    assert it["engagement"] == {"mode": "scheduled", "at": "00:00", "tz": "America/Los_Angeles", "missed": "skip"}
    assert it["guessed"] == []                                          # receives was set: no longer a guess
    gone = {e["from"] for e in got["intended_edges"] if e["gone"]}
    assert gone == set(REMOVED)


@pytest.mark.parametrize("frame,managed,mode,first", [("E3", "orchestra", "ad hoc", "command"),
                                                       ("E3-continuous", "orchestra", "continuous", "command"),
                                                       ("E3-external", "external", "continuous", "source")])
def test_e3_programmatic_forms(tmp_path, monkeypatch, frame, managed, mode, first):
    _, ms = answer(tmp_path, monkeypatch, frame)
    it = ms[NM]["intent"]
    assert it["kind"] == "programmatic" and it["managed"] == managed and it["engagement"]["mode"] == mode
    assert it["author"] == "owner" and it["state"] == "proposed" and next(iter(it["spec"])) == first


def test_e4_a_declared_machine_never_heard_with_an_attachment(tmp_path, monkeypatch):
    got, ms = answer(tmp_path, monkeypatch, "E4")
    it = ms[SAIL]["intent"]
    assert it["state"] == "declared" and not it["heard"] and it["managed"] == "external"
    assert [(a["instrument"], a["state"], a["instance_label"]) for a in it["attachments"]] == [("company_prom", "declared", "runner")]
    assert not [e for e in got["intended_edges"] if SAIL in (e["from"], e["to"])]


def test_e4_is_measured_by_its_attachment_and_never_heard(tmp_path, monkeypatch):
    def measured(g):
        ms = next(x for x in g["machines"] if x["id"] == SAIL).get("measured") or {}
        return ms.get("attachments") and not ms.get("unknown")

    project = seed_frame(project_at(tmp_path, monkeypatch), "E4")
    c = client(project)
    got = machines(c)
    for _ in range(100):
        if measured(got):
            break
        time.sleep(0.2)
        got = machines(c)
    sail = next(x for x in got["machines"] if x["id"] == SAIL)
    assert sail["comparison"] == "measured, never heard" and sail["last_seen"] is None and not sail["active"]
    ms = sail["measured"]
    assert ms["measured"] and ms["instances"] == 3 and ms["instruments"] == ["company_prom"]
    inst = ms["attachments"][0]["instances"]
    assert inst["label"] == "runner" and [i["value"] for i in inst["list"]] == ["runner-1", "runner-2", "runner-3"]
