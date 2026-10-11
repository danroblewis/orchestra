"""Acceptance tests against a running Orchestra built from the wheel under test.

ORCHESTRA_TARGET_URL points at the web server started by scripts/acceptance_target.py.
Skipped when it is not set, so the ordinary suite never depends on a built artifact."""

import json
import os
import urllib.request

import pytest

URL = os.environ.get("ORCHESTRA_TARGET_URL")
pytestmark = pytest.mark.skipif(not URL, reason="ORCHESTRA_TARGET_URL not set")


def get(path: str):
    with urllib.request.urlopen(URL.rstrip("/") + path, timeout=10) as r:
        body = r.read().decode()
        return r.status, r.headers.get("content-type", ""), body


def test_state_reflects_seeded_project():
    status, ctype, body = get("/api/state")
    assert status == 200 and "json" in ctype
    d = json.loads(body)
    assert d["project"]["key"].startswith("repo-")
    assert [m["name"] for m in d["milestones"]] == ["Acceptance"]
    assert [t["title"] for t in d["tickets"]] == ["Seeded ticket"]
    assert d["tickets"][0]["state"] == "OPEN"
    assert d["pipeline"] == {"paused": False, "reason": None}


def test_pages_and_assets():
    for path, needle in (("/", 'href="/tickets"'), ("/tickets", 'href="/"'), ("/static/app.js", "openTicket"),
                         ("/static/style.css", ".cores")):
        status, _, body = get(path)
        assert status == 200 and needle in body, path


def test_system_and_staging_endpoints():
    _, _, body = get("/api/system")
    d = json.loads(body)
    assert len(d["cpu_percent"]) >= 1 and 0 <= d["memory"]["percent"] <= 100 and 0 <= d["disk"]["percent"] <= 100
    _, _, body = get("/api/staging")
    assert json.loads(body)["configured"] is False


def test_ticket_detail_and_404():
    _, _, body = get("/api/state")
    tid = json.loads(body)["tickets"][0]["id"]
    status, _, body = get(f"/api/tickets/{tid}")
    assert status == 200 and json.loads(body)["id"] == tid
    with pytest.raises(urllib.error.HTTPError) as e:
        get("/api/tickets/NOPE-1")
    assert e.value.code == 404
