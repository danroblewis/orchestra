"""Repository for Milestone objects."""

from __future__ import annotations

from ..models import Milestone
from .base import Repository, NotFound
from .json_store import JsonStore

_COLLECTION = "milestones"


class MilestoneRepository(Repository[Milestone]):
    def __init__(self, store: JsonStore):
        self.store = store

    def find(self, entity_id: str) -> Milestone:
        for m in self.store.get(_COLLECTION):
            if m["id"] == entity_id:
                return Milestone.from_dict(m)
        raise NotFound(entity_id)

    def find_all(self, **filters) -> list[Milestone]:
        return [Milestone.from_dict(m) for m in self.store.get(_COLLECTION)]

    def query(self, **filters) -> list[Milestone]:
        return self.find_all()

    def save(self, entity: Milestone) -> Milestone:
        stored = entity.to_dict()
        existing = self.store.get(_COLLECTION)
        for i, m in enumerate(existing):
            if m["id"] == entity.id:
                existing[i] = stored
                self.store.set(_COLLECTION, existing)
                return entity
        existing.append(stored)
        self.store.set(_COLLECTION, existing)
        return entity

    def delete(self, entity_id: str) -> None:
        existing = self.store.get(_COLLECTION)
        if not any(m["id"] == entity_id for m in existing):
            raise NotFound(entity_id)
        self.store.set(_COLLECTION, [m for m in existing if m["id"] != entity_id])

    def ordered(self) -> list[Milestone]:
        return sorted(self.find_all(), key=lambda m: m.order)
