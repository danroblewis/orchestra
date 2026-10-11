"""Acceptance target: run the *installed* orchestra wheel against a throwaway project.

Invoked by the merge gate's [acceptance] start command inside an isolated environment
that has the built wheel installed. It creates a temporary ORCHESTRATOR_HOME and git
repository, initializes a project, seeds a milestone and a ticket through the CLI,
and serves the web UI on --port. Acceptance tests then talk to that server.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def sh(*args: str, cwd: Path | None = None, env: dict | None = None) -> str:
    p = subprocess.run(list(args), cwd=cwd, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout, p.stderr, file=sys.stderr)
        raise SystemExit(f"command failed: {' '.join(args)}")
    return p.stdout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="orchestra-acceptance-"))
    home = tmp / "home"
    repo = tmp / "repo"
    repo.mkdir()
    env = {**os.environ, "ORCHESTRATOR_HOME": str(home), "ORCHESTRA_REPO": str(repo)}
    sh("git", "init", "-q", "-b", "main", cwd=repo)
    sh("git", "config", "user.email", "acceptance@orchestra", cwd=repo)
    sh("git", "config", "user.name", "acceptance", cwd=repo)
    (repo / "README.md").write_text("# target\n")
    sh("git", "add", "-A", cwd=repo)
    sh("git", "commit", "-qm", "init", cwd=repo)

    cli = [sys.executable, "-m", "orchestra"]
    sh(*cli, "init", "--provider", "fake", "--model", "fake", "--prefix", "ACC", env=env, cwd=repo)
    ms = json.loads(sh(*cli, "api", "create_milestone", "--compact", "--args", json.dumps({"name": "Acceptance"}),
                       env={**env, "ORCHESTRA_ROLE": "supervisor"}, cwd=repo))
    sh(*cli, "api", "create_ticket", "--compact", "--args",
       json.dumps({"title": "Seeded ticket", "description": "seeded by acceptance_target", "acceptance": "none",
                   "milestone_id": ms["milestone"]["id"]}),
       env={**env, "ORCHESTRA_ROLE": "supervisor"}, cwd=repo)
    print(f"[acceptance_target] project at {repo}, home {home}", flush=True)
    os.chdir(repo)
    os.execve(sys.executable, [sys.executable, "-m", "orchestra", "web", "--port", str(args.port)], env)


if __name__ == "__main__":
    main()
