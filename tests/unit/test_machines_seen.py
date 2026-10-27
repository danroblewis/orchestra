"""The Machines page sees a machine by its writes as well as its events."""

import time
from datetime import UTC, datetime

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.web.machines import last_writes, machines_view, write_cadence

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


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def announce(src: str, t: float, **d) -> dict:
    return {"type": "orchestra.machine.started", "source": src, "time": iso(t), "data": {"listens_for": [], **d}}


def test_a_machine_is_active_within_its_own_cadence_fast_or_slow(tmp_path):
    evs = [announce("tides", T0, mode="scheduled", kind="program"),       # a collector, every 6 min
           announce("bitcoin", T0, mode="scheduled", kind="program"),      # one every minute
           announce("tides", T0 + 2, mode="scheduled", kind="program")]    # announced again at a restart: not a beat
    store = FileMetrics(tmp_path / "metrics.jsonl")
    store.write([Point("tide_m", 1.0, T0 + t, {"project": "p", "machine": "tides"}) for t in (0, 360, 720)])
    store.write([Point("btc_usd", 1.0, T0 + t, {"project": "p", "machine": "bitcoin"}) for t in range(0, 721, 60)])
    dumped = store.dump("", {"project": "p"})
    written, beats = last_writes(dumped, T0 + 720), write_cadence(dumped, T0 + 720)

    def active(now):
        return {m["id"]: m["active"] for m in machines_view(evs, [(n, lab) for n, lab, _ in dumped], now=now, written=written, write_beats=beats)["machines"]}

    assert active(T0 + 720 + 300) == {"orchestra-host": False, "tides": True, "bitcoin": False}     # 5 min into a 6 min round
    assert active(T0 + 720 + 100)["bitcoin"]
    assert not active(T0 + 720 + 360 * 3)["tides"]                                                 # three rounds missed
    # the cadence is observed, not announced: a collector's writes say how often it runs
    # nothing announced: the cadence it is observed at, by its writes or its events
    # a machine that announced itself once and then only writes its own series stays active while
    # they keep coming; a series alone, with nothing on the bus, makes no machine
    seen = machines_view([announce("creek", T0, mode="scheduled")], [("creek_cfs", {"machine": "creek"})], now=T0 + 720 + 1200,
                         written={("creek", ""): T0 + 720}, write_beats={("creek", ""): 900.0})
    assert {m["id"]: m["active"] for m in seen["machines"]}["creek"]
    alone = machines_view([], [("river_cfs", {"machine": "river"})], now=T0, written={("river", ""): T0}, write_beats={("river", ""): 900.0})
    assert "river" not in {m["id"] for m in alone["machines"]}
    talk = [{"type": "work.done", "source": "worker/1", "time": iso(T0 + 300 * k)} for k in range(4)]
    seen = {m["id"]: m for m in machines_view(talk, [], now=T0 + 900 + 600)["machines"]}
    assert seen["worker"]["active"] and seen["worker"]["instances"][0]["cadence_s"] == {"events": 300, "writes": None}
    assert not machines_view(talk, [], now=T0 + 900 + 900)["machines"][1]["active"]


def test_nothing_stamped_in_the_future_makes_a_machine_look_alive(tmp_path):
    now = time.time()
    store = FileMetrics(tmp_path / "metrics.jsonl")          # made directly: it refuses nothing, like a store written before the refusal
    store.write([Point("caiso_demand_mw", 1.0, now - 7200 + t, {"project": "p", "machine": "telemetry"}) for t in (0, 30, 60)])
    store.write([Point("caiso_demand_mw", 2.0, now + 13 * 3600, {"project": "p", "machine": "telemetry"})])
    dumped = store.dump("", {"project": "p"})
    written = last_writes(dumped, now)
    assert written == {("telemetry", ""): now - 7200 + 60}
    seen = {m["id"]: m for m in machines_view([announce("telemetry", now - 7200)], [(n, lab) for n, lab, _ in dumped], now=now, written=written,
                                                       write_beats=write_cadence(dumped, now))["machines"]}
    assert not seen["telemetry"]["active"]
    ahead = [{"type": "work.done", "source": "clock_ahead", "time": iso(now + 13 * 3600)}]
    m = {m["id"]: m for m in machines_view(ahead, [], now=now + 1)["machines"]}["clock_ahead"]
    assert m["last_seen"] <= now + 1


def test_kind_and_mode_belong_to_instances_and_a_machine_whose_instances_differ_says_so():
    evs = [announce("worker/1", T0, mode="continuous", kind="agent"),
           announce("worker/2", T0 + 1, mode="continuous", kind="agent"),
           announce("worker/shell", T0 + 2, mode="continuous", kind="program"),              # announced last
           announce("baker/1", T0, mode="ad hoc", kind="program"), announce("baker/2", T0, mode="ad hoc", kind="program")]
    seen = {m["id"]: m for m in machines_view(evs, [], now=T0 + 10)["machines"]}
    assert seen["worker"]["kind"] == "agent ×2, program ×1" and seen["worker"]["kinds"] == {"agent": 2, "program": 1}
    assert seen["worker"]["mode"] == "continuous"
    assert {i["id"]: i["kind"] for i in seen["worker"]["instances"]} == {"1": "agent", "2": "agent", "shell": "program"}
    assert (seen["baker"]["kind"], seen["baker"]["mode"]) == ("program", "ad hoc")
