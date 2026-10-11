"""The whole flow with real agents on every harness: a human message to the Supervisor
becomes working code on the base branch.

Occasional, opt-in (AGENTS.md): skipped unless ORCHESTRA_ACCEPTANCE=1. It runs once per
harness (Pi, Claude Code, Codex) with real models; only the configuration differs. Each
run starts its own throwaway instance with ``scripts/acceptance_target.py --real``, so
nothing but the harness binary and a model need to exist beforehand.

Configuration, all optional:
  ORCHESTRA_ACCEPTANCE_HARNESSES          comma list to run a subset (default: all three)
  ORCHESTRA_ACCEPTANCE_<HARNESS>_MODEL    model per harness (PI, CLAUDE_CODE, CODEX)
  ORCHESTRA_ACCEPTANCE_PI_PROVIDER        Pi's provider; Pi defaults to this repo's own
                                          orchestra.toml provider/model
  ORCHESTRA_ACCEPTANCE_PYTHON             interpreter that runs the target (default: this
                                          one; scripts/acceptance_real.sh points it at a
                                          venv with the built wheel)
  ORCHESTRA_ACCEPTANCE_REPORT_DIR         where the per-harness JSON reports go (default logs/)
A harness whose binary is not installed is skipped, not failed.

What it asserts, in order:
1. The Supervisor creates at least one ticket from the request without asking a question.
2. Every ticket reaches DONE through worker, review, and the merge gate.
3. The base branch has the requested function, the module's tests pass on it, and the
   project's own test file was extended.
4. The worktrees and ticket branches are cleaned up."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("ORCHESTRA_ACCEPTANCE"),
                                reason="real-model flow on every harness: set ORCHESTRA_ACCEPTANCE=1")

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "scripts" / "acceptance_target.py"
REQUEST = (
    "Please add a function `shout(name)` to greet.py. It returns the same greeting as `greet(name)` "
    "but in upper case, so shout('Ada') returns 'HELLO, ADA!'. Add a unit test for it in test_greet.py, "
    "in the same unittest style as the existing test. That is the whole request; there is nothing else "
    "to decide, so please create the ticket now."
)
SUPERVISOR_TIMEOUT = float(os.environ.get("ORCHESTRA_ACCEPTANCE_SUPERVISOR_TIMEOUT", "900"))
FLOW_TIMEOUT = float(os.environ.get("ORCHESTRA_ACCEPTANCE_FLOW_TIMEOUT", "2400"))
BINARIES = {"pi": os.environ.get("PI_BINARY", "pi"), "claude_code": os.environ.get("CLAUDE_BINARY", "claude"),
            "codex": os.environ.get("CODEX_BINARY", "codex")}


def _env(harness: str, key: str) -> str | None:
    return os.environ.get(f"ORCHESTRA_ACCEPTANCE_{harness.upper()}_{key}") or None


def _repo_default(key: str) -> str | None:
    """Pi has no default model: use what this repository's own orchestra.toml configures."""
    try:
        import tomllib
        return (tomllib.loads((ROOT / "orchestra.toml").read_text()).get("agents") or {}).get(key) or None
    except Exception:
        return None


@dataclass
class HarnessConfig:
    harness: str
    provider: str | None
    model: str | None

    @property
    def label(self) -> str:
        return f"{self.harness}/{self.model or 'default'}"


CONFIGS = [
    HarnessConfig("pi", _env("pi", "PROVIDER") or _repo_default("provider"), _env("pi", "MODEL") or _repo_default("model")),
    HarnessConfig("claude_code", None, _env("claude_code", "MODEL") or "haiku"),
    HarnessConfig("codex", None, _env("codex", "MODEL")),
]
SELECTED = {h.strip() for h in os.environ.get("ORCHESTRA_ACCEPTANCE_HARNESSES", "pi,claude_code,codex").split(",") if h.strip()}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Target:
    """A throwaway full instance on one harness, started by scripts/acceptance_target.py."""

    def __init__(self, cfg: HarnessConfig):
        self.cfg = cfg
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.log = Path(tempfile.mkdtemp(prefix=f"orchestra-acceptance-{cfg.harness}-")) / "target.log"
        python = os.environ.get("ORCHESTRA_ACCEPTANCE_PYTHON") or sys.executable
        cmd = [python, str(TARGET), "--port", str(self.port), "--real", "--harness", cfg.harness]
        cmd += ["--provider", cfg.provider] if cfg.provider else []
        cmd += ["--model", cfg.model] if cfg.model else []
        self.proc = subprocess.Popen(cmd, stdout=self.log.open("w"), stderr=subprocess.STDOUT, start_new_session=True,
                                     env={k: v for k, v in os.environ.items() if not k.startswith("ORCHESTRA_ACCEPTANCE")})

    def wait_ready(self, timeout: float = 120) -> None:
        """Ready when the web app answers and the loop has registered its control endpoint."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"target exited early:\n{self.log.read_text()[-3000:]}")
            try:
                if self.get("/api/state").get("loop", {}).get("port"):
                    return
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError(f"target not ready in {timeout:.0f}s:\n{self.log.read_text()[-3000:]}")

    def get(self, path: str) -> dict:
        with urllib.request.urlopen(self.url + path, timeout=30) as r:
            return json.loads(r.read().decode())

    def ask_supervisor(self, message: str) -> dict:
        req = urllib.request.Request(self.url + "/api/supervisor", data=json.dumps({"message": message}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=SUPERVISOR_TIMEOUT + 60) as r:
            lines = [json.loads(ln) for ln in r.read().decode().splitlines() if ln.strip()]
        return lines[-1]

    def tickets(self) -> list[dict]:
        return self.get("/api/state")["tickets"]

    def stop(self) -> None:
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=15)
        except Exception:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except Exception:
                pass


@pytest.fixture(params=CONFIGS, ids=[c.harness for c in CONFIGS])
def target(request):
    cfg: HarnessConfig = request.param
    if cfg.harness not in SELECTED:
        pytest.skip(f"{cfg.harness} not in ORCHESTRA_ACCEPTANCE_HARNESSES")
    if not shutil.which(BINARIES[cfg.harness]):
        pytest.skip(f"{BINARIES[cfg.harness]} is not installed")
    if cfg.harness == "pi" and not (cfg.provider and cfg.model):
        pytest.skip("Pi needs ORCHESTRA_ACCEPTANCE_PI_PROVIDER and _MODEL (or a provider/model in orchestra.toml)")
    t = Target(cfg)
    try:
        t.wait_ready()
        yield t
    finally:
        t.stop()


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout


def describe(ts: list[dict]) -> str:
    return "; ".join(f"{t['id']} {t['state']}" + (f" ({t.get('blocked_reason')})" if t.get("blocked_reason") else "")
                     for t in ts) or "no tickets"


def test_supervisor_request_becomes_code_on_main(target: Target):
    started = time.time()
    s = target.get("/api/state")
    repo = s["project"]["repo_root"]
    assert s["project"].get("harness") == target.cfg.harness
    assert target.tickets() == [], "the real target must start empty"

    # 1. The human asks. The Supervisor must act, not ask back.
    done = target.ask_supervisor(REQUEST)
    assert done["type"] == "done" and not done.get("error") and not done.get("timed_out"), \
        f"Supervisor turn failed on {target.cfg.label}: {done}\n{target.log.read_text()[-2000:]}"
    reply = done.get("text") or ""
    supervisor_seconds = time.time() - started
    created = target.tickets()
    assert created, f"the Supervisor created no ticket. Its reply was:\n{reply}"
    assert len(created) <= 3, f"too many tickets for one small request: {describe(created)}"
    assert target.get("/api/state")["milestones"], "tickets must belong to a milestone"

    # 2. The loop takes it from there.
    deadline = time.time() + FLOW_TIMEOUT
    while time.time() < deadline:
        ts = target.tickets()
        if ts and all(t["state"] == "DONE" for t in ts):
            break
        if any(t["state"] == "BLOCKED" for t in ts):
            pytest.fail(f"a ticket blocked: {describe(ts)}")
        if any(t["state"] == "CANCELLED" for t in ts):
            pytest.fail(f"a ticket was cancelled: {describe(ts)}")
        time.sleep(5)
    else:
        pytest.fail(f"flow did not finish in {FLOW_TIMEOUT:.0f}s: {describe(target.tickets())}")
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
    for t in target.tickets():
        detail = target.get(f"/api/tickets/{t['id']}")
        assert any(n["kind"] == "review" for n in detail["notes"]), f"{t['id']} landed without a review note"
        assert detail["worktree"] is None
    assert not git(repo, "branch", "--list", "orchestra/*").strip()
    merges = [ln for ln in git(repo, "log", "--format=%s", "main").splitlines() if ln.startswith("Merge ")]
    assert merges, "no gate merge commit on main"

    report = {"harness": target.cfg.harness, "model": s["project"].get("model") or target.cfg.model or "default",
              "supervisor_seconds": round(supervisor_seconds), "flow_seconds": round(flow_seconds),
              "tickets": [{"id": t["id"], "title": t["title"], "review_rounds": t.get("review_rounds")} for t in target.tickets()],
              "supervisor_reply": reply[:2000]}
    print(f"\nREPORT {json.dumps(report)}")
    out = Path(os.environ.get("ORCHESTRA_ACCEPTANCE_REPORT_DIR") or ROOT / "logs")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"acceptance-{target.cfg.harness}-{report['model']}.json").write_text(json.dumps(report, indent=2) + "\n")
