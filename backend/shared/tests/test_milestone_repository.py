"""Repository tests: Milestone CRUD and ordering."""

from __future__ import annotations

import pytest

from shared.models import Milestone
from shared.repositories.base import NotFound


def test_save_and_find(milestone_repo):
    m = milestone_repo.save(Milestone(name="Alpha", order=2))
    assert m.id
    loaded = milestone_repo.find(m.id)
    assert loaded.name == "Alpha"
    assert loaded.order == 2


def test_save_updates_existing(milestone_repo):
    m = milestone_repo.save(Milestone(name="Alpha", order=2))
    m.name = "Renamed"
    milestone_repo.save(m)
    assert milestone_repo.find(m.id).name == "Renamed"
    assert len(milestone_repo.find_all()) == 1


def test_ordered(milestone_repo):
    milestone_repo.save(Milestone(name="Third", order=3))
    milestone_repo.save(Milestone(name="First", order=1))
    milestone_repo.save(Milestone(name="Second", order=2))

    names = [m.name for m in milestone_repo.ordered()]
    assert names == ["First", "Second", "Third"]


def test_delete(milestone_repo):
    m = milestone_repo.save(Milestone(name="Alpha"))
    milestone_repo.delete(m.id)
    with pytest.raises(NotFound):
        milestone_repo.find(m.id)
