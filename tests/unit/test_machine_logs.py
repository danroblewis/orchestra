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
    hs = machines_view(evs)["handoffs"]
    h = {(x["from"], x["via"], x["to"]): x["count"] for x in hs}
    # the same machine twice in a row is no hand-off; with nothing announced, no type is credited,
    # and the sender's last event before it is said apart (``after``)
    assert h == {("counter", None, "baker"): 2, ("baker", None, "packer"): 1}
    assert {(x["from"], x["after"]) for x in hs} == {("counter", "order.placed"), ("baker", "order.baked")}


def test_a_subject_handed_on_through_a_machine_is_a_relay_from_the_one_before_it():
    ev = lambda src, ty, subj: {"type": ty, "source": src, "subject": subj, "time": "2026-10-25T00:00:00Z"}
    # a worker finishes, the planner offers the next step, a reviewer takes it: the planner relayed
    # the subject from the worker to the reviewer (the Machines page draws worker → reviewer through it)
    evs = [ev("planner", "x.made", "i1"), ev("worker/1", "x.done", "i1"), ev("planner", "x.made", "i1"), ev("reviewer/1", "x.done", "i1"),
           ev("planner", "x.made", "i1"), ev("worker/2", "x.done", "i1")]
    r = {(x["from"], x["through"], x["to"]): x["count"] for x in machines_view(evs)["relays"]}
    # back to the machine it came from (planner → worker → planner) is no relay
    assert r == {("worker", "planner", "reviewer"): 1, ("reviewer", "planner", "worker"): 1}


def test_a_hand_off_is_credited_to_an_event_the_receiver_listens_for():
    ev = lambda src, ty, subj: {"type": ty, "source": src, "subject": subj, "time": "2026-10-25T00:00:00Z"}
    # A publishes X then Y about the subject; B, which announced it listens for X, acts next: the
    # hand-off went via X, whatever A said last. Without the announcement, via none (A's last, Y, is ``after``).
    announced = [{"type": "orchestra.machine.started", "source": "b/1", "time": "2026-10-25T00:00:00Z", "data": {"listens_for": ["X"]}}]
    work = [ev("a", "X", "s1"), ev("a", "Y", "s1"), ev("b/1", "Z", "s1")]
    h = lambda evs: {(x["from"], x["via"], x["to"]) for x in machines_view(evs)["handoffs"]}
    assert h(announced + work) == {("a", "X", "b")}
    assert h(work) == {("a", None, "b")} and machines_view(work)["handoffs"][0]["after"] == "Y"


def test_a_hand_off_is_credited_to_a_type_a_family_pattern_takes():
    ev = lambda src, ty, subj: {"type": ty, "source": src, "subject": subj, "time": "2026-10-25T00:00:00Z"}
    announced = [{"type": "orchestra.machine.started", "source": "b/1", "time": "2026-10-25T00:00:00Z", "data": {"listens_for": ["x.*"]}}]
    work = [ev("a", "x.made", "s1"), ev("a", "y.done", "s1"), ev("b/1", "z", "s1")]
    assert {(x["from"], x["via"], x["to"]) for x in machines_view(announced + work)["handoffs"]} == {("a", "x.made", "b")}


def test_listened_for_events_that_arrive_after_a_machines_last_event_are_unanswered():
    t = lambda s: f"2026-10-25T00:{s // 60:02d}:{s % 60:02d}Z"
    evs = [{"type": "orchestra.machine.started", "source": "b/1", "time": t(0), "data": {"listens_for": ["job.*", "other"]}},
           {"type": "job.made", "source": "a", "time": t(10)}, {"type": "job.done", "source": "b/1", "time": t(20)},
           {"type": "job.made", "source": "a", "time": t(30)}, {"type": "job.made", "source": "a", "time": t(40)},
           {"type": "job.done", "source": "c", "time": t(50)}, {"type": "unrelated", "source": "a", "time": t(60)}]
    [b] = [m for m in machines_view(evs, now=1_761_350_500.0)["machines"] if m["id"] == "b"]
    from orchestra.events import event_time
    assert b["unanswered"] == {"job.*": {"count": 3, "since": event_time(evs[3])}}       # its own job.done is no answer to wait for
    [a] = [m for m in machines_view(evs)["machines"] if m["id"] == "a"]
    assert "unanswered" not in a                                                       # listens for nothing
    # another listener of job.* that acted after them answered them: b is not left holding them
    other = [{"type": "orchestra.machine.started", "source": "d/1", "time": t(1), "data": {"listens_for": ["job.made"]}},
             {"type": "job.taken", "source": "d/1", "time": t(70)}]
    [b2] = [m for m in machines_view(evs + other, now=1_761_350_500.0)["machines"] if m["id"] == "b"]
    assert b2["unanswered"]["job.*"]["count"] == 2      # only c's job.done and d's job.taken, which b alone listens for; d took the job.made


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
            "data": {"mode": "ad_hoc", "kind": "agent", "package": "bakery", "listens_for": ["order.placed"], "team": "morning", "shift": "early"}}]
    [m] = [m for m in machines_view(evs)["machines"] if m["id"] == "baker"]
    assert (m["mode"], m["kind"], m["package"], m["subscribes"]) == ("ad_hoc", "agent", "bakery", ["order.placed"])
    assert m["about"] == {"shift": "early"}, "the rest of the announcement is the package's, passed on unread"
    assert m["group"] == "morning"                     # team is read, as the group, so never passed on too
    [host] = [m for m in machines_view(evs)["machines"] if m["bootstrap"]]
    assert host["kind"] == "program"


def test_one_hung_listener_is_not_answering_and_the_other_listener_of_the_type_is_not_charged():
    t = lambda s: f"2026-10-25T00:{s // 60:02d}:{s % 60:02d}Z"
    hello = lambda src, ty: {"type": "orchestra.machine.started", "source": src, "time": t(0), "data": {"listens_for": [ty]}}
    # x answered work.offered before (a hand-off through it into x, on subject s1), then hung; y listens
    # for it too but never answered it; both were last heard before the new offers
    evs = [hello("x/1", "work.offered"), hello("y/1", "work.*"),
           {"type": "work.offered", "source": "a", "subject": "s1", "time": t(10)},
           {"type": "work.claimed", "source": "x/1", "subject": "s1", "time": t(20)},
           {"type": "work.nudge", "source": "y/1", "time": t(25)},
           *({"type": "work.offered", "source": "a", "subject": f"s{i}", "time": t(30 + i)} for i in range(2, 6))]
    view = machines_view(evs, now=1_761_350_500.0)
    by = {m["id"]: m for m in view["machines"]}
    assert by["x"]["unanswered"]["work.offered"]["count"] == 4
    assert "unanswered" not in by["y"]                       # it never answered work.offered: not charged
    assert view["unanswered_types"] == []


def test_unanswered_events_no_listener_ever_answered_are_said_once_with_their_listeners():
    t = lambda s: f"2026-10-25T00:{s // 60:02d}:{s % 60:02d}Z"
    hello = lambda src, ty: {"type": "orchestra.machine.started", "source": src, "time": t(0), "data": {"listens_for": [ty]}}
    evs = [hello("x/1", "work.offered"), hello("y/1", "work.*"),
           *({"type": "work.offered", "source": "a", "subject": f"s{i}", "time": t(30 + i)} for i in range(3))]
    view = machines_view(evs, now=1_761_350_500.0)
    assert all("unanswered" not in m for m in view["machines"])
    from orchestra.events import event_time
    assert view["unanswered_types"] == [{"type": "work.offered", "count": 3, "since": event_time(evs[2]), "listeners": ["x", "y"]}]


def test_each_announcement_of_an_instance_is_counted_so_a_restart_reads_as_one():
    t = lambda s: f"2026-10-25T00:{s // 60:02d}:{s % 60:02d}Z"
    hello = lambda src, at: {"type": "orchestra.machine.started", "source": src, "time": t(at), "data": {"listens_for": ["x"]}}
    evs = [hello("w/1", 0), {"type": "job", "source": "w/1", "time": t(5)}, hello("w/1", 300), hello("w/2", 10)]
    [w] = [m for m in machines_view(evs, now=1_761_350_500.0)["machines"] if m["id"] == "w"]
    from orchestra.events import event_time
    inst = {i["id"]: i for i in w["instances"]}
    assert inst["1"]["announced"] == 2 and inst["1"]["announced_at"] == event_time(evs[2])
    assert inst["2"]["announced"] == 1
    assert w["announced"] == 3 and w["announced_at"] == event_time(evs[2])


def test_a_stopped_process_is_said_paused_and_a_log_says_when_it_was_written(tmp_path):
    import psutil

    from orchestra.web.core import paused
    from orchestra.web.machine_logs import written
    assert paused(psutil.STATUS_STOPPED) == "stopped (paused)"
    assert paused(psutil.STATUS_RUNNING) is None and paused(psutil.STATUS_SLEEPING) is None
    log = tmp_path / "w.log"
    log.write_text("x\n")
    os.utime(log, (1_800_000_000, 1_800_000_000))
    assert written(log) == 1_800_000_000 and written(tmp_path / "none.log") is None


def test_a_listener_that_took_a_type_only_now_and_then_is_not_charged_with_its_backlog():
    t = lambda s: f"2026-10-25T00:{s // 60:02d}:{s % 60:02d}Z"
    hello = lambda src, ty: {"type": "orchestra.machine.started", "source": src, "time": t(0), "data": {"listens_for": [ty]}}
    evs = [hello("w/1", "work.offered"), hello("n/1", "work.offered")]
    for i in range(10):                              # w took nine offers, n one
        evs += [{"type": "work.offered", "source": "a", "subject": f"s{i}", "time": t(10 + 2 * i)},
                {"type": "work.taken", "source": "n/1" if i == 4 else "w/1", "subject": f"s{i}", "time": t(11 + 2 * i)}]
    evs += [{"type": "work.offered", "source": "a", "subject": f"x{i}", "time": t(60 + i)} for i in range(3)]
    by = {m["id"]: m for m in machines_view(evs, now=1_761_350_500.0)["machines"]}
    assert by["w"]["unanswered"]["work.offered"]["count"] == 3
    assert "unanswered" not in by["n"]
