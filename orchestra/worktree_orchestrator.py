"""Worktree-aware orchestration on top of the legacy :class:`Orchestrator`.

:class:`WorktreeOrchestrator` extends the existing ``backend`` ``Orchestrator`` with:

- per-ticket **git worktree** lifecycle (create -> work -> review -> merge -> remove),
- applying a Worker's structured **ticket response** to task state,
- the **pickup** rule: which BACKLOG tickets are ready to spawn a worker on.

It composes the old orchestrator rather than replacing it, so the proven
session-lifecycle / fan-out logic stays untouched.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# The legacy orchestration core lives in ``backend/`` and imports modules by
# bare package name (``from shared.models import ...``), so that directory must
# be on sys.path *before* importing it.
_BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(_BACKEND_ROOT))

from shared.models import Status  # noqa: E402
from shared.repositories.json_store import JsonStore  # noqa: E402

from orchestrator.orchestrator import Orchestrator  # noqa: E402
from orchestra.gitops import Git, WorktreeManifest, WorktreeRecord  # noqa: E402
from orchestra.ticket_contract import parse_ticket_response  # noqa: E402


class WorktreeExistsError(Exception):
    """Raised when a ticket already has an active worktree."""


@dataclass
class WorkerOutcome:
    """The result of running a worker turn: parsed response + applied task."""

    task_id: str
    task: Any
    response: Any
    applied: bool
    worktree: WorktreeRecord | None


class WorktreeOrchestrator:
    """Orchestration with git worktrees and ticket-hygiene state transitions."""

    def __init__(self, orchestrator: Orchestrator, git: Git, manifest: WorktreeManifest | None = None):
        self.orch = orchestrator
        self.git = git
        self.manifest = manifest or WorktreeManifest()
        # Mirror of the legacy task store helpers (kept for convenience).
        self.tasks = orchestrator.tasks
        self.milestones = orchestrator.milestones
        self.session_logs = orchestrator.session_logs

    # -- delegated task construction (convenience on top of the legacy core) -- #

    def create_task(self, title: str, description: str = "", **kwargs):
        return self.orch.create_task(title, description, **kwargs)

    def create_milestone(self, name: str, order: int = 0):
        return self.orch.create_milestone(name, order)

    def mark_done(self, task_id: str):
        return self.orch.mark_done(task_id)

    # -- persistence --------------------------------------------------------- #

    def save_manifest(self) -> None:
        self.git.save_manifest(self.manifest)

    # -- worktree lifecycle -------------------------------------------------- #

    def create_worktree(self, task_id: str, slug: str | None = None) -> WorktreeRecord:
        """Create a new worktree+branch for a ticket and record it in the manifest.

        Returns the :class:`WorktreeRecord`. Raises :class:`WorktreeExistsError`
        if the ticket already has an active worktree.
        """
        task = self.tasks.find(task_id)
        slug = slug or task.slug
        branch = self._branch_for(slug)
        if self.manifest.by_task(task_id):
            raise WorktreeExistsError(f"Task {task_id} already has a worktree record.")
        if self.git.branch_exists(branch):
            raise WorktreeExistsError(f"Branch {branch} already exists in git.")

        wt_path = self.git.worktrees_dir() / slug
        self.git.create_worktree(branch, wt_path)
        record = WorktreeRecord(
            slug=slug,
            task_id=task_id,
            branch=branch,
            path=str(wt_path),
            status="created",
        )
        self.manifest.upsert(record)
        self.save_manifest()

        # Mark the task in progress and assign the worker session.
        self.orch.assign_worker(task_id, f"worker-{slug}")
        record.status = "working"
        self.save_manifest()
        return record

    def _branch_for(self, slug: str) -> str:
        from orchestra.gitops import worktree_branch_for

        return worktree_branch_for(slug)

    def remove_worktree(self, slug: str) -> None:
        """Remove a worktree + branch and drop its manifest record (merged/removed)."""
        record = self.manifest.get(slug)
        if not record:
            return
        self.git.remove_worktree(Path(record.path), record.branch)
        record.status = "removed"
        self.manifest.remove(slug)
        self.save_manifest()

    def reconcile(self) -> list[str]:
        """Remove manifest records whose on-disk worktree directory is gone.

        Returns the slugs that were cleaned up.
        """
        cleaned: list[str] = []
        for record in list(self.manifest.records):
            if not Path(record.path).exists():
                self.git.prune()
                record.status = "removed"
                self.manifest.remove(record.slug)
                cleaned.append(record.slug)
        if cleaned:
            self.save_manifest()
        return cleaned

    def active_worktrees(self) -> list[WorktreeRecord]:
        return self.manifest.active()

    # -- pickup / merge ------------------------------------------------------ #

    def pick_ready(self) -> list[Any]:
        """BACKLOG tasks with all deps DONE and no active worktree (priority order)."""
        done_ids = {t.id for t in self.tasks.by_status("done")}
        ready: list[Any] = []
        for task in self.tasks.next_in_queue(limit=100):
            if self.manifest.by_task(task.id):
                continue
            if not all(d in done_ids for d in task.dependency_ids):
                continue
            ready.append(task)
        return ready

    def merge_worktree(self, slug: str, base_branch: str | None = None) -> WorktreeRecord:
        """Fast-forward merge a worktree's branch into ``base_branch``.

        Marks the task DONE and the worktree record ``merged``. Requires the branch
        to actually be mergeable into the base.
        """
        record = self.manifest.get(slug)
        if not record:
            raise ValueError(f"No worktree record for slug {slug!r}")
        base = base_branch or self.git.current_branch()
        # A fast-forward merge of the worktree branch into base is possible when
        # base is an ancestor of the worktree branch (base contained in branch).
        if not self.git.is_merged_into(base, record.branch):
            raise ValueError(
                f"Base {base} is not an ancestor of {record.branch}; refusing to fast-forward merge."
            )
        # Fast-forward the base branch (assumed checked out) to the worktree branch.
        self.git._run("merge", "--ff-only", record.branch)
        record.status = "merged"
        self.save_manifest()

        # Advance the task to DONE.
        task = self.tasks.find(record.task_id)
        task.status = Status.DONE
        self.tasks.save(task)
        return record

    # -- ticket-response application ---------------------------------------- #

    def apply_ticket_response(self, task_id: str, text: str | None) -> WorkerOutcome:
        """Parse a Worker's JSON response and apply it to the task state.

        Enforces the DONE-invariant (review + CI must have passed). Returns the
        outcome for the caller to decide on worktree/merge cleanup.
        """
        resp = parse_ticket_response(text)
        task = self.tasks.find(task_id)
        applied = False

        if not resp.valid:
            # Unparseable -> don't advance; record the error on the ticket.
            task.status = Status.BLOCKED
            task.description = (task.description or "") + f"\\n[orchestra] invalid response: {resp.error}"
            self.tasks.save(task)
            applied = True
        elif resp.state == "DONE":
            # Already enforced by parse_ticket_response (coerces to FAILED).
            task.status = Status.DONE
            applied = True
        elif resp.state == "FAILED":
            task.status = Status.FAILED
            applied = True
        elif resp.state == "BLOCKED":
            task.status = Status.BLOCKED
            applied = True
        else:  # IN_PROGRESS -- leave status as-is (caller may set IN_PROGRESS already)
            applied = False

        self.save_manifest()
        return WorkerOutcome(
            task_id=task_id, task=task, response=resp, applied=applied, worktree=None
        )
