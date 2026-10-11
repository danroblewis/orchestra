import os
import subprocess
from pathlib import Path

import pytest

from orchestra.config import Config, init_project
from orchestra.gate.bisect import bisect_branches
from orchestra.model import State, TransitionError, check_transition
from orchestra.store import Conflict, LocalStore, StoreError


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    return init_project(repo, provider="p", model="m", prefix="T")


def test_transitions():
    check_transition(State.OPEN, State.IN_PROGRESS)
    with pytest.raises(TransitionError):
        check_transition(State.OPEN, State.DONE)
    with pytest.raises(TransitionError):
        check_transition(State.DONE, State.OPEN)


def test_milestone_rules_and_ids(project):
    store = LocalStore(project)
    with pytest.raises(StoreError):
        store.create_ticket(title="x", milestone_id="M9")
    m = store.create_milestone(name="first")
    assert m.id == "M1"
    t = store.create_ticket(title="Add thing", milestone_id=m.id)
    assert t.id == "T-1" and t.state == State.OPEN
    with pytest.raises(StoreError):
        store.close_milestone(m.id, None)  # unfinished ticket
    t = store.transition(t.id, t.version, State.CANCELLED)
    store.close_milestone(m.id, None)
    with pytest.raises(StoreError):
        store.create_ticket(title="y", milestone_id=m.id)
    with pytest.raises(StoreError):
        store.update_milestone(m.id, None, status="open")


def test_version_conflict_and_blocked_reason(project):
    store = LocalStore(project)
    m = store.create_milestone(name="m")
    t = store.create_ticket(title="a", milestone_id=m.id)
    with pytest.raises(Conflict):
        store.update_ticket(t.id, t.version + 5, title="b")
    t = store.transition(t.id, t.version, State.IN_PROGRESS)
    with pytest.raises(StoreError):
        store.transition(t.id, t.version, State.BLOCKED)
    store.transition(t.id, t.version, State.BLOCKED, blocked_reason="need creds")


def test_config_durations():
    cfg = Config.from_toml('[agents]\nturn_timeout = "2m"\n[[gate.unit]]\nname="u"\ncommand="true"\n')
    assert cfg.turn_timeout == 120 and cfg.unit[0].command == "true"


@pytest.mark.parametrize("n", range(1, 9))
@pytest.mark.parametrize("bad", range(0, 8))
def test_bisect_isolates_offender(n, bad):
    if bad >= n:
        return
    branches = [f"b{i}" for i in range(n)]
    res = bisect_branches(branches, lambda sub: f"b{bad}" in sub)
    assert res.offenders == [f"b{bad}"]
    assert set(res.safe) == set(branches) - {f"b{bad}"}
    assert not res.unresolved


def test_effective_priority_propagates_and_ages():
    from datetime import UTC, datetime, timedelta

    from orchestra.model import Ticket, effective_priorities

    old = (datetime.now(UTC) - timedelta(days=5)).isoformat(timespec="seconds")
    a = Ticket(id="A", title="a", milestone_id="M1", priority=5)
    b = Ticket(id="B", title="b", milestone_id="M1", priority=1, depends_on=["A"])
    c = Ticket(id="C", title="c", milestone_id="M1", priority=6, created_at=old)
    done = Ticket(id="D", title="d", milestone_id="M1", priority=1, state=State.DONE, depends_on=["C"])
    eff = effective_priorities({"A": a, "B": b, "C": c, "D": done}, aging_days_per_level=2)
    assert eff["A"]["effective"] == 1 and eff["A"]["inherited_from"] == "B"   # prerequisite inherits
    assert eff["B"]["effective"] == 1 and eff["B"]["inherited_from"] is None
    assert eff["C"]["effective"] == 4 and eff["C"]["age_levels"] == 2          # 5 days / 2 = 2 levels
    assert "D" not in eff                                                      # terminal tickets are ignored
