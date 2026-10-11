"""End-to-end: the real loop, store, git, and gate driven by a fake Pi."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from orchestra.config import init_project
from orchestra.events import Events
from orchestra.loop import Loop
from orchestra.model import State
from orchestra.store import LocalStore

FAKE = Path(__file__).parent / "fake_pi.py"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(home))
    fake = tmp_path / "pi"
    shutil.copy(FAKE, fake)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PI_BINARY", str(fake))
    monkeypatch.delenv("FAKE_PI_WORKER_BLOCK", raising=False)
    monkeypatch.delenv("FAKE_PI_REJECT_FIRST", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.email", "t@t", cwd=repo)
    git("config", "user.name", "t", cwd=repo)
    (repo / "README.md").write_text("# e2e\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "init", cwd=repo)
    project = init_project(repo, prefix="E2E", unit_command="test -f README.md")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "orchestra config", cwd=repo)
    monkeypatch.setenv("ORCHESTRA_REPO", str(repo))
    events = Events(project.events_file)
    store = LocalStore(project, events)
    ms = store.create_milestone(name="m")
    return project, store, events, ms, repo


def run_loop(project, store, events):
    Loop(project, store, events).run(once=True)


def test_ticket_goes_open_to_done(env):
    project, store, events, ms, repo = env
    t = store.create_ticket(title="Do the thing", milestone_id=ms.id, description="x", acceptance="y")
    run_loop(project, store, events)
    t = store.get_ticket(t.id)
    assert t.state == State.DONE
    assert "WORK.md" in git("ls-tree", "--name-only", "main", cwd=repo)
    assert "Merge E2E-1" in git("log", "-1", "--format=%s", "main", cwd=repo)
    assert not (project.worktrees_dir / t.id).exists()
    assert not git("branch", "--list", "orchestra/*", cwd=repo).strip()
    assert {s["id"] for s in store.sessions()} == {"coordinator", "pipeline-manager"}
    assert store.gate_runs()[-1]["status"] == "landed"
    assert store.get_milestone(ms.id).status == "open"  # fake coordinator does not close it


def test_rejection_loops_back_to_worker(env, monkeypatch):
    project, store, events, ms, repo = env
    monkeypatch.setenv("FAKE_PI_REJECT_FIRST", "1")
    t = store.create_ticket(title="Needs two tries", milestone_id=ms.id)
    run_loop(project, store, events)
    t = store.get_ticket(t.id)
    assert t.state == State.DONE and t.review_rounds == 1
    kinds = [n["kind"] for n in store.notes(t.id)]
    assert kinds.count("review") == 2


def test_blocked_worker(env, monkeypatch):
    project, store, events, ms, repo = env
    monkeypatch.setenv("FAKE_PI_WORKER_BLOCK", "1")
    t = store.create_ticket(title="Blocked one", milestone_id=ms.id)
    run_loop(project, store, events)
    t = store.get_ticket(t.id)
    assert t.state == State.BLOCKED and t.blocked_reason == "need a decision"
    assert (project.worktrees_dir / t.id).exists()  # kept for resumption


def test_dependency_order(env):
    project, store, events, ms, repo = env
    a = store.create_ticket(title="A", milestone_id=ms.id, priority=5)
    b = store.create_ticket(title="B", milestone_id=ms.id, priority=1, depends_on=[a.id])
    run_loop(project, store, events)
    assert store.get_ticket(a.id).state == State.DONE
    assert store.get_ticket(b.id).state == State.DONE
    log = git("log", "--format=%s", "main", cwd=repo).splitlines()
    assert log.index(f"Merge {b.id}: B") < log.index(f"Merge {a.id}: A")  # B landed after A
