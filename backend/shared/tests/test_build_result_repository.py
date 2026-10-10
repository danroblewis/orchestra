"""Repository tests: BuildResult CRUD and gate/branch queries."""

from __future__ import annotations

import pytest

from shared.models import BuildResult
from shared.repositories.base import NotFound


def _make(gate_id: str = "g1", branch_ids: list[str] | None = None, status: str = "passed") -> BuildResult:
    return BuildResult(gate_id=gate_id, branch_ids=branch_ids or ["branch-a"], status=status)


# --- CRUD -------------------------------------------------------------------

def test_save_and_find(build_result_repo):
    b = build_result_repo.save(_make(gate_id="g1"))
    assert b.id
    assert b.created_at
    loaded = build_result_repo.find(b.id)
    assert loaded.id == b.id
    assert loaded.gate_id == "g1"
    assert loaded.status == "passed"


def test_save_is_insert_then_update(build_result_repo):
    b = build_result_repo.save(_make())
    b.status = "failed"
    b.failed_tests = ["t1", "t2"]
    build_result_repo.save(b)

    loaded = build_result_repo.find(b.id)
    assert loaded.status == "failed"
    assert loaded.failed_tests == ["t1", "t2"]
    assert len(build_result_repo.find_all()) == 1


def test_delete(build_result_repo):
    b = build_result_repo.save(_make())
    build_result_repo.delete(b.id)
    with pytest.raises(NotFound):
        build_result_repo.find(b.id)
    with pytest.raises(NotFound):
        build_result_repo.delete(b.id)  # already gone


def test_delete_missing_raises(build_result_repo):
    with pytest.raises(NotFound):
        build_result_repo.find("does-not-exist")


def test_to_from_dict_roundtrip(build_result_repo):
    b = build_result_repo.save(
        BuildResult(gate_id="g9", branch_ids=["a", "b"], test_ids=["t1"], status="failed", failed_tests=["t1"])
    )
    d = b.to_dict()
    loaded = BuildResult.from_dict(d)
    assert loaded == b
    assert loaded.to_dict() == d


def test_branch_ids_roundtrip_as_lists(build_result_repo):
    b = build_result_repo.save(_make(gate_id="g1", branch_ids=["x", "y"]))
    loaded = build_result_repo.find(b.id)
    assert isinstance(loaded.branch_ids, list)
    assert loaded.branch_ids == ["x", "y"]


# --- by_gate ----------------------------------------------------------------

def test_by_gate_newest_first(build_result_repo):
    old = build_result_repo.save(_make(gate_id="g1", branch_ids=["a"]))
    old.created_at = "2024-01-01T00:00:00Z"
    build_result_repo.save(old)

    new = build_result_repo.save(_make(gate_id="g1", branch_ids=["b"]))
    new.created_at = "2024-01-03T00:00:00Z"
    build_result_repo.save(new)

    mid = build_result_repo.save(_make(gate_id="g1", branch_ids=["c"]))
    mid.created_at = "2024-01-02T00:00:00Z"
    build_result_repo.save(mid)

    # Different gate is excluded.
    build_result_repo.save(_make(gate_id="g2", branch_ids=["d"]))

    results = build_result_repo.by_gate("g1")
    assert [b.id for b in results] == [new.id, mid.id, old.id]


# --- by_branch --------------------------------------------------------------

def test_by_branch(build_result_repo):
    # branch "b" is tested by two gate runs; branch "z" by only one.
    common = build_result_repo.save(_make(gate_id="g1", branch_ids=["a", "b"]))
    also_common = build_result_repo.save(_make(gate_id="g2", branch_ids=["b", "c"]))
    only_branch = build_result_repo.save(_make(gate_id="g3", branch_ids=["z"]))

    # branch "b" appears in g1 and g2, but not in g3.
    ids = {b.id for b in build_result_repo.by_branch("b")}
    assert ids == {common.id, also_common.id}

    # branch "z" only appears in g3.
    z_ids = {b.id for b in build_result_repo.by_branch("z")}
    assert z_ids == {only_branch.id}

    # branch "a" only appears in g1.
    assert len(build_result_repo.by_branch("a")) == 1


def test_by_branch_newest_first(build_result_repo):
    r1 = build_result_repo.save(_make(gate_id="g1", branch_ids=["a"]))
    r1.created_at = "2024-01-01T00:00:00Z"
    build_result_repo.save(r1)

    r2 = build_result_repo.save(_make(gate_id="g2", branch_ids=["a"]))
    r2.created_at = "2024-01-02T00:00:00Z"
    build_result_repo.save(r2)

    results = build_result_repo.by_branch("a")
    assert [b.id for b in results] == [r2.id, r1.id]
