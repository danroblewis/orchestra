"""Acceptance tests against a running Orchestra built from the wheel under test.

ORCHESTRA_TARGET_URL points at the instance started by scripts/acceptance_target.py:
the installed wheel's web UI plus its agent loop driven by the fake Pi. Only HTTP is
used here, exactly like a human at the dashboard. Tests run in file order: the
instance starts with new-worker pickup paused, and the suite resumes it.

Skipped when ORCHESTRA_TARGET_URL is not set, so the ordinary suite never depends on
a built artifact."""

import json
import os
import time
import urllib.error
import urllib.request

import pytest

URL = os.environ.get("ORCHESTRA_TARGET_URL")
pytestmark = pytest.mark.skipif(not URL, reason="ORCHESTRA_TARGET_URL not set")


def get(path: str):
    with urllib.request.urlopen(URL.rstrip("/") + path, timeout=20) as r:
        return r.status, r.headers.get("content-type", ""), r.read().decode()


def get_json(path: str) -> dict:
    status, ctype, body = get(path)
    assert status == 200 and "json" in ctype, (path, status, ctype)
    return json.loads(body)


def post_json(path: str, obj: dict, timeout: float = 60) -> tuple[int, str]:
    req = urllib.request.Request(URL.rstrip("/") + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def state() -> dict:
    return get_json("/api/state")


def ticket_states() -> dict[str, str]:
    return {t["title"]: t["state"] for t in state()["tickets"]}


def wait_for(pred, timeout: float, every: float = 1.0, what: str = "condition"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(every)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}: {ticket_states()}")


# -- resting state --------------------------------------------------------------------

def test_state_reflects_seeded_project():
    d = state()
    assert d["project"]["key"].startswith("repo-")
    assert [m["name"] for m in d["milestones"]] == ["Acceptance"]
    assert ticket_states() == {"Seeded ticket": "OPEN", "Follow-up ticket": "OPEN"}
    assert d["pipeline"] == {"paused": False, "reason": None}
    assert d["pickup_paused"] is True
    follow = next(t for t in d["tickets"] if t["title"] == "Follow-up ticket")
    assert follow["depends_on"] and not follow["ready"]  # waits on the seeded ticket


def test_loop_is_running_with_resident_agents():
    d = wait_for(lambda: state() if (state().get("loop") or {}).get("port") else None, 60, what="loop control record")
    resident = {s["id"]: s for s in d["sessions"] if s["id"] in ("supervisor", "coordinator", "pipeline-manager")}
    assert set(resident) == {"supervisor", "coordinator", "pipeline-manager"}
    assert all(s["alive"] for s in resident.values())
    assert {r["name"] for r in d["roles"]} >= {"supervisor", "coordinator", "pipeline_manager"}


def test_pages_and_assets():
    for path, needle in (("/", 'href="/tickets"'), ("/tickets", 'href="/"'), ("/agents", 'href="/"'),
                         ("/static/app.js", "openTicket"), ("/static/style.css", ".cores")):
        status, _, body = get(path)
        assert status == 200 and needle in body, path


def test_read_endpoints():
    d = get_json("/api/system")
    assert len(d["cpu_percent"]) >= 1 and 0 <= d["memory"]["percent"] <= 100 and 0 <= d["disk"]["percent"] <= 100
    assert get_json("/api/staging")["configured"] is False
    assert get_json("/api/landings")["total"] == 0
    b = get_json("/api/burndown")
    assert b["total"] == 2 and b["remaining"] == 2
    assert "text" in get_json("/api/context")
    ev = get_json("/api/events")
    assert {e["type"] for e in ev["events"]} >= {"milestone_created", "ticket_created", "pickup_paused"}
    roles = get_json("/api/roles")
    assert any(r["name"] == "supervisor" and r["builtin"] for r in roles["roles"]) if isinstance(roles, dict) else roles


def test_ticket_detail_and_404s():
    tid = state()["tickets"][0]["id"]
    d = get_json(f"/api/tickets/{tid}")
    assert d["id"] == tid and "notes" in d
    for path in ("/api/tickets/NOPE-1", "/api/sessions/nobody/transcript", "/api/gate/runs/nope"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(path)
        assert e.value.code == 404, path


def test_pause_holds_new_workers():
    time.sleep(8)  # more than two loop ticks
    assert ticket_states() == {"Seeded ticket": "OPEN", "Follow-up ticket": "OPEN"}
    assert state()["pickup_paused"] is True


def test_control_rejects_bad_requests():
    assert post_json("/api/control", {"action": "nonsense"})[0] == 400
    assert post_json("/api/control", {"action": "kill", "ticket": "NOPE-1"})[0] == 404
    tid = state()["tickets"][0]["id"]
    assert post_json("/api/control", {"action": "kill", "ticket": tid})[0] == 409  # OPEN: nothing to stop


# -- the human path: a message to the supervisor ------------------------------------

def test_supervisor_message_roundtrip():
    status, body = post_json("/api/supervisor", {"message": "hello from acceptance"}, timeout=120)
    assert status == 200, body
    lines = [json.loads(ln) for ln in body.splitlines() if ln.strip()]
    assert lines and lines[-1]["type"] == "done" and not lines[-1].get("error"), lines[-1]
    assert "acknowledges" in body  # the fake supervisor echoes the prompt
    tr = get_json("/api/sessions/supervisor/transcript")
    assert tr["total"] >= 2 and {m["role"] for m in tr["messages"]} >= {"user", "assistant"}


# -- resume, then watch both tickets land in dependency order ------------------------

def test_resume_lands_tickets_in_order():
    status, body = post_json("/api/control", {"action": "resume"})
    assert status == 200 and json.loads(body)["pickup_paused"] is False
    wait_for(lambda: ticket_states()["Seeded ticket"] == "DONE", 180, what="seeded ticket DONE")
    wait_for(lambda: ticket_states()["Follow-up ticket"] == "DONE", 180, what="follow-up DONE")

    d = state()
    first = next(t for t in d["tickets"] if t["title"] == "Seeded ticket")
    second = next(t for t in d["tickets"] if t["title"] == "Follow-up ticket")
    runs = get_json("/api/events")["events"]
    landed = [e for e in runs if e["type"] == "ticket_transition" and e.get("to") == "DONE"]
    assert [e["ticket"] for e in landed] == [first["id"], second["id"]]

    # Gate runs are recorded and readable; each one landed.
    gate_ids = {e.get("gate_run") for e in runs if e["type"] == "gate_landed" and e.get("gate_run")}
    for rid in gate_ids:
        assert get_json(f"/api/gate/runs/{rid}")["status"] == "landed"
    assert get_json("/api/landings")["total"] == 2
    b = get_json("/api/burndown")
    assert b["total"] == 2 and b["remaining"] == 0

    # Worker and reviewer sessions are archived with readable transcripts; worktrees are gone.
    detail = get_json(f"/api/tickets/{first['id']}")
    assert detail["worktree"] is None
    assert any(n["kind"] == "review" for n in detail["notes"])
    tr = get_json(f"/api/sessions/worker-{first['id']}/transcript")
    assert tr["session"]["status"] == "archived" and tr["total"] >= 2
    assert any(m["role"] == "assistant" for m in tr["messages"])
    live = {s["id"] for s in state()["sessions"] if s["status"] == "running"}
    assert not live & {f"worker-{first['id']}", f"reviewer-{first['id']}"}
