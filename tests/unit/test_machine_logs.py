"""A machine's announced log is read only within the project; its recent events are envelopes."""

import os

from orchestra.web.machine_logs import readable, tail
from orchestra.web.machines import MachineIndex, _ListBus, machines_view


def test_a_log_inside_the_project_is_read(tmp_path):
    (tmp_path / "run").mkdir()
    log = tmp_path / "run" / "baker-1.log"
    log.write_text("".join(f"line {i}\n" for i in range(500)))
    path, why = readable(str(log), [tmp_path])
    assert why is None and tail(path, 3) == ["line 497", "line 498", "line 499"]


def test_anything_outside_the_project_is_refused(tmp_path):
    root, outside = tmp_path / "repo", tmp_path / "secret"
    root.mkdir(); outside.mkdir()
    (outside / "key").write_text("no")
    assert readable(str(outside / "key"), [root])[0] is None
    assert readable(str(root / ".." / "secret" / "key"), [root])[0] is None       # no climbing out
    os.symlink(outside / "key", root / "link.log")
    assert readable(str(root / "link.log"), [root])[0] is None                    # nor through a link
    assert readable(str(root), [root])[0] is None                                 # a directory is not a log
    assert readable(None, [root])[1].startswith("this machine has not said")


def test_the_index_keeps_announced_logs_and_recent_envelopes():
    evs = [{"type": "orchestra.machine.started", "source": "baker/1", "time": "2026-10-25T00:00:00Z",
            "data": {"mode": "continuous", "listens_for": ["order.assigned"], "log": "/repo/run/baker-1.log"}},
           {"type": "order.baked", "source": "baker/1", "time": "2026-10-25T00:00:05Z", "subject": "o1", "id": "e1", "data": {"secret": 1}}]
    idx = MachineIndex(_ListBus(evs)); idx.update()
    assert idx.log_path("baker", "1") == "/repo/run/baker-1.log" and idx.log_path("baker", None) == "/repo/run/baker-1.log"
    [e] = idx.events_of("baker")
    assert e["type"] == "order.baked" and e["instance"] == "1" and e["subject"] == "o1" and "data" not in e
    [m] = [m for m in machines_view(evs)["machines"] if m["id"] == "baker"]
    assert m["logs"] == ["1"]


def test_hand_offs_are_inferred_from_events_about_the_same_subject():
    ev = lambda src, ty, subj: {"type": ty, "source": src, "subject": subj, "time": "2026-10-25T00:00:00Z"}
    evs = [ev("counter", "order.placed", "o1"), ev("baker/1", "order.baking", "o1"), ev("baker/1", "order.baked", "o1"),
           ev("packer/2", "order.boxed", "o1"), ev("counter", "order.placed", "o2"), ev("baker/3", "order.baking", "o2")]
    h = {(x["from"], x["via"], x["to"]): x["count"] for x in machines_view(evs)["handoffs"]}
    # the same machine twice in a row is no hand-off; each records the event the next machine followed
    assert h == {("counter", "order.placed", "baker"): 2, ("baker", "order.baked", "packer"): 1}


def test_a_hand_off_is_credited_to_an_event_the_receiver_listens_for():
    ev = lambda src, ty, subj: {"type": ty, "source": src, "subject": subj, "time": "2026-10-25T00:00:00Z"}
    # A publishes X then Y about the subject; B, which announced it listens for X, acts next: the
    # hand-off went via X, whatever A said last. Without the announcement, via the last event.
    announced = [{"type": "orchestra.machine.started", "source": "b/1", "time": "2026-10-25T00:00:00Z", "data": {"listens_for": ["X"]}}]
    work = [ev("a", "X", "s1"), ev("a", "Y", "s1"), ev("b/1", "Z", "s1")]
    h = lambda evs: {(x["from"], x["via"], x["to"]) for x in machines_view(evs)["handoffs"]}
    assert h(announced + work) == {("a", "X", "b")}
    assert h(work) == {("a", "Y", "b")}


def test_a_hand_off_to_a_machine_that_announced_it_listens_for_none_of_the_senders_events_has_no_type():
    ev = lambda src, ty, subj: {"type": ty, "source": src, "subject": subj, "time": "2026-10-25T00:00:00Z"}
    # B announced it listens for W only; A's events about the subject were X and Y: the hand-off
    # is counted, with no event credited (an announcement is not overruled by a guess), and the
    # view carries it with via null
    announced = [{"type": "orchestra.machine.started", "source": "b/1", "time": "2026-10-25T00:00:00Z", "data": {"listens_for": ["W"]}}]
    work = [ev("a", "X", "s1"), ev("a", "Y", "s1"), ev("b/1", "Z", "s1")]
    [h] = machines_view(announced + work)["handoffs"]
    assert (h["from"], h["via"], h["to"], h["count"]) == ("a", None, "b", 1)


def test_what_a_machine_announces_about_itself_is_read_once():
    evs = [{"type": "orchestra.machine.started", "source": "baker/1", "time": "2026-10-25T00:00:00Z",
            "data": {"mode": "ad_hoc", "kind": "agent", "package": "bakery", "listens_for": ["order.placed"], "team": "morning"}}]
    [m] = [m for m in machines_view(evs)["machines"] if m["id"] == "baker"]
    assert (m["mode"], m["kind"], m["package"], m["subscribes"]) == ("ad_hoc", "agent", "bakery", ["order.placed"])
    assert m["about"] == {"team": "morning"}, "the rest of the announcement is the package's, passed on unread"
    [host] = [m for m in machines_view(evs)["machines"] if m["bootstrap"]]
    assert host["kind"] == "program"
