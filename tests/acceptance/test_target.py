"""Acceptance tests against a running, empty Orchestra built from the package under test.

ORCHESTRA_TARGET_URL points at the instance started by scripts/acceptance_target.py: the
bootstrap host and the web UI over a throwaway project. Only HTTP is used here, like a person at
the dashboard, with the web token the target prints (ORCHESTRA_TARGET_TOKEN). Skipped when
ORCHESTRA_TARGET_URL is not set."""

import json
import os
import time
import urllib.error
import urllib.request

import pytest

URL = os.environ.get("ORCHESTRA_TARGET_URL")
TOKEN = os.environ.get("ORCHESTRA_TARGET_TOKEN", "")
pytestmark = pytest.mark.skipif(not URL, reason="ORCHESTRA_TARGET_URL not set")


def get(path: str, token: str | None = None):
    req = urllib.request.Request(URL.rstrip("/") + path, headers={"Authorization": f"Bearer {TOKEN if token is None else token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, r.headers.get("content-type", ""), r.read().decode()


def get_json(path: str) -> dict:
    status, ctype, body = get(path)
    assert status == 200 and "json" in ctype, (path, status, ctype)
    return json.loads(body)


@pytest.mark.parametrize("path", ["/", "/machines", "/dynamics", "/core"])
def test_pages_render(path):
    status, ctype, body = get(path)
    assert status == 200 and "html" in ctype and "<nav" in body and "{{v}}" not in body


def test_core_services_are_healthy():
    deadline = time.time() + 30
    while True:
        c = get_json("/api/core")
        if c["host"].get("loop", {}).get("alive") or time.time() > deadline:
            break
        time.sleep(1)
    assert c["bus"]["ok"] and c["metrics"]["ok"]
    assert c["host"]["loop"]["alive"], "the bootstrap host is running"


def test_the_host_is_a_machine_on_the_bus():
    m = get_json("/api/machines")
    host = next(x for x in m["machines"] if x["id"] == "orchestra-host")
    assert any(p["type"] == "orchestra.host.started" for p in host["publishes"])


def test_an_empty_orchestra_has_no_model_yet():
    d = get_json("/api/dynamics/model")
    assert d["ok"] is False and "discover" in d["error"]


def test_without_the_token_nothing_but_health_is_served():
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(URL.rstrip("/") + "/api/core", timeout=20)
    assert e.value.code == 401
    with urllib.request.urlopen(URL.rstrip("/") + "/health", timeout=20) as r:
        assert json.loads(r.read()) == {"ok": True}
