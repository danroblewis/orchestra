"""Repository for BuildResult (merge-gate run results) objects."""

from __future__ import annotations

from ..models import BuildResult
from .base import Repository, NotFound
from .json_store import JsonStore

_COLLECTION = "build_results"


class BuildResultRepository(Repository[BuildResult]):
    """Read/write access to build results, backed by a JsonStore."""

    def __init__(self, store: JsonStore):
        self.store = store

    def find(self, entity_id: str) -> BuildResult:
        for b in self.store.get(_COLLECTION):
            if b["id"] == entity_id:
                return BuildResult.from_dict(b)
        raise NotFound(entity_id)

    def find_all(self, **filters) -> list[BuildResult]:
        return [
            BuildResult.from_dict(b)
            for b in self.store.get(_COLLECTION)
            if all(b.get(k) == v for k, v in filters.items())
        ]

    def query(self, **filters) -> list[BuildResult]:
        return self.find_all(**filters)

    def save(self, entity: BuildResult) -> BuildResult:
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

    # ---- domain helpers -----------------------------------------------------

    def by_gate(self, gate_id: str) -> list[BuildResult]:
        """Build results for a gate, newest first."""
        return sorted(
            self.find_all(gate_id=gate_id),
            key=lambda b: b.created_at,
            reverse=True,
        )

    def by_branch(self, branch_id: str) -> list[BuildResult]:
        """Build results that tested the given branch, newest first."""
        return sorted(
            (b for b in self.find_all() if branch_id in b.branch_ids),
            key=lambda b: b.created_at,
            reverse=True,
        )

    def enabled(self) -> list[TestSpec]:
        """Test specs that produced build results (needed by the Pipeline Agent).

        The gate health / flaky-detection logic keys off the set of enabled merge-gate
        specs; the build-result store holds both collections under one JsonStore, so we
        surface the enabled specs from the sibling ``test_specs`` collection here rather
        than requiring the caller to thread a :class:`TestSpecRepository` alongside it.
        """

        from ..models import TestSpec, TestSpecGroup

        return [
            TestSpec.from_dict(t)
            for t in self.store.get("test_specs")
            if t.get("enabled", True)
            and TestSpecGroup(t.get("group", TestSpecGroup.UNIT.value)).value
            in (TestSpecGroup.UNIT.value, TestSpecGroup.CI.value)
        ]
