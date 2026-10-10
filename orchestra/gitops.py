"""Git worktree management for Orchestra.

Each ticket gets its own git worktree (branch). Orchestra **creates** them before a
worker runs and the Pipeline Manager **removes** them after the branch is merged.
Worktrees live under ``<repo>/.orchestra-wt/`` and a manifest records ownership so a
crashed worker's worktree can be reconciled later.

All git access goes through :class:`Git` -- thin ``subprocess`` wrappers -- so the
logic is easy to unit-test against a throwaway ``git init`` repo and never touches a
Python git binding.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class GitError(Exception):
    """Raised when a git command fails."""


@dataclass
class WorktreeRecord:
    """One tracked worktree entry in the manifest."""

    slug: str
    task_id: str
    branch: str
    path: str
    status: str = "created"  # created | working | review | merged | removed

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "task_id": self.task_id,
            "branch": self.branch,
            "path": self.path,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorktreeRecord":
        return cls(
            slug=d["slug"],
            task_id=d["task_id"],
            branch=d["branch"],
            path=d["path"],
            status=d.get("status", "created"),
        )


@dataclass
class WorktreeManifest:
    """Registry of Orchestra-managed worktrees."""

    records: list[WorktreeRecord] = field(default_factory=list)

    def upsert(self, record: WorktreeRecord) -> None:
        for i, existing in enumerate(self.records):
            if existing.slug == record.slug:
                self.records[i] = record
                return
        self.records.append(record)

    def remove(self, slug: str) -> None:
        self.records = [r for r in self.records if r.slug != slug]

    def get(self, slug: str) -> WorktreeRecord | None:
        for r in self.records:
            if r.slug == slug:
                return r
        return None

    def by_task(self, task_id: str) -> list[WorktreeRecord]:
        return [r for r in self.records if r.task_id == task_id]

    def active(self) -> list[WorktreeRecord]:
        """Worktrees still needing attention (not merged/removed)."""
        return [r for r in self.records if r.status not in ("merged", "removed")]

    def to_dict(self) -> dict[str, Any]:
        return {"worktrees": [r.to_dict() for r in self.records]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorktreeManifest":
        return cls([WorktreeRecord.from_dict(r) for r in d.get("worktrees", [])])


class Git:
    """Thin wrapper around the ``git`` CLI for Orchestra worktree operations."""

    def __init__(self, repo_root: str | Path):
        self.repo_root = Path(repo_root).resolve()

    # -- low level --------------------------------------------------------- #

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            ["git", "-C", str(self.repo_root), *args],
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc

    # -- branch helpers ---------------------------------------------------- #

    def current_branch(self) -> str:
        out = self._run("rev-parse", "--abbrev-ref", "HEAD")
        return out.stdout.strip()

    def branch_exists(self, branch: str) -> bool:
        # rev-parse --verify --quiet exits 1 (not an error) for a missing branch.
        out = self._run("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False)
        return out.returncode == 0

    def is_merged_into(self, branch: str, base: str) -> bool:
        """True if ``branch`` is fully contained in ``base`` (mergeable with --ff)."""
        if not self.branch_exists(branch) or not self.branch_exists(base):
            return False
        out = self._run("merge-base", "--is-ancestor", branch, base, check=False)
        return out.returncode == 0

    def unmerged_commits(self, branch: str, base: str) -> list[str]:
        """Commit SHAs on ``branch`` not yet in ``base`` (newest first)."""
        if not self.branch_exists(branch) or not self.branch_exists(base):
            return []
        out = self._run("rev-list", f"{base}..{branch}", check=False)
        return [sha for sha in out.stdout.split() if sha]

    # -- worktree operations ---------------------------------------------- #

    def worktrees_dir(self) -> Path:
        d = self.repo_root / ".orchestra-wt"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def manifest_path(self) -> Path:
        return self.worktrees_dir() / ".manifest.json"

    def load_manifest(self) -> WorktreeManifest:
        path = self.manifest_path()
        if not path.exists():
            return WorktreeManifest()
        return WorktreeManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save_manifest(self, manifest: WorktreeManifest) -> None:
        path = self.manifest_path()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
        import os

        os.replace(tmp, path)

    def list_worktrees(self) -> list[dict[str, Any]]:
        """Read ``git worktree list`` -- what actually exists on disk."""
        out = self._run("worktree", "list", "--porcelain")
        blocks: list[dict[str, Any]] = []
        current: dict[str, str] = {}
        for line in out.stdout.splitlines():
            if not line:
                if current:
                    blocks.append(current)
                    current = {}
                continue
            key, _, value = line.partition(" ")
            current[key] = value
        if current:
            blocks.append(current)
        return blocks

    def create_worktree(self, branch: str, path: Path) -> Path:
        """Create a new worktree at ``path`` on ``branch`` (checked out from HEAD)."""
        path = Path(path).resolve()
        self._run("worktree", "add", "-b", branch, str(path), "HEAD")
        return path

    def remove_worktree(self, path: Path, branch: str | None = None) -> None:
        """Force-remove a worktree directory and its (unmerged) branch ref.

        The branch is passed explicitly because Orchestra always knows it (from the
        manifest) and because ``worktree remove`` deletes the directory first,
        invalidating a path-based lookup of the branch.
        """
        self._run("worktree", "remove", "--force", str(path))
        # ``worktree remove`` leaves the branch ref behind; drop it so the tree
        # is fully cleaned up.
        if branch:
            self._run("branch", "-D", branch, check=False)
        else:  # best-effort: recover the branch from a still-present worktree
            recovered = self._branch_for_worktree(path)
            if recovered:
                self._run("branch", "-D", recovered, check=False)

    def prune(self) -> None:
        """Drop worktree entries whose directory is gone."""
        self._run("worktree", "prune")

    def _branch_for_worktree(self, path: Path) -> str | None:
        """Return the short branch name bound to a worktree path, if any."""
        for block in self.list_worktrees():
            if Path(block.get("dir", "")).resolve() == Path(path).resolve():
                ref = block.get("branch")
                if not ref:
                    return None
                # refs may be full paths like "refs/heads/foo"; strip to the name.
                return ref.rsplit("/", 1)[-1] if "/" in ref else ref
        return None


def worktree_branch_for(slug: str, prefix: str = "orchestra-") -> str:
    """Deterministic branch name for a ticket slug."""
    clean = "".join(c if (c.isalnum() or c in "-_") else "-" for c in slug)
    return f"{prefix}{clean}"
