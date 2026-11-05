"""A project that keeps its repository clean (``orchestra init --clean``, the owner, 2026-11-04:
"having no orchestra.toml file in the repo"): nothing of Orchestra's in the repository, the
private overlay in the state directory holding the whole configuration."""

import subprocess

import pytest

from orchestra.config import ConfigError, init_project, load_project


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ORCHESTRA_REPO", raising=False)
    monkeypatch.delenv("ORCHESTRA_CONFIG_OVERLAY", raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    git("init", "-q", "-b", "main", cwd=r)
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init", "--allow-empty", cwd=r)
    return r


def test_init_clean_writes_nothing_in_the_repository(repo):
    p = init_project(repo, clean=True)
    assert not (repo / "orchestra.toml").exists()
    assert p.clean
    assert p.overlay_file.exists() and p.overlay_file.is_relative_to(p.state_dir)
    assert "[events]" in p.overlay_file.read_text()
    assert p.overlay_file.stat().st_mode & 0o077 == 0
    status = subprocess.run(["git", "status", "--porcelain"], check=True, cwd=repo, capture_output=True, text=True).stdout
    assert status == ""


def test_a_clean_project_loads_from_the_overlay_alone(repo):
    p = init_project(repo, clean=True)
    p.overlay_file.write_text('[discovery]\nevery = "7m"\n')
    q = load_project(repo)
    assert q.clean and q.config.raw["discovery"]["every"] == "7m"
    assert not q.repo_config_missing()


def test_without_clean_a_missing_file_is_still_an_error(repo):
    with pytest.raises(ConfigError, match="--clean"):
        load_project(repo)


def test_an_orchestra_toml_that_reappears_is_read_and_the_project_is_no_longer_clean(repo):
    init_project(repo, clean=True)
    (repo / "orchestra.toml").write_text('[only_in_repo]\nseen = 1\n')
    q = load_project(repo)
    assert not q.clean
    assert q.config.raw["only_in_repo"]["seen"] == 1 and "events" in q.config.raw    # both files, the overlay over it


def test_a_registered_project_deleting_its_file_by_mistake_is_said_not_silently_clean(repo):
    p = init_project(repo)
    (repo / "orchestra.toml").unlink()
    assert not p.clean and p.repo_config_missing()


def test_init_clean_on_an_existing_project_copies_its_settings_to_a_new_overlay(repo):
    init_project(repo)
    (repo / "orchestra.toml").write_text('[discovery]\nevery = "9m"\n')
    p = init_project(repo, clean=True)
    assert 'every = "9m"' in p.overlay_file.read_text()
    assert (repo / "orchestra.toml").exists()            # never deleted by Orchestra
    (repo / "orchestra.toml").unlink()
    q = load_project(repo)
    assert q.clean and q.config.raw["discovery"]["every"] == "9m"


def test_config_edit_writes_a_repository_change_to_the_overlay(repo):
    p = init_project(repo, clean=True)
    change = p.config_edit.set("discovery.every", "11m")
    assert change.target == "overlay" and "clean" in change.note
    assert not (repo / "orchestra.toml").exists()
    p.reload_config()
    assert p.config.raw["discovery"]["every"] == "11m"


def test_config_edit_adds_an_entry_in_a_clean_project(repo):
    p = init_project(repo, clean=True)
    p.config_edit.add_entry("machines", {"name": "poller", "command": "true"})
    p.reload_config()
    assert [m["name"] for m in p.config.raw["machines"]] == ["poller"]
    assert not (repo / "orchestra.toml").exists()
