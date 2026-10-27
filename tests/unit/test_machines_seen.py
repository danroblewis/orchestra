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


def test_an_announced_name_and_group_are_read_and_the_latest_announcement_stands():
    started = lambda src, t, **d: {"type": "orchestra.machine.started", "source": src, "time": t, "data": {"mode": "ad hoc", **d}}
    evs = [started("person.al", "2026-09-21T13:46:40Z", kind="person", package="bridges", name="Alice Liddell", team="editor", github="alice"),
           started("person.bo", "2026-09-21T13:46:41Z", kind="person", name="Bo", group="sre", team="ignored-when-group-is-given"),
           started("telemetry", "2026-09-21T13:46:42Z"),
           started("person.cy", "2026-09-21T13:46:43Z", name="Cy", team="editor"),
           started("person.cy", "2026-09-21T13:50:00Z", name="Cy")]             # Cy left the team
    seen = {m["id"]: m for m in machines_view(evs, [], now=T0)["machines"]}
    assert (seen["person.al"]["name"], seen["person.al"]["group"]) == ("Alice Liddell", "editor")
    assert seen["person.al"]["about"] == {"team": "editor", "github": "alice"}        # the rest still goes to the card
    assert seen["person.bo"]["group"] == "sre"
    assert (seen["telemetry"]["name"], seen["telemetry"]["group"]) == (None, None)
    assert (seen["person.cy"]["name"], seen["person.cy"]["group"]) == ("Cy", None)
