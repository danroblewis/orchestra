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
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, UTC
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

# Where we persist tunnel metadata between web-server restarts.
TUNNEL_META_PATH = DATA_DIR / "tunnel.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _read_tunnel_meta() -> dict:
    """Load persisted tunnel metadata, or return an empty dict."""
    if TUNNEL_META_PATH.exists():
        try:
            return json.loads(TUNNEL_META_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_tunnel_meta(meta: dict) -> None:
    """Persist tunnel metadata atomically so the next restart can reuse it."""
    tmp = TUNNEL_META_PATH.with_suffix(TUNNEL_META_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.replace(tmp, TUNNEL_META_PATH)  # atomic on POSIX and Windows


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


# --- cloudflared tunnel management -----------------------------------------
#
# Goal: never spin up a *new* public tunnel when a working one already exists,
# across web-server restarts. We persist the last-known public URL on disk so a
# fresh process can probe it first. Only if the persisted URL is gone (or has
# moved) do we start a fresh tunnel and overwrite the metadata.

def _probe(url: str) -> int | None:
    """Return the HTTP status code for ``url``, or None if it is unreachable."""
    import httpx

    try:
        with httpx.Client(timeout=5, follow_redirects=True) as client:
            r = client.get(url)
            return r.status_code
    except Exception:
        return None


def _tunnel_public_up(url: str) -> bool:
    """Return True if the public tunnel URL is reachable."""
    status = _probe(url)
    return status is not None and status < 500


def _localhost_status(web_port: int) -> int | None:
    """HTTP status of the local web app, or None if not yet serving."""
    return _probe(f"http://127.0.0.1:{web_port}/")


def _tunnel_healthy(web_port: int, url: str) -> bool:
    """Decide whether the persisted tunnel is worth keeping.

    Decision logic (so we never restart the tunnel for a problem that isn't the
    tunnel):

    - If the localhost web app is UP but the public tunnel URL is DOWN, the
      tunnel is the culprit -> restart it.
    - If the localhost web app is DOWN (e.g. we are the process that is about
      to start it, so it cannot be serving yet), we cannot blame the tunnel. In
      that case fall back to the public URL alone, so a healthy tunnel is
      reused and a genuinely dead tunnel is replaced.
    - If both are UP, the tunnel is healthy -> reuse it.
    """
    public_ok = _tunnel_public_up(url)
    local = _localhost_status(web_port)
    if local is not None:
        # Web app is reachable -- the authoritative case. Only a dead tunnel
        # (with a healthy app) warrants a restart.
        return local < 500 and public_ok
    # Web app not yet serving (startup race). Fall back to the public URL so we
    # don't spin up a needless new tunnel just because the app isn't listening
    # this instant.
    return public_ok


def _cloudflared_tunnel_alive(tunnel_name: str) -> bool:
    """Return True if a cloudflared process is currently running our named tunnel.

    Used as a fallback when the public DNS record has not yet propagated (so a
    public-URL probe would fail) but the tunnel itself is running locally.
    """
    if not shutil.which(CLOUDFLARED_BIN):
        return False
    try:
        proc = subprocess.run(
            ["ps", "-o", "args=", "-x"],
            capture_output=True, text=True, timeout=10,
        )
        # Match a live cloudflared process whose command line *runs* our named
        # tunnel. `tunnel list` only proves the tunnel is *registered* in the
        # account (empty CONNECTIONS when idle), so we inspect the process
        # table directly instead. We require the process to be cloudflared
        # running our tunnel (tunnel run), which avoids false matches from
        # shell pipelines that happen to mention the tunnel name.
        needle = f"{tunnel_name}"
        for line in proc.stdout.splitlines():
            if not line.startswith("cloudflared"):
                continue
            if "tunnel run" not in line:
                continue
            if needle in line or TUNNEL_ID in line:
                return True
        return False
    except Exception:
        return False


def _probe_tunnel(url: str, web_port: int) -> bool:
    """Decide whether a persisted tunnel is worth reusing.

    Primary signal: the public URL is reachable AND the local web app is up
    (a dead web app must never look like a healthy tunnel). Secondary signal: a
    cloudflared process for our named tunnel is alive -- this covers the case
    where the public DNS record has not yet propagated so a probe would
    falsely report the tunnel as down.
    """
    if not _tunnel_healthy(web_port, url):
        # Local app is down, OR public URL is down. If the app is down we
        # cannot blame the tunnel; if the app is up the tunnel is the culprit
        # unless cloudflared is demonstrably running our named tunnel.
        return _cloudflared_tunnel_alive(TUNNEL_NAME)
    return True


# Named-tunnel identity. We use an authenticated named tunnel (tied to the
# cloudflared login) instead of an ephemeral quick tunnel, which avoids the
# per-IP rate limit on account-less quick tunnels. The UUID matches the tunnel
# created via `cloudflared tunnel create orchestra`.
TUNNEL_NAME = "orchestra"
TUNNEL_ID = "bd709956-314f-48b0-bc9e-949b313f1a3e"
TUNNEL_DOMAIN = "orchestra.dansproject.space"
CLOUDFLARED_BIN = "cloudflared"  # on PATH


def _tunnel_config_path() -> Path:
    """Path to the cloudflared named-tunnel config file."""
    return Path("~/.cloudflared").expanduser() / f"{TUNNEL_NAME}.yaml"


def _write_tunnel_config(port: int) -> Path:
    """Write (or refresh) the named-tunnel YAML config for ``port``."""
    cfg = {
        "tunnel": TUNNEL_ID,
        "credentials-file": str(Path("~/.cloudflared").expanduser() / f"{TUNNEL_ID}.json"),
        "ingress": [
            {"hostname": TUNNEL_DOMAIN, "service": f"http://127.0.0.1:{port}"},
            {"service": "http_status:404"},
        ],
    }
    path = _tunnel_config_path()
    import yaml

    path.write_text(yaml.dump(cfg), encoding="utf-8")
    return path


def start_tunnel(
    port: int, tunnel_url: str | None = None
) -> tuple[subprocess.Popen | None, str | None]:
    """Start (or reuse) a cloudflared named tunnel bound to the web port.

    Returns ``(proc, url)``. If ``tunnel_url`` is already known and still
    healthy it is reused (``proc`` is None). Otherwise the named-tunnel config
    is written for ``port`` and a fresh cloudflared process is launched. The
    public URL is the configured ingress hostname (known up front), so it is
    persisted and returned directly -- there is nothing to parse from stdout.
    """
    if not shutil.which(CLOUDFLARED_BIN):
        print("[tunnel] cloudflared not found in PATH; skipping tunnel startup", flush=True)
        return None, None

    # The canonical public URL is always the configured ingress hostname.
    # The persisted ``tunnel_url`` may be stale (e.g. a typo'd domain from an
    # earlier session), so we probe whatever was persisted AND the canonical
    # domain, then always report the canonical one.
    canonical_url = f"https://{TUNNEL_DOMAIN}"
    reuse = False
    if tunnel_url and tunnel_url != canonical_url and _probe_tunnel(tunnel_url, port):
        print(f"[tunnel] Reusing persisted tunnel: {tunnel_url}", flush=True)
        reuse = True
    elif _probe_tunnel(canonical_url, port):
        print(f"[tunnel] Reusing persisted tunnel: {canonical_url}", flush=True)
        reuse = True

    if reuse:
        # Refresh the config for the current port and persist the canonical URL
        # so the live config and the API always agree.
        try:
            _write_tunnel_config(port)
        except Exception as exc:  # pragma: no cover - yaml import guard
            print(f"[tunnel] Failed to refresh tunnel config ({exc})", flush=True)
        meta = {
            "url": canonical_url,
            "port": port,
            "tunnel_name": TUNNEL_NAME,
            "started_at": datetime.now(UTC).isoformat(),
        }
        _write_tunnel_meta(meta)
        return None, canonical_url

    # A named tunnel has a stable, known public URL (the ingress hostname),
    # so there is no quick-tunnel URL to "capture". We simply confirm the
    # process stays up. We give cloudflared a few seconds to establish its
    # first connection so we can tell a launch failure apart from normal start
    # up latency.
    try:
        _write_tunnel_config(port)
    except Exception as exc:  # pragma: no cover - yaml import guard
        print(f"[tunnel] Failed to write tunnel config ({exc}); local only", flush=True)
        return None, None

    proc = subprocess.Popen(
        [CLOUDFLARED_BIN, "--config", str(_tunnel_config_path()), "tunnel", "run", TUNNEL_NAME],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    url = f"https://{TUNNEL_DOMAIN}"
    # Persist the tunnel identity so restarts can probe/reuse it.
    meta = {"url": url, "port": port, "tunnel_name": TUNNEL_NAME, "started_at": datetime.now(UTC).isoformat()}
    _write_tunnel_meta(meta)
    print(f"[tunnel] Started named cloudflared tunnel: {url}", flush=True)

    def _cleanup(_signum, _frame):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)
    return proc, url


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

    # Reuse a healthy persisted tunnel if we have one. Always resolve to the
    # canonical public URL (the configured ingress hostname); a stale persisted
    # URL (e.g. a typo'd domain from an earlier session) must not leak into the
    # API or viewer.
    canonical_url = f"https://{TUNNEL_DOMAIN}"
    meta = _read_tunnel_meta()
    persisted_url = meta.get("url")
    tunnel_proc = None
    reused = (
        (persisted_url and _probe_tunnel(persisted_url, web_port))
        or _probe_tunnel(canonical_url, web_port)
    )
    tunnel_url = canonical_url if reused else None

    if not tunnel_url and shutil.which("cloudflared"):
        # Persisted tunnel missing or dead -> start a new one.
        tunnel_proc, tunnel_url = start_tunnel(web_port, persisted_url)
    elif not tunnel_url and not shutil.which("cloudflared"):
        print(f"[web] Web server on http://127.0.0.1:{web_port} (no cloudflared)", flush=True)

    print(f"[web] Web server on http://127.0.0.1:{web_port}", flush=True)
    if tunnel_url:
        print(f"[web] Public URL: {tunnel_url}", flush=True)
    else:
        print("[web] No public tunnel available (local only)", flush=True)

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
