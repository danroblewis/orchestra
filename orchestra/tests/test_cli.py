"""CLI-level tests: init, tickets, and a single-flight ``run`` against a temp repo."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from orchestra.cli import main


@pytest.fixture()
def temp_repo() -> str:
    tmp = str(tempfile.mkdtemp())
    subprocess.run(["git", "-C", tmp, "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", tmp, "config", "user.email", "t@e.com"], check=True)
    subprocess.run(["git", "-C", tmp, "config", "user.name", "Test"], check=True)
    (Path(tmp) / "f.txt").write_text("x")
    subprocess.run(["git", "-C", tmp, "add", "."], check=True)
    subprocess.run(["git", "-C", tmp, "commit", "-q", "-m", "init"], check=True)
    yield tmp


@pytest.fixture(autouse=True)
def fake_home(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCHESTRA_HOME", str(tmp_path / "home"))
    return tmp_path


def _init(temp_repo: str, slug: str) -> None:
    assert main(["init", "--repo", temp_repo, "--base_branch", "main", "--slug", slug]) == 0


def test_cli_init_and_tickets(temp_repo: str):
    _init(temp_repo, "demo")
    rc = main(["tickets", "--project", "demo"])
    assert rc == 0


def test_cli_run_nothing_to_do(temp_repo: str):
    _init(temp_repo, "demo")
    rc = main(["run", "--project", "demo"])
    assert rc == 0


def test_cli_worktrees_and_clean_empty(temp_repo: str):
    _init(temp_repo, "demo")
    assert main(["worktrees", "--project", "demo"]) == 0
    assert main(["clean", "--project", "demo"]) == 0
