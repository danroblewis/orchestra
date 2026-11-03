"""Eras (goal G11): a machine's change begins an era; the era is the window the model is
discovered in, its prior is the era before, and the boundary is compared before → after."""

import math
import random
from types import SimpleNamespace

import pytest

from orchestra.config import Config, ConfigError
from orchestra.events import Events, envelope
from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd import eras
from orchestra.sd.rediscover import rediscover
from orchestra.sd.store import ModelStore
from orchestra.sd.strategies import CONSERVATION

T0 = 1_800_000_000.0
CHANGE = T0 + 3600.0


def poisson(rng, mean):
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def queue(store, minutes, arrive, *, cancel=None, seed=3, project="p"):
    """A queue: jobs arrive at ``arrive(t)`` per minute, each is done at 0.5 per minute, and while
    ``cancel(t)`` is above 0 each is cancelled at that rate per minute; a point every 5 s."""
    rng = random.Random(seed)
    q = 10
    arrived = done = cancelled = 0
    lab = {"project": project, "machine": "worker"}
    pts = []
    for i in range(minutes * 12):
        t = T0 + i * 5
        a = poisson(rng, arrive(t) / 12)
        d = min(q, poisson(rng, 0.5 * q / 12))
        q += a - d
        c = min(q, poisson(rng, (cancel(t) if cancel else 0.0) * q / 12))
        q -= c
        arrived, done, cancelled = arrived + a, done + d, cancelled + c
        pts += [Point("jobs_waiting", q, t, lab), Point("jobs_arrived_total", arrived, t, lab), Point("jobs_done_total", done, t, lab)]
        if cancel:
            pts.append(Point("jobs_cancelled_total", cancelled, t, lab))
    store.write(pts)


def project(tmp_path, **cfg):
    conf = {"discovery_strategy": CONSERVATION, "discovery_options": {}, "discovery_window": 3600.0, "discovery_step": 30.0,
                "discovery_every": 300.0, "eras_from": ["config.changed"], "prior_for": None}
    conf.update(cfg)
    return SimpleNamespace(key="p", state_dir=tmp_path / "state", repo_root=tmp_path, config=SimpleNamespace(**conf))


def bus(tmp_path, *evs):
    events = Events(tmp_path / "events.jsonl")
    for ev in evs:
        events.bus.append(ev)
    return events


def at(t: float) -> str:
    from datetime import UTC, datetime
    return datetime.fromtimestamp(t, UTC).isoformat()



def test_system_changed_always_begins_an_era_and_unconfigured_events_never_do():
    assert eras.begins({"type": "system.changed", "source": "deployer"}, [])
    assert eras.begins({"type": "config.changed", "source": "supervisor", "subject": "machine:worker"}, ["config.changed"])
    assert not eras.begins({"type": "config.changed", "source": "supervisor", "subject": "machine:worker"}, [])
    assert not eras.begins({"type": "ticket.created", "source": "desk"}, ["config.changed"])
    assert not eras.begins({"type": "orchestra.model.changed", "source": "orchestra-host"}, ["orchestra.*"]), "never Orchestra's own"


def test_filters_read_the_envelope_only():
    f = ["role.*:source=supervisor", "gate.landed:subject=orchestra.toml"]
    assert eras.begins({"type": "role.changed", "source": "supervisor"}, f)
    assert not eras.begins({"type": "role.changed", "source": "intern"}, f)
    assert eras.begins({"type": "gate.landed", "source": "gate", "subject": "orchestra.toml"}, f)
    assert not eras.begins({"type": "gate.landed", "source": "gate", "subject": "README.md", "data": {"subject": "orchestra.toml"}}, f)
    with pytest.raises(ConfigError, match="envelope"):
        Config.from_toml('[discovery]\neras_from = ["gate.landed:path=orchestra.toml"]')
    assert Config.from_toml("").eras_from == ["config.changed"]


def test_eras_are_recorded_once_and_announced_by_whoever_recorded_them(tmp_path):
    store = ModelStore.for_state(tmp_path)
    events = bus(tmp_path, envelope("ticket.created", "desk", time=at(T0)),
                 envelope("config.changed", "supervisor", {"section": "x"}, subject="machine:worker", time=at(T0 + 60), id="c1"),
                 envelope("system.changed", "deployer", time=at(T0 + 120), id="d1"))
    said = []
    all_, new = eras.sync(store, events, ["config.changed"], lambda ty, data, **ext: said.append((ty, data, ext)))
    assert [(e.id, e.start, e.label, e.cause, e.subject) for e in all_] == [
        ("e1", T0 + 60, "config.changed from supervisor", "c1", "machine:worker"), ("e2", T0 + 120, "system.changed from deployer", "d1", None)]
    assert [s[0] for s in said] == ["orchestra.era.started"] * 2
    assert said[0][2] == {"subject": "e1", "causationid": "c1"} and said[0][1]["cause"]["type"] == "config.changed"
    events.bus.append(envelope("ticket.created", "desk", time=at(T0 + 180)))
    _, new = eras.sync(store, events, ["config.changed"], lambda *a, **k: said.append(a))
    assert new == [] and len(said) == 2, "nothing new, nothing announced"
    all_, _ = eras.sync(store, events, [])
    assert [e.cause for e in all_] == ["d1"], "other filters: the bus is read again"
    assert eras.current(all_, T0 + 119) is None and eras.current(all_, T0 + 121).id == "e1"



# --- what begins an era: a change of how the system behaves, never a measurement, a setting or a no-op

def test_the_subject_decides_what_of_a_named_change_begins_an_era():
    f = ["config.changed", "deploy.finished"]
    ev = lambda ty, subject=None, **k: {"type": ty, "source": "supervisor", "subject": subject, **k}
    for subject in ("machine:worker", "definition:pr_sail", "override:tasking"):
        assert eras.begins(ev("config.changed", subject), f), f"{subject}: a part that behaves"
    for subject in ("instrument:board", "collector:jira_poller", "source:prometheus", "series:queue_depth", "setting:agents",
                    "scrape:node"):
        assert not eras.begins(ev("config.changed", subject), f), f"{subject}: what is measured, or a setting"
        assert not eras.begins(ev("system.changed", subject), f), f"{subject}: never, whatever the type"
    assert not eras.begins(ev("config.changed"), f), "the configuration changed, not what: no era"
    assert not eras.begins(ev("config.changed", "orchestra.toml"), f), "a file is not a part that behaves"
    assert eras.begins(ev("system.changed"), f), "the generic mark: the machine says the system changed"
    assert eras.begins(ev("deploy.finished", "billing"), f), "a type the owner named"
    assert eras.begins(ev("config.changed", id="c9"), f, {"c9"}), "a change a prediction is about: a declared effect confirmed"
    assert not eras.begins(ev("config.changed", "source:prometheus", id="c9"), f, {"c9"}), "a measurement, predicted or not"


def test_run_4s_setup_begins_no_era_and_its_machine_change_does(tmp_path):
    """Run 4: a collector added, one left unchanged, a source added, a setting under [agents], the
    discovery's own setting (no subject on any): none is a change of behaviour."""
    store = ModelStore.for_state(tmp_path)
    t = T0 + 60
    events = bus(tmp_path, envelope("config.changed", "supervisor", {"change": "added [[machines]] jira_poller"}, time=at(t), id="a"),
                 envelope("config.changed", "supervisor", {"change": "nothing: changed [[machines]] jira_poller already"}, time=at(t + 30), id="b"),
                 envelope("config.changed", "supervisor", subject="source:prometheus", time=at(t + 60), id="c"),
                 envelope("config.changed", "supervisor", subject="setting:agents", time=at(t + 90), id="d"),
                 envelope("instruments.changed", "supervisor", subject="collect:board", time=at(t + 120), id="e"),
                 envelope("config.changed", "supervisor", subject="collector:slack_poller", time=at(t + 150), id="f"))
    all_, new = eras.sync(store, events, ["config.changed", "instruments.*"])
    assert all_ == [] and new == []
    events.bus.append(envelope("role.changed", "supervisor", subject="machine:reviewer", time=at(t + 180), id="g"))
    all_, _ = eras.sync(store, events, ["config.changed", "role.changed:source=supervisor"])
    assert [e.cause for e in all_] == ["g"], "a machine's duties edited"


def test_a_config_changed_that_left_the_configuration_as_it_was_begins_nothing(tmp_path):
    store = ModelStore.for_state(tmp_path)
    now = [T0 + 100]
    events = bus(tmp_path)
    conf = {"machines": [{"name": "worker", "command": "w"}]}
    key = lambda: eras.config_key(conf)
    sync = lambda: eras.sync(store, events, ["config.changed"], config=key, clock=lambda: now[0])
    events.bus.append(envelope("config.changed", "supervisor", subject="machine:worker", time=at(T0 + 90), id="real"))
    assert [e.cause for e in sync()[1]] == ["real"]
    events.bus.append(envelope("config.changed", "supervisor", subject="machine:worker", time=at(T0 + 4000), id="noop"))
    now[0] = T0 + 4010
    assert sync()[1] == [], "nothing changed since the last config.changed: a no-op"
    conf["machines"][0]["command"] = "w --faster"
    events.bus.append(envelope("config.changed", "supervisor", subject="machine:worker", time=at(T0 + 8000), id="again"))
    now[0] = T0 + 8010
    assert [e.cause for e in sync()[1]] == ["again"], "the machine's command changed"
    events.bus.append(envelope("config.changed", "supervisor", subject="machine:worker", time=at(T0 + 9000), id="old"))
    now[0] = T0 + 20000
    assert [e.cause for e in sync()[1]] == ["old"], "read long after its time (a replay): not judged a no-op"


def test_an_era_is_never_shorter_than_discovery_needs(tmp_path):
    """Run 4's per-merge eras, 5.2 minutes apart: with the shortest era half the window, a change
    within it of the current era's start is kept in that era, said, and begins none of its own."""
    store = ModelStore.for_state(tmp_path)
    events = bus(tmp_path, *[envelope("github.pr.merged", "bot.github.sail-bot", subject=f"riff/hackriff#{i}",
                                      time=at(T0 + i * 312), id=f"m{i}") for i in range(12)])
    noted = []
    all_, new = eras.sync(store, events, ["github.pr.merged"], min_s=1800.0, noted=noted)
    assert [e.cause for e in all_] == [e.cause for e in new] == ["m0", "m6"], "one era per half hour, not one per merge"
    assert [c["id"] for c in all_[0].changes] == ["m1", "m2", "m3", "m4", "m5"] and all_[0].changes[0]["at"] == T0 + 312
    assert [c["id"] for c in all_[1].changes] == ["m7", "m8", "m9", "m10", "m11"]
    assert len(noted) == 10 and noted[0][0] == "e1"
    assert eras.of_change(all_, "m3").id == "e1" and eras.by_change(all_)["m9"].id == "e2"
    assert eras.sync(store, events, ["github.pr.merged"], min_s=1800.0)[1] == [], "each kept once"
    assert eras.shortest(SimpleNamespace(discovery_window=3600.0)) == 1800.0


def test_the_host_keeps_a_change_too_soon_in_the_current_era_and_says_so(tmp_path, monkeypatch):
    import subprocess

    from orchestra.config import init_project
    from orchestra.host import Host

    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    host = Host(init_project(repo))
    host.events.publish("system.changed", {}, source="deployer", subject="machine:api")
    host.events.publish("system.changed", {}, source="deployer", subject="machine:api")
    host._eras()
    [era] = eras.recorded(ModelStore.for_state(host.project.state_dir))
    assert len(era.changes) == 1
    log = (host.project.logs_dir / "orchestra-host.log").read_text()
    assert "kept in era e1: too soon after its start" in log


def test_a_rate_that_doubles_at_a_change_is_fitted_from_the_new_era_with_the_prior_early(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    queue(store, 120, lambda t: 2.0 if t < CHANGE else 4.0)
    events = bus(tmp_path, envelope("config.changed", "supervisor", subject="machine:worker", time=at(CHANGE), id="cause"))
    p = project(tmp_path)
    models = ModelStore.for_state(p.state_dir)

    before = rediscover(p, store, now=CHANGE - 1).model          # nothing has changed yet (the event is in the future)
    assert before.era is None
    c0 = before.flow("jobs_arrived_total").current().params["c"]
    assert 1.6 < c0 < 2.4

    early = rediscover(p, store, now=CHANGE + 240, events=events).model     # 4 min into the era
    assert early.era == "e1" and early.discovery["start"] >= CHANGE, "nothing before the era is read"
    assert [v["era"] for v in models.versions()][:1] == [None], "the previous era's last model was saved first"
    e = early.flow("jobs_arrived_total").current()
    assert e.origin == "fitted" and e.prior["era"] is None and e.prior["params"]["c"] == c0
    assert e.prior["weight"] > 0.3, "early on, the prior weighs as much as the era's few events"
    assert c0 < e.params["c"] < e.prior["own"]["c"], "the era's own rate, pulled towards the prior's"

    late = rediscover(p, store, now=T0 + 7200, events=events).model
    e = late.flow("jobs_arrived_total").current()
    assert e.origin == "fitted" and e.era == "e1" and e.prior["weight"] < 0.2
    assert 3.4 < e.prior["own"]["c"] < 4.6 and 3.2 < e.params["c"] < 4.6
    cmp = {f["id"]: f for f in late.discovery["era_comparison"]["flows"]}
    arr = cmp["jobs_arrived_total"]
    assert arr["status"] == "changed"
    [c] = arr["params"]
    assert c["param"] == "c" and abs(c["before"] - c0) < 1e-9 and 1.7 < c["ratio"] < 2.3 and c["z"] > 2
    assert cmp["jobs_done_total"]["status"] == "unchanged", "the per-item rate did not change"
    assert late.eras[0].cause == "cause" and models.of_era("e1")[1].era == "e1"


def test_no_era_begins_for_unconfigured_events(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    queue(store, 120, lambda t: 2.0)
    events = bus(tmp_path, envelope("ticket.created", "desk", time=at(CHANGE)), envelope("config.changed", "supervisor", time=at(CHANGE)))
    m = rediscover(project(tmp_path, eras_from=[]), store, now=T0 + 7200, events=events).model
    assert m.era is None and m.eras == [] and m.discovery["start"] == T0 + 3600 and "era_comparison" not in m.discovery


def test_a_flow_that_stops_is_carried_from_the_prior_then_reported_gone(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    queue(store, 120, lambda t: 3.0, cancel=lambda t: 0.2 if t < CHANGE else 0.0)
    events = bus(tmp_path, envelope("system.changed", "ops", time=at(CHANGE)))
    p = project(tmp_path, prior_for=1200.0)
    assert "jobs_cancelled_total" in {f.id for f in rediscover(p, store, now=CHANGE - 1).model.flows}
    early = rediscover(p, store, now=CHANGE + 600, events=events).model
    f = early.flow("jobs_cancelled_total")
    assert f.current().origin == "prior" and f.evidence["prior"]["why"] == "not yet found in this era"
    assert {x["id"]: x["status"] for x in early.discovery["era_comparison"]["flows"]}["jobs_cancelled_total"] == "carried"
    late = rediscover(p, store, now=T0 + 7200, events=events).model
    assert "jobs_cancelled_total" not in {x.id for x in late.flows}
    assert {x["id"]: x["status"] for x in late.discovery["era_comparison"]["flows"]}["jobs_cancelled_total"] == "disappeared"
    assert late.discovery["prior"]["dropped"]["flows"] == ["jobs_cancelled_total"]


def test_a_new_era_too_young_to_read_is_its_prior(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    queue(store, 70, lambda t: 2.0)
    events = bus(tmp_path, envelope("system.changed", "ops", time=at(CHANGE)))
    p = project(tmp_path)
    rediscover(p, store, now=CHANGE - 1)
    m = rediscover(p, store, now=CHANGE + 20, events=events).model
    assert m.era == "e1" and m.discovery["too_young"] and m.stocks
    assert all(f.current().origin == "prior" for f in m.flows)
    assert ModelStore.for_state(p.state_dir).versions()[-1]["era"] == "e1"



def test_the_event_map_differs_before_and_after_a_change_that_adds_a_machine():
    from orchestra.web.machines import machines_view
    evs = [envelope("orchestra.machine.started", "worker", {"kind": "program", "listens_for": ["job.reviewed"]}, time=at(T0)),
           envelope("orchestra.machine.started", "idle", {"kind": "person"}, time=at(T0))]
    evs += [envelope("job.done", "worker", time=at(T0 + i)) for i in range(5)]
    evs.append(envelope("system.changed", "ops", time=at(CHANGE)))
    evs += [envelope("job.done", "worker", time=at(CHANGE + 10)), envelope("job.reviewed", "reviewer", time=at(CHANGE + 20))]
    every = {m["id"] for m in machines_view(evs, now=CHANGE + 30)["machines"]}
    first = {m["id"] for m in machines_view(evs, now=CHANGE + 30, until=CHANGE)["machines"]}
    second = machines_view(evs, now=CHANGE + 30, since=CHANGE)
    assert "reviewer" in every and "reviewer" not in first and "reviewer" in {m["id"] for m in second["machines"]}
    worker = next(m for m in second["machines"] if m["id"] == "worker")
    assert worker["publishes"] == [{"type": "job.done", "count": 1, "day": 1, "n_10m": 1, "window_s": 600, "per_min_10m": 0.1}], "counted within the era"
    assert worker["kind"] == "program" and worker["subscribes"] == ["job.reviewed"], "announced before the era, still what it is"
    assert "idle" not in {m["id"] for m in second["machines"]}, "an announcement before the era is no activity in it"


def test_the_dynamics_api_and_the_machines_api_show_each_era(tmp_path, monkeypatch, capsys):
    import subprocess

    from orchestra.cli import main
    from orchestra.config import init_project, load_project
    from orchestra.web.dynamics import model_view

    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    init_project(repo)
    (repo / "orchestra.toml").write_text('[discovery]\nstrategy = "conservation"\n', encoding="utf-8")
    p = load_project(repo)
    store = FileMetrics(tmp_path / "m.jsonl")
    queue(store, 120, lambda t: 2.0 if t < CHANGE else 4.0, project=p.key)
    events = Events.for_project(p)
    events.bus.append(envelope("system.changed", "ops", subject="workers", time=at(CHANGE), id="cause"))
    rediscover(p, store, now=CHANGE - 1)
    rediscover(p, store, now=T0 + 7200, events=events)

    now = model_view(p)["model"]
    assert now["era"] == "e1" and now["current_era"] == "e1" and [e["id"] for e in now["eras_recorded"]] == ["e1"]
    assert now["discovery"]["era_comparison"]["from"] is None
    before = model_view(p, era="none")["model"]
    assert before["era"] is None and before["version"] < now["current"]
    assert not model_view(p, era="e9")["ok"]

    from orchestra.sd.reads import ModelReads
    got = ModelReads(p).eras()
    assert [e["id"] for e in got["eras"]] == ["e1"] and got["current"] == "e1" and got["eras"][0]["subject"] == "workers"
    status = {f["id"]: f["status"] for f in got["comparison"]["flows"]}
    assert status["jobs_arrived_total"] == "changed" and status["jobs_done_total"] == "unchanged"
    assert got["versions"]["e1"] and got["versions"]["None"], "each era's versions"
    monkeypatch.chdir(repo)
    monkeypatch.setattr("sys.argv", ["orchestra", "sd", "eras"])
    with pytest.raises(SystemExit):
        main()
    assert "invalid choice: 'eras'" in capsys.readouterr().err, "the command is gone: the eras are read through the APIs"


def test_the_host_records_an_era_and_announces_it(tmp_path, monkeypatch):
    import subprocess

    from orchestra.config import init_project
    from orchestra.host import Host

    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    host = Host(init_project(repo))
    change = host.events.publish("system.changed", {"why": "a test"}, source="deployer")
    host._eras()
    host._eras()
    evs, _ = host.events.read(0, 100)
    [started] = [e for e in evs if e["type"] == "orchestra.era.started"]
    assert started["source"] == "orchestra-host" and started["causationid"] == change["id"] and started["data"]["era"] == "e1"
    assert "era e1 began: system.changed from deployer" in (host.project.logs_dir / "orchestra-host.log").read_text()
