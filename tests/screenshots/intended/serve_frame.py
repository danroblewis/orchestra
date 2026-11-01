"""Serve one Machines-page frame from the real web app (render.cjs starts it):

    PYTHONPATH=tests/unit uv run python tests/screenshots/intended/serve_frame.py E1 <port>

A throwaway project under a temporary ORCHESTRATOR_HOME, seeded by ``machine_frames.seed_frame`` (tests/unit)
(the captured machines replayed onto its bus, the captured model as discovered versions, the
frame's declarations through the intended model's ops), served by ``create_app`` with auth on.
Prints one JSON line {"token", "url"} when it is ready. Every answer is the server's own."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main(frame: str, port: int) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="orchestra-frames-"))
    os.environ["ORCHESTRATOR_HOME"] = str(tmp / "home")
    (tmp / "repo").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp / "repo", check=True)

    import uvicorn
    from machine_frames import replay_observed, seed_frame

    from orchestra.config import init_project
    from orchestra.web.app import create_app
    from orchestra.web.auth import token

    project = init_project(tmp / "repo")
    replay_observed(project)
    project = seed_frame(project, frame)
    app = create_app(project)
    print(json.dumps({"token": token(project), "url": f"http://127.0.0.1:{port}"}), flush=True)
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
