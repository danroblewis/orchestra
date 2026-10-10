"""Pytest fixtures that provide an isolated in-memory-backed store per test."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the backend root is importable.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def store(tmp_path):
    from shared.repositories.json_store import JsonStore

    return JsonStore(tmp_path / "orchestra.json")


@pytest.fixture()
def task_repo(store):
    from shared.repositories.task_repository import TaskRepository

    return TaskRepository(store)


@pytest.fixture()
def milestone_repo(store):
    from shared.repositories.milestone_repository import MilestoneRepository

    return MilestoneRepository(store)
