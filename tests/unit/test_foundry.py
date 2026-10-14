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
from orchestra.foundry import ModelStore
from orchestra.model import State
from orchestra.org import all_agents, all_teams
from orchestra.store import LocalStore
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
    docs = r["documents"][tuple(foundrygit.DOC_GLOBS)]
    assert docs["count"] == 2 and docs["lines"] == 3
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
    # the reviewer's verdict note makes t1's rejection a defect; t2 is sent back by a no-verdict review later
    from orchestra.model import Note
    store.add_note(t1.id, Note(author="reviewer", kind="review", text="REJECTED: colours wrong", created_at=ts(40)))
    emit("ticket_transition", 125, ticket=t2.id, **{"from": "OPEN", "to": "IN_PROGRESS"})
    emit("ticket_transition", 130, ticket=t2.id, **{"from": "IN_PROGRESS", "to": "READY_FOR_REVIEW"})
    emit("ticket_transition", 131, ticket=t2.id, **{"from": "READY_FOR_REVIEW", "to": "IN_REVIEW"})
    emit("ticket_transition", 140, ticket=t2.id, **{"from": "IN_REVIEW", "to": "REJECTED"})      # no reviewer note: no verdict
    emit("ticket_transition", 141, ticket=t2.id, **{"from": "REJECTED", "to": "IN_PROGRESS"})
    emit("session_started", 141, session=f"worker-{t2.id}", kind="worker", ticket=t2.id)
    emit("session_settled", 147, session=f"worker-{t2.id}")
    r = foundrymetrics.readings(project, store, events.read(0)[0], all_agents(project), all_teams(project))
    ins = r["inspections"]
    assert ins["review"]["arrivals"] == 3 and ins["review"]["by_cause"] == {"defect": 1, "no_verdict": 1} and ins["review"]["pass"] == 0.5   # one APPROVED verdict, one REJECTED verdict; the no-verdict send-back is not an inspection
    assert ins["gate"]["by"] == {"landed": 1, "timeout": 1, "defect": 1, "conflict": 1} and ins["gate"]["defect_stage"] == {"unit": 1}
    assert ins["gate"]["defect_tickets"] == {t2.id: 1} and ins["gate"]["pass"] == 0.5          # one landed of two runs on their own result
    f = r["pipeline"]
    assert f["start"] == 2 and f["repick"] == 1 and f["restart"] == 1                            # t2's second pickup follows a restart
    assert f["failure"] == 1 and f["conflict"] == 1 and f["fix"] == 1 and f["review"] == 1 and f["review_no_verdict"] == 1
    S = r["stocks"]
    assert S["undiscovered"]["value"] is None and S["undiscovered"]["estimable"] is False
    assert S["known_rework"]["value"] == 0                                                      # t1's defect was re-submitted; t2's send-back was no verdict
    L = S["landed"]
    assert L["value"] == 1 and L["window"] == 1 and L["lines"] == 1 and L["fcc_upper"] is None   # no cohort old enough
    assert S["wip"]["commits_per_day"] == 3                                                     # the fixture's two setup commits and the branch commit, all in the window
    A = S["really_done"]
    assert A["value"] == 3 and A["skipped"] == 2 and A["done_tickets"] == 1 and A["build"] is None and "nothing deployed" in A["source"]   # nothing deployed yet
    assert S["tests"]["value"] == 15 and S["tests"]["stages"]["acceptance"]["skipped"] == 2
    assert (S["demand"]["value"], S["resources"]["value"], S["resources"]["files"]) == (2, 2, ["AGENTS.md", "README.md"])
    assert S["demand"]["ages"] == 2 and S["demand"]["oldest_age"] is not None and S["demand"]["oldest_age"] >= 0      # residence time from state_since
    assert r["model_source"].startswith(".orchestra/model")                                       # init_project wrote the template
    c = r["time"]                                                                                  # a rate, not a stock
    assert c["turns"] == {"implement": 2, "fix": 1, "rerun": 1, "plan": 1}
    assert c["rework_share"] == round((10 / 60) / ((30 + 18 + 10) / 60), 2)                    # over productive hours; the re-run is a loss
    assert c["losses"]["restarts"] == 1 and c["losses"]["turn_timeouts"] == 1 and c["losses"]["worker_hours_ending_in_timeout"] == 0.3
    assert c["losses"]["review_no_verdict"] == 1 and c["losses"]["rerun_hours"] == 0.1
    assert S["build"]["value"] == 0 and S["build"]["status"] is None                          # nothing deployed: never "up" without a fresh health check
    assert r["rounds"]["fix_rounds"] == 1 and r["rounds"]["bad_fixes"] == 0 and r["inspections"]["review"]["approvals_gate_rejected"] == 0
    assert r["dora"]["deploys"] == 1 and r["dora"]["change_failure"] == 1.0 and r["dora"]["restore"] is None
    assert r["dora"]["lead_time"] == 70 * 60 and r["dora"]["land_to_deploy"] == 60
    assert r["rounds"]["histogram"]["0"] == 3                                                     # the tracker's review_rounds, not the log
    assert r["signals"]["restarts"] == {"now": 1, "before": 0, "direction": "up"}
    assert r["window"]["before"]["until"] == r["window"]["since"]


def test_model_is_data_written_at_init_and_curated_by_the_store(project):
    ms = ModelStore(project)
    assert ms.exists() and (project.repo_root / ".orchestra" / "model" / "stocks" / "wip.json").exists()
    m = ms.load()
    assert {s.key for s in m["stocks"]} >= {"demand", "wip", "undiscovered", "known_rework", "landed", "build", "really_done", "tests", "resources"}
    assert m["source"] == ".orchestra/model"
    ms.save("stock", foundry.Stock("findings", "Lab findings", "documents", inflows=["finding_published"], consumers=[{"agent": "product_owner", "effect": "+"}],
                                   estimators=[{"kind": "repo_docs", "globs": [".orchestra/spaces/lab/findings/*.md"]}], row="capability"))
    assert ms.get("stock", "findings").unit == "documents" and "findings" in {s.key for s in ms.load()["stocks"]}
    ms.delete("stock", "findings")
    assert "findings" not in {s.key for s in ms.load()["stocks"]}
    with pytest.raises(Exception, match="snake_case"):
        ms.save("stock", foundry.Stock("Bad Key", "x", "y"))
    assert ms.write_template() == []                                                            # nothing overwritten


def test_supervisor_curates_the_model_through_the_tools(project):
    from orchestra import api
    store = LocalStore(project)
    sup = {"role": "supervisor"}
    m = api.handle(project, store, "list_model", {})
    assert {d["key"] for d in m["detected"]} >= {"review_rework", "capability", "broken_base"} and m["source"] == ".orchestra/model"
    with pytest.raises(Exception, match="neither built in nor declared"):
        api.handle(project, store, "add_model_element", {"kind": "stock", "key": "findings", "spec": {"name": "Findings", "unit": "docs", "inflows": ["finding_published"]}}, **sup)
    r = api.handle(project, store, "add_model_element", {"kind": "stock", "key": "budget", "spec": {"name": "Token budget", "unit": "tokens", "inflows": [], "outflows": ["session_settled"],
                                                                                                "consumers": [{"agent": "coordinator", "effect": "-"}], "estimators": [{"kind": "none", "reason": "set by the operator"}]}}, **sup)
    assert r["stock"]["key"] == "budget"
    r = api.handle(project, store, "update_model_element", {"kind": "stock", "key": "budget", "spec": {"unit": "USD"}}, **sup)
    assert r["stock"]["unit"] == "USD" and r["stock"]["name"] == "Token budget"
    with pytest.raises(Exception, match="only the supervisor"):
        api.handle(project, store, "remove_model_element", {"kind": "stock", "key": "budget"}, role="coordinator")
    api.handle(project, store, "remove_model_element", {"kind": "stock", "key": "budget"}, **sup)
    assert "budget" not in {s["key"] for s in api.handle(project, store, "list_model", {})["stocks"]}


def test_propose_model_and_advice_give_a_weak_supervisor_something_to_copy(project):
    from orchestra import api
    store = LocalStore(project)
    sup = {"role": "supervisor"}
    api.handle(project, store, "create_role", {"name": "analyst", "description": "d", "prompt": "# You analyse\n\n" + "Carefully. " * 6, "tools": ["events"]}, **sup)
    api.handle(project, store, "create_agent", {"name": "keeper", "roles": ["analyst"], "team": "devex", "kind": "ad_hoc", "session": "ephemeral", "wake_on": ["ticket_transition:REJECTED"]}, **sup)
    api.handle(project, store, "create_team", {"name": "devex", "lead": "keeper", "responsibilities": "# Devex\n\n1. Docs are accurate.", "emits": ["lesson_decided", "finding_filed"]}, **sup)
    (project.repo_root / ".orchestra" / "spaces" / "devex" / "lessons").mkdir(parents=True, exist_ok=True)
    (project.repo_root / ".orchestra" / "spaces" / "devex" / "lessons" / "one.md").write_text("plan first")
    (project.repo_root / "tests" / "acceptance").mkdir(parents=True)
    (project.repo_root / "tests" / "acceptance" / "test_share.py").write_text("def test_x(): pass\n")
    pr = api.handle(project, store, "propose_model", {})
    whys = " | ".join(c["why"] for c in pr["candidates"])
    # lesson_decided already fills the template's resources stock, so it is not proposed; finding_filed is
    assert "declares the event finding_filed" in whys and "lesson_decided" not in whys
    assert "files under .orchestra/spaces/devex/lessons" in whys
    assert "acceptance suite" not in whys                                                      # the template's really_done already reads the acceptance stage
    assert all(c["call"]["kind"] == "stock" and "spec" in c["call"] for c in pr["candidates"])
    assert pr["missing_discovery"] and "staging_deployed" in pr["missing_discovery"][0]["call"]["note"]
    # the candidate is a ready call; the keeper is woken but emits nothing yet, so the capability loop stays open with a named fix
    cand = next(c for c in pr["candidates"] if "finding_filed" in c["why"])["call"]
    api.handle(project, store, "add_model_element", cand, **sup)
    lm = api.handle(project, store, "list_model", {})
    assert "finding_fileds" in {s["key"] for s in lm["stocks"]}
    # the keeper has the events tool and its team declares lesson_decided, so its effective emits fill resources: capability closes
    cap = next(d for d in lm["detected"] if d["key"] == "capability")
    assert cap["detected"] and cap["polarity"] == "B", (cap, lm["advice"])
    # a team-less agent with the same wake rule but no events tool could not: the tools decide
    assert any("earlier_detection" in line for line in lm["advice"])
    with pytest.raises(Exception, match="may not emit"):
        api.handle(project, store, "update_agent", {"name": "keeper", "emits": ["gate_landed"]}, **sup)


def test_foundry_endpoint_and_definitions(project):
    m = TestClient(web.create_app(project)).get("/api/foundry").json()
    assert m["ok"] and {s["key"] for s in m["model"]["stocks"]} >= set(foundry.TEMPLATE_STOCKS and [s.key for s in foundry.TEMPLATE_STOCKS])
    assert next(s for s in m["model"]["stocks"] if s["key"] == "undiscovered")["hidden"] is True
    assert {d["key"] for d in m["declared"] if d["detected"]} >= {"review_rework", "gate_rework", "broken_base", "replanning"}
    assert not next(d for d in m["declared"] if d["key"] == "capability")["detected"]            # no keeper in a fresh project
    assert m["readings"]["stocks"]["undiscovered"]["estimable"] is False and m["readings"]["git"] is True
    assert "agent:orchestra" in m["graph"]["nodes"] and any(e["kind"] == "fills" for e in m["graph"]["edges"])
