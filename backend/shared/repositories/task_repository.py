"""Repository for Task (ticket) objects."""

from __future__ import annotations

from typing import Any

from ..models import Task
from .base import Repository, NotFound
from .json_store import JsonStore

_COLLECTION = "tasks"


class TaskRepository(Repository[Task]):
    """Read/write access to tasks, backed by a JsonStore."""

    def __init__(self, store: JsonStore):
        self.store = store

    def find(self, entity_id: str) -> Task:
        for t in self.store.get(_COLLECTION):
            if t["id"] == entity_id:
                return Task.from_dict(t)
        raise NotFound(entity_id)

    def find_all(self, **filters) -> list[Task]:
        return [Task.from_dict(t) for t in self.store.get(_COLLECTION) if _matches(t, filters)]

    # `query` is a named alias for analytical / read-heavy callers (web server).
    def query(self, **filters) -> list[Task]:
        return self.find_all(**filters)

    def save(self, entity: Task) -> Task:
        entity.updated_at = _now()
        stored = entity.to_dict()
        existing = self.store.get(_COLLECTION)
        for i, t in enumerate(existing):
            if t["id"] == entity.id:
                existing[i] = stored
                self.store.set(_COLLECTION, existing)
                return entity
        existing.append(stored)
        self.store.set(_COLLECTION, existing)
        return entity

    def delete(self, entity_id: str) -> None:
        existing = self.store.get(_COLLECTION)
        if not any(t["id"] == entity_id for t in existing):
            raise NotFound(entity_id)
        self.store.set(_COLLECTION, [t for t in existing if t["id"] != entity_id])

    # ---- domain helpers -----------------------------------------------------

    def all(self) -> list[Task]:
        """Return every task (ordered by priority then creation)."""
        tasks = self.find_all()
        return sorted(tasks, key=lambda t: (t.priority, t.created_at))

    def by_milestone(self, milestone_id: str) -> list[Task]:
        return self.find_all(milestone_id=milestone_id)

    def by_status(self, status: str) -> list[Task]:
        return self.find_all(status=status)

    def next_in_queue(self, limit: int = 10) -> list[Task]:
        """Tasks whose dependencies are all DONE, sorted by priority.

        This is the "which tickets come next" aggregation query.
        """
        by_id = {t.id: t for t in self.find_all()}
        ready = []
        for t in self.find_all():
            if t.status != "backlog":
                continue
            deps = t.dependency_ids
            if all(by_id.get(d) is not None and by_id[d].status == "done" for d in deps):
                ready.append(t)
        return sorted(ready, key=lambda t: (t.priority, t.created_at))[:limit]

    def depends_on(self, task_id: str) -> list[Task]:
        """Tasks that depend on the given task (reverse-dependency view)."""
        return [t for t in self.find_all() if task_id in t.dependency_ids]


def _matches(record: dict[str, Any], filters: dict[str, Any]) -> bool:
    return all(record.get(k) == v for k, v in filters.items())


def _now() -> str:
    from datetime import datetime, UTC

    return datetime.now(UTC).isoformat() + "Z"
