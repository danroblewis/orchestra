"""The launcher entry that started a machine's process (``process`` in ``orchestra.machine.started``,
from ``ORCHESTRA_PROCESS``): read as part of the announcement, shown, and never a machine of its own
(AGENTS.md rule 2)."""

import pytest

from orchestra.endpoint.validate import Invalid, check
from orchestra.events import ANNOUNCEMENT, HOST, PROCESS_ENV, Events, announcing
from orchestra.web.machines import machines_view

T0 = 1_790_000_000.0


def started(src, t, **d):
    return {"type": ANNOUNCEMENT, "source": src, "time": t, "data": {"mode": "continuous", **d}}


def test_the_helper_names_the_process_only_when_the_launcher_started_it():
    assert announcing({"kind": "program"}, {PROCESS_ENV: "telemetry"}) == {"kind": "program", "process": "telemetry"}
    assert announcing({"kind": "program"}, {}) == {"kind": "program"}
    assert announcing(None, {PROCESS_ENV: ""}) == {}
    # what the machine said itself stands
    assert announcing({"process": "mine"}, {PROCESS_ENV: "telemetry"}) == {"process": "mine"}


def test_events_announce_publishes_the_announcement_with_the_process(tmp_path, monkeypatch):
    monkeypatch.setenv(PROCESS_ENV, "tools.sampler")
    events = Events(tmp_path / "events.jsonl", source="sampler")
    ev = events.announce({"mode": "continuous", "listens_for": []})
    assert ev["type"] == ANNOUNCEMENT and ev["source"] == "sampler"
    assert ev["data"] == {"mode": "continuous", "listens_for": [], "process": "tools.sampler"}
    monkeypatch.delenv(PROCESS_ENV)
    assert "process" not in events.announce({"mode": "ad hoc"})["data"]


def test_the_endpoint_takes_a_process_only_as_a_string():
    assert check({"type": ANNOUNCEMENT, "source": "t", "data": {"process": "telemetry"}})["data"]["process"] == "telemetry"
    with pytest.raises(Invalid, match="data.process must be a string"):
        check({"type": ANNOUNCEMENT, "source": "t", "data": {"process": 3}})


def test_the_page_reads_the_process_per_instance_and_the_latest_announcement_stands():
    evs = [started("baker/1", T0, process="bakers"), started("baker/2", T0 + 1, process="bakers"),
           started("telemetry", T0 + 2, process="telemetry", note="x"), started("cook", T0 + 3)]
    ms = {m["id"]: m for m in machines_view(evs, now=T0 + 10)["machines"]}
    assert ms["baker"]["processes"] == ["bakers"]
    assert {i["id"]: i["process"] for i in ms["baker"]["instances"]} == {"1": "bakers", "2": "bakers"}
    assert ms["telemetry"]["processes"] == ["telemetry"] and ms["telemetry"]["about"] == {"note": "x"}   # read, not passed on
    assert ms["cook"]["processes"] == []
    # a restart outside the launcher drops it: the latest announcement says there is none
    again = machines_view([*evs, started("telemetry", T0 + 5)], now=T0 + 10)["machines"]
    assert next(m for m in again if m["id"] == "telemetry")["processes"] == []


def test_a_launched_process_that_never_announces_is_no_machine():
    """The host says it started a process (``orchestra.process.started``, from its own source):
    that names a process, and makes no machine of it."""
    evs = [{"type": "orchestra.process.started", "source": HOST, "time": T0,
            "data": {"name": "telemetry", "pid": 42, "command": ["python", "t.py"], "owner": "project"}}]
    ids = {m["id"] for m in machines_view(evs, now=T0 + 10)["machines"]}
    assert ids == {HOST}
    # and the name a machine announced is only its field: the machine is its source
    ids = {m["id"] for m in machines_view([*evs, started("sampler", T0 + 1, process="telemetry")], now=T0 + 10)["machines"]}
    assert ids == {HOST, "sampler"}
