"""No token reaches a log: the web server's access and error logs redact ``token=`` and bearer
values, the login form's body is never logged, and the banner of ``orchestra web`` written to a
file (logs/web.log) names where the token is kept, never the token."""

from __future__ import annotations

import argparse
import logging
import subprocess

import pytest

from orchestra.config import init_project
from orchestra.web.redact import redact

SECRET = "abc123def456abc123def456abc123de"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    (tmp_path / "repo").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path / "repo", check=True)
    return init_project(tmp_path / "repo")


def test_redact_takes_the_value_of_every_token_form():
    for said in (f"GET /login?next=%2F&token={SECRET} HTTP/1.1", f"/login#token={SECRET}", f"token={SECRET}&next=/",
                 f"Authorization: Bearer {SECRET}", f'"GET /x?access_token={SECRET}" 200'):
        assert SECRET not in redact(said) and "<redacted>" in redact(said), said
    assert redact("GET /api/dynamics/model 200") == "GET /api/dynamics/model 200"


def test_a_request_to_login_with_a_token_leaves_no_token_in_the_log(project, caplog):
    from fastapi.testclient import TestClient

    from orchestra.web.app import create_app

    caplog.set_level(logging.DEBUG)
    with TestClient(create_app(project)) as c:
        c.get(f"/login?next=%2F&token={SECRET}")
        c.post("/login", data={"token": SECRET, "next": "/"}, headers={"Origin": "http://testserver"})
        # what uvicorn's access log writes for such a request, in its own format
        logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET",
                                                 f"/login?next=%2F&token={SECRET}", "1.1", 200)
        logging.getLogger("uvicorn.error").warning("Invalid HTTP request: /login?token=%s", SECRET)
    said = [r.getMessage() for r in caplog.records if r.name != "httpx"]     # the test client's own log, not the server's
    assert any("<redacted>" in s for s in said)
    assert not [s for s in said if SECRET in s]


def test_the_banner_written_to_a_file_names_no_token(project, monkeypatch, capsys):
    import uvicorn

    from orchestra import cli
    from orchestra.web import auth

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_cannot_bind", lambda host, port: None)
    cli.cmd_web(argparse.Namespace(action="serve", repo=str(project.repo_root), host="127.0.0.1", port=0, rotate=False))
    out = capsys.readouterr().out
    assert "orchestra web token" in out and str(auth.token_file(project)) in out
    assert auth.token(project) not in out
