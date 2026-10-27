"""The Machines page sees a machine by its writes as well as its events."""

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.web.machines import last_writes, machines_view

T0 = 1_790_000_000.0


def test_a_collector_that_only_writes_after_announcing_stays_active(tmp_path):
    started = [{"type": "orchestra.machine.started", "source": "telemetry", "time": "2026-09-21T13:46:40Z",
                "data": {"mode": "continuous", "listens_for": []}},
               {"type": "orchestra.machine.started", "source": "sampler/2", "time": "2026-09-21T13:46:40Z",
                "data": {"mode": "continuous", "listens_for": []}}]
    store = FileMetrics(tmp_path / "metrics.jsonl")
    store.write([Point("disk_free_bytes", 1.0, T0 + t, {"project": "p", "machine": "telemetry"}) for t in (5, 300)])
    store.write([Point("repo_files", 3.0, T0 + 290, {"project": "p", "machine": "sampler", "instance": "2"}),
                 Point("other", 1.0, T0 + 999, {"project": "p"})])
    written = last_writes(store.dump("", {"project": "p"}))
    assert written == {("telemetry", ""): T0 + 300, ("sampler", "2"): T0 + 290}

    now = T0 + 310                                            # five minutes after the announcement
    seen = {m["id"]: m for m in machines_view(started, [], now=now, written=written)["machines"]}
    assert seen["telemetry"]["active"] and seen["telemetry"]["last_seen"] == T0 + 300
    assert seen["sampler"]["active"] and seen["sampler"]["instances"][0]["active"]
    assert seen["sampler"]["instances"][0]["last_seen"] == T0 + 290

    unseen = {m["id"]: m for m in machines_view(started, [], now=now)["machines"]}
    assert not unseen["telemetry"]["active"]                  # by its events alone, it looks stopped
