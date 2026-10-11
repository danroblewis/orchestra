import subprocess
from pathlib import Path

import pytest

from orchestra.config import ConfigError, find_repo_root, init_project, load_project


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ORCHESTRA_REPO", raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    git("init", "-q", "-b", "main", cwd=r)
    git("config", "user.email", "t@t", cwd=r)
    git("config", "user.name", "t", cwd=r)
    (r / "f").write_text("x")
    git("add", "-A", cwd=r)
    git("commit", "-qm", "init", cwd=r)
    return r


def test_root_from_subdirectory_and_worktree(repo, tmp_path):
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    assert find_repo_root(sub) == repo.resolve()
    wt = tmp_path / "wt"
    git("worktree", "add", "-q", "-b", "feature", str(wt), "main", cwd=repo)
    assert find_repo_root(wt) == repo.resolve()
    assert find_repo_root(wt / "a" if (wt / "a").exists() else wt) == repo.resolve()


def test_not_a_repo(tmp_path):
    with pytest.raises(ConfigError):
        find_repo_root(tmp_path)


def test_load_registers_state_on_demand(repo, monkeypatch):
    with pytest.raises(ConfigError):
        load_project(repo)  # no orchestra.toml yet
    p = init_project(repo)  # provider/model optional
    assert p.config.provider is None and p.config.model is None
    assert p.state_dir.exists()
    # A clone with orchestra.toml but no state dir: load creates it.
    import shutil
    shutil.rmtree(p.state_dir)
    monkeypatch.chdir(repo)
    q = load_project()
    assert q.key == p.key and q.state_dir.exists()
