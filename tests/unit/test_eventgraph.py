"""The binding graph and its feedback loops: found, not configured; named by the Supervisor."""

import subprocess

import pytest

from orchestra import api, eventgraph
from orchestra.config import init_project
from orchestra.events import Events
from orchestra.loop import Loop
from orchestra.store import LocalStore, StoreError


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    (repo / "README.md").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    p = init_project(repo)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "orchestra"], cwd=repo, check=True)
    return p


def agents_of(c):
    return c["agents"]


def test_builtin_delivery_loop_is_found(project):
    g = eventgraph.build(project)
    cycles = [eventgraph.describe(g, c) for c in eventgraph.elementary_cycles(g)]
    paths = [" → ".join(c["labels"] * 2) for c in cycles]                                    # doubled: rotation does not matter
    assert any("worker → READY_FOR_REVIEW → reviewer → REJECTED → worker" in p for p in paths)
    assert any("reviewer → APPROVED → merge gate → REJECTED → worker" in p for p in paths)   # the loop through the gate
    assert not any(c["self"] for c in cycles)                                                 # nothing wakes itself in a fresh project
    assert cycles == sorted(cycles, key=lambda c: c["length"])                                 # shortest first
    assert all(any(n.startswith("ev:") for n in c["nodes"]) for c in cycles)                  # every loop passes through an event


def test_custom_team_loop_closes_through_messages_and_tools(project):
    store = LocalStore(project)
    sup = {"role": "supervisor"}
    api.handle(project, store, "create_role", {"name": "keeper_role", "description": "d", "prompt": "# You keep docs\n\n" + "Accurately. " * 6, "tools": ["tickets"]}, **sup)
    api.handle(project, store, "create_role", {"name": "analyst", "description": "d", "prompt": "# You analyse\n\n" + "Carefully. " * 6, "tools": ["events"]}, **sup)
    api.handle(project, store, "create_agent", {"name": "keeper", "roles": ["keeper_role"], "team": "devex", "kind": "scheduled", "every": "1d"}, **sup)
    api.handle(project, store, "create_team", {"name": "devex", "lead": "keeper", "responsibilities": "# Devex\n\n1. The docs are accurate and small.",
                                               "members": ["retro"]}, **sup)
    api.handle(project, store, "create_agent", {"name": "retro", "roles": ["analyst"], "team": "devex", "kind": "ad_hoc", "session": "ephemeral",
                                                "wake_on": ["ticket_transition:REJECTED"]}, **sup)
    g = eventgraph.build(project)
    cycles = [eventgraph.describe(g, c) for c in eventgraph.elementary_cycles(g)]
    paths = [" → ".join(c["labels"] * 2) for c in cycles]
    assert any("REJECTED → retro → keeper" in p for p in paths)                 # a message, delivered as a wake-up, closes the loop
    assert any("keeper → ticket_created → orchestra → IN_PROGRESS → worker" in p for p in paths)   # the tickets tool, then the loop's pickup
    loop = next(c for c, p in zip(cycles, paths) if "REJECTED → retro → keeper" in p and "keeper → ticket_created" in p)
    # naming: the Supervisor gives the cycle a purpose; the API refuses unknown signatures
    with pytest.raises(StoreError, match="no detected loop"):
        api.handle(project, store, "name_loop", {"name": "x", "signature": "nope", "purpose": "p"}, **sup)
    r = api.handle(project, store, "name_loop", {"name": "lessons", "signature": loop["signature"], "purpose": "Every rejection teaches the docs",
                                                 "signal": "rejections per landed ticket", "owner": "devex"}, **sup)
    assert r["loop"]["agents"] == loop["agents"] and r["storage"].startswith("committed")
    det = api.handle(project, store, "list_loops", {})
    fam = next(c for c in det["detected"] if c["signature"] == loop["signature"])
    assert fam["named"]["name"] == "lessons" and fam["variants"] >= 1 and det["cycles"] >= len(det["detected"])
    with pytest.raises(StoreError):
        api.handle(project, store, "name_loop", {"name": "y", "signature": loop["signature"], "purpose": "p"}, role="keeper")   # supervisor only
    # the loop notices a new unnamed cycle once and asks the Supervisor
    events = Events(project.events_file)
    store.drain_wakeups("supervisor")
    lp = Loop(project, store, events)
    lp._refresh_org(); lp._detect_loops()
    assert store.drain_wakeups("supervisor") == []                                              # first run: a silent baseline
    api.handle(project, store, "delete_loop", {"name": "lessons"}, **sup)
    api.handle(project, store, "create_agent", {"name": "watcher", "roles": ["keeper_role"], "team": "devex", "kind": "ad_hoc", "session": "ephemeral",
                                                "wake_on": ["gate_conflict"]}, **sup)         # files tickets on conflicts: new loops
    lp._refresh_org(); lp._detect_loops()
    wakes = store.drain_wakeups("supervisor")
    assert len(wakes) == 1 and "new feedback loop" in wakes[0]["reason"] and "watcher" in wakes[0]["reason"]
    assert any(e["type"] == "loop_detected" for e in events.read(0)[0])
    lp._org_sig = None; lp._detect_loops()
    assert store.drain_wakeups("supervisor") == []                                              # told once
