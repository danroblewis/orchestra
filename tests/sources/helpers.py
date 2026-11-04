"""Shared by the sources tests: a project with an orchestra.toml, and the rig's world as data."""

from __future__ import annotations

import subprocess
from pathlib import Path

from rig.world import World

from orchestra.config import load_project

LABELS = """
[sources.labels]
service = ["service", "app", "k8s_app"]
region = ["region", "zone", "location"]
pod = ["pod", "pod_name", "kubernetes_pod_name"]
"""


def project(tmp_path: Path, monkeypatch, toml: str):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "orchestra.toml").write_text(toml)
    return load_project(repo)


TEST_MATCH = '{__name__=~"[a-zA-Z_:].*"}'   # the fake store is the test's own: every name in it (a source needs a match)
MATCH_LINE = f"match = ['{TEST_MATCH}']"


def source_toml(url: str, *, auth: str = "", extra: str = "", window: str = "120m", step: str = "60s") -> str:
    return f"""
[discovery]
window = "{window}"
step = "{step}"
strategy = "conservation"

[[sources]]
name = "rig"
url = "{url}"
machine = "service"
{auth}
{extra if "match" in extra else MATCH_LINE}
{"" if "match" in extra else extra}
{LABELS}"""


def world(end: float, minutes: int, **kw):
    """The world's last ``minutes`` before ``end``: (dump, truth per minute)."""
    return World(end - minutes * 60, **kw).run(minutes)
