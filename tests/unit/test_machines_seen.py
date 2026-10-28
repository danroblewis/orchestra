"""The Machines page sees a machine by its events alone, never by series labelled with it."""

import time
from datetime import UTC, datetime

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.web.machines import machines_view

T0 = 1_790_000_000.0


def test_series_labelled_with_a_machine_make_no_machine_and_keep_none_alive(tmp_path):
    """A machine does not produce metrics (AGENTS.md rules 2 and 7): series labelled ``machine=``
    neither make a machine nor keep one active. Only its events do."""
    store = FileMetrics(tmp_path / "metrics.jsonl")
    store.write([Point("disk_free_bytes", 1.0, T0 + t, {"project": "p", "machine": "telemetry"}) for t in range(0, 600, 30)])
    store.write([Point("repo_files", 3.0, T0 + 590, {"project": "p", "machine": "sampler", "instance": "2"})])
    assert len(store.dump("", {"project": "p"})) == 2
    alone = {m["id"] for m in machines_view([], now=T0 + 600)["machines"]}
    assert alone == {"orchestra-host"}                         # written for, never seen on the bus

    started = [announce("telemetry", T0, mode="continuous")]
    seen = {m["id"]: m for m in machines_view(started, now=T0 + 600)["machines"]}
    assert not seen["telemetry"]["active"] and seen["telemetry"]["last_seen"] == T0   # its writes do not count
    assert "sampler" not in seen


def test_an_announced_name_and_group_are_read_and_the_latest_announcement_stands():
    started = lambda src, t, **d: {"type": "orchestra.machine.started", "source": src, "time": t, "data": {"mode": "ad hoc", **d}}
    evs = [started("person.al", "2026-09-21T13:46:40Z", kind="person", package="bridges", name="Alice Liddell", team="editor", github="alice"),
           started("person.bo", "2026-09-21T13:46:41Z", kind="person", name="Bo", group="sre", team="ignored-when-group-is-given"),
           started("telemetry", "2026-09-21T13:46:42Z"),
           started("person.cy", "2026-09-21T13:46:43Z", name="Cy", team="editor"),
           started("person.cy", "2026-09-21T13:50:00Z", name="Cy")]             # Cy left the team
    seen = {m["id"]: m for m in machines_view(evs, now=T0)["machines"]}
    assert (seen["person.al"]["name"], seen["person.al"]["group"]) == ("Alice Liddell", "editor")
    assert seen["person.al"]["about"] == {"team": "editor", "github": "alice"}        # the rest still goes to the card
    assert seen["person.bo"]["group"] == "sre"
    assert (seen["telemetry"]["name"], seen["telemetry"]["group"]) == (None, None)
    assert (seen["person.cy"]["name"], seen["person.cy"]["group"]) == ("Cy", None)


def test_one_machine_made_of_an_agent_and_a_program_shows_both_and_neither_erases_the_other():
    """The coordinator is an AI agent (its own announcement: package, harness, model) and a
    plugin's dispatch acting as it (``coordinator/dispatch``: only what it listens for and what it
    is). One machine: what it listens for is the union, its kind says both, and the dispatch's bare
    announcement, whenever it comes, erases neither the agent's package nor the rest of its card."""
    started = lambda src, t, **d: {"type": "orchestra.machine.started", "source": src, "time": t, "data": d}
    agent = started("coordinator", "2026-09-21T13:46:40Z", package="agents", mode="continuous", kind="agent",
                    listens_for=["task.attention_needed", "request.done"], harness="dummy", model="m")
    dispatch = started("coordinator/dispatch", "2026-09-21T13:46:41Z", mode="continuous", kind="program",
                       listens_for=["ticket.created", "task.released"])
    for evs in ([agent, dispatch], [dispatch, agent]):
        [c] = [m for m in machines_view(evs, now=T0)["machines"] if m["id"] == "coordinator"]
        assert c["subscribes"] == ["request.done", "task.attention_needed", "task.released", "ticket.created"]
        assert c["kind"] == "agent ×1, program ×1" and c["package"] == "agents"
        assert c["about"] == {"harness": "dummy", "model": "m"}
        assert [i["id"] for i in c["instances"]] == ["dispatch"]


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def announce(src: str, t: float, **d) -> dict:
    return {"type": "orchestra.machine.started", "source": src, "time": iso(t), "data": {"listens_for": [], **d}}


def test_a_machine_is_active_within_its_own_event_cadence_fast_or_slow():
    evs = [announce("tides", T0, mode="scheduled", kind="program"),
           announce("tides", T0 + 2, mode="scheduled", kind="program"),       # announced again in the same burst: not a beat
           *[{"type": "tide.read", "source": "tides", "time": iso(T0 + t)} for t in (360, 720)],             # every 6 min
           *[{"type": "btc.priced", "source": "bitcoin", "time": iso(T0 + t)} for t in range(0, 721, 60)]]   # every minute

    def view(now):
        return {m["id"]: m for m in machines_view(evs, now=now)["machines"]}

    assert view(T0 + 720)["tides"]["instances"] == [] and {m: v["active"] for m, v in view(T0 + 720 + 300).items()} \
        == {"orchestra-host": False, "tides": True, "bitcoin": False}                    # 5 min into a 6 min round
    assert view(T0 + 720 + 100)["bitcoin"]["active"]                                     # the 120 s floor
    assert not view(T0 + 720 + 360 * 3)["tides"]["active"]                               # three rounds missed
    talk = [{"type": "work.done", "source": "worker/1", "time": iso(T0 + 300 * k)} for k in range(4)]
    seen = {m["id"]: m for m in machines_view(talk, now=T0 + 900 + 600)["machines"]}
    assert seen["worker"]["active"] and seen["worker"]["instances"][0]["cadence_s"] == 300
    assert not machines_view(talk, now=T0 + 900 + 900)["machines"][1]["active"]


def test_a_scheduled_job_that_publishes_rarely_is_active_by_its_own_rhythm():
    """A job run every hour, which announces itself at each run (a fresh process) and publishes
    half a minute later: each run is one burst, one beat, so its cadence is the hour (not the
    half minute between a run's own events),
    and it is active between runs and quiet after a few missed ones. A cadence over a day counts
    as a day."""
    HOUR = 3600.0
    evs = []
    for k in range(4):
        t = T0 + k * HOUR
        evs += [announce("nightly", t, mode="scheduled"), announce("nightly", t + 1, mode="scheduled"),
                {"type": "report.made", "source": "nightly", "time": iso(t + 30)}]
    [inst] = [m for m in machines_view(evs, now=T0 + 3 * HOUR + 30)["machines"] if m["id"] == "nightly"]
    assert inst["active"]

    def active(now):
        return {m["id"]: m["active"] for m in machines_view(evs, now=now)["machines"]}["nightly"]

    assert active(T0 + 3 * HOUR + 30 + 2 * HOUR)                    # an hour or two late is still within its rhythm
    assert not active(T0 + 3 * HOUR + 30 + 3 * HOUR)                # three runs missed: quiet
    weekly = [{"type": "report.made", "source": "weekly", "time": iso(T0 + k * 7 * 86400)} for k in range(3)]
    assert {m["id"]: m["active"] for m in machines_view(weekly, now=T0 + 14 * 86400 + 2 * 86400)["machines"]}["weekly"]
    assert not {m["id"]: m["active"] for m in machines_view(weekly, now=T0 + 14 * 86400 + 3 * 86400)["machines"]}["weekly"]


def test_nothing_stamped_in_the_future_makes_a_machine_look_alive():
    now = time.time()
    ahead = [{"type": "work.done", "source": "clock_ahead", "time": iso(now + 13 * 3600)}]
    m = {m["id"]: m for m in machines_view(ahead, now=now + 1)["machines"]}["clock_ahead"]
    assert m["last_seen"] <= now + 1


def test_kind_and_mode_belong_to_instances_and_a_machine_whose_instances_differ_says_so():
    evs = [announce("worker/1", T0, mode="continuous", kind="agent"),
           announce("worker/2", T0 + 1, mode="continuous", kind="agent"),
           announce("worker/shell", T0 + 2, mode="continuous", kind="program"),              # announced last
           announce("baker/1", T0, mode="ad hoc", kind="program"), announce("baker/2", T0, mode="ad hoc", kind="program")]
    seen = {m["id"]: m for m in machines_view(evs, now=T0 + 10)["machines"]}
    assert seen["worker"]["kind"] == "agent ×2, program ×1" and seen["worker"]["kinds"] == {"agent": 2, "program": 1}
    assert seen["worker"]["mode"] == "continuous"
    assert {i["id"]: i["kind"] for i in seen["worker"]["instances"]} == {"1": "agent", "2": "agent", "shell": "program"}
    assert (seen["baker"]["kind"], seen["baker"]["mode"]) == ("program", "ad hoc")
