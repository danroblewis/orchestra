"""The Dynamics page's data with no model yet still says what discovery left out, and why."""

import subprocess

from orchestra.config import init_project
from orchestra.sd.model import Model
from orchestra.sd.store import ModelStore
from orchestra.web.dynamics import model_view


def test_no_model_yet_comes_with_the_left_out_list(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    (tmp_path / "repo").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path / "repo", check=True)
    project = init_project(tmp_path / "repo")
    found = Model("m", "nothing yet", discovery={"left_out": {"disk_free_bytes{machine=\"telemetry\"}": "no counters balance it"},
                                                 "series": 1, "step": 5.0, "start": 100.0, "end": 3700.0, "min_r2": 0.9,
                                                 "gaps": []})
    ModelStore.for_state(project.state_dir).write_discovery(found)
    out = model_view(project)
    assert not out["ok"] and out["error"].startswith("There is no model yet")
    assert out["discovery"] == {"left_out": {"disk_free_bytes{machine=\"telemetry\"}": "no counters balance it"},
                                "series": 1, "step": 5.0, "start": 100.0, "end": 3700.0, "min_r2": 0.9}
