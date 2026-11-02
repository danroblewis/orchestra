"""Without ``orchestra[sd]`` (numpy, scipy, ...) the always-imported path imports, conservation
discovery finds the bakery's stocks (with no behaviour trust, and why), and the web server answers
what needs the extra with a 503 naming it. The extra's modules are hidden by an import hook in a
child interpreter, so this runs in the dev environment, where they are installed."""

import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent

SCRIPT = textwrap.dedent('''
    import sys

    class Hide:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in {"numpy", "scipy", "numba", "highspy"}:
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    sys.meta_path.insert(0, Hide())
    sys.path.insert(0, sys.argv[1])
    tmp = sys.argv[2]

    import orchestra.cli, orchestra.host, orchestra.web.app, orchestra.sd.rediscover, orchestra.sources.report  # noqa: E401,F401
    from orchestra.sd.extra import installed
    assert not installed()

    from test_discover import simulate
    from orchestra.metrics.file import FileMetrics
    from orchestra.sd.strategies import discover_with
    store = FileMetrics(tmp + "/m.jsonl")
    start, end = simulate(store, minutes=60)
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30)
    assert m.stocks, "conservation found no stocks"
    assert "orchestra[sd]" in m.discovery["behaviour"]["error"]
    assert not any("behaviour" in (s.evidence.get("trust") or {}) for s in m.stocks)

    from fastapi.testclient import TestClient
    from orchestra.config import init_project
    from orchestra.web.app import create_app
    import os, subprocess
    os.environ["ORCHESTRATOR_HOME"] = tmp + "/state"
    repo = tmp + "/repo"
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    from orchestra.web import auth
    project = init_project(repo)
    c = TestClient(create_app(project), headers={"Authorization": f"Bearer {auth.token(project)}"})
    r = c.get("/api/dynamics/model")
    assert r.status_code == 200 and r.json()["error"] == "no model" and "orchestra[sd]" in r.json()["sd_missing"], r.text
    for path in ("/api/dynamics/simulate", "/api/dynamics/observability"):
        r = c.get(path)
        assert r.status_code == 503 and r.json()["needs"] == "orchestra[sd]", (path, r.text)
    assert c.get("/api/dynamics/eras").status_code == 200
    print("ok")
''')


def test_the_core_path_needs_no_sd_extra(tmp_path):
    r = subprocess.run([sys.executable, "-c", SCRIPT, str(HERE), str(tmp_path)], check=False, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), r.stdout + r.stderr


def test_a_handler_that_imports_the_extra_answers_503():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from orchestra.web.sd_extra import install

    app = FastAPI()
    install(app)

    @app.get("/needs")
    def needs():
        raise ModuleNotFoundError("No module named 'scipy.linalg'", name="scipy.linalg")

    @app.get("/other")
    def other():
        raise ModuleNotFoundError("No module named 'nothere'", name="nothere")

    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/needs")
    assert r.status_code == 503 and "orchestra[sd]" in r.json()["error"]
    assert c.get("/other").status_code == 500
