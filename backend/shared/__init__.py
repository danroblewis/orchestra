"""Shared library used by both the orchestrator and web server.

Contains the data models, the Repository pattern (with a JSON-backed
implementation), and the API contract. Neither process writes to the store
directly except through a repository, and the web server only ever *reads*
through repositories.
"""

from .models import Task, Milestone, BuildOutput, SessionLog, Status

__all__ = ["Task", "Milestone", "BuildOutput", "SessionLog", "Status"]
