"""Repository tests: CRUD, dependency filtering, and "what's next" queries."""

from __future__ import annotations

import pytest

from shared.models import Task, Status
from shared.repositories.base import NotFound


def _make(
    title: str,
    deps: list[str] | None = None,
    status: Status = Status.BACKLOG,
    priority: int = 5,
    milestone_id: str | None = None,
) -> Task:
    return Task(
        title=title,
        dependency_ids=deps or [],
        status=status,
        priority=priority,
        milestone_id=milestone_id,
    )


# --- CRUD -------------------------------------------------------------------

def test_save_and_find(task_repo):
    t = task_repo.save(_make("Implement login"))
    assert t.id
    assert t.updated_at
    loaded = task_repo.find(t.id)
    assert loaded.id == t.id
    assert loaded.title == "Implement login"


def test_save_is_insert_then_update(task_repo):
    t = task_repo.save(_make("First"))
    t.title = "Renamed"
    t.status = Status.IN_PROGRESS
    task_repo.save(t)

    loaded = task_repo.find(t.id)
    assert loaded.title == "Renamed"
    assert loaded.status == Status.IN_PROGRESS

    # Only one row exists in the store.
    assert len(task_repo.find_all()) == 1


def test_delete(task_repo):
    t = task_repo.save(_make("Temp"))
    task_repo.delete(t.id)
    with pytest.raises(NotFound):
        task_repo.find(t.id)
    with pytest.raises(NotFound):
        task_repo.delete(t.id)  # already gone


def test_delete_missing_raises(task_repo):
    with pytest.raises(NotFound):
        task_repo.find("does-not-exist")


# --- Filtering --------------------------------------------------------------

def test_find_all_with_filter(task_repo):
    a = task_repo.save(_make("A", status=Status.BACKLOG))
    b = task_repo.save(_make("B", status=Status.DONE))
    c = task_repo.save(_make("C", status=Status.BACKLOG))

    backlog = task_repo.by_status(Status.BACKLOG.value)
    assert {t.id for t in backlog} == {a.id, c.id}


def test_by_milestone(task_repo):
    a = task_repo.save(_make("A", milestone_id="ms1"))
    b = task_repo.save(_make("B", milestone_id="ms1"))
    task_repo.save(_make("C", milestone_id="ms2"))

    ids = {t.id for t in task_repo.by_milestone("ms1")}
    assert {a.id, b.id} == ids


def test_depends_on_reverse_query(task_repo):
    base = task_repo.save(_make("base"))
    dep1 = task_repo.save(_make("dep1", deps=[base.id]))
    dep2 = task_repo.save(_make("dep2", deps=[base.id]))
    task_repo.save(_make("no-deps"))

    ids = {t.id for t in task_repo.depends_on(base.id)}
    assert {dep1.id, dep2.id} == ids


# --- "what's next" ----------------------------------------------------------

def test_next_in_queue_respects_dependencies(task_repo):
    base = task_repo.save(_make("base", status=Status.DONE, priority=10))
    awaiting = task_repo.save(_make("awaiting-base", deps=[base.id], priority=2))
    blocked = task_repo.save(_make("blocked-by-other", deps=["missing-done"], priority=3))
    other = task_repo.save(_make("other", status=Status.IN_PROGRESS, priority=1))  # not done
    todo = task_repo.save(_make("todo-with-no-deps", priority=4))

    ready_ids = {t.id for t in task_repo.next_in_queue()}
    assert awaiting.id in ready_ids
    assert todo.id in ready_ids
    # "other" is not done, so "blocked-by-other" is not ready.
    assert blocked.id not in ready_ids
    # in-progress/done tasks are excluded from "next".
    assert other.id not in ready_ids


def test_next_in_queue_respects_priority(task_repo):
    p1 = task_repo.save(_make("low-priority", priority=9))
    p2 = task_repo.save(_make("high-priority", priority=1))
    next_list = task_repo.next_in_queue()
    assert next_list[0].id == p2.id
