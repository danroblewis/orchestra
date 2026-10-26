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
    [m] = [m for m in machines_view(evs, [])["machines"] if m["id"] == "baker"]
    assert m["logs"] == ["1"]


def test_hand_offs_are_inferred_from_events_about_the_same_subject():
    ev = lambda src, ty, subj: {"type": ty, "source": src, "subject": subj, "time": "2026-10-25T00:00:00Z"}
    evs = [ev("planner", "issue.create", "t1"), ev("worker/1", "issue.update", "t1"), ev("worker/1", "issue.update", "t1"),
           ev("reviewer/2", "issue.close", "t1"), ev("planner", "issue.create", "t2"), ev("worker/3", "issue.update", "t2")]
    h = {(x["from"], x["via"], x["to"]): x["count"] for x in machines_view(evs, [])["handoffs"]}
    # the same machine twice in a row is no hand-off; each records the event the next machine followed
    assert h == {("planner", "issue.create", "worker"): 2, ("worker", "issue.update", "reviewer"): 1}
