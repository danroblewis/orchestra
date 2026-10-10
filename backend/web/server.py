"""Read-only web server process for Orchestra.

This process is EFFECTIVELY READ-ONLY. It serves the static frontend and the
live state snapshot (built from the shared repositories). It never mutates
state -- that is the orchestrator's job. The web viewer updates frequently, so
the server just reads whatever the orchestrator has persisted.

On startup it also starts a cloudflared tunnel (if one is not already running)
so the web viewer is reachable on a public URL.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from uvicorn.config import Config
from uvicorn.main import Server

# Make the shared library importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.repositories.json_store import JsonStore
from shared.repositories.task_repository import TaskRepository
from shared.repositories.milestone_repository import MilestoneRepository
from shared.repositories.build_output_repository import BuildOutputRepository
from shared.repositories.session_log_repository import SessionLogRepository

DATA_DIR = Path(os.environ.get("ORCHESTRA_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")))
STORE_PATH = DATA_DIR / "orchestra.json"
STORE = JsonStore(STORE_PATH)
STATIC_DIR = Path(__file__).resolve().parent / "static"


def build_state() -> dict:
    """Build the read-only state snapshot served to the frontend."""
    store = JsonStore(STORE_PATH)
    tasks = TaskRepository(store).all()
    milestones = MilestoneRepository(store).ordered()
    builds = BuildOutputRepository(store).find_all()
    session_logs = SessionLogRepository(store).find_all()

    return {
        "tasks": [t.to_dict() for t in tasks],
        "milestones": [m.to_dict() for m in milestones],
        "builds": [b.to_dict() for b in builds],
        "sessionLogs": [s.to_dict() for s in session_logs],
        "nextInQueue": [t.to_dict() for t in TaskRepository(store).next_in_queue()],
    }


async def _get_available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_tunnel(port: int) -> subprocess.Popen | None:
    """Start a cloudflared tunnel if one is not already running.

    Returns the running process (or None if cloudflared is unavailable). The
    public URL is captured from cloudflared's logs after it comes up.
    """
    if not shutil.which("cloudflared"):
        print("[tunnel] cloudflared not found in PATH; skipping tunnel startup", flush=True)
        return None

    # Check for an existing tunnel by probing the local metrics endpoint.
    existing = _existing_tunnel()
    if existing:
        print(f"[tunnel] Using existing cloudflared tunnel: {existing}", flush=True)
        return None

    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    def _cleanup(_signum, _frame):
        proc.terminate()
        proc.wait()

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)
    return proc


def _existing_tunnel() -> str | None:
    """Best-effort check for an existing cloudflared tunnel on localhost."""
    import httpx

    for port in range(8000, 8100):
        try:
            with httpx.Client(timeout=2) as client:
                r = client.get(f"http://127.0.0.1:{port}/metrics")
                if r.status_code == 200 and "http_route" in r.text:
                    return None
        except Exception:
            continue
    return None


def capture_tunnel_url(proc: subprocess.Popen, timeout: float = 30.0) -> str | None:
    """Read cloudflared's stdout until it prints a public tunnel URL."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()  # type: ignore[union-attr]
        if not line:
            break
        text = line.decode("utf-8", errors="ignore").strip()
        for token in text.split():
            if "trycloudflare.com" in token:
                url = token.strip(",")
                if url.startswith("https://"):
                    print(f"[tunnel] Started cloudflared tunnel: {url}", flush=True)
                    return url
    print("[tunnel] Failed to capture tunnel URL; web server still runs locally", flush=True)
    return None


def create_app(web_port: int, tunnel_proc: subprocess.Popen | None = None, tunnel_url: str | None = None) -> FastAPI:
    app = FastAPI(title="Orchestra Web Viewer")

    @app.get("/api/state", summary="Read-only full state snapshot")
    async def read_state() -> dict:
        return build_state()

    @app.get("/api/port", summary="Local port the web server listens on")
    async def read_port() -> dict:
        return {"port": web_port}

    @app.get("/api/tunnel", summary="Public cloudflared tunnel URL if available")
    async def read_tunnel() -> dict:
        return {"url": tunnel_url}

    @app.get("/api/sessions/{session_id}", summary="Get a session's message history")
    async def read_session(session_id: str) -> dict:
        """Return the full message history for a given session log.

        The message text is parsed from the session log file to render the
        Coordinator / Pipeline Manager session details in a modal dialog.
        """
        from shared.repositories.session_log_repository import SessionLogRepository
        from shared.models import SessionLog

        repo = SessionLogRepository(STORE)
        log = repo.find(session_id)
        if not log:
            raise HTTPException(status_code=404, detail="Session not found")

        # Re-read the session log file to get the full message history.
        messages = _read_session_messages(log.session_file_path, log.message_count)

        return {
            "id": log.id,
            "session_name": log.session_name,
            "layer": log.layer,
            "status": log.status,
            "message_count": log.message_count,
            "last_entry_id": log.last_entry_id,
            "created_at": log.created_at,
            "updated_at": log.updated_at,
            "messages": messages,
        }

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
        # Serve the full index.html from the static directory at the root.
        @app.get("/", response_class=HTMLResponse)
        async def index() -> HTMLResponse:
            index_path = STATIC_DIR / "index.html"
            return HTMLResponse(index_path.read_text(encoding="utf-8"))
    else:
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/", response_class=HTMLResponse)
        async def index() -> HTMLResponse:
            return HTMLResponse(
                "<!doctype html><html><head><title>Orchestra</title></head>"
                "<body><div id='root'></div></body></html>"
            )

    app.state.web_port = web_port
    app.state.tunnel_proc = tunnel_proc
    app.state.tunnel_url = tunnel_url
    return app


def _read_session_messages(session_file_path: str, message_count: int) -> list:
    """Read session messages from the JSONL log file.

    Falls back to a simple line-based parse if the rich entry structure
    isn't present. Returns a list of {role, content, created_at} dicts.
    """
    from datetime import datetime, UTC

    messages = []
    try:
        import json

        # Resolve relative paths against the data directory.
        if session_file_path and not os.path.isabs(session_file_path):
            data_dir = os.environ.get(
                "ORCHESTRA_DATA_DIR",
                str(Path(__file__).resolve().parents[2] / "data"),
            )
            session_file_path = os.path.normpath(
                os.path.join(data_dir, session_file_path)
            )

        if session_file_path and Path(session_file_path).exists():
            with open(session_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            for i, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Rich entry structure (from the session log format).
                if entry.get("type") == "assistant" or "role" in entry:
                    role = entry.get("role", "assistant")
                    content = entry.get("text") or entry.get("content") or ""
                elif "message" in entry:
                    msg = entry["message"]
                    role = msg.get("role", "assistant")
                    content = msg.get("text") or msg.get("content") or ""
                else:
                    # Unknown structure — include the raw line.
                    continue

                created_at = entry.get("ts") or entry.get("created_at") or ""
                if isinstance(created_at, (int, float)):
                    created_at = datetime.fromtimestamp(
                        created_at, tz=UTC
                    ).isoformat()
                elif isinstance(created_at, str):
                    created_at = created_at

                messages.append(
                    {"role": role, "content": content[:5000], "created_at": created_at}
                )

                if message_count and len(messages) >= message_count:
                    break
    except Exception:
        # If anything goes wrong reading the log, return what we have.
        pass

    return messages


def main():
    import uvicorn

    web_port = int(os.environ.get("WEB_PORT", "8000"))
    # Start the tunnel first so its URL is known by the time the app starts.
    tunnel_proc = None
    tunnel_url = None
    if shutil.which("cloudflared"):
        tunnel_proc = start_tunnel(web_port)
        tunnel_url = capture_tunnel_url(tunnel_proc) if tunnel_proc else None
        print(f"[web] Web server on http://127.0.0.1:{web_port}", flush=True)
        if tunnel_url:
            print(f"[web] Public URL: {tunnel_url}", flush=True)
    else:
        print(f"[web] Web server on http://127.0.0.1:{web_port} (no cloudflared)", flush=True)

    app = create_app(web_port, tunnel_proc, tunnel_url)
    config = Config(app=app, host="127.0.0.1", port=web_port, log_level="info")
    server = Server(config)

    def _shutdown(_signum, _frame):
        if tunnel_proc:
            tunnel_proc.terminate()
            tunnel_proc.wait()
        server.should_exit = True

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    server.run()


if __name__ == "__main__":
    main()
