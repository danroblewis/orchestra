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
    assert not out["ok"] and out["error"] == "no model" and out["text"].startswith("There is no model yet")
    assert out["discovery"] == {"left_out": {"disk_free_bytes{machine=\"telemetry\"}": "no counters balance it"},
                                "series": 1, "step": 5.0, "start": 100.0, "end": 3700.0, "min_r2": 0.9, "looked_at": 1, "kept": []}
    # the page points at its own button, not a command, and says when the host last looked
    assert "rediscover now" in out["hint"] and "orchestra sd discover" not in out["text"] and out["as_of"] is not None


def test_the_counts_agree_with_each_other(tmp_path, monkeypatch):
    """The live test's finding: 'no stocks among 162 series', 'Left out 162' and 'Discovered from
    154 series' on one page. Every number is now the series looked at, of which some were left out
    at once (Orchestra's own) and the rest considered."""
    from orchestra.sd.discover import discover
    from orchestra.web.dynamics import looked_at

    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    (tmp_path / "repo").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path / "repo", check=True)
    project = init_project(tmp_path / "repo")
    pts = [(1000.0 + 10 * i, float(i % 3)) for i in range(60)]
    dump = [("orchestra_host_up", {"machine": "orchestra-host"}, [(t, 1.0) for t, _ in pts]),
            ("disk_free_bytes", {"machine": "telemetry"}, pts),
            ("jobs_done_total", {"machine": "telemetry"}, [(t, float(i // 7)) for i, (t, _) in enumerate(pts)])]
    m = discover(dump, start=1000.0, end=1590.0, step=10.0)
    d = m.discovery
    assert not m.stocks and d["sampled"] == 3 and d["series"] == 2
    assert len(d["left_out"]) == looked_at(d) == 3
    ModelStore.for_state(project.state_dir).write_discovery(m)
    out = model_view(project)
    assert "among the 3 series it looked at" in out["text"] and out["discovery"]["looked_at"] == 3
    old = {k: v for k, v in d.items() if k != "sampled"}       # a discovery from before "sampled" was recorded
    assert looked_at(old) == 3


def test_no_model_yet_says_which_source_was_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    (tmp_path / "repo").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path / "repo", check=True)
    project = init_project(tmp_path / "repo")
    sources = {"own": {"ok": True, "series": 0}, "rig": {"ok": False, "error": "refused in orchestra.toml: a literal secret"}}
    found = Model("m", "nothing yet", discovery={"left_out": {}, "series": 0, "step": 60.0, "start": 100.0, "end": 3700.0, "min_r2": 0.9,
                                                 "sources": sources, "not_saved": "missing rig: refused in orchestra.toml: a literal secret",
                                                 "since_last_s": 7200})
    ModelStore.for_state(project.state_dir).write_discovery(found)
    out = model_view(project)
    assert not out["ok"] and "a source was missing" in out["text"] and "nothing balances yet" not in out["text"]
    assert out["discovery"]["sources"] == sources and out["discovery"]["since_last_s"] == 7200
    assert out["discovery"]["not_saved"].startswith("missing rig")


def _project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    (tmp_path / "repo").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path / "repo", check=True)
    return init_project(tmp_path / "repo")


def test_no_model_says_none_could_be_judged_when_every_series_is_too_new(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    new = "too new to measure: its first point is after the window's last step, so the next discovery considers it"
    found = Model("m", "nothing yet", discovery={"left_out": {"a": new, "b": new, "c": new}, "sampled": 3, "series": 0,
                                                 "step": 5.0, "start": 100.0, "end": 3700.0, "min_r2": 0.9})
    ModelStore.for_state(project.state_dir).write_discovery(found)
    err = model_view(project)["text"]
    assert "none could be judged yet: all 3 series are newer than one step" in err and "nothing balances" not in err
    # no orchestra run: no promise that it looks again by itself
    assert "No orchestra run is running, so discovery will not run again until it starts" in err
    assert "looks again every few minutes" not in err


def test_no_model_says_it_looks_again_only_while_a_host_runs(tmp_path, monkeypatch):
    from orchestra import runtime
    from orchestra.web import dynamics

    project = _project(tmp_path, monkeypatch)
    found = Model("m", "nothing yet", discovery={"left_out": {"disk": "no counters balance it"}, "sampled": 1, "series": 1,
                                                 "step": 5.0, "start": 100.0, "end": 3700.0, "min_r2": 0.9})
    ModelStore.for_state(project.state_dir).write_discovery(found)
    monkeypatch.setattr(dynamics, "host_running", lambda p: True)
    err = model_view(project)["text"]
    assert "(nothing balances yet)" in err and "It looks again every few minutes" in err
    monkeypatch.setattr(dynamics, "host_running", lambda p: False)
    assert "No orchestra run is running" in model_view(project)["text"]
    # nothing discovered at all: the second message says the same
    ModelStore.for_state(project.state_dir).dir.joinpath("discovered.json").unlink()
    assert model_view(project)["text"].startswith("There is no model yet: no discovery has run yet. No orchestra run is running")
    monkeypatch.setattr(dynamics, "host_running", lambda p: True)
    assert "It looks again every few minutes" in model_view(project)["text"]
    # the runtime record decides it for real: this process registered as a host
    monkeypatch.undo()
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    runtime.update(project, lambda d: d.setdefault("hosts", {}).update({"1": runtime.me()}))
    assert dynamics.host_running(project)
