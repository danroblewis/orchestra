"""Getting a collector's text: its command's standard output, or its URL's body.

A command runs in the repository root with ``ORCHESTRA_REPO`` (the root) and
``ORCHESTRA_MACHINE_LOG`` (its log) set, in a process group of its own, its standard error going
to its log. It fails when it exits non-zero, outlasts its timeout (its group is then killed) or
cannot be started. A URL fails on anything but a 200, or when the server is silent for longer
than the timeout (it bounds each wait, not the whole transfer). Either fails when the text is
larger than ``MAX_BYTES``."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .spec import Collector

MAX_BYTES = 10_000_000
ACCEPT = "text/plain;version=0.0.4;q=1.0, */*;q=0.1"


class Failed(Exception):
    pass


def run_command(c: Collector, repo: Path, log: Path, stop: threading.Event | None = None) -> str:
    """The command's standard output; raises ``Failed`` saying why there is none."""
    env = {**os.environ, "ORCHESTRA_REPO": str(repo), "ORCHESTRA_MACHINE_LOG": str(log)}
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log.open("ab") as err:
            p = subprocess.Popen(c.argv(), cwd=repo, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=err, start_new_session=True)
    except PermissionError as e:
        raise Failed(f"cannot run `{c.target}`: {e} (is it executable? chmod +x)") from e
    except FileNotFoundError as e:
        hint = f" (to run the file in the repository, write ./{c.argv()[0]})" if "/" not in c.argv()[0] and (repo / c.argv()[0]).exists() else ""
        raise Failed(f"cannot run `{c.target}`: {e}{hint}") from e
    except OSError as e:
        raise Failed(f"cannot run `{c.target}`: {type(e).__name__}: {e}") from e
    out: list[bytes] = []
    reader = threading.Thread(target=lambda: out.append(p.stdout.read(MAX_BYTES + 1)), daemon=True)
    reader.start()
    deadline = time.monotonic() + c.timeout_s
    while p.poll() is None and time.monotonic() < deadline and not (stop and stop.is_set()):
        try:
            p.wait(timeout=max(0.0, min(0.1, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            pass
    timed_out = p.poll() is None
    _kill(p)                                    # its group: a timed-out command, or what it left running
    reader.join(5.0)
    p.stdout.close()
    if timed_out:
        raise Failed("stopped with orchestra run" if stop and stop.is_set() else f"took longer than its timeout ({c.timeout_s:g} s); killed")
    if p.returncode != 0:
        raise Failed(f"exited with code {p.returncode}")
    text = out[0] if out else b""
    if len(text) > MAX_BYTES:
        raise Failed(f"printed more than {MAX_BYTES} bytes")
    return text.decode("utf-8", "replace")


def fetch_url(c: Collector) -> str:
    """The URL's body; raises ``Failed`` saying why there is none."""
    req = urllib.request.Request(c.target, headers={"Accept": ACCEPT, "User-Agent": "orchestra-scrape"})
    try:
        with urllib.request.urlopen(req, timeout=c.timeout_s) as r:
            if r.status != 200:
                raise Failed(f"answered {r.status}")
            body = r.read(MAX_BYTES + 1)
            charset = r.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as e:
        raise Failed(f"answered {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        raise Failed(f"cannot fetch {c.target}: {reason}") from e
    if len(body) > MAX_BYTES:
        raise Failed(f"answered more than {MAX_BYTES} bytes")
    return body.decode(charset, "replace")


def _kill(p: subprocess.Popen) -> None:
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    p.wait()
