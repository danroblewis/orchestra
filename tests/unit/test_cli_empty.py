"""The CLI's empty states say why: `orchestra sd versions` and `sd show` with no model give the
reason the Dynamics page gives, and whether discovery will run by itself."""

import subprocess

import pytest

from orchestra import plugins
from orchestra.cli import main
from orchestra.config import init_project
from orchestra.sd.model import Model
from orchestra.sd.store import ModelStore


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(plugins, "entry_points", lambda group: [])
    (tmp_path / "repo").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path / "repo", check=True)
    return init_project(tmp_path / "repo")


def test_no_versions_and_no_model_say_why(project, capsys):
    repo = str(project.repo_root)
    assert main(["--repo", repo, "sd", "versions"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("no versions yet: no discovery has run yet; no orchestra run is running")
    new = "too new to measure: its first point is after the window's last step, so the next discovery considers it"
    ModelStore.for_state(project.state_dir).write_discovery(
        Model("m", "nothing yet", discovery={"left_out": {"a": new, "b": new}, "sampled": 2, "series": 0}))
    assert main(["--repo", repo, "sd", "show"]) == 0
    assert "no model yet: none could be judged yet: all 2 series are newer than one step" in capsys.readouterr().out
    assert main(["--repo", repo, "sd", "show", "--version", "4"]) == 1
    assert "there is no version 4" in capsys.readouterr().out


def test_every_action_is_described_in_help(capsys):
    for cmd in (["sd"], ["events"], ["sources"], ["metrics"], ["web"]):
        with pytest.raises(SystemExit):
            main([*cmd, "--help"])
        out = capsys.readouterr().out
        assert out.count(":") > 3, cmd
    with pytest.raises(SystemExit):
        main(["web", "--help"])
    assert "the port to serve on" in capsys.readouterr().out
