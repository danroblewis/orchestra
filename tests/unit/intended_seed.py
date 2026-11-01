"""A seeded project for the intended model's tests: the mockups' captured model
(``mockups/fixtures/api/dynamics_model.json``) saved as two versions, v1 with a flow files →
commits that v2 no longer has, and v2 with a new stock, acceptance tests passing, recorded by the
instrument features.acceptance and fed from DONE; the declared layer of frames D1 and E1."""

from __future__ import annotations

import copy
import json
import subprocess
import time
from pathlib import Path

from orchestra.config import init_project
from orchestra.sd.model import Flow, Model, SeriesRef, Stock
from orchestra.sd.store import ModelStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "mockups" / "fixtures" / "api"
QUOTE = "I think we need to start tracking features, then, because we currently aren't. I'm going to create a Features stock."


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def captured_model() -> Model:
    return Model.from_json(fixture("dynamics_model")["model"])


def project_at(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    (tmp_path / "repo").mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path / "repo", check=True)
    return init_project(tmp_path / "repo")


def v1_model() -> Model:
    m = copy.deepcopy(captured_model())
    m.flows.append(Flow("repo_files_to_commits", "files to commits", "repo_files", "repo_commits",
                        SeriesRef("repo_files_committed_total", {"instrument": "repo"}),
                        evidence={"machines": {"hypotheses": [{"machine": "merge_gate", "confidence": 0.71}]}}))
    return m


def v2_model() -> Model:
    m = copy.deepcopy(captured_model())
    m.stocks.append(Stock("acceptance_tests_passing", "acceptance tests passing",
                          series=SeriesRef("acceptance_tests_passing", {"instrument": "features.acceptance"})))
    m.flows.append(Flow("done_to_acceptance", "acceptance tests passing (net)", "tasks_tickets_DONE", "acceptance_tests_passing"))
    return m


def seed(project, *, declared: bool = True, discovered: bool = True) -> ModelStore:
    store = ModelStore.for_state(project.state_dir)
    if discovered:
        store.save(v1_model(), note="v1")
        store.save(v2_model(), note="v2")
        store.write_discovery(v2_model())
    if declared:
        store.intended().apply([
            {"op": "declare_stock", "id": "features", "name": "Features", "near": 'tasks_tickets{state="DONE"}'},
            {"op": "record_measurement", "part": "stock", "id": "features", "chosen": "a", "options": [
                {"key": "a", "title": "passing acceptance tests on main", "how": "pytest tests/acceptance --junitxml",
                 "kind": "script collector", "instrument": "features.acceptance", "simulated": False, "cost": "a CI run",
                 "caveat": "counts tests, not features", "clearance": "none", "provenance": "free text", "commit": "3f2c1aa",
                 "first_points": [[1.0, 41]]},
                {"key": "d", "title": "a simulated ramp", "kind": "simulated", "instrument": "features.sim", "simulated": True}]}],
            {"author": "owner", "source": "supervisor", "turn": "sessions/supervisor/41", "message": "msg_0193", "quote": QUOTE})
        store.intended().apply([
            {"op": "propose_machine", "id": "feature_count_improver", "title": "Feature Count Improver",
             "description": "improves how many features land a day", "tags": ["features", "feedback loop"], "kind": "universal",
             "managed": "orchestra", "engagement": {"mode": "continuous"},
             "receives": ["session.settled", "task.reported"], "emits": ["work.requested"],
             "reads": ["features", "acceptance_tests_passing"],
             "spec": {"invariants": ["never lands a change itself"], "steps": ["read the queue", "pick one", "ask"]},
             "guessed": ["receives[0]", "receives[1]"]},
            {"op": "set_expected_effect", "machine": "feature_count_improver", "horizon_s": 604800,
             "edits": [{"stock": "features", "rises": True}]}],
            {"author": "supervisor", "source": "supervisor", "reason": "the owner asked for a feedback loop"})
    return store


def record_points(project, instrument: str = "features.acceptance", name: str = "acceptance_tests_passing",
                  values=(41, 43, 46), every_s: float = 900.0) -> None:
    from orchestra.metrics import Point
    from orchestra.metrics import for_project as metrics_for

    now = time.time()
    pts = [Point(name, float(v), now - (len(values) - i) * every_s, {"project": project.key, "instrument": instrument})
           for i, v in enumerate(values)]
    metrics_for(project).write(pts)
