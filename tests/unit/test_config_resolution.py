import subprocess

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


def test_worktree_of_a_bare_clone_is_its_own_root(repo, tmp_path):
    """A bare clone in <dir>/.git with worktrees beside it: <dir> has no files, so
    each worktree is the project, never the bare clone's directory."""
    bare = tmp_path / "bare"
    bare.mkdir()
    git("clone", "-q", "--bare", str(repo), str(bare / ".git"), cwd=tmp_path)
    wt = tmp_path / "worktree_1"
    git("worktree", "add", "-q", str(wt), "main", cwd=bare / ".git")
    (wt / "sub").mkdir()
    assert find_repo_root(wt) == wt.resolve()
    assert find_repo_root(wt / "sub") == wt.resolve()
    named = tmp_path / "service.git"         # a bare clone named the usual way
    git("clone", "-q", "--bare", str(repo), str(named), cwd=tmp_path)
    wt2 = tmp_path / "worktree_2"
    git("worktree", "add", "-q", "-b", "other", str(wt2), "main", cwd=named)
    assert find_repo_root(wt2) == wt2.resolve()


def test_not_a_repo(tmp_path):
    with pytest.raises(ConfigError):
        find_repo_root(tmp_path)


def test_load_registers_state_on_demand(repo, monkeypatch):
    with pytest.raises(ConfigError):
        load_project(repo)  # no orchestra.toml yet
    p = init_project(repo)
    starter = (repo / "orchestra.toml").read_text()
    assert all(s in starter for s in ("[events]", "[metrics]", "[discovery]"))      # STARTER_TOML
    assert p.state_dir.exists()
    # A clone with orchestra.toml but no state dir: load creates it.
    import shutil
    shutil.rmtree(p.state_dir)
    monkeypatch.chdir(repo)
    q = load_project()
    assert q.key == p.key and q.state_dir.exists()
