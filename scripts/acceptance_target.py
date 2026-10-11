"""Acceptance target: run the *installed* orchestra wheel as a complete instance.

Invoked by the merge gate's [acceptance] start command inside an isolated environment
that has the built wheel installed. Two modes:

- Throwaway (default): a temporary ORCHESTRATOR_HOME and git repository, a project
  initialised and seeded through the CLI, the agent loop running against a fake Pi
  (tests/e2e/fake_pi.py, which plays every role over the real RPC protocol), and the
  web UI on --port. New-worker pickup starts PAUSED so the acceptance tests observe
  the resting state first, then resume it and watch tickets land.
- Staging (--project): the same build serving a persistent demo project with real agents.

The CLI's read commands are run once at startup as a smoke test; any failure aborts.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAKE_PI = HERE.parent / "tests" / "e2e" / "fake_pi.py"


def sh(*args: str, cwd: Path | None = None, env: dict | None = None) -> str:
    p = subprocess.run(list(args), cwd=cwd, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout, p.stderr, file=sys.stderr)
        raise SystemExit(f"command failed: {' '.join(args)}")
    return p.stdout


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def staging(project: str, port: int) -> None:
    # The new build serves a persistent demo project, sharing the operator's
    # ~/.orchestrator state so tickets and history survive redeploys.
    repo = Path(project).expanduser().resolve()
    env = {**os.environ, "ORCHESTRA_REPO": str(repo)}
    if not (repo / "orchestra.toml").exists():
        sh(sys.executable, "-m", "orchestra", "init", "--prefix", "DEMO", env=env, cwd=repo)
    print(f"[acceptance_target] staging: full instance on demo project {repo}", flush=True)
    os.chdir(repo)
    # The loop (resident agents, workers, gate) runs as a child in this process group, so
    # stopping staging stops it too. The web UI runs in the foreground on --port.
    subprocess.Popen([sys.executable, "-m", "orchestra", "run"], env=env, cwd=repo)
    os.execve(sys.executable, [sys.executable, "-m", "orchestra", "web", "--port", str(port)], env)


GREET_PY = '''"""A tiny module for the real-model acceptance flow."""


def greet(name: str) -> str:
    return f"Hello, {name}!"
'''

TEST_GREET_PY = '''import unittest

from greet import greet


class GreetTest(unittest.TestCase):
    def test_greet(self):
        self.assertEqual(greet("Ada"), "Hello, Ada!")


if __name__ == "__main__":
    unittest.main()
'''


def throwaway(port: int, real: bool, provider: str | None, model: str | None, harness: str) -> None:
    """A temporary project. With ``real`` the loop runs real agents on the given harness and
    model and nothing is seeded: the acceptance test talks to the Supervisor. Otherwise the
    fake Pi plays every role and two tickets are seeded with pickup paused."""
    tmp = Path(tempfile.mkdtemp(prefix="orchestra-acceptance-"))
    home, repo = tmp / "home", tmp / "repo"
    repo.mkdir()
    env = {**os.environ, "ORCHESTRATOR_HOME": str(home), "ORCHESTRA_REPO": str(repo),
           # the worker, reviewer, and gate run python3 from PATH: make it the one with the wheel.
           "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")}
    if not real:
        fake = tmp / "pi"
        shutil.copy(FAKE_PI, fake)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        env["PI_BINARY"] = str(fake)
    sh("git", "init", "-q", "-b", "main", cwd=repo)
    sh("git", "config", "user.email", "acceptance@orchestra", cwd=repo)
    sh("git", "config", "user.name", "acceptance", cwd=repo)
    (repo / "README.md").write_text("# target\n\nA tiny Python module. Tests: `python3 -m unittest -q`.\n")
    (repo / "greet.py").write_text(GREET_PY)
    (repo / "test_greet.py").write_text(TEST_GREET_PY)
    (repo / ".gitignore").write_text("__pycache__/\n")
    sh("git", "add", "-A", cwd=repo)
    sh("git", "commit", "-qm", "init", cwd=repo)

    cli = [sys.executable, "-m", "orchestra"]
    init = ["init", "--prefix", "ACC", "--unit-command", "python3 -m unittest -q"]
    if real:
        init += (["--provider", provider] if provider else []) + (["--model", model] if model else [])
    else:
        init += ["--provider", "fake", "--model", "fake"]
    sh(*cli, *init, env=env, cwd=repo)
    toml = repo / "orchestra.toml"
    text = toml.read_text()
    assert "[agents]\n" in text and 'harness = "pi"' in text, "init template changed; cannot place control_port/harness"
    text = text.replace("[agents]\n", f"[agents]\ncontrol_port = {free_port()}\n", 1)
    toml.write_text(text.replace('harness = "pi"', f'harness = "{harness if real else "pi"}"', 1))
    sh("git", "add", "-A", cwd=repo)
    sh("git", "commit", "-qm", "orchestra config", cwd=repo)

    if real:
        print(f"[acceptance_target] real agents on {harness}: provider={provider or 'default'} model={model or 'default'}; "
              f"project at {repo}, home {home}", flush=True)
        os.chdir(repo)
        subprocess.Popen([sys.executable, "-m", "orchestra", "run"], env=env, cwd=repo)
        os.execve(sys.executable, [sys.executable, "-m", "orchestra", "web", "--port", str(port)], env)

    sup = {**env, "ORCHESTRA_ROLE": "supervisor"}
    ms = json.loads(sh(*cli, "api", "create_milestone", "--compact", "--args", json.dumps({"name": "Acceptance"}),
                       env=sup, cwd=repo))["milestone"]
    first = json.loads(sh(*cli, "api", "create_ticket", "--compact", "--args",
                          json.dumps({"title": "Seeded ticket", "description": "seeded by acceptance_target",
                                      "acceptance": "WORK.md mentions the ticket", "milestone_id": ms["id"]}),
                          env=sup, cwd=repo))["ticket"]
    sh(*cli, "api", "create_ticket", "--compact", "--args",
       json.dumps({"title": "Follow-up ticket", "description": "depends on the seeded ticket",
                   "acceptance": "WORK.md has two lines", "milestone_id": ms["id"], "depends_on": [first["id"]]}),
       env=sup, cwd=repo)
    # Hold new workers until the tests say go (the operator's pause control).
    sh(sys.executable, "-c",
       "from orchestra.config import load_project; from orchestra.store import LocalStore; "
       "LocalStore(load_project()).set_pickup_paused(True, by='acceptance_target')", env=env, cwd=repo)

    # Every human-facing read command must work on the installed wheel.
    for cmd in (["status"], ["status", "--json"], ["ticket", "list"], ["ticket", "show", first["id"]],
                ["milestone", "list"], ["sessions", "list"], ["roles", "list"], ["doctor"], ["--version"]):
        sh(*cli, *cmd, env=env, cwd=repo)

    print(f"[acceptance_target] project at {repo}, home {home}", flush=True)
    os.chdir(repo)
    subprocess.Popen([sys.executable, "-m", "orchestra", "run"], env=env, cwd=repo)
    os.execve(sys.executable, [sys.executable, "-m", "orchestra", "web", "--port", str(port)], env)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--project", help="serve this existing demo project instead of a throwaway one")
    ap.add_argument("--real", action="store_true", help="run real Pi agents instead of the fake; nothing is seeded")
    ap.add_argument("--provider", default=os.environ.get("ORCHESTRA_ACCEPTANCE_PROVIDER"))
    ap.add_argument("--model", default=os.environ.get("ORCHESTRA_ACCEPTANCE_MODEL"))
    ap.add_argument("--harness", default=os.environ.get("ORCHESTRA_ACCEPTANCE_HARNESS") or "pi", help="pi | claude_code | codex")
    args = ap.parse_args()
    if args.project:
        staging(args.project, args.port)
    else:
        throwaway(args.port, args.real, args.provider, args.model, args.harness)


if __name__ == "__main__":
    main()
