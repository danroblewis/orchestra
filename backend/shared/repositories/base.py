"""Abstract repository interface and a small exception type.

Every repository implements this interface so callers treat storage
uniformly regardless of the underlying implementation.
"""

from __future__ import annotations

from typing import Generic, TypeVar, Protocol

T = TypeVar("T")
ID = str


class NotFound(KeyError):
    """Raised when an entity with the given id does not exist."""


class Repository(Protocol, Generic[T]):
    """The common contract every repository must satisfy."""

    def find(self, entity_id: ID) -> T:
        """Return a single entity by id, or raise NotFound."""
        ...

    def find_all(self, **filters) -> list[T]:
        """Return all entities, optionally filtered by field equality."""
        ...

    def save(self, entity: T) -> T:
        """Insert or update an entity; return the stored copy."""
        ...

    def delete(self, entity_id: ID) -> None:
        """Remove an entity by id, or raise NotFound."""
        ...

    def query(self, **filters) -> list[T]:
        """Alias for find_all — named `query` to hint analytical use."""
        ...
