"""Persistence round-trip: data written to the flat JSON file is readable
after the store is reopened, proving the store is swappable behind the repo.
"""

from __future__ import annotations

from shared.models import Task, Milestone, Status, BuildOutput, SessionLog
from shared.repositories.task_repository import TaskRepository
from shared.repositories.milestone_repository import MilestoneRepository
from shared.repositories.build_output_repository import BuildOutputRepository
from shared.repositories.session_log_repository import SessionLogRepository


def test_data_survives_store_reopen(tmp_path):
    path = tmp_path / "orchestra.json"

    # First store instance: write some data.
    store1 = __import__("shared.repositories.json_store", fromlist=["JsonStore"]).JsonStore(path)
    task_repo = TaskRepository(store1)
    task_repo.save(Task(title="Task A", status=Status.BACKLOG, priority=2))
    task_repo.save(Task(title="Task B", status=Status.DONE))

    # Reopen a fresh store from the same file.
    from shared.repositories.json_store import JsonStore

    store2 = JsonStore(path)
    assert store2.get("tasks")  # file actually persisted

    reloaded = TaskRepository(store2).find_all()
    assert {t.title for t in reloaded} == {"Task A", "Task B"}
    assert reloaded[0].status in (Status.BACKLOG, Status.DONE)


def test_build_output_and_session_logs_roundtrip(tmp_path):
    from shared.repositories.json_store import JsonStore

    store = JsonStore(tmp_path / "orchestra.json")
    builds = BuildOutputRepository(store)
    logs = SessionLogRepository(store)

    b = builds.save(BuildOutput(task_id="t1", status="failed", logs="boom"))
    builds.save(BuildOutput(task_id="t1", status="passed"))
    assert len(builds.by_task("t1")) == 2

    log = logs.save(SessionLog(session_name="supervisor", layer="supervisor"))
    assert logs.by_name("supervisor").id == log.id
    assert logs.by_layer("supervisor")
