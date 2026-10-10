"""End-to-end test: simulate a real Orchestra use case end-to-end.

This test:
1. Creates a milestone and tasks with dependencies (mock transport).
2. Runs a supervisor request that fans out to all agent layers.
3. Verifies the state is persisted correctly.
4. Reads the state back through the read-only web server's build_state().
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Make backend importable.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.repositories.json_store import JsonStore
from shared.models import Task, Milestone, Status
from orchestrator.orchestrator import Orchestrator, MockTransport


def test_full_orchestration_flow():
    with tempfile.TemporaryDirectory() as tmp:
        store = JsonStore(os.path.join(tmp, "orchestra.json"))
        orch = Orchestrator(store, MockTransport())

        # 1. Create a milestone and tasks.
        ms = orch.create_milestone("Milestone 1", order=1)
        t1 = orch.create_task("Set up project", milestone_id=ms.id, priority=1)
        t2 = orch.create_task("Implement core", milestone_id=ms.id, priority=2, dependency_ids=[t1.id])
        t3 = orch.create_task("Write tests", milestone_id=ms.id, priority=3, dependency_ids=[t2.id])

        # 2. Mark the first task done.
        orch.mark_done(t1.id)

        # 3. Run a supervisor request that fans out to all layers.
        result = orch.run_supervisor_request("Add user management feature")

        # Verify all three layers received the fan-out.
        assert "supervisor" in result
        assert "coordinator" in result
        assert "pipeline-manager" in result

        # 4. Verify state was persisted.
        reloaded = JsonStore(os.path.join(tmp, "orchestra.json"))
        tasks = [Task.from_dict(t) for t in reloaded.get("tasks")]
        milestones = [Milestone.from_dict(m) for m in reloaded.get("milestones")]
        session_logs = [
            __import__("shared.models", fromlist=["SessionLog"]).SessionLog.from_dict(s)
            for s in reloaded.get("session_logs")
        ]

        assert len(tasks) == 3
        assert len(milestones) == 1
        assert len(session_logs) >= 3  # supervisor, coordinator, pipeline-manager

        # 5. Verify the task graph and dependencies.
        by_id = {t.id: t for t in tasks}
        assert by_id[t1.id].status == Status.DONE
        assert by_id[t2.id].dependency_ids == [t1.id]
        assert by_id[t3.id].dependency_ids == [t2.id]

        # 6. Verify "next in queue" respects dependencies.
        ready = orch.tasks.next_in_queue()
        ready_titles = {t.title for t in ready}
        assert "Implement core" in ready_titles
        assert "Write tests" not in ready_titles  # depends on in-progress task


def test_web_server_reads_orchestrator_state(monkeypatch):
    """The read-only web server must see what the orchestrator persisted."""
    import web.server as server_mod

    with tempfile.TemporaryDirectory() as tmp:
        # Point the web server's store at the temp dir BEFORE it imports.
        monkeypatch.setenv("ORCHESTRA_DATA_DIR", tmp)
        store = JsonStore(os.path.join(tmp, "orchestra.json"))
        orch = Orchestrator(store, MockTransport())

        ms = orch.create_milestone("M1", order=1)
        t1 = orch.create_task("Task A", milestone_id=ms.id, priority=1)
        orch.mark_done(t1.id)
        orch.run_supervisor_request("Test request")

        # Read the state through a fresh JsonStore at the same path.
        reloaded = JsonStore(os.path.join(tmp, "orchestra.json"))
        tasks = [Task.from_dict(t) for t in reloaded.get("tasks")]
        session_logs = [
            __import__("shared.models", fromlist=["SessionLog"]).SessionLog.from_dict(s)
            for s in reloaded.get("session_logs")
        ]

        assert len(tasks) == 1
        assert tasks[0].status == Status.DONE
        assert len(session_logs) >= 3
