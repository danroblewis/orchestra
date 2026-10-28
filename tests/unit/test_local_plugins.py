"""A project's own plugins and overrides (.orchestra/plugins/, .orchestra/overrides/): loaded by file,
never through sys.path (AGENTS.md rule 10); an override applied only on the version it was written
against, once, and taken out when it goes."""

import importlib.metadata
import subprocess
import sys
import textwrap

import pytest

from orchestra import cadence, commands, overrides, plugins
from orchestra.config import init_project

VERSION = importlib.metadata.version("orchestra")
ORIGINAL = cadence.active_within


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    p = init_project(r)
    yield p
    import shutil
    shutil.rmtree(r / ".orchestra" / "overrides", ignore_errors=True)
    overrides.apply(r)                    # whatever the test left is taken out
    assert cadence.active_within is ORIGINAL


def write(root, rel, text):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(textwrap.dedent(text))
    return f


def an_override(root, name="slow", pin=VERSION, kind="wrap", factor=10):
    body = (f"def override(original):\n    return lambda c: original(c) * {factor}\n" if kind == "wrap"
            else f"def override(cadence):\n    return {factor}.0\n")
    return write(root, f".orchestra/overrides/{name}.py",
                 f'TARGET = "orchestra.cadence:active_within"\nPACKAGE = "orchestra=={pin}"\nKIND = "{kind}"\n'
                 f'ISSUE = "danroblewis/orchestra#1"\n' + body)


def test_a_project_plugin_is_loaded_by_file_beside_the_installed_ones(project):
    write(project.repo_root, ".orchestra/plugins/mine/__init__.py", """
        from orchestra.plugins import Plugin
        from .helper import NAME
        def plugin(project):
            return Plugin(name=NAME)
    """)
    write(project.repo_root, ".orchestra/plugins/mine/helper.py", 'NAME = "mine"\n')
    write(project.repo_root, ".orchestra/plugins/single.py", """
        from orchestra.plugins import Plugin
        def plugin(project):
            return Plugin(name="single")
    """)
    write(project.repo_root, ".orchestra/plugins/broken.py", "raise RuntimeError('no')\n")
    path_before = list(sys.path)
    loaded = plugins.load(project, found=list)
    assert sys.path == path_before
    assert [p.name for p in loaded.plugins] == ["mine", "single"]
    assert sys.modules["orchestra_local.mine.helper"].NAME == "mine"
    status = {x["name"]: x["status"] for x in loaded.local}
    assert status == {"broken": "failed", "mine": "loaded", "single": "loaded"}
    assert any(e["plugin"] == "broken" and "no" in e["error"] for e in loaded.errors)


def test_an_override_wraps_its_target_once_and_comes_out_when_removed(project):
    f = an_override(project.repo_root)
    [r] = overrides.apply(project.repo_root)
    assert r["status"] == "applied" and r["target"] == "orchestra.cadence:active_within" and r["issue"] == "danroblewis/orchestra#1"
    assert cadence.active_within(100.0) == ORIGINAL(100.0) * 10
    overrides.apply(project.repo_root)
    assert cadence.active_within(100.0) == ORIGINAL(100.0) * 10, "applied again is not wrapped twice"
    an_override(project.repo_root, factor=3)
    import os
    os.utime(f, ns=(f.stat().st_mtime_ns + 10**9,) * 2)
    overrides.apply(project.repo_root)
    assert cadence.active_within(100.0) == ORIGINAL(100.0) * 3, "a changed file is applied from the original"
    f.unlink()
    assert overrides.apply(project.repo_root) == []
    assert cadence.active_within is ORIGINAL


def test_replace_and_stale_and_broken_overrides(project):
    an_override(project.repo_root, kind="replace", factor=7)
    [r] = overrides.apply(project.repo_root)
    assert r["status"] == "applied" and cadence.active_within(1.0) == 7.0
    an_override(project.repo_root, pin="0.0.0-other")
    [r] = overrides.apply(project.repo_root)
    assert r["status"] == "stale" and "not applied" in r["error"] and r["installed"] == VERSION
    assert cadence.active_within is ORIGINAL, "a stale override is taken out"
    write(project.repo_root, ".orchestra/overrides/bad.py", 'TARGET = "nowhere"\n')
    reports = {x["name"]: x for x in overrides.apply(project.repo_root)}
    assert reports["bad"]["status"] == "failed" and "TARGET" in reports["bad"]["error"]


def test_overrides_are_applied_with_the_plugins_and_before_a_plugin_command(project, monkeypatch):
    an_override(project.repo_root)
    loaded = plugins.load(project, found=list)
    assert [x["status"] for x in loaded.local if x["kind_of"] == "override"] == ["applied"]
    write(project.repo_root, ".orchestra/overrides/slow.py", "")      # an empty file: no header
    overrides.apply(project.repo_root)
    assert cadence.active_within is ORIGINAL
    an_override(project.repo_root, factor=5)
    seen = []

    class EP:
        value = "x:main"

        def load(self):
            return lambda argv: seen.append(cadence.active_within(100.0))
    monkeypatch.chdir(project.repo_root)
    assert commands.run("x", EP(), []) == 0
    assert seen == [ORIGINAL(100.0) * 5]
