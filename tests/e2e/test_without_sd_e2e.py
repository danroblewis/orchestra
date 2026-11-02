"""Orchestra installed without the ``sd`` extra (no numpy, no scipy) starts and serves the Core page
(AGENTS.md rule 8); what needs the extra says so, naming it.

A real install: ``uv venv`` and ``uv pip install`` of this repository with no extras (a few
seconds with uv's cache), then a project initialised through the CLI, ``orchestra run`` and
``orchestra web`` on a free port above 8100, and the endpoints read over HTTP. Run it with
``uv run python -m pytest tests/e2e/test_without_sd_e2e.py``; it skips without ``uv``."""

import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
NEVER = {8000, 8001, 8002, 8003, 8040, 8050, 8060, 8062, 8070, 8074, 8428, 9090}

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to install without extras")


def free_port() -> int:
    for port in range(8131, 8999):
        if port in NEVER:
            continue
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("no free port")


def get(url: str, token: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def wait_for(fn, timeout: float, what: str):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            got = fn()
            if got:
                return got
        except OSError:
            pass
        time.sleep(0.5)
    raise AssertionError(f"timed out waiting for {what}")


def test_orchestra_without_the_sd_extra(tmp_path):
    venv = tmp_path / "venv"
    subprocess.run(["uv", "venv", "-q", str(venv)], check=True, timeout=120)
    py = venv / "bin" / "python"
    subprocess.run(["uv", "pip", "install", "-q", "--python", str(py), str(REPO)], check=True, timeout=300)
    for mod in ("numpy", "scipy"):
        assert subprocess.run([str(py), "-I", "-c", f"import {mod}"], check=False, capture_output=True).returncode != 0, f"{mod} is installed"

    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "ORCHESTRATOR_HOME": str(tmp_path / "state"), "ORCHESTRA_REPO": str(repo)}
    for k in ("ORCHESTRA_EVENTS_URL", "ORCHESTRA_METRICS_URL", "VIRTUAL_ENV", "PYTHONPATH"):
        env.pop(k, None)
    cli = [str(py), "-I", "-m", "orchestra"]
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run([*cli, "init"], cwd=repo, env=env, check=True, capture_output=True, timeout=60)
    token = subprocess.run([*cli, "web", "token"], cwd=repo, env=env, check=True, capture_output=True, text=True,
                           timeout=60).stdout.strip()
    sd = subprocess.run([*cli, "sd", "discover"], check=False, cwd=repo, env=env, capture_output=True, text=True, timeout=120)
    assert "conservation" in sd.stdout and "Traceback" not in sd.stderr, sd.stdout + sd.stderr  # rc 1: no model yet

    port = free_port()
    host_log, web_log = (tmp_path / "host.log").open("w"), (tmp_path / "web.log").open("w")
    host = subprocess.Popen([*cli, "run"], cwd=repo, env=env, stdout=host_log, stderr=subprocess.STDOUT)
    web = subprocess.Popen([*cli, "web", "--port", str(port)], cwd=repo, env=env, stdout=web_log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        wait_for(lambda: get(base + "/health", token)[0] == 200, 60, "/health")
        status, body = get(base + "/api/core", token)
        assert status == 200, body

        status, body = get(base + "/api/dynamics/model", token)
        assert status == 404 and '"error":"no model"' in body, body
        assert "orchestra[sd]" in body and "pip install" in body, body

        status, body = get(base + "/api/dynamics/simulate", token)
        assert status == 503 and "orchestra[sd]" in body, (status, body)
        status, body = get(base + "/api/dynamics/observability", token)
        assert status == 503 and "orchestra[sd]" in body, (status, body)
        for path in ("/dynamics", "/core", "/api/dynamics/strategies", "/api/dynamics/eras",
                     "/api/dynamics/history", "/api/dynamics/predictions"):
            status, body = get(base + path, token)
            assert status in (200, 503), (path, status, body)
            if status == 503:
                assert "orchestra[sd]" in body, (path, body)

        log = tmp_path / "host.log"
        wait_for(lambda: "discovery (conservation)" in log.read_text(), 60, "the host's first discovery")
        text = log.read_text()
        assert text.count("needs orchestra[sd]") == 1, text
        assert "Traceback" not in text and "ModuleNotFoundError" not in text, text
        assert "Traceback" not in (tmp_path / "web.log").read_text()
    finally:
        for p in (web, host):
            p.terminate()
        for p in (web, host):
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
        host_log.close()
        web_log.close()
