"""Tests for project resolution + ``~/.orchestra`` state management."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orchestra.project import (
    ProjectError,
    find_repo_root,
    get_repo_slug,
    home_dir,
    init_project,
    list_projects,
    load_project,
    read_repo_config,
    resolve_from_cwd,
)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A git repo with a pyproject.toml containing a [tool.orchestra] table."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[tool.orchestra]\n'
        'base_branch = "develop"\n'
        'max_concurrent_workers = 7\n'
        'labels = ["custom"]\n'
    )
    return tmp_path


@pytest.fixture(autouse=True)
def fake_home(monkeypatch):
    """Point ~/.orchestra at a temp dir so tests never touch the real home."""
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("ORCHESTRA_HOME", d)
        yield Path(d)


def test_find_repo_root_and_slug(repo: Path):
    assert find_repo_root(repo) == repo.resolve()
    assert get_repo_slug(repo) == repo.name


def test_find_repo_root_not_a_repo(tmp_path: Path):
    import pytest

    with pytest.raises(Exception):
        find_repo_root(tmp_path)


def test_init_and_load_roundtrip(repo: Path, fake_home: Path):
    project = init_project(repo, base_branch="develop", model="anthropic/x")
    assert project.slug == repo.name
    assert project.state_root == fake_home / repo.name
    assert (project.state_root / "config.json").exists()

    loaded = load_project(project.slug, repo)
    assert loaded.config["base_branch"] == "develop"
    assert loaded.config["model"] == "anthropic/x"
    assert loaded.base_branch == "develop"
    assert loaded.max_concurrent_workers == 4  # default, not overridden in config

    # Loading a missing project raises.
    with pytest.raises(ProjectError):
        load_project("does-not-exist", repo)


def test_init_duplicate_raises(repo: Path):
    init_project(repo)
    with pytest.raises(ProjectError):
        init_project(repo)


def test_read_repo_config_merges_tool_table(repo: Path):
    cfg = read_repo_config(repo)
    assert cfg["base_branch"] == "develop"
    assert cfg["max_concurrent_workers"] == 7
    assert cfg["labels"] == ["custom"]


def test_session_path_and_state_env(repo: Path, fake_home: Path):
    project = init_project(repo)
    sp = project.session_path("supervisor")
    assert sp == project.sessions_dir / "supervisor.jsonl"
    project.state_root.mkdir(parents=True, exist_ok=True)
    env = project.to_state_env()
    assert env["ORCHESTRA_DATA_DIR"] == str(project.state_dir)


def test_list_and_resolve_from_cwd(repo: Path, fake_home: Path):
    init_project(repo, slug="proj-a")
    projects = list_projects()
    assert [p.slug for p in projects] == ["proj-a"]

    resolved = resolve_from_cwd(repo)
    assert resolved.slug == "proj-a"


def test_resolve_from_cwd_unknown_raises(tmp_path: Path):
    import pytest

    with pytest.raises(ProjectError):
        resolve_from_cwd(tmp_path)
