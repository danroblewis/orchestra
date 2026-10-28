"""A remote source that is down leaves only its own stocks without a level: the own store's levels
and the history still update, the source's error is recorded for the page, and ``orchestra sd
show`` says the level is unavailable instead of failing."""

import subprocess
import time

from orchestra import cli
from orchestra.config import init_project, load_project
from orchestra.events import Events
from orchestra.metrics import Point, for_project
from orchestra.sd.model import Model, SeriesRef, Stock
from orchestra.sd.store import ModelStore
from orchestra.web.background import Refresher

DOWN = """
[[sources]]
name = "rig"
url = "http://127.0.0.1:9"
timeout = "2s"
"""


def _project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    init_project(repo)
    with open(repo / "orchestra.toml", "a") as fh:
        fh.write(DOWN)
    project = load_project(repo)
    lab = {"machine": "board"}
    for_project(project).write([Point("queue_depth", v, time.time() - ago, {**lab, "project": project.key}) for v, ago in ((3.0, 1800), (7.0, 5))])
    model = Model("m", "m", stocks=[Stock("queue", "queue", series=SeriesRef("queue_depth", lab)),
                                    Stock("pods", "pods", series=SeriesRef("rig:pods", {"machine": "rig.search"}, source="rig"))])
    ModelStore.for_state(project.state_dir).save(model, note="test")
    return project


def test_a_down_source_never_stops_the_own_levels_or_the_history(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    bg = Refresher(project, Events.for_project(project), for_project(project))
    bg.want("remote")                              # a page shows the levels
    try:
        deadline = time.time() + 20
        while time.time() < deadline and not (bg.ready("history") and "source rig" in bg.errors and "queue" in bg.levels):
            time.sleep(0.2)
    finally:
        bg.stop()
    assert bg.levels["queue"]["v"] == 7.0 and "pods" not in bg.levels
    assert "127.0.0.1:9" in bg.errors["source rig"] and "rig" in (bg.levels_error or "")
    assert "history" not in bg.errors and bg.history["stocks"]["queue"] and bg.history["stocks"]["pods"] == []


def test_sd_show_says_a_down_sources_level_is_unavailable(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path, monkeypatch)
    assert cli.main(["--repo", str(project.repo_root), "sd", "show"]) == 0
    out = capsys.readouterr()
    line = next(x for x in out.out.splitlines() if x.strip().startswith("pods"))
    assert "unavailable" in line and "rig:" in line and "Traceback" not in out.out + out.err
    assert next(x for x in out.out.splitlines() if x.strip().startswith("queue")).split()[-1] == "7.0"


def test_no_page_no_remote_read(tmp_path, monkeypatch):
    """With no page asking for remote levels or history, the web server reads no other store; the
    own store's levels and the history still update."""
    project = _project(tmp_path, monkeypatch)
    bg = Refresher(project, Events.for_project(project), for_project(project))
    asked = []
    bg.catalogue.reader = lambda *a, **k: asked.append(a) or (lambda ref: [])
    try:
        deadline = time.time() + 10
        while time.time() < deadline and not (bg.ready("history") and "queue" in bg.levels):
            time.sleep(0.2)
        time.sleep(1.5)
        assert asked == [] and "source rig" not in bg.errors and bg.history["stocks"]["queue"]
        bg.want("remote")
        deadline = time.time() + 10
        while time.time() < deadline and not asked:
            time.sleep(0.2)
        assert asked, "a page's ask starts the remote reads"
        ref_window = asked[0]
        assert ref_window[2] == project.config.discovery_step   # read on discovery's grid: the host's reads are reused
    finally:
        bg.stop()
