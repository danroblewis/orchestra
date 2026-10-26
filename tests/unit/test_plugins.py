"""Plugins: another package's pages and API routes in Orchestra's web app (orchestra/plugins.py)."""

import subprocess

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from orchestra import plugins
from orchestra.config import init_project


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


def a_plugin(tmp_path):
    def make(project):
        page = tmp_path / "tasks.html"
        page.write_text("<nav id='nav'></nav>tasks of {{v}}")
        (tmp_path / "s").mkdir(exist_ok=True)
        (tmp_path / "s" / "graph.js").write_text("// graph")
        (tmp_path / "s" / "everywhere.js").write_text("// on every page")
        r = APIRouter()

        @r.get("/hello")
        def hello() -> dict:
            return {"project": project.key}
        return plugins.Plugin("tasks", [plugins.Page("/tasks", "Tasks", page), plugins.Page("/machines", "Mine", page)], tmp_path / "s", r,
                              scripts=["everywhere.js", "missing.js"])
    return make


def test_a_plugin_adds_pages_static_files_and_routes_and_a_broken_one_is_reported(project, tmp_path, monkeypatch):
    def broken(project):
        raise RuntimeError("no database")
    monkeypatch.setattr(plugins, "entry_points", lambda group: [EntryPoint("tasks", a_plugin(tmp_path)), EntryPoint("bad", broken)])
    from orchestra.web.app import create_app
    c = TestClient(create_app(project))
    page = c.get("/tasks")
    assert page.status_code == 200 and "tasks of " in page.text and "{{v}}" not in page.text
    assert c.get("/plugins/tasks/static/graph.js").text == "// graph"
    assert c.get("/api/plugins/tasks/hello").json() == {"project": project.key}
    d = c.get("/api/plugins").json()
    assert d["pages"] == [{"plugin": "tasks", "path": "/tasks", "title": "Tasks"}]          # /machines is Orchestra's
    assert d["scripts"] == ["/plugins/tasks/static/everywhere.js"]                         # a missing file is left out
    assert {e["plugin"] for e in d["errors"]} == {"bad", "tasks"}
    assert "tasks of" not in c.get("/machines").text                                       # still Orchestra's page
