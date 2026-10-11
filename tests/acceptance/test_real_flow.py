"""The whole flow with real agents: a human message to the Supervisor becomes working code
on the base branch.

Opt-in (AGENTS.md): needs ORCHESTRA_ACCEPTANCE=1 and ORCHESTRA_TARGET_URL pointing at an
instance started with ``scripts/acceptance_target.py --real [--provider P --model M]``.
It is model-agnostic on purpose: run it against other models (and, later, other agent
harnesses) to compare them on the same task. ORCHESTRA_ACCEPTANCE_REPORT=path writes a
JSON record of the run (model, timings, ticket history) for that comparison.

What it asserts, in order:
1. The Supervisor creates at least one ticket from the request without asking a question.
2. Every ticket reaches DONE through worker, review, and the merge gate.
3. The base branch has the requested function, the module's tests pass on it, and the
   project's own test file was extended.
4. The worktrees and ticket branches are cleaned up."""

import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

URL = os.environ.get("ORCHESTRA_TARGET_URL")
pytestmark = pytest.mark.skipif(not (URL and os.environ.get("ORCHESTRA_ACCEPTANCE")),
                                reason="real-model flow: set ORCHESTRA_ACCEPTANCE=1 and ORCHESTRA_TARGET_URL")

REQUEST = (
    "Please add a function `shout(name)` to greet.py. It returns the same greeting as `greet(name)` "
    "but in upper case, so shout('Ada') returns 'HELLO, ADA!'. Add a unit test for it in test_greet.py, "
    "in the same unittest style as the existing test. That is the whole request; there is nothing else "
    "to decide, so please create the ticket now."
)
SUPERVISOR_TIMEOUT = float(os.environ.get("ORCHESTRA_ACCEPTANCE_SUPERVISOR_TIMEOUT", "900"))
FLOW_TIMEOUT = float(os.environ.get("ORCHESTRA_ACCEPTANCE_FLOW_TIMEOUT", "2400"))


def get_json(path: str) -> dict:
    with urllib.request.urlopen(URL.rstrip("/") + path, timeout=30) as r:
        return json.loads(r.read().decode())


def state() -> dict:
    return get_json("/api/state")


def tickets() -> list[dict]:
    return state()["tickets"]


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout


def describe(ts: list[dict]) -> str:
    return "; ".join(f"{t['id']} {t['state']}" + (f" ({t.get('blocked_reason')})" if t.get("blocked_reason") else "")
                     for t in ts) or "no tickets"


def test_supervisor_request_becomes_code_on_main():
    started = time.time()
    s = state()
    repo = s["project"]["repo_root"]
    assert tickets() == [], "the real target must start empty"

    # 1. The human asks. The Supervisor must act, not ask back.
    req = urllib.request.Request(URL.rstrip("/") + "/api/supervisor", data=json.dumps({"message": REQUEST}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=SUPERVISOR_TIMEOUT + 60) as r:
        lines = [json.loads(ln) for ln in r.read().decode().splitlines() if ln.strip()]
    done = lines[-1]
    assert done["type"] == "done" and not done.get("error") and not done.get("timed_out"), done
    reply = done.get("text") or ""
    supervisor_seconds = time.time() - started
    created = tickets()
    assert created, f"the Supervisor created no ticket. Its reply was:\n{reply}"
    assert len(created) <= 3, f"too many tickets for one small request: {describe(created)}"
    assert state()["milestones"], "tickets must belong to a milestone"

    # 2. The loop takes it from there.
    deadline = time.time() + FLOW_TIMEOUT
    while time.time() < deadline:
        ts = tickets()
        if ts and all(t["state"] == "DONE" for t in ts):
            break
        if any(t["state"] == "BLOCKED" for t in ts):
            pytest.fail(f"a ticket blocked: {describe(ts)}")
        if any(t["state"] == "CANCELLED" for t in ts):
            pytest.fail(f"a ticket was cancelled: {describe(ts)}")
        time.sleep(5)
    else:
        pytest.fail(f"flow did not finish in {FLOW_TIMEOUT:.0f}s: {describe(tickets())}")
    flow_seconds = time.time() - started

    # 3. The tangible outcome: main has the function and its tests pass.
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(f"git -C {repo} archive main | tar -x -C {tmp}", shell=True, check=True)
        greet_py = Path(tmp, "greet.py").read_text()
        assert "def shout(" in greet_py, greet_py
        test_py = Path(tmp, "test_greet.py").read_text()
        assert "shout" in test_py, "the request asked for a unit test; test_greet.py does not mention shout"
        check = subprocess.run(["python3", "-c", "from greet import greet, shout; assert greet('Ada') == 'Hello, Ada!'; "
                                "assert shout('Ada') == 'HELLO, ADA!', shout('Ada')"], cwd=tmp, capture_output=True, text=True)
        assert check.returncode == 0, check.stderr
        tests = subprocess.run(["python3", "-m", "unittest", "-q"], cwd=tmp, capture_output=True, text=True)
        assert tests.returncode == 0, tests.stderr

    # 4. Review happened and the house is tidy.
    for t in tickets():
        detail = get_json(f"/api/tickets/{t['id']}")
        assert any(n["kind"] == "review" for n in detail["notes"]), f"{t['id']} landed without a review note"
        assert detail["worktree"] is None
    assert not git(repo, "branch", "--list", "orchestra/*").strip()
    merges = [ln for ln in git(repo, "log", "--format=%s", "main").splitlines() if ln.startswith("Merge ")]
    assert merges, "no gate merge commit on main"

    report = {"model": s["project"].get("model") or os.environ.get("ORCHESTRA_ACCEPTANCE_MODEL"),
              "supervisor_seconds": round(supervisor_seconds), "flow_seconds": round(flow_seconds),
              "tickets": [{"id": t["id"], "title": t["title"], "review_rounds": t.get("review_rounds")} for t in tickets()],
              "supervisor_reply": reply[:2000]}
    print("\nREPORT " + json.dumps(report))
    if os.environ.get("ORCHESTRA_ACCEPTANCE_REPORT"):
        Path(os.environ["ORCHESTRA_ACCEPTANCE_REPORT"]).write_text(json.dumps(report, indent=2) + "\n")
