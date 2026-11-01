"""Serve one Machines-page frame from the real web app (render.cjs starts it):

    PYTHONPATH=tests/unit uv run python tests/screenshots/intended/serve_frame.py E1 8191

A throwaway project under a temporary ORCHESTRATOR_HOME, seeded by ``intended_frames.seed_frame``
(the captured machines replayed onto its bus, the captured model as discovered versions, the
frame's declarations through the intended model's ops), served by ``create_app`` with auth on.
Prints one JSON line {"token", "url"} when it is ready. For E4 only, ``/api/machines`` gains P5's
``measured`` block on the declared machine (``intended_frames.measured_e4``), which the core does
not compute yet (C4); everything else is the server's own answer."""

from __future__ import annotations

import json
import os
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
    from intended_frames import SAIL, measured_e4, replay_observed, seed_frame

    from orchestra.config import init_project
    from orchestra.web.app import create_app
    from orchestra.web.auth import token

    project = init_project(tmp / "repo")
    replay_observed(project)
    seed_frame(project, frame)
    app = create_app(project)
    if frame == "E4":
        app.middleware("http")(_with_measured(SAIL, measured_e4))
    print(json.dumps({"token": token(project), "url": f"http://127.0.0.1:{port}"}), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def _with_measured(machine: str, block):
    async def add(request, call_next):
        resp = await call_next(request)
        if request.url.path != "/api/machines" or resp.status_code != 200:
            return resp
        from starlette.responses import JSONResponse
        body = b"".join([chunk async for chunk in resp.body_iterator])
        out = json.loads(body)
        for m in out.get("machines") or []:
            if m["id"] == machine:
                m["measured"] = block()
        return JSONResponse(out)
    return add


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
