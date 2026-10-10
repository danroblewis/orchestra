"""Core data models for Orchestra.

These are plain data classes (no framework dependency) so they can be used by
both the read-write orchestrator and the read-only web server.

Task objects are called "tickets" per the project invariants. Tickets are
grouped into milestones and form a directed graph of dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(UTC).isoformat() + "Z"


class Status(str, Enum):
    """Lifecycle status of a task."""

    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass
class Task:
    """A single unit of work (a "ticket")."""

    id: str = field(default_factory=lambda: uuid4().hex)
    title: str = ""
    description: str = ""
    status: Status = Status.BACKLOG
    priority: int = 5  # 1 (highest) .. 10 (lowest)
    milestone_id: str | None = None
    dependency_ids: list[str] = field(default_factory=list)
    assignee_session_id: str | None = None  # worker session id
    build_status: str | None = None  # "passed", "failed", "slow", "unknown"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @property
    def slug(self) -> str:
        """URL-safe identifier derived from the title (e.g. worktree branch)."""
        base = "".join(c if (c.isalnum() or c == " ") else " " for c in self.title).strip()
        return "-".join(base.lower().split())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority,
            "milestone_id": self.milestone_id,
            "dependency_ids": list(self.dependency_ids),
            "assignee_session_id": self.assignee_session_id,
            "build_status": self.build_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        return cls(
            id=d["id"],
            title=d.get("title", ""),
            description=d.get("description", ""),
            status=Status(d.get("status", Status.BACKLOG.value)),
            priority=d.get("priority", 5),
            milestone_id=d.get("milestone_id"),
            dependency_ids=list(d.get("dependency_ids", [])),
            assignee_session_id=d.get("assignee_session_id"),
            build_status=d.get("build_status"),
            created_at=d.get("created_at", _now()),
            updated_at=d.get("updated_at", _now()),
        )


@dataclass
class Milestone:
    """An ordered grouping of tasks."""

    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = ""
    order: int = 0
    task_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "order": self.order,
            "task_ids": list(self.task_ids),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Milestone":
        return cls(
            id=d["id"],
            name=d.get("name", ""),
            order=d.get("order", 0),
            task_ids=list(d.get("task_ids", [])),
        )


@dataclass
class BuildOutput:
    """Build/merge-queue output tracked per task."""

    id: str = field(default_factory=lambda: uuid4().hex)
    task_id: str = ""
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    status: str = "unknown"  # "passed", "failed", "slow", "unknown"
    duration_seconds: float | None = None
    logs: str = ""
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "logs": self.logs,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BuildOutput":
        return cls(
            id=d["id"],
            task_id=d.get("task_id", ""),
            started_at=d.get("started_at", _now()),
            finished_at=d.get("finished_at"),
            status=d.get("status", "unknown"),
            duration_seconds=d.get("duration_seconds"),
            logs=d.get("logs", ""),
            created_at=d.get("created_at", _now()),
        )


@dataclass
class TestSpecGroup(Enum):
    """The merge-gate test category a TestSpec belongs to."""

    UNIT = "unit"
    CI = "ci"
    DAILY = "daily"


# Ordered by how often the merge gate runs: unit first, then ci, then daily.
_TEST_SPEC_GROUP_ORDER = {g.value: i for i, g in enumerate(TestSpecGroup)}


@dataclass
class TestSpec:
    """A named shell command the merge gate runs over a batch of branches."""

    id: str = field(default_factory=lambda: uuid4().hex)
    label: str = ""  # human name, e.g. "unit", "integration", "smoke"
    command: str = ""  # the shell command the merge gate runs, e.g. "pytest tests/"
    group: TestSpecGroup = field(default_factory=lambda: TestSpecGroup.UNIT)
    enabled: bool = True
    failure_count: int = 0
    last_failure: str | None = None
    notes: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def run_in_isolation(self, selector: str) -> str:
        """Return a command filtered down to a subset of tests.

        The selector is a pytest ``-k`` expression or a file path. When the
        command is pytest-based, ``-k "<selector>"`` is inserted right after
        ``pytest``; otherwise the selector is appended as trailing arguments.
        An empty selector returns the command unchanged.
        """
        if not selector:
            return self.command

        if "pytest" in self.command:
            parts = self.command.split()
            for i, part in enumerate(parts):
                if part == "pytest":
                    parts.insert(i + 1, f'-k "{selector}"')
                    return " ".join(parts)
            return self.command + f' -k "{selector}"'

        # bash-style command: append the selector as trailing arguments.
        return f"{self.command} {selector}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "command": self.command,
            "group": self.group.value,
            "enabled": self.enabled,
            "failure_count": self.failure_count,
            "last_failure": self.last_failure,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TestSpec":
        return cls(
            id=d["id"],
            label=d.get("label", ""),
            command=d.get("command", ""),
            group=TestSpecGroup(d.get("group", TestSpecGroup.UNIT.value)),
            enabled=d.get("enabled", True),
            failure_count=d.get("failure_count", 0),
            last_failure=d.get("last_failure"),
            notes=d.get("notes", ""),
            created_at=d.get("created_at", _now()),
            updated_at=d.get("updated_at", _now()),
        )


@dataclass
class BuildResult:
    """A single merge-gate run over a batch of candidate branches."""

    id: str = field(default_factory=lambda: uuid4().hex)
    gate_id: str = ""
    branch_ids: list[str] = field(default_factory=list)
    test_ids: list[str] = field(default_factory=list)
    status: str = "unknown"  # "passed", "failed", "slow", "unknown"
    duration_seconds: float | None = None
    failed_tests: list[str] = field(default_factory=list)
    logs: str = ""
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "gate_id": self.gate_id,
            "branch_ids": list(self.branch_ids),
            "test_ids": list(self.test_ids),
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "failed_tests": list(self.failed_tests),
            "logs": self.logs,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BuildResult":
        return cls(
            id=d["id"],
            gate_id=d.get("gate_id", ""),
            branch_ids=list(d.get("branch_ids", [])),
            test_ids=list(d.get("test_ids", [])),
            status=d.get("status", "unknown"),
            duration_seconds=d.get("duration_seconds"),
            failed_tests=list(d.get("failed_tests", [])),
            logs=d.get("logs", ""),
            created_at=d.get("created_at", _now()),
        )


@dataclass
class SessionLog:
    """Retained session metadata so a Pi session can be restarted."""

    id: str = field(default_factory=lambda: uuid4().hex)
    session_name: str = ""  # e.g. "supervisor", "coordinator", "worker-feature-x"
    layer: str = ""  # "supervisor" | "coordinator" | "pipeline-manager" | "worker"
    session_file_path: str = ""
    cwd: str = ""
    model: str | None = None
    message_count: int = 0
    last_entry_id: str | None = None
    status: str = "idle"  # "idle" | "running" | "error"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_name": self.session_name,
            "layer": self.layer,
            "session_file_path": self.session_file_path,
            "cwd": self.cwd,
            "model": self.model,
            "message_count": self.message_count,
            "last_entry_id": self.last_entry_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SessionLog":
        return cls(
            id=d["id"],
            session_name=d.get("session_name", ""),
            layer=d.get("layer", ""),
            session_file_path=d.get("session_file_path", ""),
            cwd=d.get("cwd", ""),
            model=d.get("model"),
            message_count=d.get("message_count", 0),
            last_entry_id=d.get("last_entry_id"),
            status=d.get("status", "idle"),
            created_at=d.get("created_at", _now()),
            updated_at=d.get("updated_at", _now()),
        )
