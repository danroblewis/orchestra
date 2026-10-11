"""Tickets, milestones, notes, and the state machine. See SPEC.md section 3."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class State(StrEnum):
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    IN_REVIEW = "IN_REVIEW"
    MERGING = "MERGING"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


WAITING = {State.OPEN, State.BLOCKED, State.READY_FOR_REVIEW, State.REJECTED, State.APPROVED}
ACTIVE = {State.IN_PROGRESS, State.IN_REVIEW, State.MERGING}
TERMINAL = {State.DONE, State.CANCELLED}

# Board column order.
STATE_ORDER = [
    State.OPEN, State.BLOCKED, State.IN_PROGRESS, State.REJECTED, State.READY_FOR_REVIEW,
    State.IN_REVIEW, State.APPROVED, State.MERGING, State.DONE, State.CANCELLED,
]

TRANSITIONS: dict[State, set[State]] = {
    State.OPEN: {State.IN_PROGRESS, State.CANCELLED},
    State.IN_PROGRESS: {State.READY_FOR_REVIEW, State.BLOCKED, State.OPEN, State.CANCELLED},
    State.READY_FOR_REVIEW: {State.IN_REVIEW, State.CANCELLED},
    State.IN_REVIEW: {State.APPROVED, State.REJECTED, State.READY_FOR_REVIEW, State.CANCELLED},
    State.REJECTED: {State.IN_PROGRESS, State.CANCELLED},
    State.APPROVED: {State.MERGING, State.CANCELLED},
    State.MERGING: {State.DONE, State.REJECTED, State.APPROVED, State.CANCELLED},
    State.BLOCKED: {State.OPEN, State.CANCELLED},
    State.DONE: set(),
    State.CANCELLED: set(),
}

# The waiting state an active state falls back to on crash recovery.
RECOVERY = {
    State.IN_PROGRESS: State.OPEN,
    State.IN_REVIEW: State.READY_FOR_REVIEW,
    State.MERGING: State.APPROVED,
}


class TransitionError(ValueError):
    pass


def check_transition(src: State, dst: State) -> None:
    if dst not in TRANSITIONS[src]:
        raise TransitionError(f"cannot move {src} -> {dst}")


class MilestoneStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass
class Note:
    author: str  # worker | reviewer | merge_gate | supervisor | coordinator | pipeline_manager | orchestra
    text: str
    kind: str = "note"  # note | review | gate | blocker
    created_at: str = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Milestone:
    id: str
    name: str
    description: str = ""
    order: int = 0
    status: MilestoneStatus = MilestoneStatus.OPEN
    version: int = 1
    created_at: str = field(default_factory=now)
    closed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Milestone:
        d = dict(d)
        d["status"] = MilestoneStatus(d.get("status", "open"))
        return cls(**d)


@dataclass
class Ticket:
    id: str
    title: str
    milestone_id: str
    description: str = ""
    acceptance: str = ""
    state: State = State.OPEN
    priority: int = 5
    depends_on: list[str] = field(default_factory=list)
    branch: str | None = None
    worker_session: str | None = None
    reviewer_session: str | None = None
    reviewed_commit: str | None = None
    blocked_reason: str | None = None
    feedback: str | None = None
    rejected_by: str | None = None
    review_rounds: int = 0
    created_by: str = "supervisor"
    version: int = 1
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    state_since: str = field(default_factory=now)

    @property
    def slug(self) -> str:
        base = "".join(c if c.isalnum() else " " for c in self.title.lower()).split()
        return "-".join(base)[:40].strip("-") or "ticket"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Ticket:
        d = dict(d)
        d["state"] = State(d.get("state", "OPEN"))
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})


def is_ready(t: Ticket, tickets: dict[str, Ticket], milestones: dict[str, Milestone]) -> bool:
    if t.state != State.OPEN:
        return False
    ms = milestones.get(t.milestone_id)
    if ms is None or ms.status != MilestoneStatus.OPEN:
        return False
    return all(d in tickets and tickets[d].state == State.DONE for d in t.depends_on)
