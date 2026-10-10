"""Repository tests: TestSpec CRUD and grouping helpers."""

from __future__ import annotations

import pytest

from shared.models import TestSpec, TestSpecGroup
from shared.repositories.base import NotFound


def _make(label: str = "", group: TestSpecGroup = TestSpecGroup.UNIT, command: str = "pytest tests/") -> TestSpec:
    return TestSpec(label=label, group=group, command=command)


# --- CRUD -------------------------------------------------------------------

def test_save_and_find(test_spec_repo):
    t = test_spec_repo.save(_make("unit"))
    assert t.id
    assert t.created_at
    loaded = test_spec_repo.find(t.id)
    assert loaded.id == t.id
    assert loaded.label == "unit"
    assert loaded.group == TestSpecGroup.UNIT


def test_save_is_insert_then_update(test_spec_repo):
    t = test_spec_repo.save(_make("unit"))
    t.label = "integration"
    t.enabled = False
    test_spec_repo.save(t)

    loaded = test_spec_repo.find(t.id)
    assert loaded.label == "integration"
    assert loaded.enabled is False
    # Only one row exists in the store.
    assert len(test_spec_repo.find_all()) == 1


def test_delete(test_spec_repo):
    t = test_spec_repo.save(_make("temp"))
    test_spec_repo.delete(t.id)
    with pytest.raises(NotFound):
        test_spec_repo.find(t.id)
    with pytest.raises(NotFound):
        test_spec_repo.delete(t.id)  # already gone


def test_delete_missing_raises(test_spec_repo):
    with pytest.raises(NotFound):
        test_spec_repo.find("does-not-exist")


# --- round-trip -------------------------------------------------------------

def test_to_from_dict_roundtrip(test_spec_repo):
    t = test_spec_repo.save(
        TestSpec(label="smoke", group=TestSpecGroup.CI, command="pytest -q tests/smoke/", enabled=False)
    )
    d = t.to_dict()
    loaded = TestSpec.from_dict(d)
    assert loaded == t
    assert loaded.to_dict() == d


# --- grouping helpers -------------------------------------------------------

def test_by_group(test_spec_repo):
    u1 = test_spec_repo.save(_make("u1", TestSpecGroup.UNIT))
    i1 = test_spec_repo.save(_make("i1", TestSpecGroup.CI))
    u2 = test_spec_repo.save(_make("u2", TestSpecGroup.UNIT))

    by_unit = test_spec_repo.by_group(TestSpecGroup.UNIT)
    assert {t.id for t in by_unit} == {u1.id, u2.id}
    assert len(by_unit) == 2
    assert all(t.group == TestSpecGroup.UNIT for t in by_unit)

    by_ci = test_spec_repo.by_group(TestSpecGroup.CI)
    assert {t.id for t in by_ci} == {i1.id}


def test_by_group_with_string(test_spec_repo):
    test_spec_repo.save(_make("u1", TestSpecGroup.UNIT))
    c = test_spec_repo.save(_make("c1", TestSpecGroup.CI))

    ids = {t.id for t in test_spec_repo.by_group("ci")}
    assert ids == {c.id}


def test_enabled(test_spec_repo):
    on = test_spec_repo.save(_make("on", TestSpecGroup.UNIT))
    off = test_spec_repo.save(_make("off", TestSpecGroup.UNIT))
    off.enabled = False
    test_spec_repo.save(off)

    enabled_ids = {t.id for t in test_spec_repo.enabled()}
    assert enabled_ids == {on.id}


def test_all_ordered_by_group_then_label(test_spec_repo):
    test_spec_repo.save(_make("zeta", TestSpecGroup.UNIT))
    test_spec_repo.save(_make("alpha", TestSpecGroup.CI))
    test_spec_repo.save(_make("beta", TestSpecGroup.UNIT))
    test_spec_repo.save(_make("gamma", TestSpecGroup.DAILY))

    ordered = test_spec_repo.all_ordered()
    labels = [(t.group, t.label) for t in ordered]
    # unit group first (beta, zeta by label), then ci (alpha), then daily (gamma)
    assert labels == [
        (TestSpecGroup.UNIT, "beta"),
        (TestSpecGroup.UNIT, "zeta"),
        (TestSpecGroup.CI, "alpha"),
        (TestSpecGroup.DAILY, "gamma"),
    ]


# --- run_in_isolation -------------------------------------------------------

def test_run_in_isolation_inserts_k_expression():
    spec = TestSpec(command="pytest tests/")
    assert spec.run_in_isolation("test_login") == 'pytest -k "test_login" tests/'


def test_run_in_isolation_empty_selector_returns_unchanged():
    spec = TestSpec(command="pytest tests/")
    assert spec.run_in_isolation("") == "pytest tests/"


def test_run_in_isolation_pytest_with_args():
    spec = TestSpec(command="pytest -q tests/ --tb=short")
    assert spec.run_in_isolation("smoke") == 'pytest -k "smoke" -q tests/ --tb=short'


def test_run_in_isolation_non_pytest_appends_selector():
    spec = TestSpec(command="bash run_smoke.sh")
    assert spec.run_in_isolation("tests/smoke/") == "bash run_smoke.sh tests/smoke/"
