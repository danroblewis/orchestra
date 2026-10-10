"""Repositories — the only layer that touches persistence.

The Repository pattern hides the underlying storage (a flat JSON file for now)
behind a clean interface so it can be swapped for a real database later.
Business logic never touches raw JSON — it always goes through a repository.
"""

from .base import Repository, NotFound
from .json_store import JsonStore
from .task_repository import TaskRepository
from .milestone_repository import MilestoneRepository
from .build_output_repository import BuildOutputRepository
from .session_log_repository import SessionLogRepository
from .test_spec_repository import TestSpecRepository
from .build_result_repository import BuildResultRepository

__all__ = [
    "Repository",
    "NotFound",
    "JsonStore",
    "TaskRepository",
    "MilestoneRepository",
    "BuildOutputRepository",
    "SessionLogRepository",
    "TestSpecRepository",
    "BuildResultRepository",
]
