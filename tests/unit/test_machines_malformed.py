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


def test_events_appended_between_end_and_the_read_are_all_folded():
    from orchestra.web.machines import _ListBus

    class Racing(_ListBus):
        """Appends two events each time end() is asked, the way a busy bus grows between calls."""
        def end(self):
            n = len(self.evs)
            self.evs += [{"type": "thing.done", "source": "a/1", "time": T.format(i % 10), "id": f"e{n + i}"} for i in range(2)]
            return n

    bus = Racing([{"type": "thing.done", "source": "a/1", "time": T.format(0), "id": "e0"}])
    idx = MachineIndex(bus)
    for _ in range(3):
        idx.update()
    assert idx.total["a"]["thing.done"] == idx.offset           # every event read was folded, none pushed out
    assert idx.offset >= 5


def test_bus_since_is_the_earliest_any_instance_was_first_seen():
    from orchestra.web.machines import _ListBus

    idx = MachineIndex(_ListBus([{"type": "a", "source": "x/1", "time": T.format(3)}, {"type": "a", "source": "y", "time": T.format(1)}]))
    assert idx.bus_since() is None
    idx.update()
    from orchestra.events import event_time
    assert idx.bus_since() == event_time({"time": T.format(1)})
