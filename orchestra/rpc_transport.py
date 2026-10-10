"""Real Pi-driven transport: long-lived ``pi --mode rpc`` processes.

The legacy :class:`~orchestrator.orchestrator.RpcTransport` spawns a fresh ``pi``
process per prompt and never waits for the agent to settle. That is fine for a
demo but useless for orchestration, where we need to (a) bind each agent to its
worktree via ``cwd``, (b) layer the role/project system prompt, and (c) wait for
``agent_settled`` before reading the result.

:class:`RpcTransport` below keeps one ``pi`` child per named session and drives it
over a single stdin/stdout pipe. It is the transport the real ``orchestra run``
loop uses; the tests use :class:`~orchestrator.orchestrator.MockTransport`.

Commands and events are one JSON object per line. We subscribe to events before
sending a prompt, wait for ``agent_settled``, then read ``get_last_assistant_text``.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from orchestrator.orchestrator import Transport  # re-export the interface


def _read_log_assistant_text(session_file: str) -> str:
    """Return the last assistant text message from a pi JSONL session log.

    The log stores entries as ``{"type": "message", "role": ..., "message": {"content": [...]}}``
    (raw pi format) or the simpler web ``{"type": "message", "role": ..., "text": ...}``
    format. This reads whichever is present and returns the last assistant turn,
    stripping markdown code-fence wrappers if the agent wrapped its JSON in them.
    """
    try:
        lines = Path(session_file).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return ""
    last = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "message":
            continue
        msg = entry.get("message") if not isinstance(entry.get("message"), str) else {}
        role = (entry.get("role") or (msg or {}).get("role")) if isinstance(msg, dict) else entry.get("role")
        if role != "assistant":
            continue
        # Raw pi format: message.content is a list of parts.
        if isinstance(msg, dict) and "content" in msg:
            chunks = []
            for part in msg.get("content", []):
                if isinstance(part, dict) and part.get("type") == "text":
                    chunks.append(part.get("text", ""))
            text = "".join(chunks)
        else:  # web-format: a flat "text" field.
            text = entry.get("text", "") if not isinstance(msg, dict) else (msg.get("text", "") or "")
        if text.strip():
            last = text.strip()
    return last


class RpcError(Exception):
    """The Pi process failed or did not settle within the deadline."""


class RpcTransport(Transport):
    """Drives real Pi agent sessions, one ``pi`` child per session file.

    Each session is launched with ``cwd=<worktree>`` so the agent operates inside
    the right branch, and ``--append-system-prompt`` carries its role + project
    context. A single stdin/stdout pipe per process carries prompts, events, and
    follow-up commands.
    """

    def __init__(
        self,
        pi_binary: str | None = None,
        default_prompt: str = "",
        cwd: str | os.PathLike[str] | None = None,
        timeout: float = 900,
    ):
        self.pi_binary = pi_binary or os.environ.get("PI_BINARY", "pi")
        self.default_prompt = default_prompt
        self.cwd = cwd
        self.timeout = timeout
        self._sessions: dict[str, _PiSession] = {}
        self._lock = threading.Lock()

    # -- session management -------------------------------------------------- #

    def _launch(self, session_file: str, system_prompt: str = "") -> _PiSession:
        args = [self.pi_binary, "--mode", "rpc", "--session", str(session_file)]
        if system_prompt:
            args += ["--append-system-prompt", system_prompt]
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self.cwd) if self.cwd else None,
        )
        sess = _PiSession(session_file, proc, self.timeout)
        with self._lock:
            self._sessions[session_file] = sess
        return sess

    def _get(self, session_file: str, system_prompt: str = "") -> _PiSession:
        with self._lock:
            sess = self._sessions.get(session_file)
        if sess is None or sess.proc.poll() is not None:
            sess = self._launch(session_file, system_prompt)
        return sess

    def send(self, session_file: str, prompt: str, system_prompt: str = "") -> dict[str, Any]:
        """Send one prompt, wait for the agent to settle, return the settled result."""
        sess = self._get(session_file, system_prompt)
        return sess.run_prompt(prompt)

    def read_last_assistant_text(self, session_file: str) -> str:
        # The JSONL session log is the durable record of what the agent actually
        # said. Reading it directly is more reliable than the RPC ``get_last_
        # assistant_text`` cursor, which can return text from an earlier turn when a
        # session has several assistant messages. Fall back to the RPC result when
        # the log is unreadable.
        text = _read_log_assistant_text(session_file)
        if text.strip():
            return text
        sess = self._sessions.get(session_file)
        if sess is not None:
            return sess.get_last_assistant_text() or ""
        return ""

    def settle(self, session_file: str) -> dict[str, Any]:
        """Reconnect a live session and wait for its current run to settle."""
        sess = self._get(session_file)
        return sess.wait_settled()

    def close(self, session_file: str) -> None:
        with self._lock:
            sess = self._sessions.pop(session_file, None)
        if sess:
            sess.close()

    def close_all(self) -> None:
        for sf in list(self._sessions):
            self.close(sf)

    def __enter__(self) -> "RpcTransport":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close_all()


class _PiSession:
    """Manages one ``pi`` child process and its single stdin/stdout pipe."""

    def __init__(self, session_file: str, proc: subprocess.Popen, timeout: float):
        self.session_file = session_file
        self.proc = proc
        self.timeout = timeout
        self._next_id = 0
        self._settle_event = threading.Event()

    # -- helpers ------------------------------------------------------------- #

    def _send(self, command: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        command.setdefault("id", f"req-{self._next_id}")
        self.proc.stdin.write(json.dumps(command) + "\n")
        self.proc.stdin.flush()
        return command["id"]

    def _read_line(self, deadline: float) -> dict[str, Any] | None:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            line = self.proc.stdout.readline()
            if line == "":
                return None
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    # -- public operations --------------------------------------------------- #

    def run_prompt(self, prompt: str) -> dict[str, Any]:
        """Send a prompt, await ``agent_settled``, then return the assistant's text.

        The final assistant message is captured directly from the event stream
        (the ``message_end``/``turn_end`` events carry ``role: assistant`` with the
        reply). This is required because ``pi --mode rpc`` never persists the
        ``--session`` JSONL file, so reading it back -- or issuing a separate
        ``get_last_assistant_text`` RPC command -- returns empty.
        """
        self._settle_event.clear()
        deadline = time.time() + self.timeout

        # Subscribe before sending so we never miss a fast completion.
        self._send({"type": "subscribe"})
        self._send({"type": "prompt", "message": prompt})
        if os.environ.get("ORCHESTRA_DEBUG"):
            print("[rpc-debug] sent subscribe+prompt to", self.session_file, flush=True)

        settled = False
        settle_record: dict[str, Any] | None = None
        assistant_text = ""
        while not settled and time.time() < deadline:
            rec = self._read_line(deadline)
            if rec is None:
                break
            t = rec.get("type")
            if t == "agent_settled":
                settled = True
                settle_record = rec
            elif t in ("message_end", "turn_end") and rec.get("message", {}).get("role") == "assistant":
                # Last assistant text wins.
                parts = rec.get("message", {}).get("content", [])
                if isinstance(parts, list):
                    chunks = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"]
                    if chunks:
                        assistant_text = "".join(chunks).strip()
            elif t == "response" and rec.get("command") == "prompt" and not rec.get("success", False):
                raise RpcError(f"Prompt rejected by Pi: {rec.get('error')}")

        if not settled:
            self.close()
            raise RpcError(f"Agent did not settle within {self.timeout}s")

        # Fall back to the durable log, then the RPC cursor, if the stream gave
        # nothing. (``pi --mode rpc`` never persists the --session JSONL, so both
        # are empty in practice -- but the scripted tests rely on these paths.)
        if not assistant_text.strip():
            assistant_text = _read_log_assistant_text(self.session_file)
        if not assistant_text.strip():
            assistant_text = self.get_last_assistant_text() or ""
        return {"settled": settle_record, "text": assistant_text}

    def wait_settled(self) -> dict[str, Any]:
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            rec = self._read_line(deadline)
            if rec is None:
                break
            if rec.get("type") == "agent_settled":
                return rec
            if os.environ.get("ORCHESTRA_DEBUG"):
                print(f"[rpc-debug] {rec.get('type')}", flush=True)
        raise RpcError("Agent did not settle")

    def get_last_assistant_text(self) -> str:
        deadline = time.time() + 30
        self._send({"type": "get_last_assistant_text"})
        while time.time() < deadline:
            rec = self._read_line(deadline)
            if rec is None:
                break
            if rec.get("type") == "response" and rec.get("command") == "get_last_assistant_text":
                if not rec.get("success", False):
                    return ""
                return rec.get("data", {}).get("text") or ""
        return ""

    def close(self) -> None:
        proc = self.proc
        if proc.poll() is not None:
            return
        try:
            proc.stdin.close()
        except (ValueError, OSError):
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
