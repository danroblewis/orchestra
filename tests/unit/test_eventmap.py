"""The event map: who wakes whom through which events, declared and observed."""

import subprocess

import pytest
from fastapi.testclient import TestClient

from orchestra import api
from orchestra.agents.roles import ROLES
from orchestra.config import init_project
from orchestra.store import LocalStore
from orchestra.web import app as web


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


def test_builtin_roles_name_real_events():
    from orchestra.roles import EVENT_TYPES
    for r in ROLES.values():
        for w in r.wake_on + r.emits:
            assert w.split(":")[0] in EVENT_TYPES, (r.name, w)
    assert "ticket_transition:READY_FOR_REVIEW" in ROLES["reviewer"].wake_on
    assert "ticket_transition:APPROVED" in ROLES["reviewer"].emits and "a free reviewer slot" in ROLES["reviewer"].triggers


def test_eventmap_has_declared_and_observed_edges(project):
    store = LocalStore(project)
    sup = {"role": "supervisor"}
    api.handle(project, store, "create_role", {"name": "analyst", "description": "d", "prompt": "# You analyse\n\n" + "Carefully. " * 6, "tools": ["events"]}, **sup)
    api.handle(project, store, "create_agent", {"name": "keeper", "roles": ["analyst"], "team": "devex", "kind": "scheduled", "every": "1d"}, **sup)
    api.handle(project, store, "create_team", {"name": "devex", "lead": "keeper", "responsibilities": "# Devex\n\n1. The docs are accurate and under budget.", "emits": ["lesson_proposed"],
                                               "probes": [{"name": "docs_budget", "command": "true", "every": "1h"}]}, **sup)
    api.handle(project, store, "create_agent", {"name": "retro", "roles": ["analyst"], "team": "devex", "kind": "ad_hoc", "session": "ephemeral",
                                                "wake_on": ["lesson_proposed", "probe_failed:docs_budget"]}, **sup)
    api.handle(project, store, "emit_event", {"type": "lesson_proposed", "subject": "T-1"}, role="keeper")
    m = TestClient(web.create_app(project)).get("/api/eventmap").json()
    edge = lambda f, t, k=None: any(e["from"] == f and e["to"] == t and (k is None or e["kind"] == k) for e in m["edges"])
    assert edge("ev:ticket_transition", "agent:reviewer", "wakes")                      # a built-in, woken by the loop
    assert next(e for e in m["edges"] if e["from"] == "ev:ticket_transition" and e["to"] == "agent:reviewer")["loop"] is True
    assert edge("agent:reviewer", "ev:ticket_transition", "emits")
    assert edge("ev:ticket_transition", "sys:merge_gate", "wakes") and edge("sys:merge_gate", "ev:gate_landed", "emits")
    assert edge("probe:docs_budget", "ev:probe_failed", "emits") and edge("ev:probe_failed", "agent:retro", "wakes")
    assert edge("agent:keeper", "ev:lesson_proposed", "may_emit") and edge("ev:lesson_proposed", "agent:retro", "wakes")
    assert next(e for e in m["edges"] if e["from"] == "agent:keeper" and e["to"] == "ev:lesson_proposed")["seen"] == 1   # declared, and it fired
    assert m["by"]["keeper"]["lesson_proposed"] == 1
    assert m["counts"]["lesson_proposed"] == 1
    assert next(n for n in m["nodes"] if n["id"] == "ev:lesson_proposed")["custom"] is True
