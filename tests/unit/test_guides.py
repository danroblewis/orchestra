"""Guides: Orchestra's own operator's guide and the plugins' (orchestra/guides.py, /api/guides)."""

import re
import shlex
import subprocess
import tomllib

import pytest
from fastapi.testclient import TestClient

from orchestra import guides, plugins
from orchestra.collect import spec as collect_spec
from orchestra.config import init_project
from orchestra.config_edit import problems
from orchestra.instruments import test_reports
from orchestra.sources import spec as sources_spec

BLOCKS = re.findall(r"```toml\n(.*?)```", guides.CORE.read_text(encoding="utf-8"), re.DOTALL)


class EntryPoint:
    def __init__(self, name, fn):
        self.name, self.fn = name, fn

    def load(self):
        return self.fn


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    return init_project(r)


def test_the_core_guide_ships_in_the_package_and_has_toml_examples():
    assert guides.CORE.parent.name == "orchestra" and guides.CORE.is_file()
    assert len(BLOCKS) >= 6


@pytest.mark.parametrize("block", BLOCKS, ids=[b.split("\n")[0][:30] for b in BLOCKS])
def test_every_toml_example_in_the_core_guide_is_a_configuration_orchestra_accepts(block, tmp_path):
    raw = tomllib.loads(block)
    assert problems(raw) == []                                              # what config_edit would refuse
    assert sources_spec.load(raw, tmp_path).refused == {}                   # [[sources]] are checked apart
    for c in collect_spec.from_toml(raw)[0]:                                # the test-report instrument's options
        words = shlex.split(c.target) if isinstance(c.target, str) else list(c.target)
        if words[:3] == ["python", "-m", "orchestra.instruments.test_reports"]:
            test_reports.arguments(words[3:])


def test_collect_puts_orchestras_guide_first_then_each_plugins_and_reports_an_unreadable_one(project, tmp_path):
    good = tmp_path / "bakery.md"
    good.write_text("# The bakery\nset ovens = 2")
    found = [EntryPoint("bakery", lambda p: plugins.Plugin("bakery", guide=good)),
             EntryPoint("plain", lambda p: plugins.Plugin("plain")),
             EntryPoint("lost", lambda p: plugins.Plugin("lost", guide=tmp_path / "missing.md"))]
    got = guides.collect(project, plugins.load(project, lambda: found))
    assert [g["name"] for g in got] == ["orchestra", "bakery", "lost"]      # a plugin with none is not listed
    assert got[0]["text"] == guides.CORE.read_text(encoding="utf-8")
    assert got[1] == {"name": "bakery", "text": "# The bakery\nset ovens = 2"}
    assert got[2]["text"] == "" and "cannot be read" in got[2]["error"]


def test_the_guides_are_served_behind_the_login(project, tmp_path, monkeypatch):
    g = tmp_path / "bakery.md"
    g.write_text("# The bakery")
    monkeypatch.setattr(plugins, "entry_points", lambda group: [EntryPoint("bakery", lambda p: plugins.Plugin("bakery", guide=g))])
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer
    app = create_app(project)
    assert TestClient(app).get("/api/guides").status_code == 401
    d = TestClient(app, headers=bearer(project)).get("/api/guides").json()
    assert d["ok"] and [x["name"] for x in d["guides"]] == ["orchestra", "bakery"]
    assert d["guides"][1]["text"] == "# The bakery"
