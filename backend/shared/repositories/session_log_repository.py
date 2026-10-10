"""Repository for SessionLog objects (metadata for restartable Pi sessions)."""

from __future__ import annotations

from ..models import SessionLog
from .base import Repository, NotFound
from .json_store import JsonStore

_COLLECTION = "session_logs"


class SessionLogRepository(Repository[SessionLog]):
    def __init__(self, store: JsonStore):
        self.store = store

    def find(self, entity_id: str) -> SessionLog:
        for s in self.store.get(_COLLECTION):
            if s["id"] == entity_id:
                return SessionLog.from_dict(s)
        raise NotFound(entity_id)

    def find_all(self, **filters) -> list[SessionLog]:
        return [
            SessionLog.from_dict(s)
            for s in self.store.get(_COLLECTION)
            if all(s.get(k) == v for k, v in filters.items())
        ]

    def query(self, **filters) -> list[SessionLog]:
        return self.find_all(**filters)

    def save(self, entity: SessionLog) -> SessionLog:
        entity.updated_at = _now()
        stored = entity.to_dict()
        existing = self.store.get(_COLLECTION)
        for i, s in enumerate(existing):
            if s["id"] == entity.id:
                existing[i] = stored
                self.store.set(_COLLECTION, existing)
                return entity
        existing.append(stored)
        self.store.set(_COLLECTION, existing)
        return entity

    def delete(self, entity_id: str) -> None:
        existing = self.store.get(_COLLECTION)
        if not any(s["id"] == entity_id for s in existing):
            raise NotFound(entity_id)
        self.store.set(_COLLECTION, [s for s in existing if s["id"] != entity_id])

    def by_name(self, session_name: str) -> SessionLog | None:
        """Return the current log for a named session (e.g. 'supervisor')."""
        for s in self.store.get(_COLLECTION):
            if s["session_name"] == session_name:
                return SessionLog.from_dict(s)
        return None

    def by_layer(self, layer: str) -> list[SessionLog]:
        return self.find_all(layer=layer)


def _now() -> str:
    from datetime import datetime, UTC

    return datetime.now(UTC).isoformat() + "Z"
