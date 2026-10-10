"""Integration tests for the worktree-aware orchestrator (Phase 3)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from shared.models import Status
from shared.repositories.json_store import JsonStore

# Import the backend Orchestrator through the same sys.path shim the package uses.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))  # backend is 2 up from tests/
from orchestrator.orchestrator import Orchestrator, MockTransport  # noqa: E402

from orchestra.gitops import Git  # noqa: E402
from orchestra.ticket_contract import parse_ticket_response  # noqa: E402
from orchestra.worktree_orchestrator import WorktreeExistsError, WorktreeOrchestrator  # noqa: E402


@pytest.fixture()
def repo() -> Path:
    tmp = Path(tempfile.mkdtemp())
    try:
        subprocess.run(["git", "-C", tmp, "init", "-q", "-b", "main"], check=True)
        subprocess.run(["git", "-C", tmp, "config", "user.email", "t@e.com"], check=True)
        subprocess.run(["git", "-C", tmp, "config", "user.name", "Test"], check=True)
        (tmp / "f.txt").write_text("x")
        subprocess.run(["git", "-C", tmp, "add", "."], check=True)
        subprocess.run(["git", "-C", tmp, "commit", "-q", "-m", "init"], check=True)
        yield tmp
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def orch(repo: Path):
    store = JsonStore(Path(tempfile.mkdtemp()) / "orchestra.json")
    o = Orchestrator(store, MockTransport())
    git = Git(repo)
    return WorktreeOrchestrator(o, git)


def test_create_and_reconcile_worktree(orch: WorktreeOrchestrator, repo: Path):
    t = orch.create_task("Login flow", status=Status.BACKLOG)
    rec = orch.create_worktree(t.id, "login")
    assert rec.branch == "orchestra-login"
    assert (repo / ".orchestra-wt" / "login").is_dir()
    assert rec.status == "working"
    assert len(orch.active_worktrees()) == 1

    # Removing the on-disk dir should be reconciled away.
    import shutil
    shutil.rmtree(repo / ".orchestra-wt" / "login")
    cleaned = orch.reconcile()
    assert cleaned == ["login"]
    assert orch.active_worktrees() == []


def test_reconcile_orphaned_worktree(orch: WorktreeOrchestrator, repo: Path):
    # A worktree exists on disk but has no manifest record (crashed run).
    orphan = repo / ".orchestra-wt" / "orphan"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-b", "orchestra-orphan", str(orphan), "HEAD"], check=True)
    cleaned = orch.reconcile()
    assert "orphan" in cleaned
    assert not orphan.exists()


def test_create_worktree_duplicate_raises(orch: WorktreeOrchestrator):
    t = orch.create_task("Task", status=Status.BACKLOG)
    orch.create_worktree(t.id, "t")
    with pytest.raises(WorktreeExistsError):
        orch.create_worktree(t.id, "t")


def test_pick_ready_ignores_active_and_unmet_deps(orch: WorktreeOrchestrator):
    t1 = orch.create_task("First", status=Status.BACKLOG)
    t2 = orch.create_task("Second", status=Status.BACKLOG, dependency_ids=[t1.id])
    t3 = orch.create_task("Third", status=Status.BACKLOG)

    # All three are ready initially; reserve one and confirm the others remain.
    orch.create_worktree(t3.id, "third")
    ready = {t.id for t in orch.pick_ready()}
    assert t1.id in ready
    assert t2.id not in ready  # depends on t1 (not done yet)
    assert t3.id not in ready  # worktree already reserved

    # Advance t1 to DONE; now t2 becomes ready.
    t1_done = orch.tasks.find(t1.id)
    t1_done.status = Status.DONE
    orch.tasks.save(t1_done)
    ready2 = {t.id for t in orch.pick_ready()}
    assert t2.id in ready2


def test_merge_and_apply_response(orch: WorktreeOrchestrator, repo: Path):
    t = orch.create_task("Feature", status=Status.BACKLOG)
    rec = orch.create_worktree(t.id, "feature")

    # Do real work on the branch, then fast-forward merge.
    wt = repo / ".orchestra-wt" / "feature"
    (wt / "new.txt").write_text("done")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-q", "-m", "feat"],
        check=True,
    )
    orch.merge_worktree("feature")
    assert orch.tasks.find(t.id).status == Status.DONE
    assert rec.status == "merged"


def test_apply_ticket_response_done_requires_review_and_ci(orch: WorktreeOrchestrator):
    t = orch.create_task("T", status=Status.BACKLOG)
    # DONE without review -> coerced to FAILED.
    out = orch.apply_ticket_response(t.id, '{"task_id": "%s", "state": "DONE"}' % t.id)
    assert out.task.status == Status.FAILED

    t2 = orch.create_task("T2", status=Status.BACKLOG)
    out2 = orch.apply_ticket_response(
        t2.id,
        '{"task_id": "%s", "state": "DONE", "review": {"passed": true}, "ci": {"status": "passed"}}'
        % t2.id,
    )
    assert out2.task.status == Status.DONE


def test_apply_invalid_response_blocks(orch: WorktreeOrchestrator):
    t = orch.create_task("T", status=Status.BACKLOG)
    out = orch.apply_ticket_response(t.id, "not json at all")
    assert out.task.status == Status.BLOCKED


def test_reviewer_verdict_overrides_worker_claim(orch: WorktreeOrchestrator):
    # Worker claims DONE with its own review.passed=true, but the Reviewer layer
    # did NOT pass -> the orchestrator must coerce to FAILED.
    t = orch.create_task("T", status=Status.BACKLOG)
    worker_text = (
        '{"task_id": "%s", "state": "DONE", '
        '"review": {"passed": true}, "ci": {"status": "passed"}}'
    ) % t.id
    reviewer = parse_ticket_response(
        '{"task_id": "%s", "review": {"passed": false}, "verdict": "tests failed"}' % t.id
    )
    out = orch.apply_ticket_response(t.id, worker_text, review=reviewer)
    assert out.task.status == Status.FAILED


def test_reviewer_approval_confirms_done(orch: WorktreeOrchestrator):
    t = orch.create_task("T", status=Status.BACKLOG)
    worker_text = (
        '{"task_id": "%s", "state": "DONE", '
        '"review": {"passed": true}, "ci": {"status": "passed"}}'
    ) % t.id
    reviewer = parse_ticket_response(
        '{"task_id": "%s", "review": {"passed": true}, "verdict": "good"}' % t.id
    )
    out = orch.apply_ticket_response(t.id, worker_text, review=reviewer)
    assert out.task.status == Status.DONE
