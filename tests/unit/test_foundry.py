"""The foundry readings: every number comes from the log, the store, or the repository, with
send-backs split by cause and the hidden stock never shown as a count."""

import datetime as dt
import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from orchestra import foundry, foundrygit, foundrymetrics
from orchestra.config import init_project
from orchestra.events import Events
from orchestra.org import all_agents, all_teams
from orchestra.store import LocalStore
from orchestra.model import State
from orchestra.web import app as web


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        git(repo, *args)
    (repo / "README.md").write_text("one\ntwo\n")
    (repo / "AGENTS.md").write_text("rules\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    p = init_project(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "orchestra")
    return p


def _land(repo, branch, text):
    """A ticket branch with one commit, merged into main the way the gate does (a merge commit)."""
    git(repo, "checkout", "-q", "-b", branch)
    (repo / f"{branch.split('/')[-1]}.py").write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"work on {branch}")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", f"Merge {branch}", branch)
    return git(repo, "rev-parse", "HEAD").strip()


def test_git_readings_are_read_only_and_first_parent(project):
    repo = project.repo_root
    c1 = _land(repo, "orchestra/T-1-first", "a = 1\nb = 2\nc = 3\n")
    # a later landing rewrites one of T-1's lines: two of three survive
    git(repo, "checkout", "-q", "-b", "orchestra/T-2-second")
    (repo / "T-1-first.py").write_text("a = 1\nb = 20\nc = 3\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "rewrite b")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge T-2", "orchestra/T-2-second")
    c2 = git(repo, "rev-parse", "HEAD").strip()
    # an open branch with two commits ahead
    git(repo, "checkout", "-q", "-b", "orchestra/T-3-open")
    for i in range(2):
        (repo / "open.txt").write_text(str(i))
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", f"wip {i}")
    git(repo, "checkout", "-q", "main")
    status_before = git(repo, "status", "--porcelain")
    r = foundrygit.readings(repo, "main", [c1, c2])
    assert r["ahead"]["orchestra/T-3-open"] == 2 and r["ahead"]["orchestra/T-1-first"] == 0
    assert r["landings"][c1] == {"added": 3, "removed": 0, "files": 1}
    assert r["landings"][c2] == {"added": 1, "removed": 1, "files": 1}
    assert r["survival"][c1] == 2 and r["survival"][c2] == 1
    assert r["documents"]["count"] == 2 and r["documents"]["lines"] == 3
    assert git(repo, "status", "--porcelain") == status_before
    assert foundrygit.readings(repo, "main", [c1, c2]) is r          # cached while the heads are unchanged


def test_readings_split_send_backs_and_never_count_the_hidden_stock(project):
    store, events = LocalStore(project), Events(project.events_file)
    repo = project.repo_root
    m = store.create_milestone(name="m")
    t1 = store.create_ticket(title="a", milestone_id=m.id, branch="orchestra/T-1-a")
    t2 = store.create_ticket(title="b", milestone_id=m.id, branch="orchestra/T-2-b")
    store.create_ticket(title="c", milestone_id=m.id)
    # the tracker's state is set first; its own log lines are then cleared so the log below is the whole story
    for st in (State.IN_PROGRESS, State.READY_FOR_REVIEW, State.IN_REVIEW, State.APPROVED, State.MERGING, State.DONE):
        store.transition(t1.id, None, st)
    project.events_file.write_text("")
    now = dt.datetime.now(dt.UTC)
    base = now - dt.timedelta(hours=3)
    ts = lambda mins: (base + dt.timedelta(minutes=mins)).isoformat(timespec="seconds")
    def emit(type_, mins, **d):                      # written with a chosen timestamp, in the log's own shape
        e = {"ts": ts(mins), "type": type_, **d}
        with open(project.events_file, "a") as fh:
            fh.write(json.dumps(e) + "\n")
        return e
    emit("ticket_created", 0, ticket=t1.id, by="coordinator")
    emit("ticket_created", 0, ticket=t2.id, by="coordinator")
    # t1: implemented, rejected in review, fixed, approved, landed
    emit("ticket_transition", 1, ticket=t1.id, **{"from": "OPEN", "to": "IN_PROGRESS"})
    emit("session_started", 1, session=f"worker-{t1.id}", kind="worker", ticket=t1.id)
    emit("ticket_transition", 31, ticket=t1.id, **{"from": "IN_PROGRESS", "to": "READY_FOR_REVIEW"})
    emit("session_settled", 31, session=f"worker-{t1.id}")
    emit("ticket_transition", 32, ticket=t1.id, **{"from": "READY_FOR_REVIEW", "to": "IN_REVIEW"})
    emit("ticket_transition", 40, ticket=t1.id, **{"from": "IN_REVIEW", "to": "REJECTED"})
    emit("ticket_transition", 41, ticket=t1.id, **{"from": "REJECTED", "to": "IN_PROGRESS"})
    emit("session_started", 41, session=f"worker-{t1.id}", kind="worker", ticket=t1.id)
    emit("ticket_transition", 51, ticket=t1.id, **{"from": "IN_PROGRESS", "to": "READY_FOR_REVIEW"})
    emit("session_settled", 51, session=f"worker-{t1.id}")
    emit("ticket_transition", 52, ticket=t1.id, **{"from": "READY_FOR_REVIEW", "to": "IN_REVIEW"})
    emit("ticket_transition", 60, ticket=t1.id, **{"from": "IN_REVIEW", "to": "APPROVED"})
    emit("ticket_transition", 61, ticket=t1.id, **{"from": "APPROVED", "to": "MERGING"})
    c1 = _land(repo, "orchestra/T-1-a", "x = 1\n")
    emit("gate_landed", 70, gate_run="g1", tickets=[t1.id], commit=c1)
    emit("ticket_transition", 70, ticket=t1.id, **{"from": "MERGING", "to": "DONE"})
    emit("staging_deployed", 71, build="g1", commit=c1)
    emit("staging_restarted", 90, build="g1")
    # t2: a turn that timed out and restarted, then a gate timeout
    emit("ticket_transition", 2, ticket=t2.id, **{"from": "OPEN", "to": "IN_PROGRESS"})
    emit("session_started", 2, session=f"worker-{t2.id}", kind="worker", ticket=t2.id)
    emit("turn_timed_out", 20, session=f"worker-{t2.id}", agent="worker", ticket=t2.id, stopped_by="silence", limit=600)
    emit("session_settled", 20, session=f"worker-{t2.id}")
    emit("ticket_transition", 20, ticket=t2.id, **{"from": "IN_PROGRESS", "to": "OPEN"})
    emit("session_started", 100, session="coordinator", kind="coordinator")
    emit("session_settled", 110, session="coordinator")
    stage = lambda name, status, rc, tail="": {"stage": name, "name": name, "command": "uv run pytest tests -q" if name != "build" else "make", "status": status, "returncode": rc, "tail": tail}
    store.save_gate_run({"id": "g1", "batch": [t1.id], "status": "landed", "started_at": ts(62), "finished_at": ts(70), "gate_commit": c1,
                         "stages": [stage("build", "passed", 0), stage("unit", "passed", 0, "12 passed"), stage("acceptance", "passed", 0, "3 passed, 2 skipped")]})
    store.save_gate_run({"id": "g2", "batch": [t2.id], "status": "rejected", "started_at": ts(95), "finished_at": ts(110),
                         "stages": [stage("build", "passed", 0), stage("unit", "passed", 0, "12 passed"), stage("acceptance", "failed", 124, "timed out")]})
    store.save_gate_run({"id": "g3", "batch": [t2.id], "status": "rejected", "started_at": ts(111), "finished_at": ts(120),
                         "stages": [stage("build", "passed", 0), stage("unit", "failed", 1, "1 failed, 11 passed")]})
    store.save_gate_run({"id": "g4", "batch": [t2.id], "status": "conflict", "started_at": ts(121), "finished_at": ts(122), "stages": []})
    r = foundrymetrics.readings(project, store, events.read(0)[0], all_agents(project), all_teams(project))
    ins = r["inspections"]
    assert ins["review"]["arrivals"] == 2 and ins["review"]["sent_back"] == 1 and ins["review"]["pass"] == 0.5
    assert ins["gate"]["by"] == {"landed": 1, "timeout": 1, "defect": 1, "conflict": 1} and ins["gate"]["defect_stage"] == {"unit": 1}
    assert ins["gate"]["pass"] == 0.5                                                 # one landed of two runs that ended on their own result
    assert r["flows"]["failure"] == 1 and r["flows"]["conflict"] == 1 and r["flows"]["fix"] == 1
    assert r["stocks"]["U"]["value"] is None and r["stocks"]["U"]["estimable"] is False
    assert r["stocks"]["L"]["count"] == 1 and r["stocks"]["L"]["added"] == 1 and r["stocks"]["L"]["fcc_upper"] is None   # no cohort old enough
    assert r["stocks"]["A"]["passing"] == 3 and r["stocks"]["A"]["skipped"] == 2 and r["stocks"]["A"]["done_tickets"] == 1
    assert r["stocks"]["T"]["value"] == 15 and r["stocks"]["T"]["stages"]["acceptance"]["skipped"] == 2
    assert (r["stocks"]["D"]["value"], r["stocks"]["R"]["value"], r["stocks"]["R"]["files"]) == (2, 2, ["AGENTS.md", "README.md"])
    c = r["stocks"]["C"]
    assert c["turns"] == {"implement": 2, "fix": 1, "plan": 1}
    assert c["rework_share"] == round((10 / 60) / ((30 + 18) / 60 + 10 / 60), 2)
    assert c["losses"]["restarts"] == 1 and c["losses"]["turn_timeouts"] == 1 and c["losses"]["worker_hours_ending_in_timeout"] == 0.3
    assert r["dora"]["deploys"] == 1 and r["dora"]["change_failure"] == 1.0 and r["dora"]["restore"] is None
    assert r["dora"]["lead_time"] == 70 * 60 and r["dora"]["land_to_deploy"] == 60
    assert r["rounds"]["histogram"]["0"] == 3                                        # the tracker's review_rounds, not the log


def test_foundry_endpoint_and_definitions(project):
    m = TestClient(web.create_app(project)).get("/api/foundry").json()
    assert m["ok"] and {s["key"] for s in m["stocks"]} == set(foundry.STOCKS)
    assert next(s for s in m["stocks"] if s["key"] == "U")["hidden"] is True
    assert {f["key"] for f in m["flows"] if f["machine"] is None} == {"failure", "escape", "tests", "improve", "base"}
    assert [lp["polarity"] for lp in m["loops"]] == ["B", "B", "B", "B", "B", "R", "R"]
    assert m["readings"]["stocks"]["U"]["estimable"] is False and m["readings"]["git"] is True
