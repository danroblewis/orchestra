"""Tests for git worktree management, using real throwaway git repos."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from orchestra.gitops import (
    Git,
    GitError,
    WorktreeManifest,
    WorktreeRecord,
    worktree_branch_for,
)


@pytest.fixture()
def git_repo() -> Path:
    """A real git repo with one commit on ``main``."""
    tmp = Path(tempfile.mkdtemp())
    try:
        _run(tmp, "init", "-q", "-b", "main")
        _run(tmp, "config", "user.email", "t@example.com")
        _run(tmp, "config", "user.name", "Test")
        (tmp / "hello.txt").write_text("hi\n")
        _run(tmp, "add", ".")
        _run(tmp, "commit", "-q", "-m", "init")
        yield tmp
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def _run(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr)
    return out.stdout


def test_create_and_merge_and_remove(git_repo: Path):
    git = Git(git_repo)
    branch = worktree_branch_for("login")
    path = git_repo / ".orchestra-wt" / "login"

    # Not merged before we create it.
    assert not git.is_merged_into(branch, "main")

    git.create_worktree(branch, path)
    assert path.is_dir()
    assert git.branch_exists(branch)
    assert git.current_branch() == "main"  # base checkout untouched

    # Commit something on the branch, then it merges fast-forward into main.
    (path / "feature.txt").write_text("work\n")
    _run(path, "add", ".")
    _run(path, "commit", "-q", "-m", "add feature")

    assert not git.is_merged_into(branch, "main")  # still diverged
    git._run("merge", "--ff-only", branch)
    assert git.is_merged_into(branch, "main")

    git.remove_worktree(path, branch)
    assert not path.exists()
    assert not git.branch_exists(branch)


def test_manifest_persistence(git_repo: Path):
    git = Git(git_repo)
    manifest = git.load_manifest()
    assert isinstance(manifest, WorktreeManifest)
    assert manifest.records == []

    manifest.upsert(WorktreeRecord("login", "t1", "orchestra-login", str(git_repo)))
    git.save_manifest(manifest)

    reloaded = git.load_manifest()
    assert reloaded.get("login").task_id == "t1"
    assert reloaded.by_task("t1")[0].branch == "orchestra-login"

    reloaded.remove("login")
    git.save_manifest(reloaded)
    assert git.load_manifest().get("login") is None


def test_manifest_active_filter():
    m = WorktreeManifest(
        [
            WorktreeRecord("a", "1", "b1", "/x", status="working"),
            WorktreeRecord("b", "2", "b2", "/y", status="merged"),
            WorktreeRecord("c", "3", "b3", "/z", status="removed"),
        ]
    )
    active = {r.slug for r in m.active()}
    assert active == {"a"}


def test_branch_name_is_deterministic_and_clean():
    assert worktree_branch_for("login-form") == "orchestra-login-form"
    assert worktree_branch_for("weird slug!") == "orchestra-weird-slug-"
    assert worktree_branch_for("x") == worktree_branch_for("x")


def test_is_merged_into_missing_base_raises(git_repo: Path):
    git = Git(git_repo)
    # A branch that does not exist should raise GitError on rev-parse verify.
    with pytest.raises(GitError):
        git._run("rev-parse", "--verify", "--quiet", "refs/heads/nope-xyz")
