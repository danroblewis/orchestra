"""Repository for BuildOutput (merge-queue build results) objects."""

from __future__ import annotations

from ..models import BuildOutput
from .base import Repository, NotFound
from .json_store import JsonStore

_COLLECTION = "build_outputs"


class BuildOutputRepository(Repository[BuildOutput]):
    def __init__(self, store: JsonStore):
        self.store = store

    def find(self, entity_id: str) -> BuildOutput:
        for b in self.store.get(_COLLECTION):
            if b["id"] == entity_id:
                return BuildOutput.from_dict(b)
        raise NotFound(entity_id)

    def find_all(self, **filters) -> list[BuildOutput]:
        return [
            BuildOutput.from_dict(b)
            for b in self.store.get(_COLLECTION)
            if all(b.get(k) == v for k, v in filters.items())
        ]

    def query(self, **filters) -> list[BuildOutput]:
        return self.find_all(**filters)

    def save(self, entity: BuildOutput) -> BuildOutput:
        stored = entity.to_dict()
        existing = self.store.get(_COLLECTION)
        for i, b in enumerate(existing):
            if b["id"] == entity.id:
                existing[i] = stored
                self.store.set(_COLLECTION, existing)
                return entity
        existing.append(stored)
        self.store.set(_COLLECTION, existing)
        return entity

    def delete(self, entity_id: str) -> None:
        existing = self.store.get(_COLLECTION)
        if not any(b["id"] == entity_id for b in existing):
            raise NotFound(entity_id)
        self.store.set(_COLLECTION, [b for b in existing if b["id"] != entity_id])

    def by_task(self, task_id: str) -> list[BuildOutput]:
        """Most-recent build outputs for a task, newest first."""
        return sorted(
            (b for b in self.find_all(task_id=task_id)),
            key=lambda b: b.started_at,
            reverse=True,
        )
