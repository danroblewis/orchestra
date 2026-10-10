"""Repository for TestSpec (merge-gate test command) objects."""

from __future__ import annotations

from typing import Any

from ..models import TestSpec, TestSpecGroup
from .base import Repository, NotFound
from .json_store import JsonStore

_COLLECTION = "test_specs"

_GROUP_ORDER = {g.value: i for i, g in enumerate(TestSpecGroup)}


class TestSpecRepository(Repository[TestSpec]):
    """Read/write access to test specs, backed by a JsonStore."""

    def __init__(self, store: JsonStore):
        self.store = store

    def find(self, entity_id: str) -> TestSpec:
        for t in self.store.get(_COLLECTION):
            if t["id"] == entity_id:
                return TestSpec.from_dict(t)
        raise NotFound(entity_id)

    def find_all(self, **filters) -> list[TestSpec]:
        return [
            TestSpec.from_dict(t)
            for t in self.store.get(_COLLECTION)
            if all(t.get(k) == v for k, v in filters.items())
        ]

    def query(self, **filters) -> list[TestSpec]:
        return self.find_all(**filters)

    def save(self, entity: TestSpec) -> TestSpec:
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

    def by_group(self, group: TestSpecGroup | str) -> list[TestSpec]:
        value = group.value if isinstance(group, TestSpecGroup) else group
        return self.find_all(group=value)

    def enabled(self) -> list[TestSpec]:
        return self.find_all(enabled=True)

    def all_ordered(self) -> list[TestSpec]:
        """All specs ordered by group order then label."""
        return sorted(
            self.find_all(),
            key=lambda t: (_GROUP_ORDER.get(t.group.value, 99), t.label),
        )


def _now() -> str:
    from datetime import datetime, UTC

    return datetime.now(UTC).isoformat() + "Z"
