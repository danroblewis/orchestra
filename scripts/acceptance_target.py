"""Acceptance target: run the *installed* orchestra package as a complete, empty Orchestra.

A throwaway ORCHESTRATOR_HOME and git repository, a project initialised through the CLI, the
bootstrap host (`orchestra run`) in the background, and the web UI on --port. The acceptance
tests (tests/acceptance/) then use only HTTP, like a person at the dashboard.

    python scripts/acceptance_target.py --port 8123      # prints the web token to export
    ORCHESTRA_TARGET_URL=http://127.0.0.1:8123 ORCHESTRA_TARGET_TOKEN=<token> uv run pytest tests/acceptance -q
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8123)
    args = ap.parse_args()
    home = Path(tempfile.mkdtemp(prefix="orchestra-acc-"))
    repo = home / "repo"
    repo.mkdir()
    env = {**os.environ, "ORCHESTRATOR_HOME": str(home / "state"), "ORCHESTRA_REPO": str(repo)}
    env.pop("ORCHESTRA_EVENTS_URL", None)
    env.pop("ORCHESTRA_METRICS_URL", None)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    cli = [sys.executable, "-m", "orchestra"]
    subprocess.run([*cli, "init"], cwd=repo, env=env, check=True)
    token = subprocess.run([*cli, "web", "token"], cwd=repo, env=env, check=True, capture_output=True, text=True).stdout.strip()
    print(f"export ORCHESTRA_TARGET_URL=http://127.0.0.1:{args.port} ORCHESTRA_TARGET_TOKEN={token}", flush=True)
    host = subprocess.Popen([*cli, "run"], cwd=repo, env=env)
    web = subprocess.Popen([*cli, "web", "--port", str(args.port)], cwd=repo, env=env)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))      # stopping this script stops both
    try:
        return web.wait()
    finally:
        for p in (web, host):
            p.terminate()
            p.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
