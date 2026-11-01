"""One malformed event on the bus never sticks the Machines index (web/machines.py): an announcement
whose data is not an object, or whose listens_for is a string, reads as empty, and an event the fold
cannot read at all is skipped and counted; the events after it are folded."""

from orchestra.web.machines import MachineIndex, _ListBus

T = "2026-10-25T00:00:0{}Z"


def test_a_malformed_announcement_reads_as_empty_and_the_events_after_it_are_folded():
    evs = [{"type": "orchestra.machine.started", "source": "a/1", "time": T.format(0), "data": [1, 2]},
           {"type": "orchestra.machine.started", "source": "b/1", "time": T.format(1), "data": "continuous"},
           {"type": "orchestra.machine.started", "source": "c/1", "time": T.format(2),
            "data": {"listens_for": "a.b", "mode": 3, "kind": ["x"]}},
           {"type": "orchestra.machine.started", "source": "d/1", "time": T.format(3),
            "data": {"listens_for": ["x.y", {"t": 1}, 4]}},
           {"source": "e/1", "time": T.format(4)},                                  # no type: the fold cannot count it
           {"type": "thing.done", "source": "a/1", "time": T.format(5)}]
    idx = MachineIndex(_ListBus(evs))
    idx.update()
    assert idx.offset == len(evs)
    assert idx.subs["c"] == set() and idx.subs["d"] == {"x.y"}
    assert "c" not in idx.mode and "c" not in idx.kind
    assert idx.total["a"]["thing.done"] == 1
    assert idx.skipped == 1
    view = idx.view()
    assert {m["id"] for m in view["machines"]} >= {"a", "b", "c", "d"}
