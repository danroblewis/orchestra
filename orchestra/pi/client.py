"""One `pi --mode rpc` process per live session. SPEC.md section 5."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

EXTENSION_PATH = Path(__file__).parent / "extension" / "orchestra.ts"


class PiError(RuntimeError):
    pass


@dataclass
class TurnResult:
    text: str = ""
    settled: bool = False
    timed_out: bool = False
    error: str | None = None
    tool_calls: list[str] = field(default_factory=list)


def _assistant_text(msg: dict) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


class PiProcess:
    """Drives a single Pi session. Thread-safe for one prompt at a time."""

    def __init__(self, *, session_id: str, session_dir: Path, cwd: Path, system_prompt: str,
                 provider: str | None, model: str | None, thinking: str | None,
                 env: dict[str, str], log_path: Path, pi_binary: str | None = None):
        self.session_id = session_id
        self.cwd = cwd
        self.log_path = log_path
        args = [pi_binary or os.environ.get("PI_BINARY", "pi"), "--mode", "rpc",
                "--session-dir", str(session_dir), "--session-id", session_id,
                "--extension", str(EXTENSION_PATH)]
        if provider:
            args += ["--provider", provider]
        if model:
            args += ["--model", model]
        if thinking:
            args += ["--thinking", thinking]
        if system_prompt:
            args += ["--append-system-prompt", system_prompt]
        full_env = {**os.environ, **env, "ORCHESTRA_PYTHON": sys.executable}
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._stderr = log_path.open("a", encoding="utf-8")
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self._stderr, text=True, cwd=str(cwd), env=full_env,
                                     bufsize=1)
        self._q: queue.Queue[dict | None] = queue.Queue()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        self._lock = threading.Lock()
        self.session_file: str | None = None
        self.busy = False

    # -- plumbing --------------------------------------------------------------

    def _read(self) -> None:
        for line in self.proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            if not line:
                continue
            try:
                self._q.put(json.loads(line))
            except json.JSONDecodeError:
                continue
        self._q.put(None)

    def _send(self, cmd: dict) -> None:
        if self.proc.poll() is not None or self.proc.stdin is None:
            raise PiError(f"pi process for {self.session_id} is not running")
        self.proc.stdin.write(json.dumps(cmd) + "\n")
        self.proc.stdin.flush()

    def alive(self) -> bool:
        return self.proc.poll() is None

    def _next(self, timeout: float) -> dict | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return {}

    def _reply_ui(self, ev: dict) -> None:
        # Never block on an extension dialog: cancel it.
        rid = ev.get("id")
        if rid is not None:
            try:
                self._send({"type": "extension_ui_response", "id": rid, "cancelled": True})
            except PiError:
                pass

    # -- commands --------------------------------------------------------------

    def command(self, cmd: dict, timeout: float = 30) -> dict:
        """Send a non-prompt command and wait for its response."""
        with self._lock:
            self._send(cmd)
            deadline = time.time() + timeout
            while time.time() < deadline:
                ev = self._next(1.0)
                if ev is None:
                    raise PiError("pi exited")
                if ev.get("type") == "response" and ev.get("command") == cmd["type"]:
                    return ev
                if ev.get("type") == "extension_ui_request":
                    self._reply_ui(ev)
            raise PiError(f"timeout waiting for {cmd['type']}")

    def get_state(self) -> dict:
        r = self.command({"type": "get_state"})
        data = r.get("data", {}) if r.get("success") else {}
        self.session_file = data.get("sessionFile") or self.session_file
        return data

    def prompt(self, text: str, timeout: float, on_event: Callable[[dict], None] | None = None) -> TurnResult:
        """Send a prompt and wait for agent_settled."""
        with self._lock:
            self.busy = True
            result = TurnResult()
            try:
                self._send({"type": "prompt", "message": text})
                deadline = time.time() + timeout
                last_text = ""
                while time.time() < deadline:
                    ev = self._next(min(5.0, max(0.1, deadline - time.time())))
                    if ev is None:
                        result.error = "pi exited"
                        return result
                    if not ev:
                        continue
                    t = ev.get("type")
                    if on_event:
                        try:
                            on_event(ev)
                        except Exception:
                            pass
                    if t == "response" and ev.get("command") == "prompt" and not ev.get("success", True):
                        result.error = f"prompt rejected: {ev.get('error')}"
                        return result
                    if t == "extension_ui_request":
                        self._reply_ui(ev)
                    elif t == "message_end":
                        msg = ev.get("message", {})
                        if msg.get("role") == "assistant":
                            txt = _assistant_text(msg)
                            if txt.strip():
                                last_text = txt
                            for p in msg.get("content", []) if isinstance(msg.get("content"), list) else []:
                                if isinstance(p, dict) and p.get("type") == "toolCall":
                                    result.tool_calls.append(p.get("name", "?"))
                    elif t == "agent_settled":
                        result.settled = True
                        result.text = last_text
                        return result
                result.timed_out = True
                result.text = last_text
                self._abort()
                return result
            finally:
                self.busy = False

    def _abort(self) -> None:
        try:
            self._send({"type": "abort"})
            deadline = time.time() + 15
            while time.time() < deadline:
                ev = self._next(1.0)
                if ev is None or (ev and ev.get("type") in ("agent_settled",)):
                    return
                if ev and ev.get("type") == "response" and ev.get("command") == "abort":
                    return
        except PiError:
            pass

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        try:
            self._stderr.close()
        except OSError:
            pass


def read_transcript(session_file: str | Path) -> list[dict]:
    """Parse a Pi session JSONL into [{role, text, tool_calls, ts}]."""
    out: list[dict] = []
    p = Path(session_file)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") != "message":
            continue
        msg = e.get("message", {})
        role = msg.get("role")
        if role not in ("user", "assistant", "toolResult"):
            continue
        content = msg.get("content")
        text, tools = "", []
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    text += part.get("text", "")
                elif part.get("type") == "toolCall":
                    tools.append({"name": part.get("name"), "args": part.get("arguments")})
        if role == "toolResult":
            text = text[:2000]
        out.append({"role": role, "text": text, "tool_calls": tools, "ts": e.get("timestamp")})
    return out
